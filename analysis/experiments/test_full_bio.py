"""Comprehensive test: full bio config vs baseline.

Configurations:
  1. baseline (everything bio OFF): old behaviour
  2. full bio: shared-phase oscillator + diff readout + RIA cross-coupling
              + A-MN UNC-2 oscillator (Gao 2018) + RIA cross-comp (Hendricks 2012)
              + bio resting potentials (Mellem 2008, Lockery 2009, Suzuki 2008)

Per-config: 30k ticks. Reports head co-contraction, body wave, AVA bursts,
body reversals, and concordance between AVA and reversals.
"""
from __future__ import annotations
from analysis.lib.lab_client import (
    LAB_REST as URL_REST,
    LAB_WS as URL_WS,
    post_json,
    get_json,
    unpack_bits,
)
import asyncio, json, urllib.request
import numpy as np
import websockets

async def collect(label, ticks_target, params):
    print(f'\n=== {label} ===', flush=True)
    patches = [{'path': k, 'value': v} for k, v in params.items()]
    post_json('/api/patch', {'patches': patches})
    post_json('/api/reset', {})
    await asyncio.sleep(0.5)
    rows = []
    last_tick = -1
    async with websockets.connect(URL_WS, max_size=2 ** 24) as ws:
        hello = json.loads(await ws.recv())
        names = hello['L']['nm']
        muscle_names = hello['L_body'].get('muscles', [])
        ava_ids = [names.index(n) for n in ('AVAL', 'AVAR') if n in names]
        avb_ids = [names.index(n) for n in ('AVBL', 'AVBR') if n in names]
        rmd_d_ids = [names.index(n) for n in ('RMDDL', 'RMDDR') if n in names]
        rmd_v_ids = [names.index(n) for n in ('RMDVL', 'RMDVR') if n in names]
        m_idx = {nm: i for i, nm in enumerate(muscle_names)}

        def mi(seg, q):
            return m_idx.get(f'muscle_seg{seg}_{q}', -1)
        muscle_idx = {seg: {q: mi(seg, q) for q in ('DL', 'DR', 'VL', 'VR')} for seg in (1, 2, 3, 4, 6, 9, 12)}
        while True:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
            except asyncio.TimeoutError:
                break
            d = json.loads(msg)
            if d.get('t') != 's':
                continue
            tick = d.get('k', 0)
            if tick == last_tick:
                continue
            last_tick = tick
            Si = d.get('Si', [])
            ma = d.get('ma', [])
            sm = np.array(d.get('sm', []), dtype=np.int64)
            com = np.array(d.get('cm', [0, 0, 0]), dtype=np.int64)
            S_ava = float(np.mean([Si[i] / 10000.0 for i in ava_ids])) if ava_ids else 0
            S_avb = float(np.mean([Si[i] / 10000.0 for i in avb_ids])) if avb_ids else 0
            S_rmd_d = float(np.mean([Si[i] / 10000.0 for i in rmd_d_ids])) if rmd_d_ids else 0
            S_rmd_v = float(np.mean([Si[i] / 10000.0 for i in rmd_v_ids])) if rmd_v_ids else 0
            seg_DV = {}
            for seg, idx in muscle_idx.items():
                D = (ma[idx['DL']] + ma[idx['DR']]) / 20000.0 if idx['DL'] >= 0 else 0
                V = (ma[idx['VL']] + ma[idx['VR']]) / 20000.0 if idx['VL'] >= 0 else 0
                seg_DV[seg] = (D, V)
            rows.append((tick, S_ava, S_avb, S_rmd_d, S_rmd_v, seg_DV, com, sm))
            if tick >= ticks_target:
                break
    n = len(rows)
    if n < 100:
        print(f'  WARNING: only {n} frames')
        return
    sec = np.array([(r[0] - rows[0][0]) * 0.002 for r in rows])
    rate_per_s = (n - 1) / sec[-1] if sec[-1] > 0 else 0
    S_ava = np.array([r[1] for r in rows])
    S_avb = np.array([r[2] for r in rows])
    S_rmd_d = np.array([r[3] for r in rows])
    S_rmd_v = np.array([r[4] for r in rows])
    com = np.stack([r[6] / 1000000.0 for r in rows])
    seg_data = np.stack([r[7] / 1000000.0 for r in rows]).reshape(n, -1, 3)
    head = seg_data[:, 0, :2]
    tail = seg_data[:, -1, :2]
    fwd_dir = (head - tail) / (np.linalg.norm(head - tail, axis=1, keepdims=True) + 1e-09)
    com_vel = np.diff(com[:, :2], axis=0) / np.diff(sec).reshape(-1, 1)
    fwd_speed = np.einsum('ij,ij->i', com_vel, fwd_dir[:-1]) * 1000
    win = max(1, int(2.0 * rate_per_s))
    fs_smooth = np.convolve(fwd_speed, np.ones(win) / win, mode='same')
    rmd_corr = np.corrcoef(S_rmd_d, S_rmd_v)[0, 1] if S_rmd_d.std() > 0 else float('nan')
    gate_active = S_ava > 1.1
    diffs = np.diff(gate_active.astype(int), prepend=0, append=0)
    g_starts = np.where(diffs == 1)[0]
    g_ends = np.where(diffs == -1)[0]
    gate_episodes = [(s, e) for s, e in zip(g_starts, g_ends) if (e - s) / rate_per_s >= 0.3]
    is_rev = fs_smooth < -10
    diffs_r = np.diff(is_rev.astype(int), prepend=0, append=0)
    r_starts = np.where(diffs_r == 1)[0]
    r_ends = np.where(diffs_r == -1)[0]
    rev_episodes = [(s, e) for s, e in zip(r_starts, r_ends) if (e - s) / rate_per_s >= 1.0]
    concordant = sum((1 for rs, re in rev_episodes for gs, ge in gate_episodes if max(rs, gs) < min(re, ge)))
    print(f'  duration={sec[-1]:.0f}s  frames={n}  rate={rate_per_s:.0f}/s', flush=True)
    print(f'  AVA mean S={S_ava.mean():+.3f}  std={S_ava.std():.3f}  max={S_ava.max():+.3f}', flush=True)
    print(f'  AVB mean S={S_avb.mean():+.3f}  std={S_avb.std():.3f}', flush=True)
    print(f'  RMD pool D-V corr = {rmd_corr:+.3f}  (target: negative)', flush=True)
    print(f'  RMDD={S_rmd_d.mean():+.2f}±{S_rmd_d.std():.2f}  RMDV={S_rmd_v.mean():+.2f}±{S_rmd_v.std():.2f}', flush=True)
    for seg in (1, 2, 3, 4, 6, 9, 12):
        D = np.array([r[5][seg][0] for r in rows])
        V = np.array([r[5][seg][1] for r in rows])
        c = np.corrcoef(D, V)[0, 1] if D.std() > 0 and V.std() > 0 else float('nan')
        cc = float((D * V).mean())
        print(f'  seg{seg:2d}  D={D.mean():.2f}±{D.std():.2f}  V={V.mean():.2f}±{V.std():.2f}  D×V={cc:.3f}  D-V corr={c:+.2f}', flush=True)
    print(f'  AVA gate episodes (≥0.3s): {len(gate_episodes)}  ({len(gate_episodes) / sec[-1] * 60:.1f}/min)', flush=True)
    print(f'  Body reversals (≥1s):       {len(rev_episodes)}  ({len(rev_episodes) / sec[-1] * 60:.1f}/min)', flush=True)
    print(f'  Concordance (rev∩gate):     {concordant}/{len(rev_episodes)}', flush=True)
    print(f'  Mean fwd: {fwd_speed.mean():+.1f} µm/s  smoothed range: [{fs_smooth.min():+.0f}, {fs_smooth.max():+.0f}]', flush=True)

async def main():
    ticks = 30000
    baseline = {'sim.muscles.HEAD_DIFFERENTIAL_READOUT': False, 'sim.neuromod.RIA_COMPARTMENTS_ENABLED': False, 'sim.neuromod.A_MN_OSC_ENABLED': False, 'sim.neuromod.BIO_RESTING_POTENTIALS': False, 'sim.neuromod.INTRINSIC_OSC_AMP': 0.025, 'sim.neuromod.CMD_NOISE_SIGMA': 0.05, 'sim.neuromod.CMD_NOISE_TAU': 50.0}
    full_bio = {'sim.muscles.HEAD_DIFFERENTIAL_READOUT': True, 'sim.neuromod.RIA_COMPARTMENTS_ENABLED': True, 'sim.neuromod.RIA_COMPARTMENT_GAIN': 0.1, 'sim.neuromod.A_MN_OSC_ENABLED': True, 'sim.neuromod.A_MN_OSC_AMP': 0.1, 'sim.neuromod.A_MN_OSC_GATE_THRESHOLD': 1.0, 'sim.neuromod.BIO_RESTING_POTENTIALS': True, 'sim.neuromod.INTRINSIC_OSC_AMP': 0.1, 'sim.neuromod.CMD_NOISE_SIGMA': 0.1, 'sim.neuromod.CMD_NOISE_TAU': 1000.0}
    await collect('1. baseline (all bio OFF)', ticks, baseline)
    await collect('2. full bio (all enabled)', ticks, full_bio)
if __name__ == '__main__':
    asyncio.run(main())

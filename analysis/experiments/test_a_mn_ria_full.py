"""Full integration test: A-MN intrinsic oscillator + RIA cross-compartmentalization.

Compares four configurations:
  1. baseline:  A-MN off, RIA off  (current behaviour pre-Gao/Hendricks)
  2. A-MN only: A-MN on,  RIA off
  3. RIA only:  A-MN off, RIA on
  4. both:      A-MN on,  RIA on   (full Gao 2018 + Hendricks 2012 model)

Metrics per run:
  - Head co-contraction:  mean (D × V) for segs 1, 2, 3 (lower = better antiphase)
  - Head dorsal/ventral RMS amplitude over time
  - AVA bursts (S > 1.10) per minute
  - Body reversals (smoothed COM speed < -10 µm/s ≥ 1s) per minute
  - Concordance: AVA ∩ body-reversal episodes
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

async def collect(label: str, ticks_target: int, params: dict, cmd_sigma: float=0.1, cmd_tau: float=1000.0) -> dict:
    print(f'\n=== {label} ===')
    patches = [{'path': k, 'value': v} for k, v in params.items()]
    patches.append({'path': 'sim.neuromod.CMD_NOISE_SIGMA', 'value': float(cmd_sigma)})
    patches.append({'path': 'sim.neuromod.CMD_NOISE_TAU', 'value': float(cmd_tau)})
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
        smd_d_ids = [names.index(n) for n in ('SMDDL', 'SMDDR') if n in names]
        smd_v_ids = [names.index(n) for n in ('SMDVL', 'SMDVR') if n in names]
        m_idx = {nm: i for i, nm in enumerate(muscle_names)}

        def mi(seg: int, quad: str) -> int:
            return m_idx.get(f'muscle_seg{seg}_{quad}', -1)
        seg_muscle_idx = {seg: {q: mi(seg, q) for q in ('DL', 'DR', 'VL', 'VR')} for seg in range(1, 13)}
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
            S_ava = np.mean([Si[i] / 10000.0 for i in ava_ids if 0 <= i < len(Si)]) if ava_ids else 0
            S_rmd_d = np.mean([Si[i] / 10000.0 for i in rmd_d_ids if 0 <= i < len(Si)]) if rmd_d_ids else 0
            S_rmd_v = np.mean([Si[i] / 10000.0 for i in rmd_v_ids if 0 <= i < len(Si)]) if rmd_v_ids else 0
            S_smd_d = np.mean([Si[i] / 10000.0 for i in smd_d_ids if 0 <= i < len(Si)]) if smd_d_ids else 0
            S_smd_v = np.mean([Si[i] / 10000.0 for i in smd_v_ids if 0 <= i < len(Si)]) if smd_v_ids else 0
            seg_D = []
            seg_V = []
            for seg in range(1, 13):
                idx = seg_muscle_idx[seg]
                D = []
                V = []
                for q in ('DL', 'DR'):
                    if 0 <= idx[q] < len(ma):
                        D.append(ma[idx[q]] / 10000.0)
                for q in ('VL', 'VR'):
                    if 0 <= idx[q] < len(ma):
                        V.append(ma[idx[q]] / 10000.0)
                seg_D.append(float(np.mean(D)) if D else 0.0)
                seg_V.append(float(np.mean(V)) if V else 0.0)
            rows.append((tick, S_ava, S_rmd_d, S_rmd_v, S_smd_d, S_smd_v, seg_D, seg_V, com, sm))
            if tick >= ticks_target:
                break
    n = len(rows)
    if n < 100:
        print(f'  WARNING: only {n} frames captured')
        return {}
    sec = np.array([(r[0] - rows[0][0]) * 0.002 for r in rows])
    S_ava = np.array([r[1] for r in rows])
    S_rmd_d = np.array([r[2] for r in rows])
    S_rmd_v = np.array([r[3] for r in rows])
    S_smd_d = np.array([r[4] for r in rows])
    S_smd_v = np.array([r[5] for r in rows])
    seg_D = np.stack([r[6] for r in rows])
    seg_V = np.stack([r[7] for r in rows])
    com = np.stack([r[8] / 1000000.0 for r in rows])
    seg = np.stack([r[9] / 1000000.0 for r in rows]).reshape(n, -1, 3)
    head = seg[:, 0, :2]
    tail = seg[:, -1, :2]
    fwd_dir = (head - tail) / (np.linalg.norm(head - tail, axis=1, keepdims=True) + 1e-09)
    com_vel = np.diff(com[:, :2], axis=0) / np.diff(sec).reshape(-1, 1)
    fwd_speed = np.einsum('ij,ij->i', com_vel, fwd_dir[:-1]) * 1000
    fps = 100
    win = max(1, int(2.0 * fps))
    fwd_smooth = np.convolve(fwd_speed, np.ones(win) / win, mode='same')
    head_cocontract = (seg_D[:, 0:3] * seg_V[:, 0:3]).mean(axis=0)
    head_corr = []
    for s in range(0, 3):
        D = seg_D[:, s] - seg_D[:, s].mean()
        V = seg_V[:, s] - seg_V[:, s].mean()
        if D.std() > 1e-06 and V.std() > 1e-06:
            head_corr.append(np.corrcoef(D, V)[0, 1])
        else:
            head_corr.append(float('nan'))
    rmd_corr = float('nan')
    if S_rmd_d.std() > 1e-06 and S_rmd_v.std() > 1e-06:
        rmd_corr = float(np.corrcoef(S_rmd_d, S_rmd_v)[0, 1])
    gate_active = S_ava > 1.1
    diffs = np.diff(gate_active.astype(int))
    g_starts = np.where(diffs == 1)[0]
    g_ends = np.where(diffs == -1)[0]
    if len(g_ends) and len(g_starts) and (g_ends[0] < g_starts[0]):
        g_ends = g_ends[1:]
    if len(g_starts) > len(g_ends):
        g_starts = g_starts[:len(g_ends)]
    gate_episodes = [(s, e) for s, e in zip(g_starts, g_ends) if (e - s) / fps >= 0.3]
    is_rev = fwd_smooth < -10
    diffs_r = np.diff(is_rev.astype(int))
    r_starts = np.where(diffs_r == 1)[0]
    r_ends = np.where(diffs_r == -1)[0]
    if len(r_ends) and len(r_starts) and (r_ends[0] < r_starts[0]):
        r_ends = r_ends[1:]
    if len(r_starts) > len(r_ends):
        r_starts = r_starts[:len(r_ends)]
    rev_episodes = [(s, e) for s, e in zip(r_starts, r_ends) if (e - s) / fps >= 1.0]
    concordant = sum((1 for rs, re in rev_episodes for gs, ge in gate_episodes if max(rs, gs) < min(re, ge)))
    print(f'  duration={sec[-1]:.0f}s  AVA mean S={S_ava.mean():+.3f} (max={S_ava.max():+.3f})')
    print(f'  RMD_D mean S={S_rmd_d.mean():+.3f} std={S_rmd_d.std():.3f}  RMD_V mean S={S_rmd_v.mean():+.3f} std={S_rmd_v.std():.3f}  corr={rmd_corr:+.3f}')
    print(f'  SMD_D mean S={S_smd_d.mean():+.3f} std={S_smd_d.std():.3f}  SMD_V mean S={S_smd_v.mean():+.3f} std={S_smd_v.std():.3f}')
    print(f'  Head co-contraction (mean D×V):  seg1={head_cocontract[0]:.3f}  seg2={head_cocontract[1]:.3f}  seg3={head_cocontract[2]:.3f}  (lower = better)')
    print(f'  Head D vs V corr (anti-phase):   seg1={head_corr[0]:+.2f}  seg2={head_corr[1]:+.2f}  seg3={head_corr[2]:+.2f}  (negative = good)')
    print(f'  AVA gate episodes (≥0.3s, S>1.10): {len(gate_episodes)}  ({len(gate_episodes) / sec[-1] * 60:.1f}/min)')
    print(f'  Body reversals (≥1s):              {len(rev_episodes)}  ({len(rev_episodes) / sec[-1] * 60:.1f}/min)')
    print(f'  Concordance (rev∩gate):            {concordant}/{len(rev_episodes)}')
    print(f'  Mean fwd: {fwd_speed.mean():+.1f} µm/s  smoothed range: [{fwd_smooth.min():+.0f}, {fwd_smooth.max():+.0f}]')
    return {'head_cocontract': head_cocontract.tolist(), 'head_corr': head_corr, 'rmd_corr': rmd_corr, 'n_gate': len(gate_episodes), 'n_rev': len(rev_episodes), 'concordant': concordant}

async def main() -> None:
    base_params = {'sim.neuromod.A_MN_OSC_ENABLED': False, 'sim.neuromod.RIA_COMPARTMENTS_ENABLED': False}
    a_mn_params = {'sim.neuromod.A_MN_OSC_ENABLED': True, 'sim.neuromod.A_MN_OSC_AMP': 0.1, 'sim.neuromod.RIA_COMPARTMENTS_ENABLED': False}
    ria_params = {'sim.neuromod.A_MN_OSC_ENABLED': False, 'sim.neuromod.RIA_COMPARTMENTS_ENABLED': True, 'sim.neuromod.RIA_COMPARTMENT_GAIN': 0.05}
    both_params = {'sim.neuromod.A_MN_OSC_ENABLED': True, 'sim.neuromod.A_MN_OSC_AMP': 0.1, 'sim.neuromod.RIA_COMPARTMENTS_ENABLED': True, 'sim.neuromod.RIA_COMPARTMENT_GAIN': 0.05}
    ticks = 30000
    sigma = 0.1
    tau = 1000.0
    await collect('1. Baseline (A-MN off, RIA off)', ticks, base_params, sigma, tau)
    await collect('2. A-MN OSC only (Gao 2018)', ticks, a_mn_params, sigma, tau)
    await collect('3. RIA compartments only (Hendricks 2012)', ticks, ria_params, sigma, tau)
    await collect('4. Both (full bio model)', ticks, both_params, sigma, tau)
if __name__ == '__main__':
    asyncio.run(main())

"""Find the best combination of bio mechanisms.

The bisect test showed:
  - diff readout fixes head co-contraction (seg1 0.5/0.5 → 0.24/0.61) but loses fwd speed
  - bio rest helps slightly
  - RIA at 0.10 mostly hurts (or no effect)
  - A-MN OSC + high CMD noise produces big body waves (std 0.45)

Configurations to compare:
  α. diff + bio_rest + A-MN + high noise (NO RIA)
  β. diff + bio_rest + A-MN + RIA=0.05 + high noise
  γ. diff + A-MN + high noise (no bio rest, no RIA — bisect winner D)
  δ. diff + bio_rest + RIA=0.05 + A-MN + lower osc amp + high noise
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
        m_idx = {nm: i for i, nm in enumerate(muscle_names)}

        def mi(seg, q):
            return m_idx.get(f'muscle_seg{seg}_{q}', -1)
        muscle_idx = {seg: {q: mi(seg, q) for q in ('DL', 'DR', 'VL', 'VR')} for seg in (1, 2, 4, 6, 9)}
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
            seg_DV = {seg: ((ma[idx['DL']] + ma[idx['DR']]) / 20000.0 if idx['DL'] >= 0 else 0, (ma[idx['VL']] + ma[idx['VR']]) / 20000.0 if idx['VL'] >= 0 else 0) for seg, idx in muscle_idx.items()}
            rows.append((tick, S_ava, S_avb, seg_DV, com, sm))
            if tick >= ticks_target:
                break
    n = len(rows)
    if n < 100:
        print(f'  WARNING: only {n} frames')
        return
    sec = np.array([(r[0] - rows[0][0]) * 0.002 for r in rows])
    rate = (n - 1) / sec[-1] if sec[-1] > 0 else 0
    S_ava = np.array([r[1] for r in rows])
    S_avb = np.array([r[2] for r in rows])
    com = np.stack([r[4] / 1000000.0 for r in rows])
    seg_data = np.stack([r[5] / 1000000.0 for r in rows]).reshape(n, -1, 3)
    h = seg_data[:, 0, :2]
    t = seg_data[:, -1, :2]
    fdir = (h - t) / (np.linalg.norm(h - t, axis=1, keepdims=True) + 1e-09)
    com_vel = np.diff(com[:, :2], axis=0) / np.diff(sec).reshape(-1, 1)
    fwd = np.einsum('ij,ij->i', com_vel, fdir[:-1]) * 1000
    win = max(1, int(2.0 * rate))
    fwd_smooth = np.convolve(fwd, np.ones(win) / win, mode='same')
    ga = S_ava > 1.1
    ds = np.diff(ga.astype(int), prepend=0, append=0)
    starts = np.where(ds == 1)[0]
    ends = np.where(ds == -1)[0]
    eps = [(s, e) for s, e in zip(starts, ends) if (e - s) / rate >= 0.3]
    ir = fwd_smooth < -10
    dr = np.diff(ir.astype(int), prepend=0, append=0)
    rs = np.where(dr == 1)[0]
    re = np.where(dr == -1)[0]
    revs = [(s, e) for s, e in zip(rs, re) if (e - s) / rate >= 1.0]
    conc = sum((1 for rs2, re2 in revs for gs, ge in eps if max(rs2, gs) < min(re2, ge)))
    print(f'  AVA={S_ava.mean():+.2f}±{S_ava.std():.2f}  AVB={S_avb.mean():+.2f}±{S_avb.std():.2f}  AVA bursts ≥0.3s: {len(eps)}/min={len(eps) / sec[-1] * 60:.1f}', flush=True)
    for seg in (1, 2, 4, 6, 9):
        D = np.array([r[3][seg][0] for r in rows])
        V = np.array([r[3][seg][1] for r in rows])
        c = np.corrcoef(D, V)[0, 1] if D.std() > 0 and V.std() > 0 else float('nan')
        print(f'  seg{seg:2d} D={D.mean():.2f}±{D.std():.2f} V={V.mean():.2f}±{V.std():.2f} D-V corr={c:+.2f}  D×V={(D * V).mean():.3f}', flush=True)
    print(f'  Body reversals (≥1s): {len(revs)} ({len(revs) / sec[-1] * 60:.1f}/min)  Concordant: {conc}/{len(revs)}', flush=True)
    print(f'  Mean fwd: {fwd.mean():+.1f} µm/s  smoothed range: [{fwd_smooth.min():+.0f}, {fwd_smooth.max():+.0f}]', flush=True)

async def main():
    ticks = 30000
    common = {'sim.muscles.HEAD_DIFFERENTIAL_READOUT': True, 'sim.neuromod.A_MN_OSC_ENABLED': True, 'sim.neuromod.A_MN_OSC_AMP': 0.1, 'sim.neuromod.A_MN_OSC_GATE_THRESHOLD': 1.1, 'sim.neuromod.CMD_NOISE_SIGMA': 0.1, 'sim.neuromod.CMD_NOISE_TAU': 1000.0}
    a = {**common, 'sim.neuromod.BIO_RESTING_POTENTIALS': True, 'sim.neuromod.RIA_COMPARTMENTS_ENABLED': False, 'sim.neuromod.INTRINSIC_OSC_AMP': 0.025}
    b = {**common, 'sim.neuromod.BIO_RESTING_POTENTIALS': True, 'sim.neuromod.RIA_COMPARTMENTS_ENABLED': True, 'sim.neuromod.RIA_COMPARTMENT_GAIN': 0.05, 'sim.neuromod.INTRINSIC_OSC_AMP': 0.025}
    g = {**common, 'sim.neuromod.BIO_RESTING_POTENTIALS': False, 'sim.neuromod.RIA_COMPARTMENTS_ENABLED': False, 'sim.neuromod.INTRINSIC_OSC_AMP': 0.025}
    d = {**common, 'sim.neuromod.BIO_RESTING_POTENTIALS': True, 'sim.neuromod.RIA_COMPARTMENTS_ENABLED': True, 'sim.neuromod.RIA_COMPARTMENT_GAIN': 0.05, 'sim.neuromod.INTRINSIC_OSC_AMP': 0.05}
    await collect('α. diff+bio_rest+A-MN+noise (no RIA)', ticks, a)
    await collect('β. diff+bio_rest+A-MN+RIA=0.05+noise', ticks, b)
    await collect('γ. diff+A-MN+noise (no bio_rest, no RIA)', ticks, g)
    await collect('δ. diff+bio_rest+RIA=0.05+A-MN+osc=0.05', ticks, d)
if __name__ == '__main__':
    asyncio.run(main())

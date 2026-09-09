"""Sweep A-MN gate threshold to find one that engages without overdriving."""
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
            seg_DV = {seg: ((ma[idx['DL']] + ma[idx['DR']]) / 20000.0 if idx['DL'] >= 0 else 0, (ma[idx['VL']] + ma[idx['VR']]) / 20000.0 if idx['VL'] >= 0 else 0) for seg, idx in muscle_idx.items()}
            rows.append((tick, S_ava, seg_DV, com, sm))
            if tick >= ticks_target:
                break
    n = len(rows)
    if n < 100:
        return
    sec = np.array([(r[0] - rows[0][0]) * 0.002 for r in rows])
    rate = (n - 1) / sec[-1]
    S_ava = np.array([r[1] for r in rows])
    com = np.stack([r[3] / 1000000.0 for r in rows])
    seg_data = np.stack([r[4] / 1000000.0 for r in rows]).reshape(n, -1, 3)
    h = seg_data[:, 0, :2]
    t = seg_data[:, -1, :2]
    fdir = (h - t) / (np.linalg.norm(h - t, axis=1, keepdims=True) + 1e-09)
    cv = np.diff(com[:, :2], axis=0) / np.diff(sec).reshape(-1, 1)
    fwd = np.einsum('ij,ij->i', cv, fdir[:-1]) * 1000
    win = max(1, int(2.0 * rate))
    fwd_smooth = np.convolve(fwd, np.ones(win) / win, mode='same')
    thr = float(params.get('sim.neuromod.A_MN_OSC_GATE_THRESHOLD', 1.1))
    above = (S_ava > thr).sum() / n
    print(f'  AVA={S_ava.mean():+.2f}±{S_ava.std():.2f}  time above gate ({thr:.2f}): {above * 100:.0f}%', flush=True)
    for seg in (1, 2, 4, 6, 9):
        D = np.array([r[2][seg][0] for r in rows])
        V = np.array([r[2][seg][1] for r in rows])
        c = np.corrcoef(D, V)[0, 1] if D.std() > 0 and V.std() > 0 else float('nan')
        print(f'  seg{seg:2d} D={D.mean():.2f}±{D.std():.2f} V={V.mean():.2f}±{V.std():.2f} D-V corr={c:+.2f}', flush=True)
    print(f'  fwd: {fwd.mean():+.1f} µm/s  smoothed [{fwd_smooth.min():+.0f},{fwd_smooth.max():+.0f}]', flush=True)

async def main():
    ticks = 30000
    base = {'sim.muscles.HEAD_DIFFERENTIAL_READOUT': True, 'sim.neuromod.A_MN_OSC_ENABLED': True, 'sim.neuromod.A_MN_OSC_AMP': 0.1, 'sim.neuromod.RIA_COMPARTMENTS_ENABLED': False, 'sim.neuromod.BIO_RESTING_POTENTIALS': False, 'sim.neuromod.INTRINSIC_OSC_AMP': 0.025}
    cfgs = [('thr=1.10 σ=0.10 τ=1000', {**base, 'sim.neuromod.A_MN_OSC_GATE_THRESHOLD': 1.1, 'sim.neuromod.CMD_NOISE_SIGMA': 0.1, 'sim.neuromod.CMD_NOISE_TAU': 1000.0}), ('thr=0.90 σ=0.10 τ=1000', {**base, 'sim.neuromod.A_MN_OSC_GATE_THRESHOLD': 0.9, 'sim.neuromod.CMD_NOISE_SIGMA': 0.1, 'sim.neuromod.CMD_NOISE_TAU': 1000.0}), ('thr=0.85 σ=0.20 τ=1500', {**base, 'sim.neuromod.A_MN_OSC_GATE_THRESHOLD': 0.85, 'sim.neuromod.CMD_NOISE_SIGMA': 0.2, 'sim.neuromod.CMD_NOISE_TAU': 1500.0}), ('thr=0.70 σ=0.20 τ=1500', {**base, 'sim.neuromod.A_MN_OSC_GATE_THRESHOLD': 0.7, 'sim.neuromod.CMD_NOISE_SIGMA': 0.2, 'sim.neuromod.CMD_NOISE_TAU': 1500.0})]
    for label, cfg in cfgs:
        await collect(label, ticks, cfg)
if __name__ == '__main__':
    asyncio.run(main())

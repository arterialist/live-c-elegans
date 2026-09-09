"""Test the binary-latch fix.

Check that:
  - Forward periods sustain (no flicker)
  - Reversals are clean (B-proprio fully off)
  - Head muscles oscillate across whole body
  - Opposing muscle gets residual signal (not 0)
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

async def main():
    post_json('/api/patch', {'patches': [{'path': 'sim.muscles.HEAD_DIFFERENTIAL_READOUT', 'value': True}, {'path': 'sim.neuromod.A_MN_OSC_ENABLED', 'value': True}, {'path': 'sim.neuromod.A_MN_OSC_AMP', 'value': 0.1}, {'path': 'sim.neuromod.RIA_COMPARTMENTS_ENABLED', 'value': False}, {'path': 'sim.neuromod.BIO_RESTING_POTENTIALS', 'value': False}, {'path': 'sim.neuromod.INTRINSIC_OSC_AMP', 'value': 0.025}, {'path': 'sim.neuromod.CMD_NOISE_SIGMA', 'value': 0.2}, {'path': 'sim.neuromod.CMD_NOISE_TAU', 'value': 1500.0}]})
    post_json('/api/reset', {})
    await asyncio.sleep(0.5)
    rows = []
    last_tick = -1
    target = 30000
    async with websockets.connect(URL_WS, max_size=2 ** 24) as ws:
        hello = json.loads(await ws.recv())
        names = hello['L']['nm']
        muscle_names = hello['L_body'].get('muscles', [])
        ava_ids = [names.index(n) for n in ('AVAL', 'AVAR') if n in names]
        avb_ids = [names.index(n) for n in ('AVBL', 'AVBR') if n in names]
        m_idx = {nm: i for i, nm in enumerate(muscle_names)}

        def mi(seg, q):
            return m_idx.get(f'muscle_seg{seg}_{q}', -1)
        muscle_idx = {seg: {q: mi(seg, q) for q in ('DL', 'DR', 'VL', 'VR')} for seg in (1, 2, 3, 4, 6, 9, 12)}
        while True:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
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
            if tick >= target:
                break
    n = len(rows)
    sec = np.array([(r[0] - rows[0][0]) * 0.002 for r in rows])
    rate = (n - 1) / sec[-1] if sec[-1] > 0 else 0
    S_ava = np.array([r[1] for r in rows])
    S_avb = np.array([r[2] for r in rows])
    com = np.stack([r[4] / 1000000.0 for r in rows])
    seg_data = np.stack([r[5] / 1000000.0 for r in rows]).reshape(n, -1, 3)
    h = seg_data[:, 0, :2]
    t = seg_data[:, -1, :2]
    fdir = (h - t) / (np.linalg.norm(h - t, axis=1, keepdims=True) + 1e-09)
    cv = np.diff(com[:, :2], axis=0) / np.diff(sec).reshape(-1, 1)
    fwd = np.einsum('ij,ij->i', cv, fdir[:-1]) * 1000
    win = max(1, int(2.0 * rate))
    fwd_smooth = np.convolve(fwd, np.ones(win) / win, mode='same')
    ava_high = S_ava > 0.85
    diffs = np.diff(ava_high.astype(int), prepend=0, append=0)
    starts = np.where(diffs == 1)[0]
    ends = np.where(diffs == -1)[0]
    eps = list(zip(starts, ends))
    print(f'=== Binary latch test (60s) ===')
    print(f'  AVA={S_ava.mean():+.2f}±{S_ava.std():.2f}  AVB={S_avb.mean():+.2f}±{S_avb.std():.2f}')
    print(f'  AVA crossings >0.85: {len(eps)}  ({len(eps) / sec[-1] * 60:.1f}/min)')
    if eps:
        durs = [(e - s) / rate for s, e in eps]
        print(f'  episode durations: mean={np.mean(durs):.2f}s  max={np.max(durs):.2f}s')
    for seg in (1, 2, 3, 4, 6, 9, 12):
        D = np.array([r[3][seg][0] for r in rows])
        V = np.array([r[3][seg][1] for r in rows])
        c = np.corrcoef(D, V)[0, 1] if D.std() > 0 and V.std() > 0 else float('nan')
        active_both = ((D > 0.05) & (V > 0.05)).mean() * 100
        silent_max = max((D < 0.05).mean(), (V < 0.05).mean()) * 100
        print(f'  seg{seg:2d}  D={D.mean():.2f}±{D.std():.2f} V={V.mean():.2f}±{V.std():.2f} D-V corr={c:+.2f}  both-active%={active_both:.0f}  one-silent%={silent_max:.0f}')
    print(f'  Mean fwd: {fwd.mean():+.1f} µm/s  smoothed range: [{fwd_smooth.min():+.0f}, {fwd_smooth.max():+.0f}]')
if __name__ == '__main__':
    asyncio.run(main())

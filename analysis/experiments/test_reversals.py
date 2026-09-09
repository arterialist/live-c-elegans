"""Detect real reversals (forward speed sustained negative for ≥1s)."""
from __future__ import annotations
from analysis.lib.lab_client import (
    LAB_REST as URL_REST,
    LAB_WS as URL_WS,
    post_json,
    get_json,
    unpack_bits,
)
import asyncio, base64, json, sys, time, urllib.request
import numpy as np
import websockets

async def run(sigma, tau, target=60000):
    label = f'σ={sigma} τ={tau}'
    print(f'\n=== {label} ===')
    post_json('/api/patch', {'patches': [{'path': 'sim.neuromod.CMD_NOISE_SIGMA', 'value': float(sigma)}, {'path': 'sim.neuromod.CMD_NOISE_TAU', 'value': float(tau)}]})
    post_json('/api/reset', {})
    await asyncio.sleep(0.5)
    async with websockets.connect(URL_WS, max_size=2 ** 24) as ws:
        hello = json.loads(await ws.recv())
        joints = hello['L_body']['joints']
        ticks_l, com_l, sm_l = ([], [], [])
        last_tick = -1
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
            ticks_l.append(tick)
            com_l.append(np.array(d.get('cm', [0, 0, 0]), dtype=np.int64))
            sm_l.append(np.array(d.get('sm', []), dtype=np.int64))
            if tick >= target:
                break
        ticks = np.array(ticks_l, dtype=np.int32)
        n = len(ticks)
        sec = (ticks - ticks[0]) * 0.002
        com = np.stack([c / 1000000.0 for c in com_l])
        seg = np.stack([s / 1000000.0 for s in sm_l]).reshape(n, -1, 3)
        fps = 1.0 / np.median(np.diff(ticks)) / 0.002
        head = seg[:, 0, :2]
        tail = seg[:, -1, :2]
        fwd = (head - tail) / (np.linalg.norm(head - tail, axis=1, keepdims=True) + 1e-09)
        com_vel = np.diff(com[:, :2], axis=0) / np.diff(sec).reshape(-1, 1)
        fwd_speed = np.einsum('ij,ij->i', com_vel, fwd[:-1]) * 1000
        win = max(1, int(round(2.0 * fps)))
        smoothed = np.convolve(fwd_speed, np.ones(win) / win, mode='same')
        reversal = smoothed < 0
        sustain_n = max(1, int(round(1.0 * fps)))
        diffs = np.diff(reversal.astype(int))
        starts = np.where(diffs == 1)[0]
        ends = np.where(diffs == -1)[0]
        if len(ends) > 0 and (len(starts) == 0 or ends[0] < starts[0]):
            ends = ends[1:]
        if len(starts) > len(ends):
            starts = starts[:len(ends)]
        rev_durations = (ends - starts) / fps
        real_reversals = rev_durations[rev_durations >= 1.0]
        print(f'  duration={sec[-1]:.0f}s  smoothed-fwd mean={smoothed.mean():+.1f}µm/s  std={smoothed.std():.1f}µm/s')
        print(f'  total reversal time={reversal.mean() * sec[-1]:.1f}s ({reversal.mean() * 100:.0f}%)')
        print(f'  reversal episodes ≥1s: {len(real_reversals)}  rate {len(real_reversals) / sec[-1] * 60:.1f}/min')
        if len(real_reversals) > 0:
            print(f'  reversal duration: mean {real_reversals.mean():.1f}s  median {np.median(real_reversals):.1f}s  max {real_reversals.max():.1f}s')
        return {'sigma': sigma, 'tau': tau, 'rev_count': len(real_reversals), 'rev_rate_per_min': len(real_reversals) / sec[-1] * 60, 'smooth_fwd_mean': smoothed.mean()}

async def main():
    results = []
    for s in [0.0, 0.1, 0.2, 0.3, 0.5, 0.7, 1.0]:
        results.append(await run(s, 50.0, target=60000))
    print('\n=== summary (target real C. elegans: 5-10 reversals/min on agar foraging) ===')
    for r in results:
        print(f'  σ={r['sigma']:.2f}  reversals={r['rev_count']:3d}  rate={r['rev_rate_per_min']:.1f}/min  smooth_fwd={r['smooth_fwd_mean']:+.1f}µm/s')
if __name__ == '__main__':
    asyncio.run(main())

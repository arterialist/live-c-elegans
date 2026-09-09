"""Fine sweep: frequency × amplitude grid, measuring fraction of frames in 2-cross (S) state.

Compute distribution of zero-crossings, not just average. Ideally want >70% frames with ≥2 crossings.
"""
from __future__ import annotations
from analysis.lib.lab_client import (
    LAB_REST as URL_REST,
    LAB_WS as URL_WS,
    post_json,
    get_json,
    unpack_bits,
)
import asyncio
import json
import time
import urllib.request
import websockets
from collections import Counter

def zero_crossings(yaws, deadband=0.03):
    cnt = 0
    prev = None
    for y in yaws:
        if abs(y) < deadband:
            continue
        s = 1 if y > 0 else -1
        if prev is not None and s != prev:
            cnt += 1
        prev = s
    return cnt

async def snap(seconds):
    async with websockets.connect(URL_WS, max_size=2 ** 24) as ws:
        hello = json.loads(await ws.recv())
        joints = hello['L_body']['joints']
        yaw_idx = [i for i, jn in enumerate(joints) if 'yaw' in jn]
        rows = []
        deadline = time.time() + seconds
        while time.time() < deadline:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
            except asyncio.TimeoutError:
                break
            d = json.loads(msg)
            if d.get('t') != 's':
                continue
            ja = [v / 10000.0 for v in d.get('ja', [])]
            yaws = [ja[i] for i in yaw_idx]
            rows.append((d.get('k', 0), yaws))
        return rows

async def evaluate(label, patches, seconds=15.0):
    if patches:
        post_json('/api/patch', {'patches': patches})
    await asyncio.sleep(0.2)
    rows = await snap(seconds)
    if not rows:
        print(f'[{label}] no data')
        return None
    n = len(rows)
    zc_per_frame = [zero_crossings(yaws) for _, yaws in rows]
    dist = Counter(zc_per_frame)
    avg = sum(zc_per_frame) / n
    pct_ge2 = sum((1 for z in zc_per_frame if z >= 2)) / n * 100
    pct_eq2 = sum((1 for z in zc_per_frame if z == 2)) / n * 100
    pct_ge3 = sum((1 for z in zc_per_frame if z >= 3)) / n * 100
    n_j = len(rows[0][1])
    per_amp = [max((r[1][j] for r in rows)) - min((r[1][j] for r in rows)) for j in range(n_j)]
    tail_amp = sum(per_amp[-3:]) / 3
    head_amp = sum(per_amp[:3]) / 3
    target = max(zc_per_frame, key=lambda z: zc_per_frame.count(z))
    rep_idx = next((i for i, z in enumerate(zc_per_frame) if z == target))
    rep_yaws = rows[rep_idx][1]
    print(f'[{label}]  n={n}  avg_zc={avg:.2f}  pct_=2={pct_eq2:.0f}%  pct_>=2={pct_ge2:.0f}%  pct_>=3={pct_ge3:.0f}%  head_amp={head_amp:.2f} tail_amp={tail_amp:.2f}  dist={dict(sorted(dist.items()))}')
    print(f'    rep mode={target}: ' + ' '.join((f'{y:+.2f}' for y in rep_yaws)))
    return {'label': label, 'pct_eq2': pct_eq2, 'pct_ge2': pct_ge2, 'pct_ge3': pct_ge3, 'tail_amp': tail_amp, 'head_amp': head_amp, 'avg': avg}

async def main():
    results = []
    r = await evaluate('FIX-C baseline', [{'path': 'sim.neuromod.HEAD_CPG_FREQ_HZ', 'value': 0.5}, {'path': 'sim.neuromod.HEAD_CPG_AMP', 'value': 0.15}, {'path': 'sim.muscles.filter_alpha', 'value': 0.08}, {'path': 'sim.neuromod.PROPRIO_TAIL_DECAY', 'value': 0.7}, {'path': 'sim.neuromod.PROPRIO_MOTOR_GAIN', 'value': 0.1}], seconds=12.0)
    results.append(r)
    for freq in [0.6, 0.7, 0.8, 0.9, 1.0, 1.2]:
        r = await evaluate(f'freq={freq}', [{'path': 'sim.neuromod.HEAD_CPG_FREQ_HZ', 'value': freq}], seconds=12.0)
        results.append(r)
    for amp in [0.18, 0.22, 0.25]:
        r = await evaluate(f'freq=1.0, amp={amp}', [{'path': 'sim.neuromod.HEAD_CPG_FREQ_HZ', 'value': 1.0}, {'path': 'sim.neuromod.HEAD_CPG_AMP', 'value': amp}], seconds=12.0)
        results.append(r)
    for prop in [0.07, 0.05]:
        r = await evaluate(f'freq=0.5, proprio={prop}', [{'path': 'sim.neuromod.HEAD_CPG_FREQ_HZ', 'value': 0.5}, {'path': 'sim.neuromod.HEAD_CPG_AMP', 'value': 0.15}, {'path': 'sim.neuromod.PROPRIO_MOTOR_GAIN', 'value': prop}], seconds=12.0)
        results.append(r)
    post_json('/api/patch', {'patches': [{'path': 'sim.neuromod.HEAD_CPG_FREQ_HZ', 'value': 0.5}, {'path': 'sim.neuromod.HEAD_CPG_AMP', 'value': 0.15}, {'path': 'sim.muscles.filter_alpha', 'value': 0.08}, {'path': 'sim.neuromod.PROPRIO_TAIL_DECAY', 'value': 0.7}, {'path': 'sim.neuromod.PROPRIO_MOTOR_GAIN', 'value': 0.1}]})
    print('\n=== ranking by pct_ge2 (S or better) ===')
    valid = [r for r in results if r]
    for r in sorted(valid, key=lambda x: -x['pct_ge2']):
        print(f'  {r['label']:35s}  pct_>=2={r['pct_ge2']:.0f}%  pct_=2={r['pct_eq2']:.0f}%  pct_>=3={r['pct_ge3']:.0f}%  head/tail amp={r['head_amp']:.2f}/{r['tail_amp']:.2f}')
if __name__ == '__main__':
    asyncio.run(main())

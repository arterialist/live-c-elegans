"""Find params giving a true S (two half-waves along body).

Wavelength = wave_speed / freq. Current FIX-C gives ~1 half-wave (single C bend).
Test combinations of CPG frequency and PROPRIO gain to halve the wavelength.

This script does NOT reset (we want to leave the long-run test alone). It applies
patches, takes a quick snapshot of body shape, then moves on. Captures look at
the NUMBER OF ZERO CROSSINGS along the yaw chain (a true S has 2; a C has 1).
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

def zero_crossings(yaws):
    """Count sign changes (zero crossings) along yaw chain."""
    cnt = 0
    prev = None
    for y in yaws:
        if abs(y) < 0.02:
            continue
        s = 1 if y > 0 else -1
        if prev is not None and s != prev:
            cnt += 1
        prev = s
    return cnt

async def snap(seconds):
    """Capture for `seconds`, return list of yaw vectors and per-frame zero crossings."""
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

async def evaluate(label, patches, seconds=12.0):
    if patches:
        post_json('/api/patch', {'patches': patches})
    await asyncio.sleep(0.2)
    rows = await snap(seconds)
    if not rows:
        print(f'[{label}] no data')
        return
    n = len(rows)
    zc_per_frame = [zero_crossings(yaws) for _, yaws in rows]
    avg_zc = sum(zc_per_frame) / n
    max_zc = max(zc_per_frame)
    max_idx = next((i for i, z in enumerate(zc_per_frame) if z == max_zc))
    rep_yaws = rows[max_idx][1]
    last_yaws = rows[-1][1]
    n_j = len(rows[0][1])
    per_amp = []
    for j in range(n_j):
        col = [r[1][j] for r in rows]
        per_amp.append(max(col) - min(col))
    multi_bend = sum((1 for z in zc_per_frame if z >= 2))
    print(f'[{label}]  ticks {rows[0][0]}..{rows[-1][0]}  n={n}')
    print(f'  zero-crossings per frame:  avg={avg_zc:.2f}  max={max_zc}  ≥2 in {multi_bend}/{n} frames ({multi_bend / n * 100:.0f}%)')
    print(f'  per-joint amp: ' + ' '.join((f'{a:.2f}' for a in per_amp)))
    print(f'  rep frame ({max_zc}-cross): ' + ' '.join((f'{y:+.2f}' for y in rep_yaws)))
    print(f'  last frame:                ' + ' '.join((f'{y:+.2f}' for y in last_yaws)))

async def main():
    await evaluate('current FIX-C', [], seconds=8.0)
    await evaluate('freq=1.0', [{'path': 'sim.neuromod.HEAD_CPG_FREQ_HZ', 'value': 1.0}], seconds=10.0)
    await evaluate('freq=1.5, amp=0.20', [{'path': 'sim.neuromod.HEAD_CPG_FREQ_HZ', 'value': 1.5}, {'path': 'sim.neuromod.HEAD_CPG_AMP', 'value': 0.2}], seconds=10.0)
    await evaluate('freq=1.5, amp=0.20, alpha=0.15', [{'path': 'sim.neuromod.HEAD_CPG_FREQ_HZ', 'value': 1.5}, {'path': 'sim.neuromod.HEAD_CPG_AMP', 'value': 0.2}, {'path': 'sim.muscles.filter_alpha', 'value': 0.15}], seconds=10.0)
    await evaluate('freq=1.0, amp=0.18, alpha=0.10', [{'path': 'sim.neuromod.HEAD_CPG_FREQ_HZ', 'value': 1.0}, {'path': 'sim.neuromod.HEAD_CPG_AMP', 'value': 0.18}, {'path': 'sim.muscles.filter_alpha', 'value': 0.1}], seconds=10.0)
    post_json('/api/patch', {'patches': [{'path': 'sim.neuromod.HEAD_CPG_FREQ_HZ', 'value': 0.5}, {'path': 'sim.neuromod.HEAD_CPG_AMP', 'value': 0.15}, {'path': 'sim.muscles.filter_alpha', 'value': 0.08}]})
    print('\nrestored FIX-C')
if __name__ == '__main__':
    asyncio.run(main())

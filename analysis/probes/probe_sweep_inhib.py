"""Sweep INHIB_WEIGHT (live) at fixed high angle. The new lab knob lets us
patch this without restart."""
from __future__ import annotations
from analysis.lib.lab_client import (
    LAB_REST as URL_REST,
    LAB_WS as URL_WS,
    post_json,
    get_json,
    unpack_bits,
)
import asyncio, json, sys, time, urllib.request
import numpy as np
import websockets

async def probe(angle, inhib, target=20000):
    label = f'a={angle} inhib={inhib}'
    print(f'\n=== {label} ===')
    post_json('/api/patch', {'patches': [{'path': 'sim.joints.angle_max', 'value': angle}]})
    post_json('/api/apply-pending', {})
    await asyncio.sleep(1.5)
    post_json('/api/patch', {'patches': [{'path': 'sim.muscles.inhib_weight', 'value': float(inhib)}]})
    await asyncio.sleep(0.4)
    async with websockets.connect(URL_WS, max_size=2 ** 24) as ws:
        hello = json.loads(await ws.recv())
        joints = hello['L_body']['joints']
        yaw_idx = np.array([i for i, jn in enumerate(joints) if 'yaw' in jn], dtype=np.int32)
        rows = []
        last_tick = -1
        wall0 = time.time()
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
            ja = [v / 10000.0 for v in d.get('ja', [])]
            yaws = [ja[i] for i in yaw_idx]
            rows.append((tick, yaws))
            if tick >= target:
                break
        if not rows:
            return None
        n = len(rows)
        late = rows[3 * n // 5:]
        all_yaws = np.array([r[1] for r in late])
        per_amp = all_yaws.max(0) - all_yaws.min(0)
        head, mid, tail = (per_amp[1], per_amp[6], per_amp[10])
        print(f'  late head/mid/tail: {head:.2f}/{mid:.2f}/{tail:.2f}')
        return {'angle': angle, 'inhib': inhib, 'head': head, 'mid': mid, 'tail': tail}

async def main():
    angles = [0.4]
    inhibs = [0.5, 0.8, 1.0, 1.2, 1.5]
    results = []
    for ang in angles:
        for inh in inhibs:
            r = await probe(ang, inh, target=18000)
            if r:
                results.append(r)
    print('\n=== summary ===')
    for r in results:
        print(f'  a={r['angle']:.2f} inhib={r['inhib']:.2f}  h/m/t={r['head']:.2f}/{r['mid']:.2f}/{r['tail']:.2f}')
if __name__ == '__main__':
    asyncio.run(main())

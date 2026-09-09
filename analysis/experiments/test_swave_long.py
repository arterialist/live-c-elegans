"""freq=0.8 persistence test at 30k ticks."""
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

async def main():
    target_ticks = 30000
    print(f'applying freq=0.8 + reset, capture until tick {target_ticks}')
    post_json('/api/patch', {'patches': [{'path': 'sim.neuromod.HEAD_CPG_FREQ_HZ', 'value': 0.8}, {'path': 'sim.neuromod.HEAD_CPG_AMP', 'value': 0.15}, {'path': 'sim.muscles.filter_alpha', 'value': 0.08}, {'path': 'sim.neuromod.PROPRIO_TAIL_DECAY', 'value': 0.7}]})
    post_json('/api/reset', {})
    await asyncio.sleep(0.3)
    async with websockets.connect(URL_WS, max_size=2 ** 24) as ws:
        hello = json.loads(await ws.recv())
        joints = hello['L_body']['joints']
        yaw_idx = [i for i, jn in enumerate(joints) if 'yaw' in jn]
        WIN = 3000
        cur_window_start = None
        cur, wins = ([], [])
        wall0 = time.time()
        last_tick = 0
        while True:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
            except asyncio.TimeoutError:
                break
            d = json.loads(msg)
            if d.get('t') != 's':
                continue
            tick = d.get('k', 0)
            last_tick = tick
            ja = [v / 10000.0 for v in d.get('ja', [])]
            yaws = [ja[i] for i in yaw_idx]
            if cur_window_start is None:
                cur_window_start = tick
            cur.append((tick, yaws))
            if tick - cur_window_start >= WIN:
                wins.append(cur)
                cur = []
                cur_window_start = tick
            if tick >= target_ticks:
                break
        if cur:
            wins.append(cur)
        print(f'\ndone: tick {last_tick}, {len(wins)} windows, wall {time.time() - wall0:.1f}s\n')
        print(f'{'win':4s}  {'tick0':>5s}-{'tick1':>5s}  {'pct_=2':>6s} {'pct_>=2':>7s} {'pct_>=3':>7s}  {'head':>5s} {'mid':>5s} {'tail':>5s}  rep mode')
        for i, w in enumerate(wins):
            if not w:
                continue
            zc = [zero_crossings(yaws) for _, yaws in w]
            n = len(zc)
            ge2 = sum((1 for z in zc if z >= 2))
            eq2 = sum((1 for z in zc if z == 2))
            ge3 = sum((1 for z in zc if z >= 3))
            head = max((r[1][1] for r in w)) - min((r[1][1] for r in w))
            mid = max((r[1][6] for r in w)) - min((r[1][6] for r in w))
            tail = max((r[1][10] for r in w)) - min((r[1][10] for r in w))
            mode = max(set(zc), key=zc.count)
            rep_idx = next((j for j, z in enumerate(zc) if z == mode))
            rep = w[rep_idx][1]
            print(f'{i:4d}  {w[0][0]:5d}-{w[-1][0]:5d}  {eq2 / n * 100:5.0f}% {ge2 / n * 100:6.0f}% {ge3 / n * 100:6.0f}%  {head:.3f} {mid:.3f} {tail:.3f}  m={mode}: ' + ' '.join((f'{y:+.2f}' for y in rep)))
if __name__ == '__main__':
    asyncio.run(main())

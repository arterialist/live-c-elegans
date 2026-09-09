"""Long persistence test: reset & capture until ~50k ticks pass.

Tracks per-window oscillation amplitude and saturation count to verify the S-wave
holds up over many minutes of sim time.
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
import sys
import time
import urllib.request
import websockets

async def main():
    target_ticks = int(sys.argv[1]) if len(sys.argv) > 1 else 50000
    print(f'reset & capture until tick {target_ticks}')
    post_json('/api/reset', {})
    await asyncio.sleep(0.4)
    async with websockets.connect(URL_WS, max_size=2 ** 24) as ws:
        hello = json.loads(await ws.recv())
        joints = hello['L_body']['joints']
        names = hello['L']['nm']
        yaw_idx = [i for i, jn in enumerate(joints) if 'yaw' in jn]
        db1 = names.index('DB1')
        vb1 = names.index('VB1')
        WIN = 2500
        cur_window_start = None
        cur = []
        wins = []
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
            ma = [v / 10000.0 for v in d.get('ma', [])]
            Si = d.get('Si', [])
            db_s = Si[db1] / 10000.0 if 0 <= db1 < len(Si) else 0.0
            vb_s = Si[vb1] / 10000.0 if 0 <= vb1 < len(Si) else 0.0
            yaws = [ja[i] for i in yaw_idx]
            if cur_window_start is None:
                cur_window_start = tick
            cur.append((tick, db_s, vb_s, yaws, ma))
            if tick - cur_window_start >= WIN:
                wins.append(cur)
                cur = []
                cur_window_start = tick
            if tick >= target_ticks:
                break
        if cur:
            wins.append(cur)
        wall = time.time() - wall0
        print(f'\ndone: last tick {last_tick}, {len(wins)} windows, wall time {wall:.1f}s')
        print(f'\n{'win':4s}  {'tick0':>6s}-{'tick1':>6s}  {'head_amp':>8s} {'mid_amp':>7s} {'tail_amp':>8s}  {'yaws_full_amp':>13s}  {'sat_pct':>7s}  {'DB1amp':>6s}  {'final_yaws':>40s}')
        for i, w in enumerate(wins):
            if not w:
                continue
            head_yaws = [r[3][1] for r in w]
            mid_yaws = [r[3][6] for r in w]
            tail_yaws = [r[3][10] for r in w]
            all_yaws = [v for r in w for v in r[3]]
            sat = sum((1 for r in w if all((abs(y) >= 0.14 for y in r[3]))))
            db_amp = max((r[1] for r in w)) - min((r[1] for r in w))
            final_yaws = w[-1][3]
            yaws_str = '[' + ' '.join((f'{y:+.2f}' for y in final_yaws)) + ']'
            print(f'{i:4d}  {w[0][0]:6d}-{w[-1][0]:6d}  {max(head_yaws) - min(head_yaws):8.3f} {max(mid_yaws) - min(mid_yaws):7.3f} {max(tail_yaws) - min(tail_yaws):8.3f}  {max(all_yaws) - min(all_yaws):13.3f}  {sat / len(w) * 100:6.1f}%  {db_amp:6.2f}  {yaws_str}')
if __name__ == '__main__':
    asyncio.run(main())

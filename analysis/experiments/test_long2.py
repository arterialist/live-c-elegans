"""Multi-minute capture to find when oscillation breaks down."""
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

async def main():
    seconds = float(__import__('sys').argv[1]) if len(__import__('sys').argv) > 1 else 60.0
    print(f'reset and capture {seconds}s')
    post_json('/api/reset', {})
    await asyncio.sleep(0.3)
    async with websockets.connect(URL_WS, max_size=2 ** 24) as ws:
        hello = json.loads(await ws.recv())
        joints = hello['L_body']['joints']
        names = hello['L']['nm']
        yaw_idx = [i for i, jn in enumerate(joints) if 'yaw' in jn]
        db1 = names.index('DB1')
        vb1 = names.index('VB1')
        deadline = time.time() + seconds
        window = 5.0
        win_end = time.time() + window
        cur = []
        wins = []
        while time.time() < deadline:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
            except asyncio.TimeoutError:
                break
            d = json.loads(msg)
            if d.get('t') != 's':
                continue
            tick = d.get('k', 0)
            ja = [v / 10000.0 for v in d.get('ja', [])]
            ma = [v / 10000.0 for v in d.get('ma', [])]
            Si = d.get('Si', [])
            db_s = Si[db1] / 10000.0 if 0 <= db1 < len(Si) else 0.0
            vb_s = Si[vb1] / 10000.0 if 0 <= vb1 < len(Si) else 0.0
            yaws = [ja[i] for i in yaw_idx]
            cur.append((tick, db_s, vb_s, yaws, ma))
            if time.time() >= win_end:
                wins.append(cur)
                cur = []
                win_end = time.time() + window
        if cur:
            wins.append(cur)
        print(f'\n{len(wins)} windows of {window}s captured\n')
        print(f'{'win':3s} {'tick0':>6s}-{'tick1':>6s}  {'mid_yaw_amp':>11s}  {'mid_yaw_mean':>12s}  {'mid_dv_last':>11s}  {'DB.S_amp':>9s}  {'sat_count':>9s}')
        for i, w in enumerate(wins):
            if not w:
                continue
            mid_yaws = [row[3][6] for row in w]
            yaw_amp = max(mid_yaws) - min(mid_yaws)
            yaw_mean = sum(mid_yaws) / len(mid_yaws)
            db_vals = [row[1] for row in w]
            db_amp = max(db_vals) - min(db_vals)
            sat = sum((1 for row in w if all((abs(y) >= 0.14 for y in row[3]))))
            last_ma = w[-1][4]
            mid_dv = (last_ma[6 * 4] + last_ma[6 * 4 + 1]) / 2 - (last_ma[6 * 4 + 2] + last_ma[6 * 4 + 3]) / 2
            print(f'{i:3d} {w[0][0]:6d}-{w[-1][0]:6d}  {yaw_amp:11.3f}  {yaw_mean:+12.3f}  {mid_dv:+11.3f}  {db_amp:9.3f}  {sat:5d}/{len(w)}')
if __name__ == '__main__':
    asyncio.run(main())

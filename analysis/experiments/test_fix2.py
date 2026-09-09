"""Validate the proposed calibration: stronger CPG, faster muscle filter, stronger tail decay."""
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

async def windowed_capture(seconds, label, window=5.0):
    print(f'\n>>> {label}: capturing {seconds}s (windows of {window}s)')
    async with websockets.connect(URL_WS, max_size=2 ** 24) as ws:
        hello = json.loads(await ws.recv())
        joints = hello['L_body']['joints']
        names = hello['L']['nm']
        yaw_idx = [i for i, jn in enumerate(joints) if 'yaw' in jn]
        db_ids = [(nm, names.index(nm)) for nm in ['DB1', 'DB2', 'DB3', 'DB4'] if nm in names]
        vb_ids = [(nm, names.index(nm)) for nm in ['VB1', 'VB2', 'VB3', 'VB4'] if nm in names]
        deadline = time.time() + seconds
        win_end = time.time() + window
        cur, wins = ([], [])
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
            yaws = [ja[i] for i in yaw_idx]
            db_s = [Si[i] / 10000.0 if 0 <= i < len(Si) else 0.0 for _, i in db_ids]
            vb_s = [Si[i] / 10000.0 if 0 <= i < len(Si) else 0.0 for _, i in vb_ids]
            cur.append((tick, yaws, ma, db_s, vb_s))
            if time.time() >= win_end:
                wins.append(cur)
                cur = []
                win_end = time.time() + window
        if cur:
            wins.append(cur)
        for i, w in enumerate(wins):
            if not w:
                continue
            mid_yaws = [row[1][6] for row in w]
            head_yaws = [row[1][1] for row in w]
            tail_yaws = [row[1][10] for row in w]
            sat = sum((1 for row in w if all((abs(y) >= 0.14 for y in row[1]))))
            db_oscillation = max((row[3][0] for row in w)) - min((row[3][0] for row in w))
            vb_oscillation = max((row[4][0] for row in w)) - min((row[4][0] for row in w))
            print(f'  win{i:2d}  t={w[0][0]:5d}-{w[-1][0]:5d}  head_amp={max(head_yaws) - min(head_yaws):.3f}  mid_amp={max(mid_yaws) - min(mid_yaws):.3f}  tail_amp={max(tail_yaws) - min(tail_yaws):.3f}  sat={sat:3d}/{len(w)}  DB1amp={db_oscillation:.2f} VB1amp={vb_oscillation:.2f}')
        last = wins[-1][-1] if wins and wins[-1] else None
        if last:
            print(f'  final yaws: ' + ' '.join((f'{y:+.3f}' for y in last[1])))
            print(f'  final DB:   ' + ' '.join((f'{nm}={s:+.2f}' for nm, _ in db_ids for s in [last[3][0]])))

async def run(label, patches, seconds):
    if patches:
        r = post_json('/api/patch', {'patches': patches})
        print(f'\n[{label}] applied={r.get('applied')}')
    print(f'[{label}] reset')
    post_json('/api/reset', {})
    await asyncio.sleep(0.4)
    await windowed_capture(seconds, label)

async def main():
    defaults = [{'path': 'sim.muscles.filter_alpha', 'value': 0.03}, {'path': 'sim.neuromod.HEAD_CPG_AMP', 'value': 0.08}, {'path': 'sim.neuromod.HEAD_CPG_FREQ_HZ', 'value': 0.4}, {'path': 'sim.neuromod.PROPRIO_MOTOR_GAIN', 'value': 0.1}, {'path': 'sim.neuromod.PROPRIO_TAIL_DECAY', 'value': 0.5}, {'path': 'sim.mujoco.opt.density', 'value': 2000.0}]
    await run('DEFAULTS (60s)', defaults, 60.0)
    await run('FIX-A: CPG_AMP=0.15 only', [{'path': 'sim.neuromod.HEAD_CPG_AMP', 'value': 0.15}], 60.0)
    await run('FIX-B: CPG_AMP=0.15, alpha=0.08', [{'path': 'sim.neuromod.HEAD_CPG_AMP', 'value': 0.15}, {'path': 'sim.muscles.filter_alpha', 'value': 0.08}], 60.0)
    await run('FIX-C: full recipe', [{'path': 'sim.neuromod.HEAD_CPG_AMP', 'value': 0.15}, {'path': 'sim.muscles.filter_alpha', 'value': 0.08}, {'path': 'sim.neuromod.PROPRIO_TAIL_DECAY', 'value': 0.7}, {'path': 'sim.neuromod.HEAD_CPG_FREQ_HZ', 'value': 0.5}], 60.0)
if __name__ == '__main__':
    asyncio.run(main())

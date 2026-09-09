"""Long capture to see lockup develop. Multiple param sweeps."""
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

async def capture_windows(seconds, window_size=2.0):
    """Return per-window statistics on yaw amp."""
    async with websockets.connect(URL_WS, max_size=2 ** 24) as ws:
        hello = json.loads(await ws.recv())
        joints = hello['L_body']['joints']
        yaw_idx = [i for i, jn in enumerate(joints) if 'yaw' in jn]
        names = hello['L']['nm']
        db1 = names.index('DB1')
        vb1 = names.index('VB1')
        windows = []
        cur_window = []
        deadline = time.time() + seconds
        window_end = time.time() + window_size
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
            cur_window.append((tick, db_s, vb_s, yaws, ma))
            if time.time() >= window_end:
                if cur_window:
                    windows.append(cur_window)
                cur_window = []
                window_end = time.time() + window_size
        if cur_window:
            windows.append(cur_window)
        return windows

def report_window(idx, w):
    if not w:
        return
    n = len(w)
    yaws_all = [v for row in w for v in row[3]]
    db = [r[1] for r in w]
    vb = [r[2] for r in w]
    last_yaws = w[-1][3]
    last_ma = w[-1][4]
    seg_dv = []
    for s in range(12):
        b = s * 4
        if b + 3 < len(last_ma):
            d = (last_ma[b] + last_ma[b + 1]) / 2
            v = (last_ma[b + 2] + last_ma[b + 3]) / 2
            seg_dv.append(d - v)
    print(f'  win{idx} t={w[0][0]:5d}-{w[-1][0]:5d}  yaw[{min(yaws_all):+.3f},{max(yaws_all):+.3f}]  DB[{min(db):+.3f},{max(db):+.3f}]  VB[{min(vb):+.3f},{max(vb):+.3f}]')
    print(f'        last_yaws: ' + ' '.join((f'{y:+.2f}' for y in last_yaws)))
    print(f'        D-V last:  ' + ' '.join((f'{x:+.2f}' for x in seg_dv)))

async def run_exp(label, patches, seconds=30.0):
    if patches:
        r = post_json('/api/patch', {'patches': patches})
        print(f'[{label}] applied={r.get('applied')}')
    print(f'[{label}] reset')
    post_json('/api/reset', {})
    await asyncio.sleep(0.4)
    windows = await capture_windows(seconds, window_size=4.0)
    print(f'[{label}] {len(windows)} windows of ~4s:')
    for i, w in enumerate(windows):
        report_window(i, w)

async def main():
    await run_exp('baseline (defaults)', [], seconds=24.0)
    await run_exp('alpha=0.10', [{'path': 'sim.muscles.filter_alpha', 'value': 0.1}], seconds=24.0)
    await run_exp('alpha=0.05, density=500', [{'path': 'sim.muscles.filter_alpha', 'value': 0.05}, {'path': 'sim.mujoco.opt.density', 'value': 500.0}], seconds=24.0)
if __name__ == '__main__':
    asyncio.run(main())

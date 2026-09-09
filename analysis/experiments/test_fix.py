"""Reset sim, apply patches, capture, report.

Sequence of experiments. Each: reset → optional patches → capture for N seconds → report yaw range / DB1.S range / muscle balance.
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
import base64
import json
import sys
import time
import urllib.request
import websockets

async def capture(seconds: float) -> dict:
    async with websockets.connect(URL_WS, max_size=2 ** 24) as ws:
        hello = json.loads(await ws.recv())
        names = hello['L']['nm']
        joints = hello['L_body']['joints']
        muscles = hello['L_body']['muscles']
        yaw_idx = [i for i, jn in enumerate(joints) if 'yaw' in jn]
        db1 = names.index('DB1')
        vb1 = names.index('VB1')
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
            tick = d.get('k', 0)
            ja = [v / 10000.0 for v in d.get('ja', [])]
            ma = [v / 10000.0 for v in d.get('ma', [])]
            Si = d.get('Si', [])
            db_s = Si[db1] / 10000.0 if 0 <= db1 < len(Si) else 0.0
            vb_s = Si[vb1] / 10000.0 if 0 <= vb1 < len(Si) else 0.0
            rows.append((tick, db_s, vb_s, ja, ma))
        if not rows:
            return {'n': 0}
        n = len(rows)
        yaws = [[row[3][i] for i in yaw_idx] for row in rows]
        per_yaw_mean = [sum((yaws[t][j] for t in range(n))) / n for j in range(len(yaw_idx))]
        per_yaw_min = [min((yaws[t][j] for t in range(n))) for j in range(len(yaw_idx))]
        per_yaw_max = [max((yaws[t][j] for t in range(n))) for j in range(len(yaw_idx))]
        per_yaw_amp = [per_yaw_max[j] - per_yaw_min[j] for j in range(len(yaw_idx))]
        all_yaws = [v for row in yaws for v in row]
        all_min = min(all_yaws)
        all_max = max(all_yaws)
        db_vals = [r[1] for r in rows]
        vb_vals = [r[2] for r in rows]
        last_ma = rows[-1][4]
        seg_d_minus_v = []
        for seg in range(12):
            base = seg * 4
            if base + 3 < len(last_ma):
                d = (last_ma[base] + last_ma[base + 1]) / 2
                v = (last_ma[base + 2] + last_ma[base + 3]) / 2
                seg_d_minus_v.append(d - v)
        return {'n': n, 'tick0': rows[0][0], 'tick1': rows[-1][0], 'all_yaw_min': all_min, 'all_yaw_max': all_max, 'all_yaw_amp': all_max - all_min, 'per_yaw_amp': per_yaw_amp, 'per_yaw_mean': per_yaw_mean, 'db_min': min(db_vals), 'db_max': max(db_vals), 'db_mean': sum(db_vals) / n, 'vb_min': min(vb_vals), 'vb_max': max(vb_vals), 'vb_mean': sum(vb_vals) / n, 'seg_d_minus_v_last': seg_d_minus_v, 'yaws_last': rows[-1][3][1::2], 'first_5_yaws_last': [rows[-1][3][i] for i in yaw_idx]}

def report(label: str, stats: dict) -> None:
    if stats.get('n', 0) == 0:
        print(f'\n=== {label} === (no data)')
        return
    print(f'\n=== {label} === (n={stats['n']}, ticks {stats['tick0']}..{stats['tick1']})')
    print(f'  yaw range across body+time: [{stats['all_yaw_min']:+.3f}, {stats['all_yaw_max']:+.3f}] amp={stats['all_yaw_amp']:.3f}')
    print(f'  DB1.S [{stats['db_min']:+.3f}, {stats['db_max']:+.3f}] mean={stats['db_mean']:+.3f}')
    print(f'  VB1.S [{stats['vb_min']:+.3f}, {stats['vb_max']:+.3f}] mean={stats['vb_mean']:+.3f}')
    print(f'  per-yaw amp: ' + ' '.join((f'{a:.3f}' for a in stats['per_yaw_amp'])))
    print(f'  per-yaw mean: ' + ' '.join((f'{m:+.3f}' for m in stats['per_yaw_mean'])))
    print(f'  last yaws: ' + ' '.join((f'{y:+.3f}' for y in stats['first_5_yaws_last'])))
    print(f'  last D-V per seg: ' + ' '.join((f'{x:+.2f}' for x in stats['seg_d_minus_v_last'])))

async def run_experiment(label: str, patches: list[dict], capture_seconds: float=8.0, post_reset_wait: float=0.5) -> None:
    if patches:
        r = post_json('/api/patch', {'patches': patches})
        print(f'[{label}] patch result: applied={r.get('applied', [])}')
    rr = post_json('/api/reset', {})
    print(f'[{label}] reset: {rr}')
    await asyncio.sleep(post_reset_wait)
    stats = await capture(capture_seconds)
    report(label, stats)

async def main() -> None:
    await run_experiment('baseline (current params)', [], capture_seconds=8.0)
    await run_experiment('HEAD_CPG_AMP=0.30', [{'path': 'sim.neuromod.HEAD_CPG_AMP', 'value': 0.3}], capture_seconds=8.0)
    await run_experiment('PROPRIO=0, CPG_AMP=0.30', [{'path': 'sim.neuromod.PROPRIO_MOTOR_GAIN', 'value': 0.0}, {'path': 'sim.neuromod.HEAD_CPG_AMP', 'value': 0.3}], capture_seconds=8.0)
    await run_experiment('alpha=0.15, PROPRIO=0.05, CPG_AMP=0.20', [{'path': 'sim.muscles.filter_alpha', 'value': 0.15}, {'path': 'sim.neuromod.PROPRIO_MOTOR_GAIN', 'value': 0.05}, {'path': 'sim.neuromod.HEAD_CPG_AMP', 'value': 0.2}], capture_seconds=8.0)
if __name__ == '__main__':
    asyncio.run(main())

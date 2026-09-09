"""Sweep JOINT_ANGLE_MAX_RAD and measure body curvature.

Each angle_max value is a rebuild patch: must go via /api/patch (lands in pending) then
/api/apply-pending (commits + resets sim). After rebuild, capture for a few seconds and
report:
  - per-joint amplitude utilization (how close to the new max joints actually swing)
  - total curl angle in degrees per half-wave (the S-arc magnitude)
  - zero-crossings (preserve true S?)
  - saturation rate (any lockup?)
  - stability (head/mid/tail amp present)
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
import math
import sys
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

def half_wave_arc_deg(yaws):
    """Sum of absolute yaws between zero crossings, in degrees.
    Returns the largest single half-wave arc found."""
    runs = []
    cur = 0.0
    cur_sign = 0
    for y in yaws:
        s = 1 if y > 0.03 else -1 if y < -0.03 else 0
        if s == 0:
            if cur_sign != 0:
                runs.append(cur)
                cur = 0.0
                cur_sign = 0
            continue
        if cur_sign == 0:
            cur_sign = s
            cur = abs(y)
        elif s == cur_sign:
            cur += abs(y)
        else:
            runs.append(cur)
            cur = abs(y)
            cur_sign = s
    if cur_sign != 0:
        runs.append(cur)
    if not runs:
        return 0.0
    return math.degrees(max(runs))

async def snap(seconds):
    async with websockets.connect(URL_WS, max_size=2 ** 24) as ws:
        hello = json.loads(await ws.recv())
        joints = hello['L_body']['joints']
        yaw_idx = [i for i, jn in enumerate(joints) if 'yaw' in jn]
        rows = []
        deadline = time.time() + seconds
        while time.time() < deadline:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
            except asyncio.TimeoutError:
                break
            d = json.loads(msg)
            if d.get('t') != 's':
                continue
            ja = [v / 10000.0 for v in d.get('ja', [])]
            yaws = [ja[i] for i in yaw_idx]
            rows.append((d.get('k', 0), yaws))
        return rows

async def evaluate(angle_max, seconds=20.0):
    label = f'angle={angle_max}'
    patch_res = post_json('/api/patch', {'patches': [{'path': 'sim.joints.angle_max', 'value': float(angle_max)}]})
    apply_res = post_json('/api/apply-pending', {})
    print(f'\n[{label}] applied={apply_res.get('applied')} failed={apply_res.get('failed')}')
    await asyncio.sleep(1.5)
    rows = await snap(seconds)
    if not rows:
        print(f'[{label}] no data')
        return None
    n = len(rows)
    n_j = len(rows[0][1])
    per_amp = [max((r[1][j] for r in rows)) - min((r[1][j] for r in rows)) for j in range(n_j)]
    per_max_abs = [max((abs(r[1][j]) for r in rows)) for j in range(n_j)]
    utilization = [m / angle_max for m in per_max_abs]
    util_avg = sum(utilization) / len(utilization)
    zc = [zero_crossings(yaws) for _, yaws in rows]
    pct_ge2 = sum((1 for z in zc if z >= 2)) / n * 100
    arcs = [half_wave_arc_deg(yaws) for _, yaws in rows]
    avg_arc = sum(arcs) / n
    max_arc = max(arcs)
    sat_thresh = 0.9 * angle_max
    sat_count = sum((1 for _, yaws in rows if all((abs(y) >= sat_thresh for y in yaws))))
    sat_pct = sat_count / n * 100
    head = sum(per_amp[:3]) / 3
    mid = sum(per_amp[5:8]) / 3
    tail = sum(per_amp[-3:]) / 3
    s_indices = [i for i, z in enumerate(zc) if z == 2]
    rep_idx = s_indices[len(s_indices) // 2] if s_indices else 0
    rep = rows[rep_idx][1]
    rep_arc = half_wave_arc_deg(rep)
    print(f'  pct_>=2 (true S): {pct_ge2:.0f}%   sat_pct: {sat_pct:.1f}%')
    print(f'  per-joint amp: ' + ' '.join((f'{a:.2f}' for a in per_amp)))
    print(f'  per-joint utilization (|y|/max): ' + ' '.join((f'{u:.2f}' for u in utilization)) + f'  avg={util_avg:.2f}')
    print(f'  half-wave arc (deg):  avg={avg_arc:.0f}°  max={max_arc:.0f}°')
    print(f'  head/mid/tail amp: {head:.3f}/{mid:.3f}/{tail:.3f}')
    print(f'  rep S frame ({rep_arc:.0f}° arc): ' + ' '.join((f'{y:+.2f}' for y in rep)))
    return {'angle_max': angle_max, 'pct_ge2': pct_ge2, 'util_avg': util_avg, 'avg_arc_deg': avg_arc, 'max_arc_deg': max_arc, 'head': head, 'mid': mid, 'tail': tail, 'sat_pct': sat_pct}

async def main():
    sweep = [0.2, 0.3, 0.4, 0.5, 0.6, 0.8]
    results = []
    for a in sweep:
        r = await evaluate(a, seconds=18.0)
        if r:
            results.append(r)
    print('\n=== summary (target: real-worm half-wave arc ≈ 90-130°) ===')
    print(f'{'angle_max':>9s}  {'avg_arc':>7s}  {'max_arc':>7s}  {'utiliz':>6s}  {'pct≥2':>5s}  {'sat%':>5s}  {'head/mid/tail':>20s}')
    for r in results:
        print(f'  {r['angle_max']:7.2f}  {r['avg_arc_deg']:6.0f}°  {r['max_arc_deg']:6.0f}°  {r['util_avg']:5.2f}  {r['pct_ge2']:4.0f}%  {r['sat_pct']:4.1f}%  {r['head']:.2f}/{r['mid']:.2f}/{r['tail']:.2f}')
if __name__ == '__main__':
    asyncio.run(main())

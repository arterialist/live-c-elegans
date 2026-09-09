"""Find stable-S config: angle × freq × amp where pct≥2 holds for many windows.

Each test runs 8000 ticks (~60s wall) and checks LATE-window stats (final 3 windows of
~3k ticks each), not early transient. Reports stability = pct≥2 in last 3k ticks.
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
import time
import urllib.request
import websockets

def zero_crossings(yaws, deadband=0.04):
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

def half_wave_arc_deg(yaws, deadband=0.04):
    runs, cur, sign = ([], 0.0, 0)
    for y in yaws:
        s = 1 if y > deadband else -1 if y < -deadband else 0
        if s == 0:
            if sign != 0:
                runs.append(cur)
                cur = 0.0
                sign = 0
            continue
        if sign == 0:
            sign = s
            cur = abs(y)
        elif s == sign:
            cur += abs(y)
        else:
            runs.append(cur)
            cur = abs(y)
            sign = s
    if sign != 0:
        runs.append(cur)
    return math.degrees(max(runs)) if runs else 0.0

async def evaluate(angle, freq, amp, alpha, ticks=8000, do_rebuild=False):
    if do_rebuild:
        post_json('/api/patch', {'patches': [{'path': 'sim.joints.angle_max', 'value': float(angle)}]})
        post_json('/api/apply-pending', {})
        await asyncio.sleep(1.5)
    post_json('/api/patch', {'patches': [{'path': 'sim.neuromod.HEAD_CPG_FREQ_HZ', 'value': float(freq)}, {'path': 'sim.neuromod.HEAD_CPG_AMP', 'value': float(amp)}, {'path': 'sim.muscles.filter_alpha', 'value': float(alpha)}]})
    await asyncio.sleep(0.4)
    async with websockets.connect(URL_WS, max_size=2 ** 24) as ws:
        hello = json.loads(await ws.recv())
        joints = hello['L_body']['joints']
        yaw_idx = [i for i, jn in enumerate(joints) if 'yaw' in jn]
        rows = []
        start_tick = None
        while True:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
            except asyncio.TimeoutError:
                break
            d = json.loads(msg)
            if d.get('t') != 's':
                continue
            tick = d.get('k', 0)
            if start_tick is None:
                start_tick = tick
            ja = [v / 10000.0 for v in d.get('ja', [])]
            yaws = [ja[i] for i in yaw_idx]
            rows.append((tick, yaws))
            if tick - start_tick >= ticks:
                break
        if not rows:
            return None
        n = len(rows)
        late = rows[2 * n // 3:]
        nl = len(late)
        zc_late = [zero_crossings(yaws) for _, yaws in late]
        pct_eq2_late = sum((1 for z in zc_late if z == 2)) / nl * 100
        pct_ge2_late = sum((1 for z in zc_late if z >= 2)) / nl * 100
        head = max((r[1][1] for r in late)) - min((r[1][1] for r in late))
        mid = max((r[1][6] for r in late)) - min((r[1][6] for r in late))
        tail = max((r[1][10] for r in late)) - min((r[1][10] for r in late))
        arcs = [half_wave_arc_deg(yaws) for _, yaws in late if zero_crossings(yaws) >= 2]
        avg_arc = sum(arcs) / len(arcs) if arcs else 0
        s_idxs = [i for i, z in enumerate(zc_late) if z >= 2]
        rep = late[s_idxs[len(s_idxs) // 2]][1] if s_idxs else late[-1][1]
        rep_zc = zero_crossings(rep)
        print(f'  a={angle:.2f} f={freq:.1f} amp={amp:.2f} α={alpha:.2f}  LATE pct≥2:{pct_ge2_late:4.0f}%  S-arc:{avg_arc:4.0f}°  h/m/t:{head:.2f}/{mid:.2f}/{tail:.2f}  rep zc={rep_zc}: ' + ' '.join((f'{y:+.2f}' for y in rep)))
        return {'angle': angle, 'freq': freq, 'amp': amp, 'alpha': alpha, 'pct_ge2': pct_ge2_late, 's_arc': avg_arc, 'h': head, 'm': mid, 't': tail}

async def main():
    results = []
    for angle in [0.2, 0.25, 0.3]:
        print(f'\n--- angle_max={angle} ---')
        for j, (freq, amp, alpha) in enumerate([(0.6, 0.2, 0.08), (0.8, 0.22, 0.1), (1.0, 0.25, 0.12), (1.2, 0.28, 0.15)]):
            r = await evaluate(angle, freq, amp, alpha, ticks=8000, do_rebuild=j == 0)
            if r:
                results.append(r)
    print('\n=== ranked by sustained pct≥2 (steady-state S-fraction) ===')
    for r in sorted([r for r in results if r['pct_ge2'] > 5], key=lambda x: -x['pct_ge2'])[:10]:
        print(f'  a={r['angle']:.2f} f={r['freq']:.1f} amp={r['amp']:.2f} α={r['alpha']:.2f}  pct≥2:{r['pct_ge2']:3.0f}%  S-arc:{r['s_arc']:.0f}°  h/m/t:{r['h']:.2f}/{r['m']:.2f}/{r['t']:.2f}')
if __name__ == '__main__':
    asyncio.run(main())

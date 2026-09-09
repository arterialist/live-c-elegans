"""Long persistence + best-shape verification for the angle=0.35 / freq=1.4 config."""
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

async def main():
    target = 30000
    print('applying angle=0.35 (rebuild), freq=1.4, amp=0.22, alpha=0.12')
    post_json('/api/patch', {'patches': [{'path': 'sim.joints.angle_max', 'value': 0.35}]})
    post_json('/api/apply-pending', {})
    await asyncio.sleep(1.5)
    post_json('/api/patch', {'patches': [{'path': 'sim.neuromod.HEAD_CPG_FREQ_HZ', 'value': 1.4}, {'path': 'sim.neuromod.HEAD_CPG_AMP', 'value': 0.22}, {'path': 'sim.muscles.filter_alpha', 'value': 0.12}]})
    await asyncio.sleep(0.4)
    async with websockets.connect(URL_WS, max_size=2 ** 24) as ws:
        hello = json.loads(await ws.recv())
        joints = hello['L_body']['joints']
        yaw_idx = [i for i, jn in enumerate(joints) if 'yaw' in jn]
        WIN = 3000
        cur_start, cur, wins = (None, [], [])
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
            if cur_start is None:
                cur_start = tick
            cur.append((tick, yaws))
            if tick - cur_start >= WIN:
                wins.append(cur)
                cur = []
                cur_start = tick
            if tick >= target:
                break
        if cur:
            wins.append(cur)
        print(f'\ndone tick {last_tick} in {time.time() - wall0:.1f}s, {len(wins)} windows\n')
        print(f'{'win':4s} {'tick':>6s}  {'pct=2':>5s} {'pct≥2':>5s} {'pct≥3':>5s}  {'S-arc':>5s}  {'h':>4s} {'m':>4s} {'t':>4s}  rep zc/arc')
        all_S_arcs = []
        all_pct_ge2 = []
        for i, w in enumerate(wins):
            if not w:
                continue
            n = len(w)
            zc = [zero_crossings(yaws) for _, yaws in w]
            pct_eq2 = sum((1 for z in zc if z == 2)) / n * 100
            pct_ge2 = sum((1 for z in zc if z >= 2)) / n * 100
            pct_ge3 = sum((1 for z in zc if z >= 3)) / n * 100
            arcs = [half_wave_arc_deg(yaws) for _, yaws in w if zero_crossings(yaws) >= 2]
            avg_arc = sum(arcs) / len(arcs) if arcs else 0
            all_S_arcs.extend(arcs)
            all_pct_ge2.append(pct_ge2)
            n_j = len(w[0][1])
            head = max((r[1][1] for r in w)) - min((r[1][1] for r in w))
            mid = max((r[1][6] for r in w)) - min((r[1][6] for r in w))
            tail = max((r[1][10] for r in w)) - min((r[1][10] for r in w))
            s_idxs = [j for j, z in enumerate(zc) if z >= 2]
            rep = w[s_idxs[len(s_idxs) // 2]][1] if s_idxs else w[-1][1]
            rep_zc = zero_crossings(rep)
            rep_arc = half_wave_arc_deg(rep)
            print(f'{i:4d} {w[-1][0]:6d}  {pct_eq2:4.0f}% {pct_ge2:4.0f}% {pct_ge3:4.0f}%  {avg_arc:4.0f}°  {head:.2f} {mid:.2f} {tail:.2f}  zc={rep_zc} {rep_arc:.0f}°: ' + ' '.join((f'{y:+.2f}' for y in rep)))
        if all_pct_ge2:
            avg_ge2 = sum(all_pct_ge2) / len(all_pct_ge2)
            avg_arc = sum(all_S_arcs) / len(all_S_arcs) if all_S_arcs else 0
            print(f'\nOVERALL: avg pct≥2 = {avg_ge2:.0f}%, avg S-arc = {avg_arc:.0f}°')
if __name__ == '__main__':
    asyncio.run(main())

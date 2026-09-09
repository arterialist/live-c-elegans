"""30k validation on a=0.30, f=0.6, amp=0.20, α=0.08."""
from __future__ import annotations
from analysis.lib.lab_client import (
    LAB_REST as URL_REST,
    LAB_WS as URL_WS,
    post_json,
    get_json,
    unpack_bits,
)
import asyncio, json, math, time, urllib.request, websockets

def zc(yaws, db=0.04):
    c = 0
    p = None
    for y in yaws:
        if abs(y) < db:
            continue
        s = 1 if y > 0 else -1
        if p is not None and s != p:
            c += 1
        p = s
    return c

def arc_deg(yaws, db=0.04):
    runs, cur, sign = ([], 0.0, 0)
    for y in yaws:
        s = 1 if y > db else -1 if y < -db else 0
        if s == 0:
            if sign != 0:
                runs.append(cur)
                cur = 0
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
    print('apply: a=0.30 (rebuild), f=0.6, amp=0.20, α=0.08 + reset')
    post_json('/api/patch', {'patches': [{'path': 'sim.joints.angle_max', 'value': 0.3}]})
    post_json('/api/apply-pending', {})
    await asyncio.sleep(1.5)
    post_json('/api/patch', {'patches': [{'path': 'sim.neuromod.HEAD_CPG_FREQ_HZ', 'value': 0.6}, {'path': 'sim.neuromod.HEAD_CPG_AMP', 'value': 0.2}, {'path': 'sim.muscles.filter_alpha', 'value': 0.08}]})
    await asyncio.sleep(0.4)
    async with websockets.connect(URL_WS, max_size=2 ** 24) as ws:
        hello = json.loads(await ws.recv())
        joints = hello['L_body']['joints']
        yaw_idx = [i for i, jn in enumerate(joints) if 'yaw' in jn]
        WIN = 3000
        cur_start, cur, wins = (None, [], [])
        wall0 = time.time()
        last_t = 0
        while True:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
            except asyncio.TimeoutError:
                break
            d = json.loads(msg)
            if d.get('t') != 's':
                continue
            tick = d.get('k', 0)
            last_t = tick
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
        print(f'\ndone tick {last_t} in {time.time() - wall0:.1f}s, {len(wins)} windows\n')
        print(f'{'win':>3s} {'tick':>6s}  {'pct=2':>5s} {'pct≥2':>5s} {'pct≥3':>5s}  {'arc':>4s}  {'h':>4s} {'m':>4s} {'t':>4s}  rep')
        for i, w in enumerate(wins):
            n = len(w)
            zcs = [zc(yaws) for _, yaws in w]
            pe2 = sum((1 for z in zcs if z == 2)) / n * 100
            pg2 = sum((1 for z in zcs if z >= 2)) / n * 100
            pg3 = sum((1 for z in zcs if z >= 3)) / n * 100
            arcs = [arc_deg(yaws) for _, yaws in w if zc(yaws) >= 2]
            avg = sum(arcs) / len(arcs) if arcs else 0
            head = max((r[1][1] for r in w)) - min((r[1][1] for r in w))
            mid = max((r[1][6] for r in w)) - min((r[1][6] for r in w))
            tail = max((r[1][10] for r in w)) - min((r[1][10] for r in w))
            sxs = [j for j, z in enumerate(zcs) if z >= 2]
            rep = w[sxs[len(sxs) // 2]][1] if sxs else w[-1][1]
            rep_zc = zc(rep)
            print(f'{i:>3d} {w[-1][0]:>6d}  {pe2:4.0f}% {pg2:4.0f}% {pg3:4.0f}%  {avg:3.0f}°  {head:.2f} {mid:.2f} {tail:.2f}  zc={rep_zc}: ' + ' '.join((f'{y:+.2f}' for y in rep)))
if __name__ == '__main__':
    asyncio.run(main())

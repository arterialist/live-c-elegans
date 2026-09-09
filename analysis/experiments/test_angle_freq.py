"""Joint of angle_max × freq sweep — find the (angle, freq) that makes a sustained S
matching real C. elegans (~25-40° per joint, ~90-100° arc per half-wave, two visible
half-waves)."""
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

async def evaluate(angle, freq, amp, alpha, seconds=14.0, do_rebuild=False):
    label = f'a={angle} f={freq} amp={amp} α={alpha}'
    if do_rebuild:
        post_json('/api/patch', {'patches': [{'path': 'sim.joints.angle_max', 'value': float(angle)}]})
        post_json('/api/apply-pending', {})
        await asyncio.sleep(1.5)
    post_json('/api/patch', {'patches': [{'path': 'sim.neuromod.HEAD_CPG_FREQ_HZ', 'value': float(freq)}, {'path': 'sim.neuromod.HEAD_CPG_AMP', 'value': float(amp)}, {'path': 'sim.muscles.filter_alpha', 'value': float(alpha)}]})
    await asyncio.sleep(0.3)
    rows = await snap(seconds)
    if not rows:
        return None
    n = len(rows)
    n_j = len(rows[0][1])
    per_amp = [max((r[1][j] for r in rows)) - min((r[1][j] for r in rows)) for j in range(n_j)]
    zc = [zero_crossings(yaws) for _, yaws in rows]
    pct_eq2 = sum((1 for z in zc if z == 2)) / n * 100
    pct_ge2 = sum((1 for z in zc if z >= 2)) / n * 100
    arcs = [half_wave_arc_deg(yaws) for _, yaws in rows if zero_crossings(yaws) >= 2]
    avg_s_arc = sum(arcs) / len(arcs) if arcs else 0.0
    head = sum(per_amp[:3]) / 3
    mid = sum(per_amp[5:8]) / 3
    tail = sum(per_amp[-3:]) / 3
    s_idxs = [i for i, z in enumerate(zc) if z == 2]
    rep = rows[s_idxs[len(s_idxs) // 2]][1] if s_idxs else rows[-1][1]
    rep_arc = half_wave_arc_deg(rep)
    rep_zc = zero_crossings(rep)
    print(f'  {label:38s}  pct=2:{pct_eq2:4.0f}%  pct≥2:{pct_ge2:4.0f}%  S-arc avg:{avg_s_arc:5.0f}°  h/m/t:{head:.2f}/{mid:.2f}/{tail:.2f}  rep(zc={rep_zc},{rep_arc:.0f}°): ' + ' '.join((f'{y:+.2f}' for y in rep)))
    return {'angle': angle, 'freq': freq, 'amp': amp, 'alpha': alpha, 'pct_eq2': pct_eq2, 'pct_ge2': pct_ge2, 's_arc': avg_s_arc, 'head': head, 'mid': mid, 'tail': tail}

async def main():
    results = []
    for angle in [0.25, 0.3, 0.35, 0.4]:
        print(f'\n--- angle_max={angle} ---')
        for i, (freq, amp, alpha) in enumerate([(0.8, 0.15, 0.08), (1.0, 0.18, 0.1), (1.2, 0.2, 0.1), (1.4, 0.22, 0.12), (1.6, 0.25, 0.15)]):
            r = await evaluate(angle, freq, amp, alpha, seconds=12.0, do_rebuild=i == 0)
            if r:
                results.append(r)
    print('\n=== top 8 by S-quality (high pct_>=2 & S-arc ~90-130°) ===')
    valid = [r for r in results if r['pct_ge2'] > 5]

    def score(r):
        arc_penalty = abs(r['s_arc'] - 100) / 50 if r['s_arc'] > 0 else 5
        return r['pct_ge2'] - arc_penalty * 10 + min(r['tail'], 0.3) * 50
    for r in sorted(valid, key=lambda x: -score(x))[:8]:
        print(f'  a={r['angle']:.2f} f={r['freq']:.1f} amp={r['amp']:.2f} α={r['alpha']:.2f}  pct≥2:{r['pct_ge2']:3.0f}%  S-arc:{r['s_arc']:.0f}°  h/m/t:{r['head']:.2f}/{r['mid']:.2f}/{r['tail']:.2f}')
if __name__ == '__main__':
    asyncio.run(main())

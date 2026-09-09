"""Density × angle sweep.

Lower density → less viscous drag → joints can swing through larger angles per
period. Should restore mid/tail propagation at 0.40 and 0.50 rad.

For each (angle, density) pair: rebuild body at angle, set opt.density (live),
reset, capture 30k ticks, measure mid/tail amp.
"""
from __future__ import annotations
from analysis.lib.lab_client import (
    LAB_REST as URL_REST,
    LAB_WS as URL_WS,
    post_json,
    get_json,
    unpack_bits,
)
import asyncio, base64, json, sys, time, urllib.request
import numpy as np
import websockets

def zero_crossings(yaws, db=0.04):
    cnt = 0
    prev = None
    for y in yaws:
        if abs(y) < db:
            continue
        s = 1 if y > 0 else -1
        if prev is not None and s != prev:
            cnt += 1
        prev = s
    return cnt

async def probe(angle, density, target=30000):
    label = f'a={angle} ρ={density}'
    print(f'\n=== {label} ===')
    post_json('/api/patch', {'patches': [{'path': 'sim.joints.angle_max', 'value': angle}]})
    post_json('/api/apply-pending', {})
    await asyncio.sleep(1.5)
    post_json('/api/patch', {'patches': [{'path': 'sim.mujoco.opt.density', 'value': float(density)}]})
    post_json('/api/reset', {})
    await asyncio.sleep(0.5)
    async with websockets.connect(URL_WS, max_size=2 ** 24) as ws:
        hello = json.loads(await ws.recv())
        joints = hello['L_body']['joints']
        names = hello['L']['nm']
        yaw_idx = np.array([i for i, jn in enumerate(joints) if 'yaw' in jn], dtype=np.int32)
        ticks, ja_l, ma_l, S_l, fired_l, com_l = ([], [], [], [], [], [])
        last_tick = -1
        wall0 = time.time()
        while True:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
            except asyncio.TimeoutError:
                break
            d = json.loads(msg)
            if d.get('t') != 's':
                continue
            tick = d.get('k', 0)
            if tick == last_tick:
                continue
            last_tick = tick
            ticks.append(tick)
            ja_l.append(np.array(d.get('ja', []), dtype=np.int32))
            ma_l.append(np.array(d.get('ma', []), dtype=np.int32))
            S_l.append(np.array(d.get('Si', []), dtype=np.int32))
            fired_l.append(unpack_bits(d.get('Fb', ''), len(names)))
            com_l.append(np.array(d.get('cm', [0, 0, 0]), dtype=np.int64))
            if tick >= target:
                break
        ticks = np.array(ticks, dtype=np.int32)

        def stack_pad(lst, dt):
            mx = max((a.size for a in lst))
            out = np.zeros((len(lst), mx), dtype=dt)
            for i, a in enumerate(lst):
                out[i, :a.size] = a
            return out
        ja = stack_pad(ja_l, np.int32).astype(np.float32) / 10000.0
        ma = stack_pad(ma_l, np.int32).astype(np.float32) / 10000.0
        S = stack_pad(S_l, np.int32).astype(np.float32) / 10000.0
        fired = stack_pad(fired_l, np.uint8)
        com = stack_pad(com_l, np.int64).astype(np.float32) / 1000000.0
        yaws = ja[:, yaw_idx]
        n = len(yaws)
        late = yaws[2 * n // 5:]
        per_amp = late.max(0) - late.min(0)
        head = per_amp[1]
        mid = per_amp[6]
        tail = per_amp[10]
        zc = np.array([zero_crossings(y) for y in late])
        pct_eq2 = (zc == 2).mean() * 100
        pct_ge2 = (zc >= 2).mean() * 100
        com_disp = float(np.linalg.norm(com[-1, :2] - com[0, :2]))
        com_path = float(np.sum(np.linalg.norm(np.diff(com[:, :2], axis=0), axis=1)))
        print(f'  late head/mid/tail amp: {head:.2f}/{mid:.2f}/{tail:.2f}  pct_=2:{pct_eq2:.0f}% pct_>=2:{pct_ge2:.0f}%  COM disp/path: {com_disp:.2f}/{com_path:.2f} mm')
        out = f'./worm_a{int(angle * 100):03d}_d{int(density):04d}.npz'
        np.savez_compressed(out, ticks=ticks, ja=ja, ma=ma, S=S, fired=fired, com=com, joint_names=np.array(joints), neuron_names=np.array(names), yaw_idx=yaw_idx)
        return {'angle': angle, 'density': density, 'head': head, 'mid': mid, 'tail': tail, 'pct_ge2': pct_ge2, 'com_disp': com_disp, 'com_path': com_path}

async def main():
    grid = []
    angles = [0.3, 0.4, 0.5]
    densities = [200, 500, 1000, 2000]
    results = []
    for ang in angles:
        for rho in densities:
            r = await probe(ang, rho, target=12000)
            results.append(r)
    post_json('/api/patch', {'patches': [{'path': 'sim.joints.angle_max', 'value': 0.3}]})
    post_json('/api/apply-pending', {})
    await asyncio.sleep(1.5)
    post_json('/api/patch', {'patches': [{'path': 'sim.mujoco.opt.density', 'value': 2000.0}]})
    print('\n=== Summary table ===')
    print(f'{'angle':>6s} {'density':>8s}  {'head':>5s} {'mid':>5s} {'tail':>5s}  {'pct≥2':>5s}  {'COM disp':>8s} {'path':>5s}')
    for r in results:
        print(f'  {r['angle']:.2f}    {r['density']:5d}    {r['head']:.2f}  {r['mid']:.2f}  {r['tail']:.2f}    {r['pct_ge2']:4.0f}%   {r['com_disp']:.2f}    {r['com_path']:.2f}')
if __name__ == '__main__':
    asyncio.run(main())

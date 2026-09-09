"""Sweep fluid medium parameters to maximize forward locomotion speed.

C. elegans on agar isn't really 'in' a fluid — agar is a thin gel surface. The
density=2000 + viscosity=0.3 regime simulates a dense viscous medium, which
dissipates a lot of muscular work. Try lower density and viscosity."""
from __future__ import annotations
from analysis.lib.lab_client import (
    LAB_REST as URL_REST,
    LAB_WS as URL_WS,
    post_json,
    get_json,
    unpack_bits,
)
import asyncio, json, sys, time, urllib.request
import numpy as np
import websockets

async def probe(density, viscosity, target=20000):
    label = f'ρ={density} ν={viscosity}'
    print(f'\n=== {label} ===')
    post_json('/api/patch', {'patches': [{'path': 'sim.mujoco.opt.density', 'value': float(density)}, {'path': 'sim.mujoco.opt.viscosity', 'value': float(viscosity)}]})
    post_json('/api/reset', {})
    await asyncio.sleep(0.5)
    async with websockets.connect(URL_WS, max_size=2 ** 24) as ws:
        hello = json.loads(await ws.recv())
        joints = hello['L_body']['joints']
        yaw_idx = [i for i, jn in enumerate(joints) if 'yaw' in jn]
        ticks_l, com_l, sm_l, ja_l = ([], [], [], [])
        last_tick = -1
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
            ticks_l.append(tick)
            com_l.append(np.array(d.get('cm', [0, 0, 0]), dtype=np.int64))
            sm_l.append(np.array(d.get('sm', []), dtype=np.int64))
            ja_l.append(np.array(d.get('ja', []), dtype=np.int32))
            if tick >= target:
                break
        ticks = np.array(ticks_l, dtype=np.int32)
        n = len(ticks)
        sec = (ticks - ticks[0]) * 0.002
        com = np.stack([c / 1000000.0 for c in com_l])
        seg = np.stack([s / 1000000.0 for s in sm_l]).reshape(n, -1, 3)
        ja = np.stack(ja_l).astype(float) / 10000.0
        head = seg[:, 0, :2]
        tail = seg[:, -1, :2]
        forward = (head - tail) / (np.linalg.norm(head - tail, axis=1, keepdims=True) + 1e-09)
        com_vel = np.diff(com[:, :2], axis=0) / np.diff(sec).reshape(-1, 1)
        fwd_speed = np.einsum('ij,ij->i', com_vel, forward[:-1])
        skip = n // 5
        late_speed = fwd_speed[skip:].mean() * 1000
        z_mean = seg[skip:, :, 2].mean()
        z_std = seg[skip:, :, 2].std()
        yaws = ja[:, yaw_idx]
        yaw_amp = yaws[skip:].max(0) - yaws[skip:].min(0)
        body_len = float(np.median(np.linalg.norm(head - tail, axis=1)))
        bl_per_min = late_speed / 1000 / body_len * 60 if body_len else 0
        print(f'  forward speed: {late_speed:+.1f} µm/s ({bl_per_min:.1f} BL/min)  body length: {body_len:.2f}mm')
        print(f'  body z mean: {z_mean * 1000:.0f} µm  std {z_std * 1000:.1f} µm')
        print(f'  yaw amp: head/mid/tail = {np.degrees(yaw_amp[1]):.0f}°/{np.degrees(yaw_amp[6]):.0f}°/{np.degrees(yaw_amp[10]):.0f}°')
        return {'density': density, 'viscosity': viscosity, 'speed_um_s': late_speed, 'bl_per_min': bl_per_min, 'z_mean_um': z_mean * 1000, 'yaw_head': np.degrees(yaw_amp[1]), 'yaw_tail': np.degrees(yaw_amp[10])}

async def main():
    grid = [(2000, 0.3), (1000, 0.3), (1000, 0.1), (200, 0.1), (200, 0.01), (0, 0.1), (0, 0.01), (0, 0.0)]
    results = []
    for rho, nu in grid:
        r = await probe(rho, nu, target=20000)
        results.append(r)
    post_json('/api/patch', {'patches': [{'path': 'sim.mujoco.opt.density', 'value': 2000.0}, {'path': 'sim.mujoco.opt.viscosity', 'value': 0.3}]})
    post_json('/api/reset', {})
    print('\n=== summary ===')
    print(f'{'ρ':>5s} {'ν':>5s}  {'fwd_speed':>10s}  {'BL/min':>7s}  {'z_µm':>5s}  {'yaw h/t':>10s}')
    for r in sorted(results, key=lambda x: -x['speed_um_s']):
        print(f'  {r['density']:4.0f}  {r['viscosity']:4.2f}    {r['speed_um_s']:+7.1f}  {r['bl_per_min']:6.1f}    {r['z_mean_um']:4.0f}    {r['yaw_head']:.0f}°/{r['yaw_tail']:.0f}°')
if __name__ == '__main__':
    asyncio.run(main())

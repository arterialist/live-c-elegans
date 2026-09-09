"""Maximize forward thrust biomechanically.

C. elegans low-Reynolds swimming — thrust scales with viscosity × ω × A². So
either bigger amplitude, faster CPG, or higher viscosity should help. Test:
  - Higher viscosity at fixed density
  - Bigger angle_max with faster CPG
  - Stronger actuator forcerange
"""
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

def patch_actuator_force(force_max):
    """Patch all 48 actuator forceranges via /api/body/patch."""
    patches = []
    for i in range(48):
        patches.append({'target': 'actuator', 'id': i, 'field': 'forcerange', 'index': 1, 'value': float(force_max)})
        patches.append({'target': 'actuator', 'id': i, 'field': 'forcerange', 'index': 0, 'value': float(-force_max)})
    post_json('/api/body/patch', {'patches': patches})

async def probe(label, density=2000, viscosity=0.3, freq=0.6, amp=0.2, force_max=3.5, target=18000, do_rebuild=False):
    print(f'\n=== {label} ===')
    if do_rebuild:
        post_json('/api/apply-pending', {})
        await asyncio.sleep(1.5)
    post_json('/api/patch', {'patches': [{'path': 'sim.mujoco.opt.density', 'value': float(density)}, {'path': 'sim.mujoco.opt.viscosity', 'value': float(viscosity)}, {'path': 'sim.neuromod.HEAD_CPG_FREQ_HZ', 'value': float(freq)}, {'path': 'sim.neuromod.HEAD_CPG_AMP', 'value': float(amp)}]})
    patch_actuator_force(force_max)
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
        fwd = np.einsum('ij,ij->i', com_vel, forward[:-1])
        skip = n // 5
        late_speed = fwd[skip:].mean() * 1000
        body_len = float(np.median(np.linalg.norm(head - tail, axis=1)))
        bl_per_min = late_speed / 1000 / body_len * 60 if body_len else 0
        yaws = ja[:, yaw_idx]
        yaw_amp = yaws[skip:].max(0) - yaws[skip:].min(0)
        print(f'  fwd speed: {late_speed:+.1f} µm/s  ({bl_per_min:.1f} BL/min)  yaw h/m/t: {np.degrees(yaw_amp[1]):.0f}/{np.degrees(yaw_amp[6]):.0f}/{np.degrees(yaw_amp[10]):.0f}°')
        return {'label': label, 'speed': late_speed, 'bl_per_min': bl_per_min, 'yaw_h': np.degrees(yaw_amp[1]), 'yaw_t': np.degrees(yaw_amp[10]), 'params': dict(density=density, viscosity=viscosity, freq=freq, amp=amp, force=force_max)}

async def main():
    results = []
    results.append(await probe('baseline ρ2000 ν0.3 f0.6 amp0.20 F3.5'))
    for nu in [0.5, 1.0, 2.0]:
        results.append(await probe(f'ν={nu}', viscosity=nu))
    for f in [0.8, 1.0, 1.2]:
        results.append(await probe(f'freq={f}', freq=f))
    for fmax in [5.0, 7.0, 10.0]:
        results.append(await probe(f'F={fmax}', force_max=fmax))
    results.append(await probe('ν=1.0 freq=0.8 F=7', viscosity=1.0, freq=0.8, force_max=7.0))
    results.append(await probe('ν=1.0 freq=1.0 F=10', viscosity=1.0, freq=1.0, force_max=10.0))
    post_json('/api/patch', {'patches': [{'path': 'sim.mujoco.opt.density', 'value': 2000.0}, {'path': 'sim.mujoco.opt.viscosity', 'value': 0.3}, {'path': 'sim.neuromod.HEAD_CPG_FREQ_HZ', 'value': 0.6}, {'path': 'sim.neuromod.HEAD_CPG_AMP', 'value': 0.2}]})
    patch_actuator_force(3.5)
    post_json('/api/reset', {})
    print('\n=== ranking by forward speed ===')
    for r in sorted(results, key=lambda x: -x['speed']):
        print(f'  {r['label']:35s}  speed={r['speed']:+.1f} µm/s  ({r['bl_per_min']:.1f} BL/min)  yaw h/t={r['yaw_h']:.0f}°/{r['yaw_t']:.0f}°')
if __name__ == '__main__':
    asyncio.run(main())

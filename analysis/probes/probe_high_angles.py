"""Run 50k-tick capture at angles 0.35, 0.40, 0.50 with current defaults."""
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

async def capture_one(angle, target=50000, out_path=None):
    out_path = out_path or f'./worm_{int(angle * 100):03d}.npz'
    print(f'\n=== angle={angle} → {out_path} ===')
    post_json('/api/patch', {'patches': [{'path': 'sim.joints.angle_max', 'value': float(angle)}]})
    post_json('/api/apply-pending', {})
    await asyncio.sleep(1.5)
    body = get_json('/api/body')
    actuator_forcerange = np.array([a['forcerange'] for a in body['actuators']], dtype=np.float32)
    joint_range = np.array([j['range'] for j in body['joints']], dtype=np.float32)
    print(f'joint range applied: {joint_range[0]}')
    async with websockets.connect(URL_WS, max_size=2 ** 24) as ws:
        hello = json.loads(await ws.recv())
        names = hello['L']['nm']
        joints = hello['L_body']['joints']
        muscles = hello['L_body']['muscles']
        n_neurons = len(names)
        yaw_idx = np.array([i for i, jn in enumerate(joints) if 'yaw' in jn], dtype=np.int32)
        ticks, ja_l, jv_l, ma_l, S_l, fired_l, com_l = ([], [], [], [], [], [], [])
        wall0 = time.time()
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
            ticks.append(tick)
            ja_l.append(np.array(d.get('ja', []), dtype=np.int32))
            jv_l.append(np.array(d.get('jv', []), dtype=np.int32))
            ma_l.append(np.array(d.get('ma', []), dtype=np.int32))
            S_l.append(np.array(d.get('Si', []), dtype=np.int32))
            fired_l.append(unpack_bits(d.get('Fb', ''), n_neurons))
            com_l.append(np.array(d.get('cm', [0, 0, 0]), dtype=np.int64))
            if len(ticks) % 5000 == 0:
                print(f'  {len(ticks):6d} frames, tick {tick}, wall {time.time() - wall0:.0f}s')
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
        jv = stack_pad(jv_l, np.int32).astype(np.float32) / 10000.0
        ma = stack_pad(ma_l, np.int32).astype(np.float32) / 10000.0
        S = stack_pad(S_l, np.int32).astype(np.float32) / 10000.0
        fired = stack_pad(fired_l, np.uint8)
        com = stack_pad(com_l, np.int64).astype(np.float32) / 1000000.0
        np.savez_compressed(out_path, ticks=ticks, ja=ja, jv=jv, ma=ma, S=S, fired=fired, com=com, joint_names=np.array(joints), muscle_names=np.array(muscles), neuron_names=np.array(names), yaw_idx=yaw_idx, actuator_forcerange=actuator_forcerange, joint_range=joint_range)
        print(f'  done {len(ticks)} frames in {time.time() - wall0:.1f}s')

async def main():
    angles = [float(x) for x in sys.argv[1:]] if len(sys.argv) > 1 else [0.35, 0.4, 0.5]
    for a in angles:
        await capture_one(a, target=50000)
if __name__ == '__main__':
    asyncio.run(main())

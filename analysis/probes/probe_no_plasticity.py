"""Disable synaptic plasticity (eta_post = eta_retro = 0) on every neuron.

Real C. elegans baseline locomotion does not depend on minute-timescale
plasticity — synaptic learning operates on hour/day timescales (habituation,
classical conditioning). The PAULA neuron model defaults eta_post=eta_retro=0.01,
which over thousands of ticks drifts u_i.info weights enough to retune
wave-propagation gains and kill posterior amplitude. Setting both to 0 freezes
the connectome at its initial calibration.

Run angle=0.30 (current default) with eta_post=eta_retro=0 on ALL 302 neurons,
50k ticks, then compare tail decay vs spike-on default.
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

def patch_neuron(name, field, value):
    return post_json(f'/api/neurons/{name}/patch', {'patches': [{'field': field, 'value': value}]})

async def main():
    angle = float(sys.argv[1]) if len(sys.argv) > 1 else 0.3
    target = int(sys.argv[2]) if len(sys.argv) > 2 else 50000
    out_path = sys.argv[3] if len(sys.argv) > 3 else './worm_noplast.npz'
    print(f'set angle_max={angle} (rebuild)')
    post_json('/api/patch', {'patches': [{'path': 'sim.joints.angle_max', 'value': angle}]})
    post_json('/api/apply-pending', {})
    await asyncio.sleep(1.5)
    connectome = get_json('/api/connectome')
    all_names = [n['name'] for n in connectome['neurons']] if 'neurons' in connectome else []
    if not all_names:
        async with websockets.connect(URL_WS, max_size=2 ** 24) as ws:
            hello = json.loads(await ws.recv())
            all_names = list(hello['L']['nm'])
    print(f'disabling plasticity on {len(all_names)} neurons (eta_post=0, eta_retro=0)…')
    n_ok = 0
    for name in all_names:
        try:
            r1 = patch_neuron(name, 'eta_post', 0.0)
            r2 = patch_neuron(name, 'eta_retro', 0.0)
            if r1.get('applied') and r2.get('applied'):
                n_ok += 1
        except Exception:
            pass
    print(f'  applied to {n_ok}/{len(all_names)}')
    verify = get_json(f'/api/neurons/{all_names[0]}')
    print(f'  verify {all_names[0]}: eta_post={verify['params']['eta_post']:.3f}  eta_retro={verify['params']['eta_retro']:.3f}')
    await asyncio.sleep(0.4)
    print(f'capture {target} ticks → {out_path}')
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
        np.savez_compressed(out_path, ticks=ticks, ja=ja, jv=jv, ma=ma, S=S, fired=fired, com=com, joint_names=np.array(joints), muscle_names=np.array(muscles), neuron_names=np.array(names), yaw_idx=yaw_idx)
        print(f'  done {len(ticks)} frames in {time.time() - wall0:.1f}s')
if __name__ == '__main__':
    asyncio.run(main())

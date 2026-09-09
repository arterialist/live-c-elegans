"""Combined biology test: graded-only motor neurons + no plasticity.

Two biologically-motivated changes applied together:
  - r_base, b_base = 1e6 on body-wall motor neurons (DB/VB/DA/VA/AS/DD/VD)
    → no spikes; smooth graded membrane potential drives muscles. Matches the
    well-documented non-spiking nature of C. elegans body-wall neurons.
  - eta_post, eta_retro = 0 on ALL 302 neurons → no synaptic plasticity at
    second timescales. Real plasticity is hour/day scale.
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

def patch(name, field, value):
    return post_json(f'/api/neurons/{name}/patch', {'patches': [{'field': field, 'value': value}]})
DB = [f'DB{i}' for i in range(1, 8)]
VB = [f'VB{i}' for i in range(1, 12)]
DA = [f'DA{i}' for i in range(1, 10)]
VA = [f'VA{i}' for i in range(1, 13)]
AS = [f'AS{i}' for i in range(1, 12)]
DD = [f'DD{i}' for i in range(1, 7)]
VD = [f'VD{i}' for i in range(1, 14)]
BODY_WALL_MOTORS = DB + VB + DA + VA + AS + DD + VD

async def main():
    angle = float(sys.argv[1]) if len(sys.argv) > 1 else 0.3
    target = int(sys.argv[2]) if len(sys.argv) > 2 else 50000
    out_path = sys.argv[3] if len(sys.argv) > 3 else './worm_combined.npz'
    print(f'set angle_max={angle} (rebuild)')
    post_json('/api/patch', {'patches': [{'path': 'sim.joints.angle_max', 'value': angle}]})
    post_json('/api/apply-pending', {})
    await asyncio.sleep(1.5)
    async with websockets.connect(URL_WS, max_size=2 ** 24) as ws:
        hello = json.loads(await ws.recv())
        all_names = list(hello['L']['nm'])
    HUGE = 1000000.0
    print(f'raise r_base, b_base → {HUGE} on {len(BODY_WALL_MOTORS)} body-wall motor neurons…')
    n_ok_m = 0
    for name in BODY_WALL_MOTORS:
        try:
            patch(name, 'r_base', HUGE)
            patch(name, 'b_base', HUGE)
            patch(name, 'r', HUGE)
            patch(name, 'b', HUGE)
            n_ok_m += 1
        except Exception:
            pass
    print(f'  applied {n_ok_m}/{len(BODY_WALL_MOTORS)}')
    print(f'set eta_post=eta_retro=0 on all {len(all_names)} neurons…')
    n_ok_p = 0
    for name in all_names:
        try:
            patch(name, 'eta_post', 0.0)
            patch(name, 'eta_retro', 0.0)
            n_ok_p += 1
        except Exception:
            pass
    print(f'  applied {n_ok_p}/{len(all_names)}')
    v = get_json('/api/neurons/DB1')
    print(f'  verify DB1: r_base={v['params']['r_base']:.0f}  eta_post={v['params']['eta_post']:.3f}')
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

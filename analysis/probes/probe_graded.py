"""Test graded-only motor neurons by raising r_base/b_base far above any reachable S.

Biological motivation: C. elegans body-wall motor neurons (DB/VB/DA/VA/AS/DD/VD)
signal via graded membrane potentials, not action potentials. The PAULA neuron model
fires when S ≥ r (or b), which RESETS S to 0 — that reset is non-biological for
these cells and visibly notches the muscle drive. Raising the threshold past any
reachable S (well above 1000) prevents the spike branch and lets S evolve as a
clean leaky integrator.

Run two captures:
  1. Current defaults (spike-enabled).
  2. r_base=b_base=1e6 on all body-wall motor neurons (graded-only).

Compare smoothness, amplitude, S-fraction, body shape.
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
DB = [f'DB{i}' for i in range(1, 8)]
VB = [f'VB{i}' for i in range(1, 12)]
DA = [f'DA{i}' for i in range(1, 10)]
VA = [f'VA{i}' for i in range(1, 13)]
AS = [f'AS{i}' for i in range(1, 12)]
DD = [f'DD{i}' for i in range(1, 7)]
VD = [f'VD{i}' for i in range(1, 14)]
ALL_MOTORS = DB + VB + DA + VA + AS + DD + VD

def patch_neuron(name, field, value, index=None):
    body = {'patches': [{'field': field, 'value': value}]}
    if index is not None:
        body['patches'][0]['index'] = index
    return post_json(f'/api/neurons/{name}/patch', body)

async def capture(target=50000, out_path='./worm_graded.npz'):
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

async def main():
    angle = float(sys.argv[1]) if len(sys.argv) > 1 else 0.3
    target = int(sys.argv[2]) if len(sys.argv) > 2 else 50000
    print(f'set angle_max={angle} (rebuild)')
    post_json('/api/patch', {'patches': [{'path': 'sim.joints.angle_max', 'value': angle}]})
    post_json('/api/apply-pending', {})
    await asyncio.sleep(1.5)
    HUGE = 1000000.0
    print(f'raising r_base, b_base → {HUGE} on {len(ALL_MOTORS)} body-wall motor neurons…')
    n_ok = 0
    n_fail = 0
    for name in ALL_MOTORS:
        try:
            res_r = patch_neuron(name, 'r_base', HUGE)
            res_b = patch_neuron(name, 'b_base', HUGE)
            patch_neuron(name, 'r', HUGE)
            patch_neuron(name, 'b', HUGE)
            if res_r.get('applied') and res_b.get('applied'):
                n_ok += 1
            else:
                n_fail += 1
        except Exception as e:
            print(f'  FAIL {name}: {e}')
            n_fail += 1
    print(f'  applied to {n_ok}/{len(ALL_MOTORS)} neurons (failed {n_fail})')
    verify = get_json('/api/neurons/DB1')
    print(f'  verify DB1: r_base={verify['params']['r_base']:.0f}  b_base={verify['params']['b_base']:.0f}')
    await asyncio.sleep(0.4)
    await capture(target=target, out_path='./worm_graded.npz')
if __name__ == '__main__':
    asyncio.run(main())

"""Long-run capture (250k+ ticks) with full per-tick state recording.

No windowing during capture; analysis stage computes continuous metrics so
no transient events are skipped.
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

async def main():
    target = int(sys.argv[1]) if len(sys.argv) > 1 else 250000
    out_path = sys.argv[2] if len(sys.argv) > 2 else './worm_long_continuous.npz'
    print(f'reset & continuous capture {target} ticks → {out_path}')
    post_json('/api/reset', {})
    await asyncio.sleep(0.5)
    async with websockets.connect(URL_WS, max_size=2 ** 24) as ws:
        hello = json.loads(await ws.recv())
        names = hello['L']['nm']
        joints = hello['L_body']['joints']
        muscles = hello['L_body']['muscles']
        n_neurons = len(names)
        yaw_idx = np.array([i for i, jn in enumerate(joints) if 'yaw' in jn], dtype=np.int32)
        pitch_idx = np.array([i for i, jn in enumerate(joints) if 'pitch' in jn], dtype=np.int32)
        ticks_l, com_l, sm_l, ja_l, jv_l, ma_l, S_l, fired_l = ([], [], [], [], [], [], [], [])
        fe_l, nm_l = ([], [])
        wall0 = time.time()
        last_tick = -1
        while True:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
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
            jv_l.append(np.array(d.get('jv', []), dtype=np.int32))
            ma_l.append(np.array(d.get('ma', []), dtype=np.int32))
            S_l.append(np.array(d.get('Si', []), dtype=np.int32))
            fired_l.append(unpack_bits(d.get('Fb', ''), n_neurons))
            fe_l.append(float(d.get('fe', 0.0)))
            nm_l.append(d.get('nm01', [0.0, 0.0]))
            if len(ticks_l) % 20000 == 0:
                print(f'  {len(ticks_l):6d} frames  tick={tick}  wall={time.time() - wall0:.0f}s')
            if tick >= target:
                break
        ticks = np.array(ticks_l, dtype=np.int32)

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
        sm = stack_pad(sm_l, np.int64).astype(np.float32) / 1000000.0
        fe = np.array(fe_l, dtype=np.float32)
        nm01 = np.array(nm_l, dtype=np.float32)
        np.savez_compressed(out_path, ticks=ticks, ja=ja, jv=jv, ma=ma, S=S, fired=fired, com=com, sm=sm, fe=fe, nm01=nm01, joint_names=np.array(joints), muscle_names=np.array(muscles), neuron_names=np.array(names), yaw_idx=yaw_idx, pitch_idx=pitch_idx)
        wall = time.time() - wall0
        print(f'  done {len(ticks)} frames in {wall:.1f}s wall ({len(ticks) / wall:.0f} frames/s)')
if __name__ == '__main__':
    asyncio.run(main())

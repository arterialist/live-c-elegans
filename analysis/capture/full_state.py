"""Capture 60k+ ticks of full WS state. Saves to ./worm_capture.npz.

Records per tick:
  - tick
  - 24 joint angles + 24 joint velocities
  - 48 muscle activations
  - 302 neuron S, R, B, t_ref, fired (full network)
  - 3 com_mm
  - free energy, neuromod m0/m1
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
    target = int(sys.argv[1]) if len(sys.argv) > 1 else 60000
    out_path = sys.argv[2] if len(sys.argv) > 2 else './worm_capture.npz'
    print(f'reset and capture {target} ticks → {out_path}')
    post_json('/api/reset', {})
    await asyncio.sleep(0.5)
    async with websockets.connect(URL_WS, max_size=2 ** 24) as ws:
        hello = json.loads(await ws.recv())
        names = hello['L']['nm']
        kinds = [m['k'] for m in hello['M']]
        joints = hello['L_body']['joints']
        muscles = hello['L_body']['muscles']
        n_neurons = len(names)
        yaw_idx = np.array([i for i, jn in enumerate(joints) if 'yaw' in jn], dtype=np.int32)
        pitch_idx = np.array([i for i, jn in enumerate(joints) if 'pitch' in jn], dtype=np.int32)
        ticks = []
        ja_all = []
        jv_all = []
        ma_all = []
        S_all = []
        fired_all = []
        com_all = []
        nm_all = []
        fe_all = []
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
            ja_all.append(np.array(d.get('ja', []), dtype=np.int32))
            jv_all.append(np.array(d.get('jv', []), dtype=np.int32))
            ma_all.append(np.array(d.get('ma', []), dtype=np.int32))
            S_all.append(np.array(d.get('Si', []), dtype=np.int32))
            fired_all.append(unpack_bits(d.get('Fb', ''), n_neurons))
            com_all.append(np.array(d.get('cm', [0, 0, 0]), dtype=np.int64))
            nm_all.append(d.get('nm01', [0.0, 0.0]))
            fe_all.append(d.get('fe', 0.0))
            if len(ticks) % 5000 == 0:
                print(f'  {len(ticks):6d} frames, tick {tick}, wall {time.time() - wall0:.0f}s')
            if tick >= target:
                break
        ticks = np.array(ticks, dtype=np.int32)

        def stack_pad(lst):
            if not lst:
                return np.zeros((0, 0), dtype=np.float32)
            maxlen = max((a.size for a in lst))
            out = np.zeros((len(lst), maxlen), dtype=lst[0].dtype)
            for i, a in enumerate(lst):
                out[i, :a.size] = a
            return out
        ja = stack_pad(ja_all).astype(np.float32) / 10000.0
        jv = stack_pad(jv_all).astype(np.float32) / 10000.0
        ma = stack_pad(ma_all).astype(np.float32) / 10000.0
        S = stack_pad(S_all).astype(np.float32) / 10000.0
        fired = stack_pad(fired_all).astype(np.uint8)
        com = stack_pad(com_all).astype(np.float32) / 1000000.0
        nm01 = np.array(nm_all, dtype=np.float32)
        fe = np.array(fe_all, dtype=np.float32)
        np.savez_compressed(out_path, ticks=ticks, ja=ja, jv=jv, ma=ma, S=S, fired=fired, com=com, nm01=nm01, fe=fe, joint_names=np.array(joints), muscle_names=np.array(muscles), neuron_names=np.array(names), neuron_kinds=np.array(kinds), yaw_idx=yaw_idx, pitch_idx=pitch_idx)
        print(f'\ndone: {len(ticks)} frames in {time.time() - wall0:.1f}s wall')
        print(f'  shapes: ja={ja.shape}, ma={ma.shape}, S={S.shape}, fired={fired.shape}')
        print(f'  saved {out_path}')
if __name__ == '__main__':
    asyncio.run(main())

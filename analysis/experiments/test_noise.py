"""Sweep CMD_NOISE_SIGMA and detect reversals."""
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

async def run(sigma, tau, target=30000):
    label = f'σ={sigma} τ={tau}'
    print(f'\n=== {label} ===')
    post_json('/api/patch', {'patches': [{'path': 'sim.neuromod.CMD_NOISE_SIGMA', 'value': float(sigma)}, {'path': 'sim.neuromod.CMD_NOISE_TAU', 'value': float(tau)}]})
    post_json('/api/reset', {})
    await asyncio.sleep(0.5)
    async with websockets.connect(URL_WS, max_size=2 ** 24) as ws:
        hello = json.loads(await ws.recv())
        names = hello['L']['nm']
        joints = hello['L_body']['joints']
        n_neurons = len(names)
        yaw_idx = [i for i, jn in enumerate(joints) if 'yaw' in jn]
        ava_ids = [names.index(n) for n in ['AVAL', 'AVAR'] if n in names]
        avb_ids = [names.index(n) for n in ['AVBL', 'AVBR'] if n in names]
        ticks_l, com_l, sm_l, fired_ava_l, fired_avb_l, S_ava_l = ([], [], [], [], [], [])
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
            b64 = d.get('Fb', '')
            fired = unpack_bits(b64, n_neurons)
            fired_ava_l.append(fired[ava_ids].sum())
            fired_avb_l.append(fired[avb_ids].sum())
            Si = d.get('Si', [])
            S_ava_l.append(Si[ava_ids[0]] / 10000.0 if 0 <= ava_ids[0] < len(Si) else 0)
            if tick >= target:
                break
        ticks = np.array(ticks_l, dtype=np.int32)
        n = len(ticks)
        sec = (ticks - ticks[0]) * 0.002
        com = np.stack([c / 1000000.0 for c in com_l])
        seg = np.stack([s / 1000000.0 for s in sm_l]).reshape(n, -1, 3)
        head = seg[:, 0, :2]
        tail = seg[:, -1, :2]
        fwd = (head - tail) / (np.linalg.norm(head - tail, axis=1, keepdims=True) + 1e-09)
        com_vel = np.diff(com[:, :2], axis=0) / np.diff(sec).reshape(-1, 1)
        fwd_speed = np.einsum('ij,ij->i', com_vel, fwd[:-1]) * 1000
        reversal = fwd_speed < -10
        transitions = np.where(np.diff(reversal.astype(int)) == 1)[0]
        n_reversals = len(transitions)
        ava_total = sum(fired_ava_l)
        avb_total = sum(fired_avb_l)
        S_ava_max = max(S_ava_l) if S_ava_l else 0
        S_ava_std = float(np.std(S_ava_l)) if S_ava_l else 0
        print(f'  duration={sec[-1]:.0f}s  reversals={n_reversals}  AVA fires={ava_total} ({ava_total / sec[-1] * 60:.1f}/min)  AVB fires={avb_total}  S_AVA: max={S_ava_max:+.2f} std={S_ava_std:.2f}  mean fwd={fwd_speed.mean():+.1f} µm/s')
        return {'sigma': sigma, 'tau': tau, 'n_rev': n_reversals, 'ava_rate': ava_total / sec[-1] * 60, 'fwd_speed': fwd_speed.mean()}

async def main():
    results = []
    for s in [0.0, 0.05, 0.1, 0.2, 0.3, 0.5]:
        results.append(await run(s, 50.0, target=30000))
    for tau in [200.0, 500.0]:
        results.append(await run(0.1, tau, target=30000))
    print('\n=== summary (target: ~5-10 reversals/min on agar) ===')
    for r in results:
        print(f'  σ={r['sigma']:.2f} τ={r['tau']:.0f}  n_reversals={r['n_rev']:3d}  AVA_rate={r['ava_rate']:.1f}/min  fwd={r['fwd_speed']:+.1f} µm/s')
if __name__ == '__main__':
    asyncio.run(main())

"""Sweep CMD_NOISE_SIGMA, measure reversal rate AND verify body moves backward.

A real reversal must satisfy:
  - AVA.S high (winning flip-flop)
  - AVB.S low (losing flip-flop)
  - Body forward speed < 0 sustained
  - A-type drive > B-type drive
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

async def run(label, sigma, tau=50.0, target=120000):
    print(f'\n=== {label} ===')
    post_json('/api/patch', {'patches': [{'path': 'sim.neuromod.CMD_NOISE_SIGMA', 'value': float(sigma)}, {'path': 'sim.neuromod.CMD_NOISE_TAU', 'value': float(tau)}]})
    post_json('/api/reset', {})
    await asyncio.sleep(0.5)
    async with websockets.connect(URL_WS, max_size=2 ** 24) as ws:
        hello = json.loads(await ws.recv())
        names = hello['L']['nm']
        joints = hello['L_body']['joints']
        n_neurons = len(names)
        ava_ids = [names.index(n) for n in ['AVAL', 'AVAR'] if n in names]
        avb_ids = [names.index(n) for n in ['AVBL', 'AVBR'] if n in names]
        rows = []
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
            ja = [v / 10000.0 for v in d.get('ja', [])]
            Si = d.get('Si', [])
            S_ava = np.mean([Si[i] / 10000.0 for i in ava_ids if 0 <= i < len(Si)]) if ava_ids else 0
            S_avb = np.mean([Si[i] / 10000.0 for i in avb_ids if 0 <= i < len(Si)]) if avb_ids else 0
            sm = np.array(d.get('sm', []), dtype=np.int64)
            com = np.array(d.get('cm', [0, 0, 0]), dtype=np.int64)
            rows.append((tick, S_ava, S_avb, com, sm))
            if tick >= target:
                break
        n = len(rows)
        sec = np.array([(r[0] - rows[0][0]) * 0.002 for r in rows])
        S_ava = np.array([r[1] for r in rows])
        S_avb = np.array([r[2] for r in rows])
        com = np.stack([r[3] / 1000000.0 for r in rows])
        seg = np.stack([r[4] / 1000000.0 for r in rows]).reshape(n, -1, 3)
        head = seg[:, 0, :2]
        tail = seg[:, -1, :2]
        fwd_dir = (head - tail) / (np.linalg.norm(head - tail, axis=1, keepdims=True) + 1e-09)
        com_vel = np.diff(com[:, :2], axis=0) / np.diff(sec).reshape(-1, 1)
        fwd_speed = np.einsum('ij,ij->i', com_vel, fwd_dir[:-1]) * 1000
        fps = 100
        win = max(1, int(2.0 * fps))
        fwd_smooth = np.convolve(fwd_speed, np.ones(win) / win, mode='same')
        ava_wins = S_ava > S_avb
        diffs = np.diff(ava_wins.astype(int))
        starts = np.where(diffs == 1)[0]
        ends = np.where(diffs == -1)[0]
        if len(ends) and len(starts) and (ends[0] < starts[0]):
            ends = ends[1:]
        if len(starts) > len(ends):
            starts = starts[:len(ends)]
        ava_episodes = [(s, e) for s, e in zip(starts, ends) if (e - s) / fps >= 0.5]
        is_rev = fwd_smooth < -10
        diffs_r = np.diff(is_rev.astype(int))
        rstarts = np.where(diffs_r == 1)[0]
        rends = np.where(diffs_r == -1)[0]
        if len(rends) and len(rstarts) and (rends[0] < rstarts[0]):
            rends = rends[1:]
        if len(rstarts) > len(rends):
            rstarts = rstarts[:len(rends)]
        rev_episodes = [(s, e) for s, e in zip(rstarts, rends) if (e - s) / fps >= 1.0]
        concordant = 0
        for ras, rae in rev_episodes:
            for aas, aae in ava_episodes:
                if max(ras, aas) < min(rae, aae):
                    concordant += 1
                    break
        print(f'  duration={sec[-1]:.0f}s')
        print(f'  AVA-wins ≥0.5s: {len(ava_episodes)}  rate {len(ava_episodes) / sec[-1] * 60:.1f}/min')
        print(f'  Body reversals ≥1s: {len(rev_episodes)}  rate {len(rev_episodes) / sec[-1] * 60:.1f}/min')
        print(f'  Concordance (rev coincides with AVA-win): {concordant}/{len(rev_episodes)}')
        print(f'  Mean fwd speed: {fwd_speed.mean():+.1f}µm/s  Smooth fwd: min={fwd_smooth.min():+.0f}  max={fwd_smooth.max():+.0f}')

async def main():
    for sigma in [0.0, 0.1, 0.2, 0.4, 0.8, 1.5]:
        await run(f'σ={sigma}', sigma, target=60000)
if __name__ == '__main__':
    asyncio.run(main())

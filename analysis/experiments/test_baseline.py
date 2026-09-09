"""Sweep baseline to find one that doesn't saturate over long runs."""
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

async def run(label, baseline, amp, target=60000):
    print(f'\n=== {label} ===')
    post_json('/api/patch', {'patches': [{'path': 'sim.neuromod.HEAD_CPG_AT_RMD', 'value': True}, {'path': 'sim.neuromod.HEAD_CPG_AMP', 'value': 0.0}, {'path': 'sim.neuromod.INTRINSIC_OSC_ENABLED', 'value': True}, {'path': 'sim.neuromod.INTRINSIC_OSC_AMP', 'value': float(amp)}, {'path': 'sim.neuromod.INTRINSIC_OSC_BASELINE', 'value': float(baseline)}]})
    post_json('/api/reset', {})
    await asyncio.sleep(0.5)
    async with websockets.connect(URL_WS, max_size=2 ** 24) as ws:
        hello = json.loads(await ws.recv())
        names = hello['L']['nm']
        joints = hello['L_body']['joints']
        yaw_idx = [i for i, jn in enumerate(joints) if 'yaw' in jn]
        rmd_id = names.index('RMDDL') if 'RMDDL' in names else -1
        ticks_l, com_l, sm_l, ja_l, S_rmd_l = ([], [], [], [], [])
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
            Si = d.get('Si', [])
            S_rmd_l.append(Si[rmd_id] / 10000.0 if 0 <= rmd_id < len(Si) else 0)
            if tick >= target:
                break
        ticks = np.array(ticks_l, dtype=np.int32)
        n = len(ticks)
        sec = (ticks - ticks[0]) * 0.002
        com = np.stack([c / 1000000.0 for c in com_l])
        seg = np.stack([s / 1000000.0 for s in sm_l]).reshape(n, -1, 3)
        ja = np.stack(ja_l).astype(float) / 10000.0
        S_rmd = np.array(S_rmd_l)
        head = seg[:, 0, :2]
        tail = seg[:, -1, :2]
        fwd = (head - tail) / (np.linalg.norm(head - tail, axis=1, keepdims=True) + 1e-09)
        com_vel = np.diff(com[:, :2], axis=0) / np.diff(sec).reshape(-1, 1)
        win_amps = []
        for w in range(0, int(sec[-1]), 30):
            mask = (sec >= w) & (sec < w + 30)
            if mask.any():
                win_amps.append(S_rmd[mask].max() - S_rmd[mask].min())
        com_disp = float(np.linalg.norm(com[-1, :2] - com[0, :2]))
        fwd_speed = np.einsum('ij,ij->i', com_vel, fwd[:-1])[len(sec) // 5:].mean() * 1000
        per_amp = np.degrees(ja[len(sec) // 5:, yaw_idx].max(0) - ja[len(sec) // 5:, yaw_idx].min(0))
        rmd_amp_str = '/'.join((f'{a:.2f}' for a in win_amps[:8]))
        print(f'  fwd={fwd_speed:+.1f}µm/s  COM_disp={com_disp:.2f}mm  yaw h/m/t: {per_amp[1]:.0f}°/{per_amp[6]:.0f}°/{per_amp[10]:.0f}°  RMDDL.S amp by 30s window: {rmd_amp_str}')

async def main():
    for baseline in [0.005, 0.01, 0.02, 0.03, 0.05, 0.1]:
        await run(f'baseline={baseline}', baseline, 0.1)
if __name__ == '__main__':
    asyncio.run(main())

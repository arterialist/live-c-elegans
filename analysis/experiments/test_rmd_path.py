"""Tune CPG params with RMD path active to recover good frequency + speed."""
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
from scipy.signal import welch

async def run(label, freq, amp, head_weight, target=18000):
    print(f'\n=== {label} ===')
    post_json('/api/patch', {'patches': [{'path': 'sim.neuromod.HEAD_CPG_AT_RMD', 'value': True}, {'path': 'sim.neuromod.HEAD_CPG_FREQ_HZ', 'value': float(freq)}, {'path': 'sim.neuromod.HEAD_CPG_AMP', 'value': float(amp)}]})
    post_json('/api/reset', {})
    await asyncio.sleep(0.5)
    async with websockets.connect(URL_WS, max_size=2 ** 24) as ws:
        hello = json.loads(await ws.recv())
        joints = hello['L_body']['joints']
        names = hello['L']['nm']
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
        yaws = ja[:, yaw_idx]
        head = seg[:, 0, :2]
        tail = seg[:, -1, :2]
        fwd = (head - tail) / (np.linalg.norm(head - tail, axis=1, keepdims=True) + 1e-09)
        com_vel = np.diff(com[:, :2], axis=0) / np.diff(sec).reshape(-1, 1)
        fwd_speed = np.einsum('ij,ij->i', com_vel, fwd[:-1])[len(sec) // 5:].mean() * 1000
        skip = n // 5
        per_amp = np.degrees(yaws[skip:].max(0) - yaws[skip:].min(0))
        fs = 1.0 / np.median(np.diff(ticks)) / 0.002
        f, P = welch(yaws[skip:, 0], fs=fs, nperseg=min(2048, len(yaws) // 4))
        mask = (f > 0.05) & (f < 5.0)
        peak_f = f[mask][np.argmax(P[mask])] if mask.any() else 0
        com_disp = float(np.linalg.norm(com[-1, :2] - com[0, :2]))
        print(f'  freq_set={freq} amp_set={amp}  measured_freq={peak_f:.2f}Hz  fwd={fwd_speed:+.1f}µm/s  amp h/m/t={per_amp[1]:.0f}°/{per_amp[6]:.0f}°/{per_amp[10]:.0f}°  COM_disp={com_disp:.2f}mm')

async def main():
    for amp in [0.2, 0.5, 1.0, 2.0]:
        await run(f'freq=0.6 amp={amp}', 0.6, amp, 1.0)
    for freq in [1.0, 1.5, 2.0, 3.0]:
        await run(f'freq={freq} amp=1.0', freq, 1.0, 1.0)
    await run('freq=2.0 amp=2.0', 2.0, 2.0, 1.0)
if __name__ == '__main__':
    asyncio.run(main())

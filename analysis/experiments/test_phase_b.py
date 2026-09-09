"""Quick test of Phase B (intrinsic oscillator) replacing external CPG.

Configurations:
  baseline:  external CPG only (Phase A current default)
  hybrid:    external CPG + intrinsic oscillator (both active)
  intrinsic: intrinsic oscillator only (external CPG = 0)  ← target bio-faithful state
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

async def run(label, patches, target=18000):
    print(f'\n=== {label} ===')
    post_json('/api/patch', {'patches': patches})
    post_json('/api/reset', {})
    await asyncio.sleep(0.5)
    async with websockets.connect(URL_WS, max_size=2 ** 24) as ws:
        hello = json.loads(await ws.recv())
        joints = hello['L_body']['joints']
        names = hello['L']['nm']
        yaw_idx = [i for i, jn in enumerate(joints) if 'yaw' in jn]
        rmd_ids = [names.index(n) for n in ['RMDDL', 'RMDDR', 'RMDVL', 'RMDVR'] if n in names]
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
            S_rmd_l.append([Si[i] / 10000.0 if 0 <= i < len(Si) else 0 for i in rmd_ids])
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
        fwd_speed = np.einsum('ij,ij->i', com_vel, fwd[:-1])[len(sec) // 5:].mean() * 1000
        skip = n // 5
        per_amp = np.degrees(ja[skip:, yaw_idx].max(0) - ja[skip:, yaw_idx].min(0))
        rmd_amp = (S_rmd[skip:].max(0) - S_rmd[skip:].min(0)).mean()
        com_disp = float(np.linalg.norm(com[-1, :2] - com[0, :2]))
        win_amps = []
        for w in range(0, int(sec[-1]), 10):
            mask = (sec >= w) & (sec < w + 10)
            if mask.any():
                win_amps.append(np.degrees(ja[mask][:, yaw_idx[6]].max() - ja[mask][:, yaw_idx[6]].min()))
        amps_str = '/'.join((f'{a:.0f}°' for a in win_amps[:6]))
        print(f'  fwd={fwd_speed:+.1f}µm/s  yaw h/m/t: {per_amp[1]:.0f}°/{per_amp[6]:.0f}°/{per_amp[10]:.0f}°  RMD.S amp={rmd_amp:.2f}  COM_disp={com_disp:.2f}mm  mid_amp_per_10s: {amps_str}')

async def main():
    await run('Phase A only (external CPG @ RMD)', [{'path': 'sim.neuromod.HEAD_CPG_AT_RMD', 'value': True}, {'path': 'sim.neuromod.HEAD_CPG_AMP', 'value': 0.2}, {'path': 'sim.neuromod.INTRINSIC_OSC_ENABLED', 'value': False}])
    await run('Hybrid (CPG=0.20 + intrinsic 0.10)', [{'path': 'sim.neuromod.HEAD_CPG_AT_RMD', 'value': True}, {'path': 'sim.neuromod.HEAD_CPG_AMP', 'value': 0.2}, {'path': 'sim.neuromod.INTRINSIC_OSC_ENABLED', 'value': True}, {'path': 'sim.neuromod.INTRINSIC_OSC_AMP', 'value': 0.1}, {'path': 'sim.neuromod.INTRINSIC_OSC_BASELINE', 'value': 0.05}])
    for amp in [0.1, 0.2, 0.3]:
        for baseline in [0.05, 0.1, 0.2]:
            await run(f'Intrinsic only (amp={amp}, baseline={baseline})', [{'path': 'sim.neuromod.HEAD_CPG_AT_RMD', 'value': True}, {'path': 'sim.neuromod.HEAD_CPG_AMP', 'value': 0.0}, {'path': 'sim.neuromod.INTRINSIC_OSC_ENABLED', 'value': True}, {'path': 'sim.neuromod.INTRINSIC_OSC_AMP', 'value': amp}, {'path': 'sim.neuromod.INTRINSIC_OSC_BASELINE', 'value': baseline}])
if __name__ == '__main__':
    asyncio.run(main())

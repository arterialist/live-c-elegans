"""Test the three phases at different settings."""
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
    if patches:
        post_json('/api/patch', {'patches': patches})
    post_json('/api/reset', {})
    await asyncio.sleep(0.5)
    async with websockets.connect(URL_WS, max_size=2 ** 24) as ws:
        hello = json.loads(await ws.recv())
        joints = hello['L_body']['joints']
        names = hello['L']['nm']
        yaw_idx = [i for i, jn in enumerate(joints) if 'yaw' in jn]
        ticks_l, com_l, sm_l, ja_l, S_l = ([], [], [], [], [])
        last_tick = -1
        rmd_ids = [names.index(n) for n in ['RMDDL', 'RMDDR', 'RMDVL', 'RMDVR'] if n in names]
        db1_id = names.index('DB1') if 'DB1' in names else -1
        vb1_id = names.index('VB1') if 'VB1' in names else -1
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
            S_l.append([Si[i] / 10000.0 if i >= 0 and i < len(Si) else 0 for i in rmd_ids + [db1_id, vb1_id]])
            if tick >= target:
                break
        ticks = np.array(ticks_l, dtype=np.int32)
        n = len(ticks)
        sec = (ticks - ticks[0]) * 0.002
        com = np.stack([c / 1000000.0 for c in com_l])
        seg = np.stack([s / 1000000.0 for s in sm_l]).reshape(n, -1, 3)
        ja = np.stack(ja_l).astype(float) / 10000.0
        head = seg[:, 0, :2]
        tail = seg[:, -1, :2]
        fwd = (head - tail) / (np.linalg.norm(head - tail, axis=1, keepdims=True) + 1e-09)
        com_vel = np.diff(com[:, :2], axis=0) / np.diff(sec).reshape(-1, 1)
        fwd_speed = np.einsum('ij,ij->i', com_vel, fwd[:-1])[len(sec) // 5:].mean() * 1000
        yaws = ja[:, yaw_idx]
        skip = n // 5
        per_amp = np.degrees(yaws[skip:].max(0) - yaws[skip:].min(0))
        S_arr = np.array(S_l)
        rmd_amp = (S_arr[skip:, :len(rmd_ids)].max(0) - S_arr[skip:, :len(rmd_ids)].min(0)).mean()
        db1_amp = S_arr[skip:, len(rmd_ids)].max() - S_arr[skip:, len(rmd_ids)].min()
        vb1_amp = S_arr[skip:, len(rmd_ids) + 1].max() - S_arr[skip:, len(rmd_ids) + 1].min()
        print(f'  fwd={fwd_speed:+.1f}µm/s  yaw amp h/m/t: {per_amp[1]:.0f}°/{per_amp[6]:.0f}°/{per_amp[10]:.0f}°  RMD.S amp={rmd_amp:.2f}  DB1.S amp={db1_amp:.2f}  VB1.S amp={vb1_amp:.2f}')

async def main():
    await run('Phase A default (CPG@RMD amp=0.20)', [{'path': 'sim.neuromod.HEAD_CPG_AT_RMD', 'value': True}, {'path': 'sim.neuromod.HEAD_CPG_AMP', 'value': 0.2}, {'path': 'sim.neuromod.INTRINSIC_OSC_ENABLED', 'value': False}])
    for amp in [0.5, 1.0, 2.0]:
        await run(f'Phase A CPG@RMD amp={amp}', [{'path': 'sim.neuromod.HEAD_CPG_AT_RMD', 'value': True}, {'path': 'sim.neuromod.HEAD_CPG_AMP', 'value': amp}, {'path': 'sim.neuromod.INTRINSIC_OSC_ENABLED', 'value': False}])
    await run('Phase B intrinsic osc only (CPG=0)', [{'path': 'sim.neuromod.HEAD_CPG_AT_RMD', 'value': True}, {'path': 'sim.neuromod.HEAD_CPG_AMP', 'value': 0.0}, {'path': 'sim.neuromod.INTRINSIC_OSC_ENABLED', 'value': True}, {'path': 'sim.neuromod.INTRINSIC_OSC_AMP', 'value': 0.2}, {'path': 'sim.neuromod.INTRINSIC_OSC_BASELINE', 'value': 0.1}])
    await run('Phase B intrinsic amp=0.50, baseline=0.20', [{'path': 'sim.neuromod.HEAD_CPG_AMP', 'value': 0.0}, {'path': 'sim.neuromod.INTRINSIC_OSC_ENABLED', 'value': True}, {'path': 'sim.neuromod.INTRINSIC_OSC_AMP', 'value': 0.5}, {'path': 'sim.neuromod.INTRINSIC_OSC_BASELINE', 'value': 0.2}])
    await run('Phase A+B combined (CPG@RMD amp=0.20 + intrinsic 0.10)', [{'path': 'sim.neuromod.HEAD_CPG_AT_RMD', 'value': True}, {'path': 'sim.neuromod.HEAD_CPG_AMP', 'value': 0.2}, {'path': 'sim.neuromod.INTRINSIC_OSC_ENABLED', 'value': True}, {'path': 'sim.neuromod.INTRINSIC_OSC_AMP', 'value': 0.1}, {'path': 'sim.neuromod.INTRINSIC_OSC_BASELINE', 'value': 0.05}])
    await run('Legacy: CPG@DB1/VB1 (Phase A=False)', [{'path': 'sim.neuromod.HEAD_CPG_AT_RMD', 'value': False}, {'path': 'sim.neuromod.HEAD_CPG_AMP', 'value': 0.2}, {'path': 'sim.neuromod.INTRINSIC_OSC_ENABLED', 'value': False}])
if __name__ == '__main__':
    asyncio.run(main())

"""Isolated controlled experiments for the turn-bias issue.

Hypotheses:
  H0  baseline                                           — what is the typical bias?
  H1  N=5 fresh resets, default params                   — is the bias direction random?
  H2  zero proprio gain                                  — does bias persist without stretch reflex?
  H3  zero CPG amplitude (no head drive)                 — does body settle straight or curl?
  H4  symmetric DB↔VB activation (boost DB by 11/7)      — does count compensation help?
  H5  graded-only body-wall motor neurons (no spikes)    — bio-accurate transmission
  H6  H4 + H5 combined                                   — best of both fixes
  H7  density 0 (kills swimming thrust)                  — pure-neural locomotion test
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

def patch_neuron(name, field, value):
    return post_json(f'/api/neurons/{name}/patch', {'patches': [{'field': field, 'value': value}]})
DB = [f'DB{i}' for i in range(1, 8)]
VB = [f'VB{i}' for i in range(1, 12)]
DA = [f'DA{i}' for i in range(1, 10)]
VA = [f'VA{i}' for i in range(1, 13)]
AS = [f'AS{i}' for i in range(1, 12)]
DD = [f'DD{i}' for i in range(1, 7)]
VD = [f'VD{i}' for i in range(1, 14)]
BODY_WALL = DB + VB + DA + VA + AS + DD + VD

async def reset_and_capture(target_ticks=15000):
    """Reset and capture body state. Returns (sec, com, seg, ja, fired_DB, fired_VB)."""
    post_json('/api/reset', {})
    await asyncio.sleep(0.5)
    async with websockets.connect(URL_WS, max_size=2 ** 24) as ws:
        hello = json.loads(await ws.recv())
        names = hello['L']['nm']
        joints = hello['L_body']['joints']
        n_neurons = len(names)
        yaw_idx = [i for i, jn in enumerate(joints) if 'yaw' in jn]
        db_ids = [names.index(n) for n in DB if n in names]
        vb_ids = [names.index(n) for n in VB if n in names]
        ticks_l, com_l, sm_l, ja_l, fdb_l, fvb_l = ([], [], [], [], [], [])
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
            b64 = d.get('Fb', '')
            if b64:
                raw = base64.b64decode(b64)
                fired_arr = np.zeros(n_neurons, dtype=np.uint8)
                for i in range(n_neurons):
                    if raw[i >> 3] & 1 << (i & 7):
                        fired_arr[i] = 1
                fdb_l.append(fired_arr[db_ids].sum())
                fvb_l.append(fired_arr[vb_ids].sum())
            else:
                fdb_l.append(0)
                fvb_l.append(0)
            if tick >= target_ticks:
                break
        ticks = np.array(ticks_l, dtype=np.int32)
        n = len(ticks)
        sec = (ticks - ticks[0]) * 0.002
        com = np.stack([c / 1000000.0 for c in com_l])
        seg = np.stack([s / 1000000.0 for s in sm_l]).reshape(n, -1, 3)
        ja = np.stack(ja_l).astype(float) / 10000.0
        fdb = np.array(fdb_l, dtype=int)
        fvb = np.array(fvb_l, dtype=int)
        return (sec, com, seg, ja, yaw_idx, fdb, fvb)

def metrics(sec, com, seg, ja, yaw_idx, fdb, fvb):
    """Compute turn metrics: signed angle change, mean yaw, D vs V firing."""
    head = seg[:, 0, :2]
    tail = seg[:, -1, :2]
    forward = (head - tail) / (np.linalg.norm(head - tail, axis=1, keepdims=True) + 1e-09)
    ang = np.arctan2(forward[:, 1], forward[:, 0])
    ang_unwrapped = np.unwrap(ang)
    heading_change_deg = float(np.degrees(ang_unwrapped[-1] - ang_unwrapped[0]))
    com_vel = np.diff(com[:, :2], axis=0) / np.diff(sec).reshape(-1, 1)
    fwd_speed = np.einsum('ij,ij->i', com_vel, forward[:-1])
    skip = len(sec) // 5
    late_fwd = fwd_speed[skip:].mean() * 1000
    yaws = ja[:, yaw_idx]
    mean_yaw = float(yaws[skip:].mean())
    fdb_total = int(fdb[skip:].sum())
    fvb_total = int(fvb[skip:].sum())
    return {'duration': sec[-1], 'heading_change_deg': heading_change_deg, 'fwd_speed_um_s': late_fwd, 'mean_yaw_rad': mean_yaw, 'DB_firings': fdb_total, 'VB_firings': fvb_total, 'VB_DB_ratio': fvb_total / max(fdb_total, 1)}

async def run_one(label, setup_fn=None, ticks=15000):
    print(f'\n=== {label} ===')
    if setup_fn:
        await setup_fn()
    out = await reset_and_capture(ticks)
    m = metrics(*out)
    print(f'  duration={m['duration']:.1f}s  fwd_speed={m['fwd_speed_um_s']:+.1f}µm/s  heading_change={m['heading_change_deg']:+.0f}°  mean_yaw={np.degrees(m['mean_yaw_rad']):+.2f}°  DB:VB firings = {m['DB_firings']}:{m['VB_firings']} (ratio {m['VB_DB_ratio']:.2f})')
    return (label, m)

async def restore_defaults():
    post_json('/api/patch', {'patches': [{'path': 'sim.neuromod.HEAD_CPG_FREQ_HZ', 'value': 0.6}, {'path': 'sim.neuromod.HEAD_CPG_AMP', 'value': 0.2}, {'path': 'sim.neuromod.PROPRIO_MOTOR_GAIN', 'value': 0.1}, {'path': 'sim.muscles.filter_alpha', 'value': 0.08}, {'path': 'sim.muscles.inhib_weight', 'value': 0.8}, {'path': 'sim.mujoco.opt.density', 'value': 2000.0}, {'path': 'sim.mujoco.opt.viscosity', 'value': 0.3}]})

async def main():
    results = []
    await restore_defaults()
    print('\n>>> H1: 5 resets at default — is turn direction random?')
    h1_runs = []
    for i in range(5):
        _, m = await run_one(f'H1.{i + 1} default-reset', ticks=10000)
        h1_runs.append(m)
        results.append((f'H1.{i + 1}', m))
    headings = [r['heading_change_deg'] for r in h1_runs]
    yaws = [r['mean_yaw_rad'] for r in h1_runs]
    print(f'\n  H1 summary: heading_change values: {[f'{h:+.0f}°' for h in headings]}')
    print(f'             same-sign? {('YES' if all((h > 0 for h in headings)) or all((h < 0 for h in headings)) else 'NO (random)')}')
    print(f'             mean_yaw: {[f'{np.degrees(y):+.2f}°' for y in yaws]}')

    async def setup_h2():
        await restore_defaults()
        post_json('/api/patch', {'patches': [{'path': 'sim.neuromod.PROPRIO_MOTOR_GAIN', 'value': 0.0}]})
    results.append(await run_one('H2 PROPRIO=0', setup_h2, ticks=12000))

    async def setup_h3():
        await restore_defaults()
        post_json('/api/patch', {'patches': [{'path': 'sim.neuromod.HEAD_CPG_AMP', 'value': 0.0}]})
    results.append(await run_one('H3 CPG_AMP=0 (no head drive)', setup_h3, ticks=12000))

    async def setup_h5():
        await restore_defaults()
        post_json('/api/reset', {})
        await asyncio.sleep(0.5)
        for n in BODY_WALL:
            try:
                patch_neuron(n, 'r_base', 1000000.0)
                patch_neuron(n, 'b_base', 1000000.0)
                patch_neuron(n, 'r', 1000000.0)
                patch_neuron(n, 'b', 1000000.0)
            except:
                pass
    print('\n>>> H5: body-wall motor neurons graded-only (no spikes — bio-accurate)')
    await setup_h5()
    out = await capture_only(12000)
    m = metrics(*out)
    print(f'H5 graded-only:  duration={m['duration']:.1f}s  fwd_speed={m['fwd_speed_um_s']:+.1f}µm/s  heading_change={m['heading_change_deg']:+.0f}°  mean_yaw={np.degrees(m['mean_yaw_rad']):+.2f}°  DB:VB = {m['DB_firings']}:{m['VB_firings']}')
    results.append(('H5 graded-only', m))

    async def setup_h7():
        await restore_defaults()
        post_json('/api/patch', {'patches': [{'path': 'sim.mujoco.opt.density', 'value': 0.0}, {'path': 'sim.mujoco.opt.viscosity', 'value': 0.0}]})
    results.append(await run_one('H7 density=0, viscosity=0 (no fluid)', setup_h7, ticks=12000))
    await restore_defaults()
    print('\n=== Summary table ===')
    print(f'{'experiment':35s}  {'fwd µm/s':>10s}  {'turn deg':>10s}  {'mean yaw':>10s}  {'DB:VB':>10s}')
    for label, m in results:
        print(f'  {label:35s}  {m['fwd_speed_um_s']:+9.1f}  {m['heading_change_deg']:+9.0f}°  {np.degrees(m['mean_yaw_rad']):+9.2f}°  {m['DB_firings']}:{m['VB_firings']}')

async def capture_only(target_ticks):
    async with websockets.connect(URL_WS, max_size=2 ** 24) as ws:
        hello = json.loads(await ws.recv())
        names = hello['L']['nm']
        joints = hello['L_body']['joints']
        n_neurons = len(names)
        yaw_idx = [i for i, jn in enumerate(joints) if 'yaw' in jn]
        db_ids = [names.index(n) for n in DB if n in names]
        vb_ids = [names.index(n) for n in VB if n in names]
        ticks_l, com_l, sm_l, ja_l, fdb_l, fvb_l = ([], [], [], [], [], [])
        last_tick = -1
        start_tick = None
        while True:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
            except asyncio.TimeoutError:
                break
            d = json.loads(msg)
            if d.get('t') != 's':
                continue
            tick = d.get('k', 0)
            if start_tick is None:
                start_tick = tick
            if tick == last_tick:
                continue
            last_tick = tick
            ticks_l.append(tick)
            com_l.append(np.array(d.get('cm', [0, 0, 0]), dtype=np.int64))
            sm_l.append(np.array(d.get('sm', []), dtype=np.int64))
            ja_l.append(np.array(d.get('ja', []), dtype=np.int32))
            b64 = d.get('Fb', '')
            if b64:
                raw = base64.b64decode(b64)
                fired_arr = np.zeros(n_neurons, dtype=np.uint8)
                for i in range(n_neurons):
                    if raw[i >> 3] & 1 << (i & 7):
                        fired_arr[i] = 1
                fdb_l.append(fired_arr[db_ids].sum())
                fvb_l.append(fired_arr[vb_ids].sum())
            else:
                fdb_l.append(0)
                fvb_l.append(0)
            if tick - start_tick >= target_ticks:
                break
        ticks = np.array(ticks_l, dtype=np.int32)
        n = len(ticks)
        sec = (ticks - ticks[0]) * 0.002
        com = np.stack([c / 1000000.0 for c in com_l])
        seg = np.stack([s / 1000000.0 for s in sm_l]).reshape(n, -1, 3)
        ja = np.stack(ja_l).astype(float) / 10000.0
        return (sec, com, seg, ja, yaw_idx, np.array(fdb_l), np.array(fvb_l))
if __name__ == '__main__':
    asyncio.run(main())

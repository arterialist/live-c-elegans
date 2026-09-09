"""Final calibration sweep with graded-only motors as default.

Address remaining issues:
  1. Wavelength too long (0.55 in body, target 1-1.5) — sweep freq
  2. Turn bias (~+3° mean yaw, 1.5mm circle) — try CPG amp + freq combos
  3. D-type silence (max S 0.05) — check connectome inputs
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

async def probe(label, freq, amp, ticks=18000):
    print(f'\n=== {label} ===')
    post_json('/api/patch', {'patches': [{'path': 'sim.neuromod.HEAD_CPG_FREQ_HZ', 'value': float(freq)}, {'path': 'sim.neuromod.HEAD_CPG_AMP', 'value': float(amp)}]})
    post_json('/api/reset', {})
    await asyncio.sleep(0.5)
    async with websockets.connect(URL_WS, max_size=2 ** 24) as ws:
        hello = json.loads(await ws.recv())
        joints = hello['L_body']['joints']
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
            if tick >= ticks:
                break
        ticks_a = np.array(ticks_l, dtype=np.int32)
        n = len(ticks_a)
        sec = (ticks_a - ticks_a[0]) * 0.002
        com = np.stack([c / 1000000.0 for c in com_l])
        seg = np.stack([s / 1000000.0 for s in sm_l]).reshape(n, -1, 3)
        ja = np.stack(ja_l).astype(float) / 10000.0
        yaws = ja[:, yaw_idx]
        skip = n // 5
        ys = yaws[skip:] if skip < n else yaws
        F = np.fft.rfft(ys - ys.mean(0), axis=0)
        fr = np.fft.rfftfreq(ys.shape[0], 1 / (1 / 0.002 / np.median(np.diff(ticks_a))))
        mask = (fr > 0.1) & (fr < 3.0)
        pk_idx = np.argmax(np.abs(F[mask, 0]))
        phases = np.angle(F[mask, :][pk_idx])
        phases_unwrapped = np.unwrap(phases)
        seg_per_2pi = 2 * np.pi / abs(np.mean(np.diff(phases_unwrapped))) if np.diff(phases_unwrapped).std() > 0 else float('inf')
        wavelengths_in_body = 12 / seg_per_2pi if seg_per_2pi > 0 else 0
        head = seg[:, 0, :2]
        tail = seg[:, -1, :2]
        forward = (head - tail) / (np.linalg.norm(head - tail, axis=1, keepdims=True) + 1e-09)
        com_vel = np.diff(com[:, :2], axis=0) / np.diff(sec).reshape(-1, 1)
        fwd_speed = np.einsum('ij,ij->i', com_vel, forward[:-1])[skip:].mean() * 1000
        ang = np.unwrap(np.arctan2(forward[:, 1], forward[:, 0]))
        heading_change_deg = float(np.degrees(ang[-1] - ang[0]))
        per_amp = yaws[skip:].max(0) - yaws[skip:].min(0)
        head_amp = np.degrees(per_amp[1])
        tail_amp = np.degrees(per_amp[10])
        zc_per = []
        for y in yaws[skip:]:
            cnt = 0
            prev = None
            for v in y:
                if abs(v) < 0.04:
                    continue
                s = 1 if v > 0 else -1
                if prev is not None and s != prev:
                    cnt += 1
                prev = s
            zc_per.append(cnt)
        pct_ge2 = (np.array(zc_per) >= 2).mean() * 100
        mean_yaw = float(yaws[skip:].mean())
        print(f'  fwd={fwd_speed:+.1f}µm/s  turn={heading_change_deg:+.0f}°  mean_yaw={np.degrees(mean_yaw):+.2f}°  wavelengths={wavelengths_in_body:.2f}  pct≥2={pct_ge2:.0f}%  amp head/tail={head_amp:.0f}°/{tail_amp:.0f}°')
        return {'label': label, 'freq': freq, 'amp': amp, 'fwd_speed': fwd_speed, 'turn_deg': heading_change_deg, 'mean_yaw_deg': np.degrees(mean_yaw), 'wavelengths': wavelengths_in_body, 'pct_ge2': pct_ge2}

async def main():
    results = []
    for f in [0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.2]:
        results.append(await probe(f'freq={f} amp=0.20', f, 0.2))
    for amp in [0.15, 0.25, 0.3]:
        results.append(await probe(f'freq=0.8 amp={amp}', 0.8, amp))
    results.append(await probe('freq=0.7 amp=0.25', 0.7, 0.25))
    results.append(await probe('freq=0.9 amp=0.18', 0.9, 0.18))
    post_json('/api/patch', {'patches': [{'path': 'sim.neuromod.HEAD_CPG_FREQ_HZ', 'value': 0.6}, {'path': 'sim.neuromod.HEAD_CPG_AMP', 'value': 0.2}]})
    print('\n=== ranking by wavelength match (target ~1.0) ===')
    for r in sorted(results, key=lambda x: abs(x['wavelengths'] - 1.0)):
        print(f'  {r['label']:25s}  λ={r['wavelengths']:.2f}  pct≥2={r['pct_ge2']:.0f}%  fwd={r['fwd_speed']:+.1f}µm/s  turn={r['turn_deg']:+.0f}°  yaw={r['mean_yaw_deg']:+.2f}°')
if __name__ == '__main__':
    asyncio.run(main())

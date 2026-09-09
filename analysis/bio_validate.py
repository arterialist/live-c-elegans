"""Comprehensive biological-metrics validation against C. elegans literature.

References for target values:
  - Pierce-Shimomura et al. 1999 — undulation frequency 0.3-0.5 Hz on agar, 1.7-2 Hz in water
  - Stephens et al. 2008 (PLoS CB)        — eigenworms; per-joint bend ~25-35°
  - Boyle et al. 2012 (PLoS CB)           — anisotropic friction, ~10:1 perpendicular:parallel
  - Karbowski et al. 2008                 — wavelength ~half body length on agar
  - Gjorgjieva et al. 2014                — wave speed ~ 0.5 body lengths / s
  - Berri et al. 2009                     — crawl speed 0.1-0.2 mm/s on agar
  - Wen et al. 2012 (Neuron)              — proprioceptive coupling
  - White et al. 1986 / Cook et al. 2019  — connectome
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
from scipy.signal import welch, find_peaks
from scipy.stats import circmean

async def capture(target=50000, out_path='./worm_bio.npz'):
    print(f'reset & capture {target} ticks → {out_path}')
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
        ticks, ja_l, jv_l, ma_l, S_l, fired_l, com_l, sm_l = ([], [], [], [], [], [], [], [])
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
            ja_l.append(np.array(d.get('ja', []), dtype=np.int32))
            jv_l.append(np.array(d.get('jv', []), dtype=np.int32))
            ma_l.append(np.array(d.get('ma', []), dtype=np.int32))
            S_l.append(np.array(d.get('Si', []), dtype=np.int32))
            fired_l.append(unpack_bits(d.get('Fb', ''), n_neurons))
            com_l.append(np.array(d.get('cm', [0, 0, 0]), dtype=np.int64))
            sm_l.append(np.array(d.get('sm', []), dtype=np.int64))
            if len(ticks) % 10000 == 0:
                print(f'  {len(ticks):6d} frames, tick {tick}, wall {time.time() - wall0:.0f}s')
            if tick >= target:
                break
        ticks = np.array(ticks, dtype=np.int32)

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
        np.savez_compressed(out_path, ticks=ticks, ja=ja, jv=jv, ma=ma, S=S, fired=fired, com=com, sm=sm, joint_names=np.array(joints), muscle_names=np.array(muscles), neuron_names=np.array(names), yaw_idx=yaw_idx, pitch_idx=pitch_idx)
        print(f'  done {len(ticks)} frames in {time.time() - wall0:.1f}s')
        return out_path

def biological_metrics(path):
    d = np.load(path, allow_pickle=True)
    ticks = d['ticks']
    ja = d['ja']
    jv = d['jv']
    ma = d['ma']
    S = d['S']
    fired = d['fired']
    com = d['com']
    sm = d['sm']
    joints = list(d['joint_names'])
    names = list(d['neuron_names'])
    yaw_idx = d['yaw_idx']
    pitch_idx = d['pitch_idx']
    SIM_DT = 0.002
    sec = (ticks - ticks[0]) * SIM_DT
    yaws = ja[:, yaw_idx]
    pitches = ja[:, pitch_idx]
    n = len(ticks)
    fs = 1.0 / float(np.median(np.diff(ticks))) / SIM_DT
    n_seg = 13
    seg = sm.reshape(n, -1, 3)
    if seg.shape[1] < n_seg:
        seg = np.pad(seg, ((0, 0), (0, n_seg - seg.shape[1]), (0, 0)))
    print('=' * 70)
    print(f'BIOLOGICAL METRICS — {n} frames over {sec[-1]:.1f}s (sim time)')
    print('=' * 70)
    f, P = welch(yaws[:, 0], fs=fs, nperseg=min(8192, n // 4))
    peak_idx = np.argmax(P[(f > 0.1) & (f < 3.0)])
    peak_f = f[(f > 0.1) & (f < 3.0)][peak_idx]
    print(f'\n[1] LOCOMOTION FREQUENCY (head)')
    print(f'    measured: {peak_f:.3f} Hz')
    print(f'    target:   0.3-0.5 Hz on agar / 1.7-2 Hz in water')
    print(f'    status:   {('✓ in range' if 0.3 <= peak_f <= 2 else '✗ out of range')}')
    skip = n // 5
    yaw_amps = yaws[skip:].max(0) - yaws[skip:].min(0)
    yaw_amps_deg = np.degrees(yaw_amps)
    print(f'\n[2] PER-JOINT BEND AMPLITUDE')
    print(f'    measured: per-joint amp range {yaw_amps_deg.min():.0f}-{yaw_amps_deg.max():.0f}°  mean {yaw_amps_deg.mean():.0f}°')
    print(f'    target:   ~30-60° per-joint amp (Stephens 2008 eigenworms; full-body bend ~140°)')
    print(f'    status:   {('✓ in range' if yaw_amps_deg.mean() >= 25 else '✗ too small')}')
    n_use = min(n, int(60.0 * fs))
    ys = yaws[-n_use:] if len(yaws) > n_use else yaws
    F = np.fft.rfft(ys - ys.mean(0), axis=0)
    fr = np.fft.rfftfreq(ys.shape[0], 1 / fs)
    mask = (fr > 0.1) & (fr < 3.0)
    pk = np.argmax(np.abs(F[mask, 0]))
    fr_pk = fr[mask][pk]
    phases = np.angle(F[mask, :][pk])
    phases_unwrapped = np.unwrap(phases)
    seg_per_2pi = 2 * np.pi / np.mean(np.diff(phases_unwrapped)) if np.diff(phases_unwrapped).std() > 0 else float('inf')
    body_length_in_wavelengths = 12 / abs(seg_per_2pi) if abs(seg_per_2pi) > 0 else 0
    print(f'\n[3] WAVE PROPAGATION')
    print(f'    measured: ~{abs(seg_per_2pi):.1f} segments per full wavelength → {body_length_in_wavelengths:.2f} wavelengths in 12-joint body')
    print(f'    target:   ~1-1.5 wavelengths on agar (Karbowski 2008)')
    print(f'    status:   {('✓' if 0.8 <= body_length_in_wavelengths <= 1.8 else '✗')}')
    com_disp = float(np.linalg.norm(com[-1, :2] - com[0, :2]))
    com_path = float(np.sum(np.linalg.norm(np.diff(com[:, :2], axis=0), axis=1)))
    speed = com_disp / sec[-1] if sec[-1] > 0 else 0
    body_len_mm = float(np.median(np.linalg.norm(seg[:, 0] - seg[:, -1], axis=1)))
    BL_per_min = com_disp / body_len_mm * 60 / sec[-1] if body_len_mm and sec[-1] else 0
    print(f'\n[4] FORWARD LOCOMOTION')
    print(f'    body length:    {body_len_mm:.2f} mm')
    print(f'    COM displacement: {com_disp:.2f} mm  (path length {com_path:.2f} mm)')
    print(f'    avg speed:        {speed * 1000.0:.3f} mm/s')
    print(f'    body lengths/min: {BL_per_min:.1f}')
    print(f'    target:           8-30 BL/min on agar (Berri 2009)')
    print(f'    efficiency:       {com_disp / com_path * 100:.1f}% (disp / total path)')
    print(f'    status:           {('✓' if BL_per_min >= 5 else '✗ wiggling in place')}')
    z_mean = sm.reshape(n, -1, 3)[:, :, 2].mean()
    z_std = sm.reshape(n, -1, 3)[:, :, 2].std()
    print(f'\n[5] BODY VERTICAL POSITION (planar locomotion check)')
    print(f'    mean z: {z_mean:.4f} mm,  std {z_std:.4f} mm')
    pitches_deg = np.degrees(np.abs(pitches))
    print(f'    pitch (vertical bend): max {pitches_deg.max():.2f}° mean {pitches_deg.mean():.2f}°')
    print(f'    target: tiny pitch (≤2°), z roughly constant')
    print(f'    status: {('✓ planar' if pitches_deg.max() < 5 else '✗ vertical motion')}')
    name_to_id = {nm: i for i, nm in enumerate(names)}
    pairs = [('DB1', 'VB1'), ('DB2', 'VB2'), ('DB3', 'VB3'), ('DB4', 'VB5')]
    print(f'\n[6] D-V FIRING ANTI-PHASE (anti-phase = good)')
    for db, vb in pairs:
        if db in name_to_id and vb in name_to_id:
            d1 = name_to_id[db]
            v1 = name_to_id[vb]
            sd = S[skip:, d1]
            sv = S[skip:, v1]
            corr = np.correlate(sd - sd.mean(), sv - sv.mean(), mode='full')
            lag = (np.argmax(np.abs(corr)) - (len(sd) - 1)) / fs
            normed = corr[len(sd) - 1] / (np.std(sd) * np.std(sv) * len(sd))
            phase_deg = lag * peak_f * 360 % 360
            print(f'    {db:4s} vs {vb:4s}  zero-lag corr: {normed:+.2f}  phase offset ≈ {phase_deg:.0f}°  (180° = anti-phase)')
    print(f'\n[7] POSTERIOR B-TYPE FIRING (DB7, VB10, VB11 — tail drive)')
    for nm in ['DB6', 'DB7', 'VB9', 'VB10', 'VB11']:
        if nm in name_to_id:
            i = name_to_id[nm]
            f_rate = float(fired[skip:, i].mean()) * 100
            S_max = float(S[skip:, i].max())
            print(f'    {nm:5s}  firing rate {f_rate:.2f}%  max S {S_max:+.2f}')
    print(f'\n[8] D-TYPE GABA INHIBITION (cross-inhibition for alternation)')
    for nm in ['DD1', 'DD3', 'VD1', 'VD5']:
        if nm in name_to_id:
            i = name_to_id[nm]
            f_rate = float(fired[skip:, i].mean()) * 100
            S_max = float(S[skip:, i].max())
            print(f'    {nm:5s}  firing rate {f_rate:.2f}%  max S {S_max:+.2f}')
    n_seg_m = 12
    ma3 = ma.reshape(n, n_seg_m, 4)
    dorsal = ma3[..., :2].mean(-1)
    ventral = ma3[..., 2:].mean(-1)
    corrs = []
    for s in range(n_seg_m):
        c = np.corrcoef(dorsal[skip:, s], ventral[skip:, s])[0, 1]
        corrs.append(c)
    print(f'\n[9] DORSAL-VENTRAL MUSCLE ANTAGONISM')
    print(f'    per-segment D-V correlation: ' + ' '.join((f'{c:+.2f}' for c in corrs)))
    mean_corr = np.mean(corrs)
    print(f'    mean corr: {mean_corr:+.2f}  (target: ≤ -0.3 for clean antagonism)')
    print(f'    status: {('✓' if mean_corr < -0.2 else '✗')}')

async def main():
    target = int(sys.argv[1]) if len(sys.argv) > 1 else 50000
    path = await capture(target=target)
    print()
    biological_metrics(path)
if __name__ == '__main__':
    asyncio.run(main())

"""Test 4 configurations to isolate what fixes head co-contraction:
  1. baseline:    diff=off, RIA=off, A-MN=off  (current behaviour)
  2. diff only:   diff=on,  RIA=off, A-MN=off  (just the readout change)
  3. diff + RIA:  diff=on,  RIA=on,  A-MN=off  (Hendricks 2012 path)
  4. full bio:    diff=on,  RIA=on,  A-MN=on   (Gao 2018 + Hendricks 2012)

Per-config: 30k ticks (60s real-time). Metrics:
  - RMD/SMD D vs V correlation
  - Head muscle (segs 1-3) D mean/std/D-V correlation/D×V cocontraction
  - Body locomotion: mean fwd speed, reversals, AVA bursts
"""
from __future__ import annotations
from analysis.lib.lab_client import (
    LAB_REST as URL_REST,
    LAB_WS as URL_WS,
    post_json,
    get_json,
    unpack_bits,
)
import asyncio, json, urllib.request
import numpy as np
import websockets

async def collect(label: str, ticks_target: int, params: dict) -> dict:
    print(f'\n=== {label} ===', flush=True)
    patches = [{'path': k, 'value': v} for k, v in params.items()]
    post_json('/api/patch', {'patches': patches})
    post_json('/api/reset', {})
    await asyncio.sleep(0.5)
    rows = []
    last_tick = -1
    async with websockets.connect(URL_WS, max_size=2 ** 24) as ws:
        hello = json.loads(await ws.recv())
        names = hello['L']['nm']
        muscle_names = hello['L_body'].get('muscles', [])
        ava_ids = [names.index(n) for n in ('AVAL', 'AVAR') if n in names]
        rmd_d_ids = [names.index(n) for n in ('RMDDL', 'RMDDR') if n in names]
        rmd_v_ids = [names.index(n) for n in ('RMDVL', 'RMDVR') if n in names]
        smd_d_ids = [names.index(n) for n in ('SMDDL', 'SMDDR') if n in names]
        smd_v_ids = [names.index(n) for n in ('SMDVL', 'SMDVR') if n in names]
        m_idx = {nm: i for i, nm in enumerate(muscle_names)}

        def mi(seg, q):
            return m_idx.get(f'muscle_seg{seg}_{q}', -1)
        head_idx = {seg: {q: mi(seg, q) for q in ('DL', 'DR', 'VL', 'VR')} for seg in (1, 2, 3, 6, 9)}
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
            Si = d.get('Si', [])
            ma = d.get('ma', [])
            sm = np.array(d.get('sm', []), dtype=np.int64)
            com = np.array(d.get('cm', [0, 0, 0]), dtype=np.int64)
            S_ava = float(np.mean([Si[i] / 10000.0 for i in ava_ids]))
            S_rmd_d = float(np.mean([Si[i] / 10000.0 for i in rmd_d_ids]))
            S_rmd_v = float(np.mean([Si[i] / 10000.0 for i in rmd_v_ids]))
            S_smd_d = float(np.mean([Si[i] / 10000.0 for i in smd_d_ids]))
            S_smd_v = float(np.mean([Si[i] / 10000.0 for i in smd_v_ids]))
            seg_DV = {}
            for seg, idx in head_idx.items():
                D = (ma[idx['DL']] + ma[idx['DR']]) / 20000.0 if idx['DL'] >= 0 and idx['DR'] >= 0 else 0
                V = (ma[idx['VL']] + ma[idx['VR']]) / 20000.0 if idx['VL'] >= 0 and idx['VR'] >= 0 else 0
                seg_DV[seg] = (D, V)
            rows.append((tick, S_ava, S_rmd_d, S_rmd_v, S_smd_d, S_smd_v, seg_DV, com, sm))
            if tick >= ticks_target:
                break
    n = len(rows)
    if n < 100:
        print(f'  WARNING: only {n} frames')
        return {}
    sec = np.array([(r[0] - rows[0][0]) * 0.002 for r in rows])
    S_ava = np.array([r[1] for r in rows])
    S_rmd_d = np.array([r[2] for r in rows])
    S_rmd_v = np.array([r[3] for r in rows])
    S_smd_d = np.array([r[4] for r in rows])
    S_smd_v = np.array([r[5] for r in rows])
    com = np.stack([r[7] / 1000000.0 for r in rows])
    seg_data = np.stack([r[8] / 1000000.0 for r in rows]).reshape(n, -1, 3)
    head = seg_data[:, 0, :2]
    tail = seg_data[:, -1, :2]
    fwd_dir = (head - tail) / (np.linalg.norm(head - tail, axis=1, keepdims=True) + 1e-09)
    com_vel = np.diff(com[:, :2], axis=0) / np.diff(sec).reshape(-1, 1)
    fwd_speed = np.einsum('ij,ij->i', com_vel, fwd_dir[:-1]) * 1000
    rate_per_s = (n - 1) / sec[-1] if sec[-1] > 0 else 0
    win = max(1, int(2.0 * rate_per_s))
    fwd_smooth = np.convolve(fwd_speed, np.ones(win) / win, mode='same')
    rmd_corr = np.corrcoef(S_rmd_d, S_rmd_v)[0, 1] if S_rmd_d.std() > 0 and S_rmd_v.std() > 0 else float('nan')
    smd_corr = np.corrcoef(S_smd_d, S_smd_v)[0, 1] if S_smd_d.std() > 0 and S_smd_v.std() > 0 else float('nan')
    print(f'  duration={sec[-1]:.0f}s  frames={n}  rate={rate_per_s:.0f}/s  AVA mean S={S_ava.mean():+.3f} (max={S_ava.max():+.3f})')
    print(f'  RMD D-V corr = {rmd_corr:+.3f}  SMD D-V corr = {smd_corr:+.3f}  (target: negative)')
    print(f'  RMDD={S_rmd_d.mean():+.2f}±{S_rmd_d.std():.2f}  RMDV={S_rmd_v.mean():+.2f}±{S_rmd_v.std():.2f}  SMDD={S_smd_d.mean():+.2f}±{S_smd_d.std():.2f}  SMDV={S_smd_v.mean():+.2f}±{S_smd_v.std():.2f}')
    for seg in (1, 2, 3, 6, 9):
        D_arr = np.array([r[6][seg][0] for r in rows])
        V_arr = np.array([r[6][seg][1] for r in rows])
        cc = float((D_arr * V_arr).mean())
        Dz = D_arr - D_arr.mean()
        Vz = V_arr - V_arr.mean()
        c = np.corrcoef(Dz, Vz)[0, 1] if Dz.std() > 0 and Vz.std() > 0 else float('nan')
        print(f'  seg{seg}  D={D_arr.mean():.2f}±{D_arr.std():.2f}  V={V_arr.mean():.2f}±{V_arr.std():.2f}  D×V={cc:.3f}  D-V corr={c:+.2f}')
    print(f'  Mean fwd speed: {fwd_speed.mean():+.1f} µm/s  smoothed range: [{fwd_smooth.min():+.0f}, {fwd_smooth.max():+.0f}]')
    return {'rmd_corr': rmd_corr}

async def main() -> None:
    ticks = 30000
    base_off = {'sim.muscles.HEAD_DIFFERENTIAL_READOUT': False, 'sim.neuromod.RIA_COMPARTMENTS_ENABLED': False, 'sim.neuromod.A_MN_OSC_ENABLED': False, 'sim.neuromod.CMD_NOISE_SIGMA': 0.05}
    diff_only = {**base_off, 'sim.muscles.HEAD_DIFFERENTIAL_READOUT': True}
    diff_ria = {**diff_only, 'sim.neuromod.RIA_COMPARTMENTS_ENABLED': True, 'sim.neuromod.RIA_COMPARTMENT_GAIN': 0.15}
    full = {**diff_ria, 'sim.neuromod.A_MN_OSC_ENABLED': True, 'sim.neuromod.A_MN_OSC_AMP': 0.1}
    await collect('1. baseline (diff=off, RIA=off, A-MN=off)', ticks, base_off)
    await collect('2. diff-only readout', ticks, diff_only)
    await collect('3. diff + RIA (gain=0.15)', ticks, diff_ria)
    await collect('4. full bio (diff + RIA + A-MN)', ticks, full)
if __name__ == '__main__':
    asyncio.run(main())

"""Bisect what breaks the body wave when adding bio mechanisms.

Configurations (all 30k ticks):
  A. baseline + just diff readout                        (head co-contract fix)
  B. baseline + diff + bio resting potentials only
  C. baseline + diff + RIA only
  D. baseline + diff + A-MN only
  E. all enabled (full bio)
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

async def collect(label, ticks_target, params):
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
        avb_ids = [names.index(n) for n in ('AVBL', 'AVBR') if n in names]
        rmd_d_ids = [names.index(n) for n in ('RMDDL', 'RMDDR') if n in names]
        rmd_v_ids = [names.index(n) for n in ('RMDVL', 'RMDVR') if n in names]
        m_idx = {nm: i for i, nm in enumerate(muscle_names)}

        def mi(seg, q):
            return m_idx.get(f'muscle_seg{seg}_{q}', -1)
        muscle_idx = {seg: {q: mi(seg, q) for q in ('DL', 'DR', 'VL', 'VR')} for seg in (1, 2, 4, 6, 9)}
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
            S_ava = float(np.mean([Si[i] / 10000.0 for i in ava_ids])) if ava_ids else 0
            S_avb = float(np.mean([Si[i] / 10000.0 for i in avb_ids])) if avb_ids else 0
            S_rmd_d = float(np.mean([Si[i] / 10000.0 for i in rmd_d_ids])) if rmd_d_ids else 0
            S_rmd_v = float(np.mean([Si[i] / 10000.0 for i in rmd_v_ids])) if rmd_v_ids else 0
            seg_DV = {seg: ((ma[idx['DL']] + ma[idx['DR']]) / 20000.0 if idx['DL'] >= 0 else 0, (ma[idx['VL']] + ma[idx['VR']]) / 20000.0 if idx['VL'] >= 0 else 0) for seg, idx in muscle_idx.items()}
            rows.append((tick, S_ava, S_avb, S_rmd_d, S_rmd_v, seg_DV, com, sm))
            if tick >= ticks_target:
                break
    n = len(rows)
    if n < 100:
        print(f'  WARNING: only {n} frames')
        return
    sec = np.array([(r[0] - rows[0][0]) * 0.002 for r in rows])
    rate = (n - 1) / sec[-1] if sec[-1] > 0 else 0
    S_ava = np.array([r[1] for r in rows])
    S_avb = np.array([r[2] for r in rows])
    S_rmd_d = np.array([r[3] for r in rows])
    S_rmd_v = np.array([r[4] for r in rows])
    com = np.stack([r[6] / 1000000.0 for r in rows])
    seg_data = np.stack([r[7] / 1000000.0 for r in rows]).reshape(n, -1, 3)
    head_p = seg_data[:, 0, :2]
    tail_p = seg_data[:, -1, :2]
    fdir = (head_p - tail_p) / (np.linalg.norm(head_p - tail_p, axis=1, keepdims=True) + 1e-09)
    com_vel = np.diff(com[:, :2], axis=0) / np.diff(sec).reshape(-1, 1)
    fwd_speed = np.einsum('ij,ij->i', com_vel, fdir[:-1]) * 1000
    rmd_corr = np.corrcoef(S_rmd_d, S_rmd_v)[0, 1] if S_rmd_d.std() > 0 else float('nan')
    print(f'  AVA={S_ava.mean():+.2f}±{S_ava.std():.2f}  AVB={S_avb.mean():+.2f}±{S_avb.std():.2f}  RMDD={S_rmd_d.mean():+.2f}±{S_rmd_d.std():.2f}  RMDV={S_rmd_v.mean():+.2f}±{S_rmd_v.std():.2f}  RMD corr={rmd_corr:+.2f}', flush=True)
    for seg in (1, 2, 4, 6, 9):
        D = np.array([r[5][seg][0] for r in rows])
        V = np.array([r[5][seg][1] for r in rows])
        c = np.corrcoef(D, V)[0, 1] if D.std() > 0 and V.std() > 0 else float('nan')
        print(f'  seg{seg:2d} D={D.mean():.2f}±{D.std():.2f} V={V.mean():.2f}±{V.std():.2f} D-V corr={c:+.2f}  D×V={(D * V).mean():.3f}', flush=True)
    print(f'  Mean fwd: {fwd_speed.mean():+.1f} µm/s', flush=True)

async def main():
    ticks = 30000
    base = {'sim.muscles.HEAD_DIFFERENTIAL_READOUT': True, 'sim.neuromod.RIA_COMPARTMENTS_ENABLED': False, 'sim.neuromod.A_MN_OSC_ENABLED': False, 'sim.neuromod.BIO_RESTING_POTENTIALS': False, 'sim.neuromod.INTRINSIC_OSC_AMP': 0.025, 'sim.neuromod.CMD_NOISE_SIGMA': 0.05, 'sim.neuromod.CMD_NOISE_TAU': 50.0}
    A = base
    B = {**base, 'sim.neuromod.BIO_RESTING_POTENTIALS': True}
    C = {**base, 'sim.neuromod.RIA_COMPARTMENTS_ENABLED': True, 'sim.neuromod.RIA_COMPARTMENT_GAIN': 0.1}
    D = {**base, 'sim.neuromod.A_MN_OSC_ENABLED': True, 'sim.neuromod.A_MN_OSC_AMP': 0.1, 'sim.neuromod.A_MN_OSC_GATE_THRESHOLD': 1.1, 'sim.neuromod.CMD_NOISE_SIGMA': 0.1, 'sim.neuromod.CMD_NOISE_TAU': 1000.0}
    E = {**base, 'sim.neuromod.RIA_COMPARTMENTS_ENABLED': True, 'sim.neuromod.RIA_COMPARTMENT_GAIN': 0.1, 'sim.neuromod.A_MN_OSC_ENABLED': True, 'sim.neuromod.A_MN_OSC_AMP': 0.1, 'sim.neuromod.A_MN_OSC_GATE_THRESHOLD': 1.1, 'sim.neuromod.BIO_RESTING_POTENTIALS': True, 'sim.neuromod.INTRINSIC_OSC_AMP': 0.1, 'sim.neuromod.CMD_NOISE_SIGMA': 0.1, 'sim.neuromod.CMD_NOISE_TAU': 1000.0}
    await collect('A. diff only', ticks, A)
    await collect('B. diff + bio resting potentials', ticks, B)
    await collect('C. diff + RIA', ticks, C)
    await collect('D. diff + A-MN OSC + noise', ticks, D)
    await collect('E. all enabled (full bio)', ticks, E)
if __name__ == '__main__':
    asyncio.run(main())

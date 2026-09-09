"""Test the shared-phase intrinsic oscillator fix.

Configurations:
  1. baseline: shared-phase oscillator + diff readout OFF + RIA OFF + A-MN OFF
  2. shared-phase + diff readout (no RIA)
  3. shared-phase + diff + RIA at gain=0.05
  4. shared-phase + diff + RIA at gain=0.15
  5. amp_boost: shared-phase amp=0.10 + diff + RIA gain=0.10 + A-MN

Key: with shared phase, RMD D-V correlation should turn NEGATIVE.
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
        rmd_d_ids = [names.index(n) for n in ('RMDDL', 'RMDDR') if n in names]
        rmd_v_ids = [names.index(n) for n in ('RMDVL', 'RMDVR') if n in names]
        smd_d_ids = [names.index(n) for n in ('SMDDL', 'SMDDR') if n in names]
        smd_v_ids = [names.index(n) for n in ('SMDVL', 'SMDVR') if n in names]
        rmddl_id = names.index('RMDDL') if 'RMDDL' in names else -1
        rmdvl_id = names.index('RMDVL') if 'RMDVL' in names else -1
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
            S_rmd_d = float(np.mean([Si[i] / 10000.0 for i in rmd_d_ids]))
            S_rmd_v = float(np.mean([Si[i] / 10000.0 for i in rmd_v_ids]))
            S_smd_d = float(np.mean([Si[i] / 10000.0 for i in smd_d_ids]))
            S_smd_v = float(np.mean([Si[i] / 10000.0 for i in smd_v_ids]))
            S_rmddl = Si[rmddl_id] / 10000.0 if 0 <= rmddl_id < len(Si) else 0
            S_rmdvl = Si[rmdvl_id] / 10000.0 if 0 <= rmdvl_id < len(Si) else 0
            seg_DV = {}
            for seg, idx in head_idx.items():
                D = (ma[idx['DL']] + ma[idx['DR']]) / 20000.0 if idx['DL'] >= 0 else 0
                V = (ma[idx['VL']] + ma[idx['VR']]) / 20000.0 if idx['VL'] >= 0 else 0
                seg_DV[seg] = (D, V)
            rows.append((tick, S_rmd_d, S_rmd_v, S_smd_d, S_smd_v, S_rmddl, S_rmdvl, seg_DV, com, sm))
            if tick >= ticks_target:
                break
    n = len(rows)
    if n < 100:
        print(f'  WARNING: only {n} frames')
        return
    sec = np.array([(r[0] - rows[0][0]) * 0.002 for r in rows])
    rate_per_s = (n - 1) / sec[-1] if sec[-1] > 0 else 0
    S_rmd_d = np.array([r[1] for r in rows])
    S_rmd_v = np.array([r[2] for r in rows])
    S_smd_d = np.array([r[3] for r in rows])
    S_smd_v = np.array([r[4] for r in rows])
    S_rmddl = np.array([r[5] for r in rows])
    S_rmdvl = np.array([r[6] for r in rows])
    com = np.stack([r[8] / 1000000.0 for r in rows])
    seg_data = np.stack([r[9] / 1000000.0 for r in rows]).reshape(n, -1, 3)
    head = seg_data[:, 0, :2]
    tail = seg_data[:, -1, :2]
    fwd_dir = (head - tail) / (np.linalg.norm(head - tail, axis=1, keepdims=True) + 1e-09)
    com_vel = np.diff(com[:, :2], axis=0) / np.diff(sec).reshape(-1, 1)
    fwd_speed = np.einsum('ij,ij->i', com_vel, fwd_dir[:-1]) * 1000
    rmd_corr_pool = np.corrcoef(S_rmd_d, S_rmd_v)[0, 1] if S_rmd_d.std() > 0 else float('nan')
    rmd_corr_individual = np.corrcoef(S_rmddl, S_rmdvl)[0, 1] if S_rmddl.std() > 0 else float('nan')
    smd_corr = np.corrcoef(S_smd_d, S_smd_v)[0, 1] if S_smd_d.std() > 0 else float('nan')
    print(f'  duration={sec[-1]:.0f}s  frames={n}  rate={rate_per_s:.0f}/s', flush=True)
    print(f'  RMD pool D-V corr   = {rmd_corr_pool:+.3f}  (target: -1.0)', flush=True)
    print(f'  RMDDL vs RMDVL corr = {rmd_corr_individual:+.3f}  (single-pair check)', flush=True)
    print(f'  SMD pool D-V corr   = {smd_corr:+.3f}', flush=True)
    print(f'  RMDDL std={S_rmddl.std():.3f}  RMDVL std={S_rmdvl.std():.3f}  |RMDDL-RMDVL| std={np.std(S_rmddl - S_rmdvl):.3f}', flush=True)
    for seg in (1, 2, 3, 6, 9):
        D = np.array([r[7][seg][0] for r in rows])
        V = np.array([r[7][seg][1] for r in rows])
        c = np.corrcoef(D, V)[0, 1] if D.std() > 0 and V.std() > 0 else float('nan')
        cc = float((D * V).mean())
        print(f'  seg{seg}  D={D.mean():.2f}±{D.std():.2f}  V={V.mean():.2f}±{V.std():.2f}  D×V={cc:.3f}  D-V corr={c:+.2f}', flush=True)
    print(f'  Mean fwd: {fwd_speed.mean():+.1f} µm/s', flush=True)

async def main():
    ticks = 30000
    cfg1 = {'sim.muscles.HEAD_DIFFERENTIAL_READOUT': False, 'sim.neuromod.RIA_COMPARTMENTS_ENABLED': False, 'sim.neuromod.A_MN_OSC_ENABLED': False, 'sim.neuromod.INTRINSIC_OSC_AMP': 0.025, 'sim.neuromod.CMD_NOISE_SIGMA': 0.05}
    cfg2 = {**cfg1, 'sim.muscles.HEAD_DIFFERENTIAL_READOUT': True}
    cfg3 = {**cfg2, 'sim.neuromod.RIA_COMPARTMENTS_ENABLED': True, 'sim.neuromod.RIA_COMPARTMENT_GAIN': 0.05}
    cfg4 = {**cfg3, 'sim.neuromod.RIA_COMPARTMENT_GAIN': 0.15}
    cfg5 = {**cfg4, 'sim.neuromod.INTRINSIC_OSC_AMP': 0.1, 'sim.neuromod.A_MN_OSC_ENABLED': True}
    await collect('1. shared-phase + diff=off + RIA=off', ticks, cfg1)
    await collect('2. shared-phase + diff=on + RIA=off', ticks, cfg2)
    await collect('3. shared-phase + diff=on + RIA=0.05', ticks, cfg3)
    await collect('4. shared-phase + diff=on + RIA=0.15', ticks, cfg4)
    await collect('5. amp=0.10 + diff + RIA=0.15 + A-MN', ticks, cfg5)
if __name__ == '__main__':
    asyncio.run(main())

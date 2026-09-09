"""Focused RIA test: does cross-compartmentalization break head co-contraction?

Single 20s window per config. Measures only what's needed:
  - RMD_D vs RMD_V correlation (should drop from +1 toward -1)
  - Head muscle anti-phase (D vs V correlation per head segment)
  - Mean co-contraction (D × V) for segs 1-3
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
        rmd_d_ids = [names.index(n) for n in ('RMDDL', 'RMDDR') if n in names]
        rmd_v_ids = [names.index(n) for n in ('RMDVL', 'RMDVR') if n in names]
        smd_d_ids = [names.index(n) for n in ('SMDDL', 'SMDDR') if n in names]
        smd_v_ids = [names.index(n) for n in ('SMDVL', 'SMDVR') if n in names]
        ria_ids = [names.index(n) for n in ('RIAL', 'RIAR') if n in names]
        m_idx = {nm: i for i, nm in enumerate(muscle_names)}

        def mi(seg: int, quad: str) -> int:
            return m_idx.get(f'muscle_seg{seg}_{quad}', -1)
        head_idx = {seg: {q: mi(seg, q) for q in ('DL', 'DR', 'VL', 'VR')} for seg in (1, 2, 3)}
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
            S_rmd_d = float(np.mean([Si[i] / 10000.0 for i in rmd_d_ids]))
            S_rmd_v = float(np.mean([Si[i] / 10000.0 for i in rmd_v_ids]))
            S_smd_d = float(np.mean([Si[i] / 10000.0 for i in smd_d_ids]))
            S_smd_v = float(np.mean([Si[i] / 10000.0 for i in smd_v_ids]))
            S_ria = float(np.mean([Si[i] / 10000.0 for i in ria_ids])) if ria_ids else 0.0
            head_DV = []
            for seg in (1, 2, 3):
                idx = head_idx[seg]
                D = (ma[idx['DL']] + ma[idx['DR']]) / 20000.0 if idx['DL'] >= 0 and idx['DR'] >= 0 else 0
                V = (ma[idx['VL']] + ma[idx['VR']]) / 20000.0 if idx['VL'] >= 0 and idx['VR'] >= 0 else 0
                head_DV.append((D, V))
            rows.append((tick, S_rmd_d, S_rmd_v, S_smd_d, S_smd_v, S_ria, head_DV))
            if tick >= ticks_target:
                break
    n = len(rows)
    print(f'  captured {n} frames', flush=True)
    if n < 50:
        print(f'  WARNING: too few frames')
        return {}
    S_rmd_d_arr = np.array([r[1] for r in rows])
    S_rmd_v_arr = np.array([r[2] for r in rows])
    S_smd_d_arr = np.array([r[3] for r in rows])
    S_smd_v_arr = np.array([r[4] for r in rows])
    S_ria_arr = np.array([r[5] for r in rows])
    seg_D = {1: [], 2: [], 3: []}
    seg_V = {1: [], 2: [], 3: []}
    for r in rows:
        for i, seg in enumerate((1, 2, 3)):
            seg_D[seg].append(r[6][i][0])
            seg_V[seg].append(r[6][i][1])
    for seg in (1, 2, 3):
        seg_D[seg] = np.array(seg_D[seg])
        seg_V[seg] = np.array(seg_V[seg])
    rmd_corr = np.corrcoef(S_rmd_d_arr, S_rmd_v_arr)[0, 1] if S_rmd_d_arr.std() > 0 and S_rmd_v_arr.std() > 0 else float('nan')
    smd_corr = np.corrcoef(S_smd_d_arr, S_smd_v_arr)[0, 1] if S_smd_d_arr.std() > 0 and S_smd_v_arr.std() > 0 else float('nan')
    print(f'  RIA  S mean={S_ria_arr.mean():+.2f}  std={S_ria_arr.std():.2f}', flush=True)
    print(f'  RMD  D vs V corr = {rmd_corr:+.3f}  (target: negative)', flush=True)
    print(f'  SMD  D vs V corr = {smd_corr:+.3f}  (target: negative)', flush=True)
    print(f'  RMDD mean={S_rmd_d_arr.mean():+.2f}±{S_rmd_d_arr.std():.2f}  RMDV mean={S_rmd_v_arr.mean():+.2f}±{S_rmd_v_arr.std():.2f}', flush=True)
    print(f'  SMDD mean={S_smd_d_arr.mean():+.2f}±{S_smd_d_arr.std():.2f}  SMDV mean={S_smd_v_arr.mean():+.2f}±{S_smd_v_arr.std():.2f}', flush=True)
    for seg in (1, 2, 3):
        D = seg_D[seg] - seg_D[seg].mean()
        V = seg_V[seg] - seg_V[seg].mean()
        c = np.corrcoef(D, V)[0, 1] if D.std() > 0 and V.std() > 0 else float('nan')
        cocontract = float((seg_D[seg] * seg_V[seg]).mean())
        print(f'  seg{seg}  D mean={seg_D[seg].mean():.2f} std={seg_D[seg].std():.2f}  V mean={seg_V[seg].mean():.2f} std={seg_V[seg].std():.2f}  D×V mean={cocontract:.3f}  D-V corr={c:+.2f}', flush=True)
    return {'rmd_corr': rmd_corr}

async def main() -> None:
    ticks = 30000
    base = {'sim.neuromod.A_MN_OSC_ENABLED': False, 'sim.neuromod.RIA_COMPARTMENTS_ENABLED': False, 'sim.neuromod.CMD_NOISE_SIGMA': 0.05}
    ria_low = {**base, 'sim.neuromod.RIA_COMPARTMENTS_ENABLED': True, 'sim.neuromod.RIA_COMPARTMENT_GAIN': 0.05}
    ria_med = {**base, 'sim.neuromod.RIA_COMPARTMENTS_ENABLED': True, 'sim.neuromod.RIA_COMPARTMENT_GAIN': 0.15}
    ria_hi = {**base, 'sim.neuromod.RIA_COMPARTMENTS_ENABLED': True, 'sim.neuromod.RIA_COMPARTMENT_GAIN': 0.3}
    await collect('baseline (RIA off)', ticks, base)
    await collect('RIA gain=0.05', ticks, ria_low)
    await collect('RIA gain=0.15', ticks, ria_med)
    await collect('RIA gain=0.30', ticks, ria_hi)
if __name__ == '__main__':
    asyncio.run(main())

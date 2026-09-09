"""Integration test: A-MN intrinsic oscillator → body reversal.

Connects to the live lab server, resets, drives AVA via OU noise, and tracks:
  1. AVA mean S over time (looking for bursts above gate threshold)
  2. Body COM velocity in head-direction frame (forward = +, backward = -)
  3. Concordance: do AVA bursts coincide with body reversals?

If A-MN oscillator works at the body level, AVA bursts > 1.10 should produce
sustained backward COM velocity for the duration of the burst.
"""
from __future__ import annotations
from analysis.lib.lab_client import (
    LAB_REST as URL_REST,
    LAB_WS as URL_WS,
    post_json,
    get_json,
    unpack_bits,
)
import asyncio, json, sys, time, urllib.request
import numpy as np
import websockets

async def collect(label: str, ticks_target: int, params: dict[str, float | bool]) -> dict:
    print(f'\n=== {label} ===')
    patches = [{'path': k, 'value': v} for k, v in params.items()]
    if patches:
        post_json('/api/patch', {'patches': patches})
    post_json('/api/reset', {})
    await asyncio.sleep(0.5)
    rows = []
    last_tick = -1
    async with websockets.connect(URL_WS, max_size=2 ** 24) as ws:
        hello = json.loads(await ws.recv())
        names = hello['L']['nm']
        ava_ids = [names.index(n) for n in ('AVAL', 'AVAR') if n in names]
        avb_ids = [names.index(n) for n in ('AVBL', 'AVBR') if n in names]
        amn_ids: dict[str, int] = {}
        for nm in ('DA1', 'DA5', 'DA9', 'VA1', 'VA6', 'VA12'):
            if nm in names:
                amn_ids[nm] = names.index(nm)
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
            S_ava = np.mean([Si[i] / 10000.0 for i in ava_ids if 0 <= i < len(Si)]) if ava_ids else 0
            S_avb = np.mean([Si[i] / 10000.0 for i in avb_ids if 0 <= i < len(Si)]) if avb_ids else 0
            S_amn = {nm: Si[i] / 10000.0 if 0 <= i < len(Si) else 0.0 for nm, i in amn_ids.items()}
            sm = np.array(d.get('sm', []), dtype=np.int64)
            com = np.array(d.get('cm', [0, 0, 0]), dtype=np.int64)
            rows.append((tick, S_ava, S_avb, S_amn, com, sm))
            if tick >= ticks_target:
                break
    n = len(rows)
    if n < 100:
        print(f'  WARNING: only {n} frames captured')
        return {}
    sec = np.array([(r[0] - rows[0][0]) * 0.002 for r in rows])
    S_ava = np.array([r[1] for r in rows])
    S_avb = np.array([r[2] for r in rows])
    S_da1 = np.array([r[3].get('DA1', 0.0) for r in rows])
    S_da9 = np.array([r[3].get('DA9', 0.0) for r in rows])
    S_va1 = np.array([r[3].get('VA1', 0.0) for r in rows])
    com = np.stack([r[4] / 1000000.0 for r in rows])
    seg = np.stack([r[5] / 1000000.0 for r in rows]).reshape(n, -1, 3)
    head = seg[:, 0, :2]
    tail = seg[:, -1, :2]
    fwd_dir = (head - tail) / (np.linalg.norm(head - tail, axis=1, keepdims=True) + 1e-09)
    com_vel = np.diff(com[:, :2], axis=0) / np.diff(sec).reshape(-1, 1)
    fwd_speed = np.einsum('ij,ij->i', com_vel, fwd_dir[:-1]) * 1000
    fps = 100
    win = max(1, int(2.0 * fps))
    fwd_smooth = np.convolve(fwd_speed, np.ones(win) / win, mode='same')
    gate_active = S_ava > 1.1
    diffs = np.diff(gate_active.astype(int))
    g_starts = np.where(diffs == 1)[0]
    g_ends = np.where(diffs == -1)[0]
    if len(g_ends) and len(g_starts) and (g_ends[0] < g_starts[0]):
        g_ends = g_ends[1:]
    if len(g_starts) > len(g_ends):
        g_starts = g_starts[:len(g_ends)]
    gate_episodes = [(s, e) for s, e in zip(g_starts, g_ends) if (e - s) / fps >= 0.3]
    gate_durations = [(e - s) / fps for s, e in gate_episodes]
    is_rev = fwd_smooth < -10
    diffs_r = np.diff(is_rev.astype(int))
    r_starts = np.where(diffs_r == 1)[0]
    r_ends = np.where(diffs_r == -1)[0]
    if len(r_ends) and len(r_starts) and (r_ends[0] < r_starts[0]):
        r_ends = r_ends[1:]
    if len(r_starts) > len(r_ends):
        r_starts = r_starts[:len(r_ends)]
    rev_episodes = [(s, e) for s, e in zip(r_starts, r_ends) if (e - s) / fps >= 1.0]
    concordant = sum((1 for rs, re in rev_episodes for gs, ge in gate_episodes if max(rs, gs) < min(re, ge)))
    amn_rest_std = float(S_da1[~gate_active].std()) if (~gate_active).sum() > 100 else float('nan')
    amn_burst_std = float(S_da1[gate_active].std()) if gate_active.sum() > 100 else float('nan')
    print(f'  duration={sec[-1]:.0f}s  AVA mean S={S_ava.mean():+.3f}  AVB mean S={S_avb.mean():+.3f}')
    print(f'  AVA gate-active episodes (S>1.10, ≥0.3s): {len(gate_episodes)}  rate {len(gate_episodes) / sec[-1] * 60:.1f}/min')
    print(f'    durations: mean={(np.mean(gate_durations) if gate_durations else 0):.2f}s  max={(max(gate_durations) if gate_durations else 0):.2f}s')
    print(f'  Body reversals (≥1s): {len(rev_episodes)}  rate {len(rev_episodes) / sec[-1] * 60:.1f}/min')
    print(f'  Concordance (rev∩gate): {concordant}/{len(rev_episodes)}')
    print(f'  Mean fwd: {fwd_speed.mean():+.1f} µm/s  smoothed range: [{fwd_smooth.min():+.0f}, {fwd_smooth.max():+.0f}]')
    print(f'  DA1 std: rest={amn_rest_std:.3f}  burst={amn_burst_std:.3f}  (burst should be >> rest if oscillator engages)')
    return {'n_gate': len(gate_episodes), 'n_rev': len(rev_episodes), 'concordant': concordant, 'fwd_mean': float(fwd_speed.mean())}

async def main() -> None:
    await collect('Default config (A-MN OSC enabled)', ticks_target=60000, params={'sim.neuromod.A_MN_OSC_ENABLED': True, 'sim.neuromod.A_MN_OSC_AMP': 0.1, 'sim.neuromod.CMD_NOISE_SIGMA': 0.1, 'sim.neuromod.CMD_NOISE_TAU': 1000.0})
    await collect('Higher noise σ=0.20', ticks_target=60000, params={'sim.neuromod.A_MN_OSC_ENABLED': True, 'sim.neuromod.A_MN_OSC_AMP': 0.1, 'sim.neuromod.CMD_NOISE_SIGMA': 0.2, 'sim.neuromod.CMD_NOISE_TAU': 1000.0})
    await collect('Control: A-MN OSC disabled', ticks_target=60000, params={'sim.neuromod.A_MN_OSC_ENABLED': False, 'sim.neuromod.CMD_NOISE_SIGMA': 0.2, 'sim.neuromod.CMD_NOISE_TAU': 1000.0})
if __name__ == '__main__':
    asyncio.run(main())

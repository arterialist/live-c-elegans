"""C. elegans behavioral repertoire detection (500k+ ticks).

Detects and characterises the canonical C. elegans behavioral states from
trajectory + neural data:

  • forward run     — sustained fwd speed > 5 µm/s for ≥ 5s
  • reversal        — sustained fwd speed < -5 µm/s for ≥ 1s
  • pause           — |fwd speed| < 2 µm/s for ≥ 2s
  • omega bend      — head curvature peak > 1.5 rad sustained ≥ 0.5s
  • dwell           — |com speed| < 1 µm/s for ≥ 5s (long pause)

Run-turn-run (Pierce-Shimomura 1999):
  expect ~5-10 reversals/min, dwell mostly forward, brief omega bends after
  reversals (90% of reversals followed by omega within 5s).

Usage:
    cd celegans-live-demo && uv sync --extra analysis
    uv run python -m analysis.behavioral_repertoire [target_ticks=500000]

Streams from the live lab server. Reports per-minute statistics + summary.
"""
from __future__ import annotations
from analysis.lib.lab_client import (
    LAB_REST as URL_REST,
    LAB_WS as URL_WS,
    post_json,
)
import asyncio, json, sys
import numpy as np
import websockets

def find_episodes(arr_bool: np.ndarray, min_ticks: int) -> list[tuple[int, int]]:
    """Find contiguous True regions of length >= min_ticks. Returns (start, end) pairs."""
    arr = arr_bool.astype(int)
    diffs = np.diff(arr, prepend=0, append=0)
    starts = np.where(diffs == 1)[0]
    ends = np.where(diffs == -1)[0]
    return [(int(s), int(e)) for s, e in zip(starts, ends) if e - s >= min_ticks]

async def main(target_ticks: int=500000) -> None:
    print(f'Behavioral repertoire detection — target {target_ticks} ticks')
    post_json('/api/patch', {'patches': [{'path': 'sim.muscles.HEAD_DIFFERENTIAL_READOUT', 'value': True}, {'path': 'sim.neuromod.A_MN_OSC_ENABLED', 'value': True}, {'path': 'sim.neuromod.A_MN_OSC_AMP', 'value': 0.1}, {'path': 'sim.neuromod.A_MN_OSC_GATE_THRESHOLD', 'value': 0.7}, {'path': 'sim.neuromod.RIA_COMPARTMENTS_ENABLED', 'value': False}, {'path': 'sim.neuromod.BIO_RESTING_POTENTIALS', 'value': False}, {'path': 'sim.neuromod.INTRINSIC_OSC_AMP', 'value': 0.025}, {'path': 'sim.neuromod.CMD_NOISE_SIGMA', 'value': 0.2}, {'path': 'sim.neuromod.CMD_NOISE_TAU', 'value': 1500.0}]})
    post_json('/api/reset', {})
    await asyncio.sleep(0.5)
    rows: list[tuple] = []
    last_tick = -1
    print_every = 30000
    next_progress = print_every
    async with websockets.connect(URL_WS, max_size=2 ** 24) as ws:
        hello = json.loads(await ws.recv())
        names = hello['L']['nm']
        ava_ids = [names.index(n) for n in ('AVAL', 'AVAR') if n in names]
        avb_ids = [names.index(n) for n in ('AVBL', 'AVBR') if n in names]
        rmd_d_ids = [names.index(n) for n in ('RMDDL', 'RMDDR') if n in names]
        rmd_v_ids = [names.index(n) for n in ('RMDVL', 'RMDVR') if n in names]
        consecutive_timeouts = 0
        while True:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=10.0)
                consecutive_timeouts = 0
            except asyncio.TimeoutError:
                consecutive_timeouts += 1
                if consecutive_timeouts >= 6:
                    print('  ws stalled 60s, breaking…')
                    break
                continue
            d = json.loads(msg)
            if d.get('t') != 's':
                continue
            tick = d.get('k', 0)
            if tick == last_tick:
                continue
            last_tick = tick
            Si = d.get('Si', [])
            sm = np.array(d.get('sm', []), dtype=np.int64)
            com = np.array(d.get('cm', [0, 0, 0]), dtype=np.int64)
            S_ava = float(np.mean([Si[i] / 10000.0 for i in ava_ids])) if ava_ids else 0
            S_avb = float(np.mean([Si[i] / 10000.0 for i in avb_ids])) if avb_ids else 0
            S_rmd_d = float(np.mean([Si[i] / 10000.0 for i in rmd_d_ids])) if rmd_d_ids else 0
            S_rmd_v = float(np.mean([Si[i] / 10000.0 for i in rmd_v_ids])) if rmd_v_ids else 0
            rows.append((tick, S_ava, S_avb, S_rmd_d, S_rmd_v, com, sm))
            if tick >= next_progress:
                next_progress += print_every
                if len(rows) > 100:
                    sec = (rows[-1][0] - rows[0][0]) * 0.002
                    com_arr = np.stack([r[5] / 1000000.0 for r in rows])
                    print(f'  tick {tick}  ({sec:.0f}s)  AVA mean S={np.mean([r[1] for r in rows[-1000:]]):+.2f}  COM moved {np.linalg.norm(com_arr[-1] - com_arr[0]) * 1000:.0f} µm', flush=True)
            if tick >= target_ticks:
                break
    n = len(rows)
    if n < 1000:
        print(f'  WARNING: only {n} frames captured')
        return
    sec = np.array([(r[0] - rows[0][0]) * 0.002 for r in rows])
    duration = sec[-1]
    rate_per_s = (n - 1) / duration if duration > 0 else 0
    print(f'\nCaptured {n} frames over {duration:.0f}s (target ticks {target_ticks}, sample rate {rate_per_s:.0f}/s)')
    S_ava = np.array([r[1] for r in rows])
    S_avb = np.array([r[2] for r in rows])
    com = np.stack([r[5] / 1000000.0 for r in rows])
    seg = np.stack([r[6] / 1000000.0 for r in rows]).reshape(n, -1, 3)
    head = seg[:, 0, :2]
    tail = seg[:, -1, :2]
    body_axis = head - tail
    body_axis_norm = body_axis / (np.linalg.norm(body_axis, axis=1, keepdims=True) + 1e-09)
    com_vel = np.diff(com[:, :2], axis=0) / np.diff(sec).reshape(-1, 1)
    fwd_speed = np.einsum('ij,ij->i', com_vel, body_axis_norm[:-1]) * 1000
    com_speed = np.linalg.norm(com_vel, axis=1) * 1000
    win = max(1, int(2.0 * rate_per_s))
    fs_smooth = np.convolve(fwd_speed, np.ones(win) / win, mode='same')
    cs_smooth = np.convolve(com_speed, np.ones(win) / win, mode='same')
    head_vec = seg[:, 0, :2] - seg[:, 2, :2]
    head_vec_n = head_vec / (np.linalg.norm(head_vec, axis=1, keepdims=True) + 1e-09)
    body_vec_n = seg[:, 5, :2] - seg[:, -1, :2]
    body_vec_n = body_vec_n / (np.linalg.norm(body_vec_n, axis=1, keepdims=True) + 1e-09)
    head_curvature = np.arccos(np.clip(np.einsum('ij,ij->i', head_vec_n, body_vec_n), -1, 1))
    min_run = max(1, int(5.0 * rate_per_s))
    min_rev = max(1, int(1.0 * rate_per_s))
    min_pause = max(1, int(2.0 * rate_per_s))
    min_omega = max(1, int(0.5 * rate_per_s))
    min_dwell = max(1, int(5.0 * rate_per_s))
    runs = find_episodes(fs_smooth > 5, min_run)
    reversals = find_episodes(fs_smooth < -5, min_rev)
    pauses = find_episodes(np.abs(fs_smooth) < 2, min_pause)
    omegas = find_episodes(head_curvature[:-1] > 1.5, min_omega)
    dwells = find_episodes(cs_smooth < 1, min_dwell)
    ava_bursts = find_episodes(S_ava > 1.1, max(1, int(0.3 * rate_per_s)))
    rev_with_omega = 0
    for rs, re in reversals:
        for os, oe in omegas:
            if 0 <= os - re <= int(5.0 * rate_per_s):
                rev_with_omega += 1
                break
    print(f'\n=== Behavioral Repertoire ===')
    print(f'  Forward runs (≥5s):       {len(runs):4d}  ({len(runs) / duration * 60:5.1f}/min)')
    print(f'  Reversals (≥1s):          {len(reversals):4d}  ({len(reversals) / duration * 60:5.1f}/min)')
    print(f'  Pauses (≥2s):             {len(pauses):4d}  ({len(pauses) / duration * 60:5.1f}/min)')
    print(f'  Omega bends (≥0.5s):      {len(omegas):4d}  ({len(omegas) / duration * 60:5.1f}/min)')
    print(f'  Long dwells (≥5s):        {len(dwells):4d}  ({len(dwells) / duration * 60:5.1f}/min)')
    print(f'  AVA bursts (S>1.1, ≥0.3s):{len(ava_bursts):4d}  ({len(ava_bursts) / duration * 60:5.1f}/min)')
    print(f'  Reversals followed by omega within 5s: {rev_with_omega}/{len(reversals)} ({100 * rev_with_omega / max(1, len(reversals)):.0f}%)')
    print(f'\n=== Locomotion Stats ===')
    print(f'  Mean fwd speed: {fwd_speed.mean():+.1f} µm/s  median {np.median(fwd_speed):+.1f}')
    print(f'  Smoothed range: [{fs_smooth.min():+.0f}, {fs_smooth.max():+.0f}] µm/s')
    print(f'  Time forward: {(fs_smooth > 1).sum() / n * 100:.0f}%   backward: {(fs_smooth < -1).sum() / n * 100:.0f}%   stationary: {(np.abs(fs_smooth) <= 1).sum() / n * 100:.0f}%')
    print(f'\n=== Biological Targets ===')
    print(f'  Reversals expected: 5-10/min   actual: {len(reversals) / duration * 60:.1f}/min  {('PASS' if 5 <= len(reversals) / duration * 60 <= 10 else 'FAIL')}')
    print(f'  Forward dwell expected: ~85%   actual: {(fs_smooth > 1).sum() / n * 100:.0f}%')
    print(f'  Reversal-omega coupling expected: 80-95%   actual: {100 * rev_with_omega / max(1, len(reversals)):.0f}%')
if __name__ == '__main__':
    target = int(sys.argv[1]) if len(sys.argv) > 1 else 500000
    asyncio.run(main(target))

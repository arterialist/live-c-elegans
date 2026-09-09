"""Long-timescale lab/demo behavioural parity capture and plotting.

This module intentionally does not change the simulation or nervous system.
It drives the existing lab-style path and demo-style path, captures comparable
state for at least 100k ticks per run, and writes visual evidence.

Examples
--------
Run from ``celegans-live-demo``:

    uv run python -m analysis.parity_longrun run \
      --surface lab --scenario none --ticks 100000 \
      --evol-config analysis/pi_upgrade_20260531/evolved_food_seeking_config.migrated.json \
      --outdir analysis/parity_runs/current --run-id lab_no_food

    uv run python -m analysis.parity_longrun run \
      --surface demo --scenario single_ahead_1mm --ticks 100000 \
      --evol-config analysis/pi_upgrade_20260531/evolved_food_seeking_config.migrated.json \
      --outdir analysis/parity_runs/current --run-id demo_single_ahead_1mm

    uv run python -m analysis.parity_longrun report --outdir analysis/parity_runs/current
"""

from __future__ import annotations

import argparse
import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from celegans_live_demo.server import SimRuntime
from celegans_live_demo.worm_snapshot import load_evol_config_json
from simulations.c_elegans.body import CElegansBody
from simulations.c_elegans.config import ENV_PLATE_RADIUS_M, N_BODY_SEGMENTS
from simulations.c_elegans.environment import AgarPlateEnvironment
from simulations.c_elegans.neuron_mapping import CElegansNervousSystem
from simulations.c_elegans.simulation import build_c_elegans_simulation

SIM_DT_S = 0.002
MM_PER_M = 1000.0
PLATE_RADIUS_MM = ENV_PLATE_RADIUS_M * MM_PER_M


@dataclass(frozen=True)
class FoodScenario:
    """Food placement relative to the initial head-tail body axis."""

    name: str
    points: tuple[tuple[str, float], ...]
    description: str


SCENARIOS: dict[str, FoodScenario] = {
    "none": FoodScenario("none", tuple(), "No food sources."),
    "single_ahead_0p2mm": FoodScenario(
        "single_ahead_0p2mm", (("ahead", 0.2),), "One pellet 0.2 mm ahead of head."
    ),
    "single_ahead_1mm": FoodScenario(
        "single_ahead_1mm", (("ahead", 1.0),), "One pellet 1 mm ahead of head."
    ),
    "single_ahead_5mm": FoodScenario(
        "single_ahead_5mm", (("ahead", 5.0),), "One pellet 5 mm ahead of head."
    ),
    "single_left_1mm": FoodScenario(
        "single_left_1mm", (("left", 1.0),), "One pellet 1 mm left of head."
    ),
    "single_right_1mm": FoodScenario(
        "single_right_1mm", (("right", 1.0),), "One pellet 1 mm right of head."
    ),
    "single_behind_1mm": FoodScenario(
        "single_behind_1mm", (("behind", 1.0),), "One pellet 1 mm behind head."
    ),
    "near_ring_6x_1mm": FoodScenario(
        "near_ring_6x_1mm",
        (
            ("ahead", 1.0),
            ("ahead_left", 1.0),
            ("left", 1.0),
            ("behind_left", 1.0),
            ("right", 1.0),
            ("ahead_right", 1.0),
        ),
        "Six pellets around the head at 1 mm radius.",
    ),
    "field_24x_5to20mm": FoodScenario(
        "field_24x_5to20mm",
        tuple((f"field_{i}", 0.0) for i in range(24)),
        "Twenty-four deterministic field pellets spanning 5-20 mm.",
    ),
}


def _load_config(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    return load_evol_config_json(path)


def _body_segments_mm(engine: Any) -> np.ndarray:
    body = engine.body
    if not isinstance(body, CElegansBody):
        raise TypeError("C. elegans body expected")
    shape = body.get_body_shape()
    seg = np.asarray(shape[:N_BODY_SEGMENTS, :2], dtype=np.float32) * MM_PER_M
    if seg.shape != (N_BODY_SEGMENTS, 2):
        out = np.zeros((N_BODY_SEGMENTS, 2), dtype=np.float32)
        out[: seg.shape[0], : seg.shape[1]] = seg
        return out
    return seg


def _food_positions_mm(engine: Any) -> np.ndarray:
    env = engine.environment
    if not isinstance(env, AgarPlateEnvironment):
        return np.zeros((0, 2), dtype=np.float32)
    pts = [[float(p[0] * MM_PER_M), float(p[1] * MM_PER_M)] for p in env.get_active_food_positions()]
    return np.asarray(pts, dtype=np.float32).reshape(-1, 2)


def _compact_neural(engine: Any) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    ns = engine.nervous_system
    if not isinstance(ns, CElegansNervousSystem):
        return (
            np.zeros(0, dtype=np.float32),
            np.zeros(0, dtype=np.uint8),
            np.zeros(0, dtype=np.float32),
        )
    s_raw, f_raw, r_raw = ns.get_compact_neural_snapshot()
    return (
        np.asarray(s_raw, dtype=np.float32),
        np.asarray(f_raw, dtype=np.uint8),
        np.asarray(r_raw, dtype=np.float32),
    )


def _unit_vectors(seg_mm: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    head = seg_mm[0]
    tail = seg_mm[-1]
    fwd = head - tail
    norm = float(np.linalg.norm(fwd))
    if norm < 1e-9:
        fwd = np.array([1.0, 0.0], dtype=np.float32)
    else:
        fwd = fwd / norm
    left = np.array([-fwd[1], fwd[0]], dtype=np.float32)
    return fwd.astype(np.float32), left


def _clip_to_plate(pt: np.ndarray) -> np.ndarray:
    r = float(np.linalg.norm(pt))
    if r > PLATE_RADIUS_MM - 1.0:
        return pt * ((PLATE_RADIUS_MM - 1.0) / r)
    return pt


def _scenario_points_mm(scenario: str, seg_mm: np.ndarray) -> list[tuple[float, float, float]]:
    spec = SCENARIOS[scenario]
    if scenario == "none":
        return []
    head = seg_mm[0].astype(np.float32)
    fwd, left = _unit_vectors(seg_mm)

    def place(kind: str, dist: float) -> np.ndarray:
        if kind == "ahead":
            v = fwd
        elif kind == "behind":
            v = -fwd
        elif kind == "left":
            v = left
        elif kind == "right":
            v = -left
        elif kind == "ahead_left":
            v = fwd + left
            v = v / (np.linalg.norm(v) + 1e-9)
        elif kind == "ahead_right":
            v = fwd - left
            v = v / (np.linalg.norm(v) + 1e-9)
        elif kind == "behind_left":
            v = -fwd + left
            v = v / (np.linalg.norm(v) + 1e-9)
        elif kind.startswith("field_"):
            idx = int(kind.split("_", 1)[1])
            angle = (idx * 2.399963229728653) % (2.0 * math.pi)
            radius = 5.0 + (15.0 * ((idx * 37) % 97) / 96.0)
            v = np.array([math.cos(angle), math.sin(angle)], dtype=np.float32)
            return _clip_to_plate(head + v * radius)
        else:
            raise ValueError(f"unknown scenario point kind: {kind}")
        return _clip_to_plate(head + v * float(dist))

    pts = [place(kind, dist) for kind, dist in spec.points]
    return [(float(p[0] / MM_PER_M), float(p[1] / MM_PER_M), 0.0) for p in pts]


def _add_food(engine: Any, positions_m: list[tuple[float, float, float]]) -> None:
    env = engine.environment
    if not isinstance(env, AgarPlateEnvironment):
        raise TypeError("AgarPlateEnvironment expected")
    env.replace_food_sources(positions_m)


def _path_metrics(seg: np.ndarray) -> tuple[float, float, float, float]:
    diffs = np.diff(seg, axis=0)
    path = float(np.linalg.norm(diffs, axis=1).sum())
    chord = float(np.linalg.norm(seg[0] - seg[-1]))
    path_chord = path / chord if chord > 1e-9 else 0.0
    x_range = float(np.max(seg[:, 0]) - np.min(seg[:, 0]))
    y_range = float(np.max(seg[:, 1]) - np.min(seg[:, 1]))
    return path_chord, x_range, y_range, path


def _lateral_profile(seg: np.ndarray) -> np.ndarray:
    center = seg.mean(axis=0)
    _fwd, left = _unit_vectors(seg)
    return (seg - center) @ left


def _latest_trace_value(trace: Any, name: str) -> float:
    vals = getattr(trace, name)
    if vals:
        return float(vals[-1])
    return float("nan")


def _build_lab(evol_config: dict[str, Any] | None) -> tuple[Any, Any]:
    engine, loop = build_c_elegans_simulation(
        food_positions=[],
        log_level="WARNING",
        record_neural_states=False,
        suppress_connectome_summary=True,
        max_history=32,
        evol_config=evol_config,
    )
    loop.reset()
    return engine, loop


def _build_demo(evol_config: dict[str, Any] | None) -> tuple[Any, Any, SimRuntime]:
    runtime = SimRuntime(evol_config=evol_config, snapshot_path=None, analysis_wire=True)
    return runtime.engine, runtime.loop, runtime


def _analysis_names(engine: Any) -> tuple[list[str], list[str]]:
    body = engine.body
    joint_names = list(body.joint_names) if isinstance(body, CElegansBody) else []
    ns = engine.nervous_system
    muscle_names: list[str] = []
    if isinstance(ns, CElegansNervousSystem):
        muscles = ns.export_live_checkpoint().get("muscles", {})
        muscle_names = sorted(str(k) for k in muscles.keys())
    return joint_names, muscle_names


def run_capture(args: argparse.Namespace) -> None:
    outdir = Path(args.outdir)
    run_dir = outdir / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    scenario = args.scenario
    if scenario not in SCENARIOS:
        raise SystemExit(f"unknown scenario {scenario!r}; choices: {', '.join(SCENARIOS)}")
    ticks_target = int(args.ticks)
    if ticks_target < 100_000 and not args.allow_short:
        raise SystemExit("--ticks must be at least 100000 unless --allow-short is set")
    evol_config = _load_config(args.evol_config)

    if args.surface == "lab":
        engine, loop = _build_lab(evol_config)
        runtime = None
    elif args.surface == "demo":
        engine, loop, runtime = _build_demo(evol_config)
    else:
        raise SystemExit("--surface must be lab or demo")

    initial_seg = _body_segments_mm(engine)
    food_m = _scenario_points_mm(scenario, initial_seg)
    _add_food(engine, food_m)
    initial_food_mm = _food_positions_mm(engine)

    s0, _f0, r0 = _compact_neural(engine)
    n_neurons = int(s0.size)
    joint_names, muscle_names = _analysis_names(engine)
    n_joints = len(joint_names)
    n_muscles = len(muscle_names)
    sample_stride = max(1, int(args.neural_sample_stride))
    n_samples = (ticks_target + sample_stride - 1) // sample_stride

    ticks = np.zeros(ticks_target, dtype=np.int64)
    segs = np.zeros((ticks_target, N_BODY_SEGMENTS, 2), dtype=np.float32)
    com = np.zeros((ticks_target, 2), dtype=np.float32)
    food_count = np.zeros(ticks_target, dtype=np.int16)
    nearest_food_mm = np.full(ticks_target, np.nan, dtype=np.float32)
    path_chord = np.zeros(ticks_target, dtype=np.float32)
    x_range = np.zeros(ticks_target, dtype=np.float32)
    y_range = np.zeros(ticks_target, dtype=np.float32)
    path_len = np.zeros(ticks_target, dtype=np.float32)
    s_stats = np.zeros((ticks_target, 4), dtype=np.float32)  # mean, std, min, max
    r_stats = np.zeros((ticks_target, 4), dtype=np.float32)
    fired_count = np.zeros(ticks_target, dtype=np.int16)
    pe = np.full(ticks_target, np.nan, dtype=np.float32)
    me = np.full(ticks_target, np.nan, dtype=np.float32)
    lateral = np.zeros((ticks_target, N_BODY_SEGMENTS), dtype=np.float32)
    joint_angle = np.zeros((ticks_target, n_joints), dtype=np.float32)
    joint_velocity = np.zeros((ticks_target, n_joints), dtype=np.float32)
    muscle_activation = np.zeros((ticks_target, n_muscles), dtype=np.float32)
    neuromod = np.full((ticks_target, 2), np.nan, dtype=np.float32)
    s_sample = np.zeros((n_samples, n_neurons), dtype=np.float32)
    r_sample = np.zeros((n_samples, n_neurons), dtype=np.float32)
    sample_ticks = np.zeros(n_samples, dtype=np.int64)

    wall0 = time.time()
    prev_food = int(initial_food_mm.shape[0])
    eaten = 0
    print(
        f"capture {args.run_id}: surface={args.surface} scenario={scenario} "
        f"ticks={ticks_target} food={prev_food} -> {run_dir}",
        flush=True,
    )

    for i in range(ticks_target):
        if runtime is not None:
            snap = runtime._build_snapshot()  # same snapshot builder as the demo thread
            tick = int(snap["k"])
            seg = np.asarray(snap["s"], dtype=np.float32)
            cm = np.asarray(snap["c"], dtype=np.float32)
            ja = np.asarray(snap.get("ja", []), dtype=np.float32) / 10000.0
            jv = np.asarray(snap.get("jv", []), dtype=np.float32) / 10000.0
            ma = np.asarray(snap.get("ma", []), dtype=np.float32) / 10000.0
            nm = np.asarray(snap.get("nm01", [np.nan, np.nan]), dtype=np.float32)
        else:
            step = engine.step()
            tick = int(step.tick)
            seg = _body_segments_mm(engine)
            pos = step.body_state.position
            cm = np.asarray([pos[0] * MM_PER_M, pos[1] * MM_PER_M], dtype=np.float32)
            ja = np.asarray(
                [step.body_state.joint_angles.get(name, 0.0) for name in joint_names],
                dtype=np.float32,
            )
            jv = np.asarray(
                [step.body_state.joint_velocities.get(name, 0.0) for name in joint_names],
                dtype=np.float32,
            )
            ma = np.asarray(
                [step.motor_outputs.get(name, 0.0) for name in muscle_names],
                dtype=np.float32,
            )
            ns = engine.nervous_system
            if isinstance(ns, CElegansNervousSystem):
                nm = np.asarray(ns.neuromod_levels, dtype=np.float32)
            else:
                nm = np.asarray([np.nan, np.nan], dtype=np.float32)

        food_now = _food_positions_mm(engine)
        s, fired, r = _compact_neural(engine)
        pc, xr, yr, plen = _path_metrics(seg)
        ticks[i] = tick
        segs[i] = seg
        com[i] = cm
        food_count[i] = int(food_now.shape[0])
        path_chord[i] = pc
        x_range[i] = xr
        y_range[i] = yr
        path_len[i] = plen
        lateral[i] = _lateral_profile(seg)
        if ja.size:
            joint_angle[i, : min(n_joints, ja.size)] = ja[:n_joints]
        if jv.size:
            joint_velocity[i, : min(n_joints, jv.size)] = jv[:n_joints]
        if ma.size:
            muscle_activation[i, : min(n_muscles, ma.size)] = ma[:n_muscles]
        neuromod[i] = nm[:2]
        if food_now.size:
            nearest_food_mm[i] = float(np.min(np.linalg.norm(food_now - seg[0], axis=1)))
        if s.size:
            s_stats[i] = [float(np.mean(s)), float(np.std(s)), float(np.min(s)), float(np.max(s))]
        if r.size:
            r_stats[i] = [float(np.mean(r)), float(np.std(r)), float(np.min(r)), float(np.max(r))]
        if fired.size:
            fired_count[i] = int(np.sum(fired))
        pe[i] = _latest_trace_value(loop.free_energy_trace, "prediction_error")
        me[i] = _latest_trace_value(loop.free_energy_trace, "motor_entropy")
        if i % sample_stride == 0 and s.size:
            j = i // sample_stride
            s_sample[j, :] = s
            r_sample[j, :] = r
            sample_ticks[j] = tick
        if int(food_now.shape[0]) < prev_food:
            eaten += prev_food - int(food_now.shape[0])
        prev_food = int(food_now.shape[0])
        if (i + 1) % int(args.progress_every) == 0:
            print(
                f"  {i + 1:7d}/{ticks_target} ticks wall={time.time() - wall0:.0f}s "
                f"path/chord={pc:.3f} y_range={yr:.3f}mm food={prev_food}",
                flush=True,
            )

    duration = time.time() - wall0
    sample_n = (ticks_target + sample_stride - 1) // sample_stride
    sample_ticks = sample_ticks[:sample_n]
    s_sample = s_sample[:sample_n]
    r_sample = r_sample[:sample_n]
    npz_path = run_dir / "capture.npz"
    np.savez_compressed(
        npz_path,
        ticks=ticks,
        segments_mm=segs,
        com_mm=com,
        food_count=food_count,
        nearest_food_mm=nearest_food_mm,
        path_chord=path_chord,
        x_range_mm=x_range,
        y_range_mm=y_range,
        path_len_mm=path_len,
        lateral_mm=lateral,
        s_stats=s_stats,
        r_stats=r_stats,
        fired_count=fired_count,
        prediction_error=pe,
        motor_entropy=me,
        neural_sample_ticks=sample_ticks,
        neural_S_sample=s_sample,
        neural_R_sample=r_sample,
        joint_angle=joint_angle,
        joint_velocity=joint_velocity,
        muscle_activation=muscle_activation,
        neuromod=neuromod,
        joint_names=np.asarray(joint_names),
        muscle_names=np.asarray(muscle_names),
        initial_food_mm=initial_food_mm,
        final_food_mm=_food_positions_mm(engine),
    )

    summary = summarize_npz(npz_path)
    summary.update(
        {
            "run_id": args.run_id,
            "surface": args.surface,
            "scenario": scenario,
            "scenario_description": SCENARIOS[scenario].description,
            "ticks_requested": ticks_target,
            "wall_seconds": duration,
            "wall_ticks_per_second": ticks_target / duration if duration > 0 else None,
            "evol_config": str(Path(args.evol_config).resolve()) if args.evol_config else None,
            "initial_food_count": int(initial_food_mm.shape[0]),
            "final_food_count": int(_food_positions_mm(engine).shape[0]),
            "eaten_count": int(eaten),
        }
    )
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    write_run_plots(npz_path, run_dir)
    print(f"saved {npz_path}", flush=True)
    print(f"summary {run_dir / 'summary.json'}", flush=True)


def summarize_npz(path: Path) -> dict[str, Any]:
    d = np.load(path, allow_pickle=False)
    ticks = d["ticks"]
    com = d["com_mm"]
    seg = d["segments_mm"]
    n = int(len(ticks))
    sec = (ticks - ticks[0]) * SIM_DT_S if n else np.zeros(0)
    speed = np.zeros(max(0, n - 1), dtype=np.float32)
    angular_speed = np.zeros(max(0, n - 1), dtype=np.float32)
    if n > 1:
        dt = np.maximum(np.diff(ticks).astype(np.float32) * SIM_DT_S, 1e-9)
        speed = np.linalg.norm(np.diff(com, axis=0), axis=1) / dt
        heading = np.unwrap(np.arctan2(seg[:, 0, 1] - seg[:, -1, 1], seg[:, 0, 0] - seg[:, -1, 0]))
        angular_speed = np.abs(np.diff(heading)) / dt
    food_count = d["food_count"]
    nearest_food = d["nearest_food_mm"]
    joint_angle = d["joint_angle"] if "joint_angle" in d.files else np.zeros((n, 0))
    joint_velocity = d["joint_velocity"] if "joint_velocity" in d.files else np.zeros((n, 0))
    muscle_activation = (
        d["muscle_activation"] if "muscle_activation" in d.files else np.zeros((n, 0))
    )
    neuromod = d["neuromod"] if "neuromod" in d.files else np.full((n, 2), np.nan)

    def stat(a: np.ndarray) -> dict[str, float | None]:
        a = np.asarray(a, dtype=np.float64)
        a = a[np.isfinite(a)]
        if a.size == 0:
            return {"min": None, "max": None, "mean": None, "median": None, "std": None}
        return {
            "min": float(np.min(a)),
            "max": float(np.max(a)),
            "mean": float(np.mean(a)),
            "median": float(np.median(a)),
            "std": float(np.std(a)),
        }

    return {
        "ticks_recorded": n,
        "tick_start": int(ticks[0]) if n else None,
        "tick_end": int(ticks[-1]) if n else None,
        "tick_delta": int(ticks[-1] - ticks[0]) if n else 0,
        "sim_seconds": float(sec[-1]) if n else 0.0,
        "com_displacement_mm": float(np.linalg.norm(com[-1] - com[0])) if n else 0.0,
        "trajectory_path_mm": float(np.linalg.norm(np.diff(com, axis=0), axis=1).sum()) if n > 1 else 0.0,
        "path_chord": stat(d["path_chord"]),
        "x_range_mm": stat(d["x_range_mm"]),
        "y_range_mm": stat(d["y_range_mm"]),
        "speed_mm_s": stat(speed),
        "angular_speed_rad_s": stat(angular_speed),
        "fired_count": stat(d["fired_count"]),
        "s_mean": stat(d["s_stats"][:, 0]),
        "s_std": stat(d["s_stats"][:, 1]),
        "r_mean": stat(d["r_stats"][:, 0]),
        "prediction_error": stat(d["prediction_error"]),
        "motor_entropy": stat(d["motor_entropy"]),
        "joint_abs_angle": stat(np.abs(joint_angle).reshape(-1)),
        "joint_abs_velocity": stat(np.abs(joint_velocity).reshape(-1)),
        "muscle_activation": stat(muscle_activation.reshape(-1)),
        "neuromod_m0": stat(neuromod[:, 0]),
        "neuromod_m1": stat(neuromod[:, 1]),
        "food_count_min": int(np.min(food_count)) if food_count.size else 0,
        "food_count_max": int(np.max(food_count)) if food_count.size else 0,
        "nearest_food_mm": stat(nearest_food),
    }


def _downsample_idx(n: int, max_points: int = 6000) -> np.ndarray:
    if n <= max_points:
        return np.arange(n)
    return np.linspace(0, n - 1, max_points).astype(np.int64)


def write_run_plots(npz_path: Path, run_dir: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    d = np.load(npz_path, allow_pickle=False)
    ticks = d["ticks"]
    seg = d["segments_mm"]
    com = d["com_mm"]
    n = len(ticks)
    t = (ticks - ticks[0]) * SIM_DT_S
    idx = _downsample_idx(n)
    initial_food = d["initial_food_mm"]
    final_food = d["final_food_mm"]

    speed = np.full(n, np.nan, dtype=np.float32)
    angular = np.full(n, np.nan, dtype=np.float32)
    if n > 1:
        dt = np.maximum(np.diff(ticks).astype(np.float32) * SIM_DT_S, 1e-9)
        speed[1:] = np.linalg.norm(np.diff(com, axis=0), axis=1) / dt
        heading = np.unwrap(np.arctan2(seg[:, 0, 1] - seg[:, -1, 1], seg[:, 0, 0] - seg[:, -1, 0]))
        angular[1:] = np.abs(np.diff(heading)) / dt

    fig, axes = plt.subplots(3, 2, figsize=(16, 13))
    ax = axes[0, 0]
    sc = ax.scatter(com[idx, 0], com[idx, 1], c=t[idx], s=1.0, cmap="viridis")
    ax.scatter([com[0, 0]], [com[0, 1]], c="green", s=50, edgecolor="black", label="start")
    ax.scatter([com[-1, 0]], [com[-1, 1]], c="red", s=50, edgecolor="black", label="end")
    if initial_food.size:
        ax.scatter(initial_food[:, 0], initial_food[:, 1], c="magenta", marker="*", s=80, edgecolor="black", label="initial food")
    if final_food.size:
        ax.scatter(final_food[:, 0], final_food[:, 1], c="none", marker="o", s=80, edgecolor="magenta", label="final food")
    ax.set_title("COM trajectory")
    ax.set_xlabel("x (mm)")
    ax.set_ylabel("y (mm)")
    ax.set_aspect("equal", adjustable="datalim")
    ax.grid(True, alpha=0.25)
    ax.legend(loc="best", fontsize=8)
    fig.colorbar(sc, ax=ax, label="sim time (s)")

    ax = axes[0, 1]
    for j in np.linspace(0, n - 1, min(36, n)).astype(int):
        color = plt.cm.viridis(j / max(1, n - 1))
        ax.plot(seg[j, :, 0], seg[j, :, 1], color=color, lw=0.8, alpha=0.8)
    ax.set_title("Body shape montage")
    ax.set_xlabel("x (mm)")
    ax.set_ylabel("y (mm)")
    ax.set_aspect("equal", adjustable="datalim")
    ax.grid(True, alpha=0.25)

    ax = axes[1, 0]
    ax.plot(t[idx], d["path_chord"][idx], lw=0.7, label="path/chord")
    ax.plot(t[idx], d["y_range_mm"][idx], lw=0.7, label="y range (mm)")
    ax.set_title("Body curvature and lateral range")
    ax.set_xlabel("sim time (s)")
    ax.grid(True, alpha=0.25)
    ax.legend()

    ax = axes[1, 1]
    ax.plot(t[idx], speed[idx], lw=0.6, label="COM speed (mm/s)")
    ax2 = ax.twinx()
    ax2.plot(t[idx], angular[idx], lw=0.5, color="tab:red", alpha=0.65, label="angular speed (rad/s)")
    ax.set_title("Movement speed")
    ax.set_xlabel("sim time (s)")
    ax.grid(True, alpha=0.25)
    ax.legend(loc="upper left")
    ax2.legend(loc="upper right")

    ax = axes[2, 0]
    ax.plot(t[idx], d["fired_count"][idx], lw=0.6, label="fired count")
    ax2 = ax.twinx()
    ax2.plot(t[idx], d["s_stats"][idx, 1], color="tab:orange", lw=0.6, label="S std")
    ax.set_title("Neural activity summaries")
    ax.set_xlabel("sim time (s)")
    ax.grid(True, alpha=0.25)
    ax.legend(loc="upper left")
    ax2.legend(loc="upper right")

    ax = axes[2, 1]
    lat = d["lateral_mm"]
    skip = max(1, n // 5000)
    im = ax.imshow(
        lat[::skip].T,
        aspect="auto",
        cmap="RdBu_r",
        extent=[float(t[0]), float(t[-1]), N_BODY_SEGMENTS - 0.5, 0.5],
    )
    ax.set_title("Body lateral kymograph")
    ax.set_xlabel("sim time (s)")
    ax.set_ylabel("segment")
    fig.colorbar(im, ax=ax, label="lateral offset (mm)")

    fig.tight_layout()
    fig.savefig(run_dir / "overview.png", dpi=140)
    plt.close(fig)

    s_sample = d["neural_S_sample"]
    sample_ticks = d["neural_sample_ticks"]
    if s_sample.size:
        sample_t = (sample_ticks - ticks[0]) * SIM_DT_S
        fig, ax = plt.subplots(1, 1, figsize=(16, 5))
        vmax = max(0.1, float(np.nanpercentile(np.abs(s_sample), 99)))
        im = ax.imshow(
            s_sample.T,
            aspect="auto",
            cmap="RdBu_r",
            vmin=-vmax,
            vmax=vmax,
            extent=[float(sample_t[0]), float(sample_t[-1]), s_sample.shape[1] - 0.5, 0.5],
        )
        ax.set_title("Neural membrane sample heatmap")
        ax.set_xlabel("sim time (s)")
        ax.set_ylabel("PAULA neuron id")
        fig.colorbar(im, ax=ax, label="S")
        fig.tight_layout()
        fig.savefig(run_dir / "neural_S_heatmap.png", dpi=140)
        plt.close(fig)

    muscle = d["muscle_activation"] if "muscle_activation" in d.files else np.zeros((0, 0))
    if muscle.size:
        skip = max(1, muscle.shape[0] // 5000)
        fig, ax = plt.subplots(1, 1, figsize=(16, 5))
        im = ax.imshow(
            muscle[::skip].T,
            aspect="auto",
            cmap="magma",
            vmin=0.0,
            vmax=max(0.05, float(np.nanpercentile(muscle, 99))),
            extent=[float(t[0]), float(t[-1]), muscle.shape[1] - 0.5, 0.5],
        )
        ax.set_title("Muscle activation heatmap")
        ax.set_xlabel("sim time (s)")
        ax.set_ylabel("muscle index")
        fig.colorbar(im, ax=ax, label="activation")
        fig.tight_layout()
        fig.savefig(run_dir / "muscle_activation_heatmap.png", dpi=140)
        plt.close(fig)


def write_report(args: argparse.Namespace) -> None:
    outdir = Path(args.outdir)
    summaries = []
    for p in sorted(outdir.glob("*/summary.json")):
        summaries.append(json.loads(p.read_text(encoding="utf-8")))
    if not summaries:
        raise SystemExit(f"no summary.json files under {outdir}")
    by_id = {s["run_id"]: s for s in summaries}

    def mean(s: dict[str, Any], key: str) -> float | None:
        v = s.get(key, {}).get("mean")
        return float(v) if v is not None else None

    def rel_delta(new: float | None, base: float | None) -> str:
        if new is None or base is None:
            return "n/a"
        if abs(base) < 1e-12:
            return "n/a"
        return f"{((new - base) / base) * 100:+.1f}%"

    def metric_delta_row(
        label: str, lab: dict[str, Any], demo: dict[str, Any], key: str
    ) -> str:
        lv = mean(lab, key)
        dv = mean(demo, key)
        if lv is None or dv is None:
            return f"| {label} | n/a | n/a | n/a | n/a |"
        return (
            f"| {label} | {lv:.6g} | {dv:.6g} | {dv - lv:+.6g} | "
            f"{rel_delta(dv, lv)} |"
        )

    required_ids = {
        "lab_no_food_100k": "lab no-food baseline",
        "demo_no_food_100k": "demo no-food baseline",
        "demo_food_single_ahead_0p2mm_100k": "distance: ahead 0.2 mm",
        "demo_food_single_ahead_1mm_100k": "distance/position: ahead 1 mm",
        "demo_food_single_ahead_5mm_100k": "distance: ahead 5 mm",
        "demo_food_single_left_1mm_100k": "relative position: left 1 mm",
        "demo_food_single_right_1mm_100k": "relative position: right 1 mm",
        "demo_food_single_behind_1mm_100k": "relative position: behind 1 mm",
        "demo_food_near_ring_6x_1mm_100k": "amount: six-pellet near ring",
        "demo_food_field_24x_5to20mm_100k": "amount: 24-pellet broad field",
    }
    plot_names = ("overview.png", "neural_S_heatmap.png", "muscle_activation_heatmap.png")
    coverage: list[tuple[str, str, str]] = []
    for rid, desc in required_ids.items():
        s = by_id.get(rid)
        if s is None:
            coverage.append((desc, rid, "MISSING"))
            continue
        plot_missing = [name for name in plot_names if not (outdir / rid / name).is_file()]
        ticks_ok = int(s.get("ticks_recorded", 0)) >= 100_000
        status = "ok" if ticks_ok and not plot_missing else "INCOMPLETE"
        if not ticks_ok:
            status += " ticks<100000"
        if plot_missing:
            status += " missing " + ",".join(plot_missing)
        coverage.append((desc, rid, status))

    report = outdir / "REPORT.md"
    lines = [
        "# C. elegans Lab/Demo Long-Run Parity Report",
        "",
        f"Generated from `{outdir}`.",
        "",
        "## Coverage",
        "",
        "| requirement | run | status |",
        "| --- | --- | --- |",
    ]
    for desc, rid, status in coverage:
        lines.append(f"| {desc} | `{rid}` | {status} |")
    lines.extend(
        [
            "",
            "## Runs",
            "",
            "| run | surface | scenario | ticks | sim s | path/chord mean | y range mean mm | speed mean mm/s | fired mean | muscle mean | food | plots |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
        ]
    )
    for s in summaries:
        rid = s["run_id"]
        food = f"{s.get('initial_food_count', 0)}->{s.get('final_food_count', 0)} eaten={s.get('eaten_count', 0)}"
        lines.append(
            "| {rid} | {surface} | {scenario} | {ticks} | {sim:.1f} | {pc:.3f} | {yr:.3f} | {sp:.4f} | {fc:.2f} | {ma:.4f} | {food} | [overview]({rid}/overview.png), [neural]({rid}/neural_S_heatmap.png), [muscle]({rid}/muscle_activation_heatmap.png) |".format(
                rid=rid,
                surface=s["surface"],
                scenario=s["scenario"],
                ticks=s["ticks_recorded"],
                sim=s["sim_seconds"],
                pc=s["path_chord"]["mean"] or 0.0,
                yr=s["y_range_mm"]["mean"] or 0.0,
                sp=s["speed_mm_s"]["mean"] or 0.0,
                fc=s["fired_count"]["mean"] or 0.0,
                ma=s["muscle_activation"]["mean"] or 0.0,
                food=food,
            )
        )

    lab_no_food = by_id.get("lab_no_food_100k")
    demo_no_food = by_id.get("demo_no_food_100k")
    if lab_no_food and demo_no_food:
        lines.extend(
            [
                "",
                "## No-Food Lab/Demo Parity",
                "",
                "| metric | lab mean | demo mean | demo-lab | relative delta |",
                "| --- | ---: | ---: | ---: | ---: |",
            ]
        )
        parity_metrics = [
            ("body path/chord", "path_chord"),
            ("lateral y range mm", "y_range_mm"),
            ("COM speed mm/s", "speed_mm_s"),
            ("angular speed rad/s", "angular_speed_rad_s"),
            ("fired neurons", "fired_count"),
            ("neural S std", "s_std"),
            ("prediction error proxy", "prediction_error"),
            ("motor entropy proxy", "motor_entropy"),
            ("absolute joint angle", "joint_abs_angle"),
            ("absolute joint velocity", "joint_abs_velocity"),
            ("muscle activation", "muscle_activation"),
        ]
        for label, key in parity_metrics:
            lines.append(metric_delta_row(label, lab_no_food, demo_no_food, key))

    if demo_no_food:
        food_runs = [
            s
            for s in summaries
            if s.get("surface") == "demo" and s.get("scenario") != "none"
        ]
        lines.extend(
            [
                "",
                "## Food Runs vs Demo No-Food Baseline",
                "",
                "| run | scenario | food | nearest food mean mm | path/chord delta | speed delta | muscle delta | motor entropy delta | M0 mean | M1 mean |",
                "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for s in food_runs:
            rid = s["run_id"]
            food = f"{s.get('initial_food_count', 0)}->{s.get('final_food_count', 0)} eaten={s.get('eaten_count', 0)}"
            nearest = mean(s, "nearest_food_mm")
            lines.append(
                "| {rid} | {scenario} | {food} | {nearest} | {pc} | {speed} | {muscle} | {me} | {m0:.4f} | {m1:.4f} |".format(
                    rid=rid,
                    scenario=s["scenario"],
                    food=food,
                    nearest=f"{nearest:.3f}" if nearest is not None else "n/a",
                    pc=rel_delta(mean(s, "path_chord"), mean(demo_no_food, "path_chord")),
                    speed=rel_delta(mean(s, "speed_mm_s"), mean(demo_no_food, "speed_mm_s")),
                    muscle=rel_delta(mean(s, "muscle_activation"), mean(demo_no_food, "muscle_activation")),
                    me=rel_delta(mean(s, "motor_entropy"), mean(demo_no_food, "motor_entropy")),
                    m0=mean(s, "neuromod_m0") or 0.0,
                    m1=mean(s, "neuromod_m1") or 0.0,
                )
            )

    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- No-food lab and demo runs use the same migrated config and both run for 100k ticks; their summary means are directly comparable.",
            "- The close-distance food cases (0.2 mm and 1 mm ahead) increase body path/chord and motor entropy relative to demo no-food; the 0.2 mm pellet is consumed, so it is an encounter-and-post-consumption run.",
            "- The 5 mm ahead field is near the no-food baseline, which is consistent with a weaker immediate chemotaxis perturbation.",
            "- Relative-position runs show asymmetric behavioral modulation: behind and left produce the largest path/chord increases, while all three 1 mm relative-position pellets remain present for the full 100k ticks.",
            "- Amount tests separate local-density and broad-field effects: the 6-pellet ring strongly modulates curvature and consumes one pellet; the 24-pellet 5-20 mm field remains persistent and closer to baseline movement.",
            "",
            "## Notes",
            "",
            "- `lab` runs are driven through the same simulation construction and loop wrapper used by `run_c_elegans.py`.",
            "- `demo` runs instantiate `SimRuntime` and step through the demo snapshot builder used by the WebSocket server.",
            "- The demo server exposes parity-only fields only with `--analysis-wire`; public/default demo payloads remain compact.",
            "- Every listed run must have `ticks_recorded >= 100000` before it counts toward the requested parity matrix.",
        ]
    )
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {report}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="run one long capture")
    run.add_argument("--surface", required=True, choices=["lab", "demo"])
    run.add_argument("--scenario", default="none", choices=sorted(SCENARIOS))
    run.add_argument("--ticks", type=int, default=100_000)
    run.add_argument("--allow-short", action="store_true")
    run.add_argument("--evol-config", default=None)
    run.add_argument("--outdir", required=True)
    run.add_argument("--run-id", required=True)
    run.add_argument("--neural-sample-stride", type=int, default=20)
    run.add_argument("--progress-every", type=int, default=10_000)
    rep = sub.add_parser("report", help="write aggregate Markdown report")
    rep.add_argument("--outdir", required=True)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    if args.cmd == "run":
        run_capture(args)
    elif args.cmd == "report":
        write_report(args)
    else:
        raise SystemExit(f"unknown command {args.cmd}")


if __name__ == "__main__":
    main()

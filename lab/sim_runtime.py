"""Lab-flavoured simulation runtime.

Owned by a single background thread. Differs from the demo ``SimRuntime``:

* No food, no food commands — the plate is empty on purpose.
* Play/pause/step transport with a shared ``sim_lock`` so parameter patches
  can be applied safely between ticks.
* Snapshots expose joint angles / velocities, contact forces, muscle
  activations, free-energy samples, and neuromod levels.
* Optional wall-clock pacing (see ``pacing_snapshot`` / ``set_pacing``):
  minimum real ms per physics step and per neural sub-tick (``0`` = no cap).
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np
from loguru import logger

from simulations.c_elegans.body import CElegansBody
from simulations.c_elegans.config import (
    BODY_RADIUS_M,
    ENV_PLATE_RADIUS_M,
    N_BODY_SEGMENTS,
)
from simulations.c_elegans.neuron_mapping import CElegansNervousSystem
from simulations.c_elegans.simulation import build_c_elegans_simulation


PatchFn = Callable[[], None]


@dataclass
class TransportState:
    running: bool = True
    tick: int = 0
    step_pending: int = 0


@dataclass
class LatestFrame:
    """Most recent lab snapshot, ready for wire encoding."""

    tick: int = 0
    running: bool = True
    # Body (mm): COM is [cx, cy, cz]; each segment is [x, y, z] (wire v5 triplets).
    com_mm: list[float] = field(default_factory=list)
    segments_mm: list[list[float]] = field(default_factory=list)
    # Neurons (paula_id order)
    neuron_s: list[float] = field(default_factory=list)
    neuron_r: list[float] = field(default_factory=list)
    neuron_b: list[float] = field(default_factory=list)
    neuron_tref: list[float] = field(default_factory=list)
    neuron_fired: list[int] = field(default_factory=list)
    # Physics extras (joint order == body.joint_names)
    joint_angles: list[float] = field(default_factory=list)
    joint_velocities: list[float] = field(default_factory=list)
    # Touch sensors: (nose, ant, post)
    touch_forces: list[float] = field(default_factory=list)
    # Muscles (order == body.muscle_names)
    muscle_activations: list[float] = field(default_factory=list)
    # Per-neuron M_vector[0] / M_vector[1] (paula_id order, same length as neuron_s)
    neuron_m0: list[float] = field(default_factory=list)
    neuron_m1: list[float] = field(default_factory=list)
    # Neuromodulators
    neuromod: tuple[float, float] = (0.0, 0.0)
    # Free-energy proxy
    free_energy: float = 0.0


class LabSimRuntime:
    """Thread-owned simulation with transport + patch queue."""

    def __init__(
        self,
        *,
        body_settle_steps: int | None = None,
        evol_config: dict[str, Any] | None = None,
        log_free_energy: bool = True,
    ) -> None:
        self.engine, self.loop = build_c_elegans_simulation(
            food_positions=[],
            log_level="WARNING",
            record_neural_states=False,
            suppress_connectome_summary=True,
            max_history=32,
            body_settle_steps=body_settle_steps,
            evol_config=evol_config,
        )
        self.loop.log_free_energy = bool(log_free_energy)
        self.loop.reset()
        logger.info("LabSimRuntime: simulation ready (no food)")

        self._sim_lock = threading.RLock()
        self._patch_queue: queue.SimpleQueue[PatchFn] = queue.SimpleQueue()
        self._transport = TransportState()
        self._running_flag = threading.Event()
        self._running_flag.set()
        self._latest_lock = threading.Lock()
        self._latest: LatestFrame = LatestFrame()
        # Wall-clock pacing (0 = no extra delay — run as fast as the CPU allows).
        self._real_ms_per_physics_step: float = 0.0
        self._real_ms_per_neural_tick: float = 0.0

        # Cached body / neuron ordering for wire encoding.
        ns0 = self.engine.nervous_system
        if not isinstance(ns0, CElegansNervousSystem):
            raise RuntimeError("Lab requires CElegansNervousSystem")
        body0 = self.engine.body
        if not isinstance(body0, CElegansBody):
            raise RuntimeError("Lab requires CElegansBody")
        self.neuron_names: list[str] = ns0.get_neuron_names_paula_order()
        self.joint_names: list[str] = list(body0.joint_names)
        self.muscle_names: list[str] = list(body0.muscle_names)
        self.touch_sensor_names: list[str] = [
            "touch_nose_sensor",
            "touch_ant_sensor",
            "touch_post_sensor",
        ]
        self.engine.real_ms_per_neural_tick = float(self._real_ms_per_neural_tick)

    # ------------------------------------------------------------------
    # Wall-clock pacing (live lab)
    # ------------------------------------------------------------------

    def pacing_snapshot(self) -> dict[str, float]:
        with self._sim_lock:
            return {
                "real_ms_per_physics_step": float(self._real_ms_per_physics_step),
                "real_ms_per_neural_tick": float(self._real_ms_per_neural_tick),
            }

    def set_pacing(
        self,
        *,
        real_ms_per_physics_step: float | None = None,
        real_ms_per_neural_tick: float | None = None,
    ) -> dict[str, float]:
        with self._sim_lock:
            if real_ms_per_physics_step is not None:
                self._real_ms_per_physics_step = max(0.0, float(real_ms_per_physics_step))
            if real_ms_per_neural_tick is not None:
                self._real_ms_per_neural_tick = max(0.0, float(real_ms_per_neural_tick))
                self.engine.real_ms_per_neural_tick = float(self._real_ms_per_neural_tick)
            return {
                "real_ms_per_physics_step": float(self._real_ms_per_physics_step),
                "real_ms_per_neural_tick": float(self._real_ms_per_neural_tick),
            }

    # ------------------------------------------------------------------
    # Transport

    @property
    def sim_lock(self) -> threading.RLock:
        return self._sim_lock

    def transport_snapshot(self) -> dict[str, Any]:
        with self._sim_lock:
            return {
                "running": bool(self._transport.running),
                "tick": int(self._transport.tick),
            }

    def play(self) -> dict[str, Any]:
        with self._sim_lock:
            self._transport.running = True
        return self.transport_snapshot()

    def pause(self) -> dict[str, Any]:
        with self._sim_lock:
            self._transport.running = False
        return self.transport_snapshot()

    def step_once(self) -> dict[str, Any]:
        """Request exactly one physics+neural step; stays paused afterwards."""
        with self._sim_lock:
            self._transport.step_pending += 1
            self._transport.running = False
        return self.transport_snapshot()

    def stop(self) -> None:
        self._running_flag.clear()

    # ------------------------------------------------------------------
    # Patch queue

    def enqueue_patch(self, fn: PatchFn) -> None:
        self._patch_queue.put(fn)

    def _drain_patches(self) -> None:
        while True:
            try:
                fn = self._patch_queue.get_nowait()
            except queue.Empty:
                return
            try:
                fn()
            except Exception:
                logger.exception("Live patch failed")

    # ------------------------------------------------------------------
    # Main loop

    def run_loop(self) -> None:
        try:
            while self._running_flag.is_set():
                should_step = False
                with self._sim_lock:
                    if self._transport.step_pending > 0:
                        self._transport.step_pending -= 1
                        should_step = True
                    elif self._transport.running:
                        should_step = True

                if not should_step:
                    time.sleep(1.0 / 120.0)
                    self._refresh_latest_paused()
                    continue

                with self._sim_lock:
                    self._drain_patches()
                    frame = self._build_frame()
                    self._transport.tick = frame.tick
                with self._latest_lock:
                    self._latest = frame
        except Exception:
            logger.exception("Lab simulation thread crashed")
            self._running_flag.clear()

    # ------------------------------------------------------------------
    # Snapshot construction

    def _refresh_latest_paused(self) -> None:
        """Keep broadcasting a fresh snapshot (same tick) while paused."""
        with self._latest_lock:
            if not self._latest.segments_mm:
                return
            self._latest.running = False

    def _build_frame(self) -> LatestFrame:
        phy_target_ms = float(self._real_ms_per_physics_step)
        self.engine.real_ms_per_neural_tick = float(self._real_ms_per_neural_tick)
        t_wall0 = time.perf_counter()
        step = self.engine.step()
        body = self.engine.body
        ns = self.engine.nervous_system
        assert isinstance(body, CElegansBody)
        assert isinstance(ns, CElegansNervousSystem)

        bs = step.body_state
        com = bs.position
        com_mm = [
            float(com[0] * 1000.0),
            float(com[1] * 1000.0),
            float(com[2] * 1000.0),
        ]

        segments_mm: list[list[float]] = []
        shape = body.get_body_shape()
        for i in range(min(N_BODY_SEGMENTS, shape.shape[0])):
            segments_mm.append(
                [
                    float(shape[i, 0] * 1000.0),
                    float(shape[i, 1] * 1000.0),
                    float(shape[i, 2] * 1000.0),
                ]
            )

        # Neurons
        s_list, r_list, b_list, tref_list, f_list = self._neuron_arrays(ns)
        m0_list, m1_list = self._neuron_m01_arrays(ns)

        # Joints
        ja = [float(bs.joint_angles.get(n, 0.0)) for n in self.joint_names]
        jv = [float(bs.joint_velocities.get(n, 0.0)) for n in self.joint_names]

        # Touch (scalar force per sensor)
        tc: list[float] = []
        for sname in self.touch_sensor_names:
            vec = bs.contact_forces.get(sname)
            if vec is None:
                tc.append(0.0)
            else:
                tc.append(float(np.linalg.norm(np.asarray(vec, dtype=float))))

        # Muscles: read post-NMJ clipped ctrl values directly from mjData.
        import mujoco  # local import keeps module-load cost down

        ma: list[float] = []
        mj_model = body.model
        mj_data = body.data
        for mname in self.muscle_names:
            aid = mujoco.mj_name2id(mj_model, mujoco.mjtObj.mjOBJ_ACTUATOR, mname)
            if aid < 0:
                ma.append(0.0)
                continue
            force_max = float(mj_model.actuator_forcerange[aid, 1]) or 1.0
            ma.append(float(mj_data.ctrl[aid]) / force_max if force_max else 0.0)

        # Neuromods
        m0, m1 = ns.neuromod_levels

        # Free-energy
        fe_val = 0.0
        if self.loop.log_free_energy and self.loop.free_energy_trace.prediction_error:
            fe_val = float(self.loop.free_energy_trace.prediction_error[-1])

        if phy_target_ms > 0.0:
            elapsed_s = time.perf_counter() - t_wall0
            remain_s = phy_target_ms / 1000.0 - elapsed_s
            if remain_s > 0.0:
                time.sleep(remain_s)

        return LatestFrame(
            tick=int(step.tick),
            running=True,
            com_mm=com_mm,
            segments_mm=segments_mm,
            neuron_s=s_list,
            neuron_r=r_list,
            neuron_b=b_list,
            neuron_tref=tref_list,
            neuron_fired=f_list,
            joint_angles=ja,
            joint_velocities=jv,
            touch_forces=tc,
            muscle_activations=ma,
            neuron_m0=m0_list,
            neuron_m1=m1_list,
            neuromod=(float(m0), float(m1)),
            free_energy=fe_val,
        )

    @staticmethod
    def _neuron_arrays(
        ns: CElegansNervousSystem,
    ) -> tuple[list[float], list[float], list[float], list[float], list[int]]:
        """Parallel per-neuron arrays in paula_id order: (S, r, b, t_ref, fired)."""
        if ns._network is None:  # type: ignore[attr-defined]
            return [], [], [], [], []
        neurons = ns._network.network.neurons  # type: ignore[attr-defined]
        if not neurons:
            return [], [], [], [], []
        ids = sorted(neurons.keys(), key=int)
        n = int(ids[-1]) + 1
        s_out = [0.0] * n
        r_out = [0.0] * n
        b_out = [0.0] * n
        tref_out = [0.0] * n
        f_out = [0] * n
        for i in ids:
            neuron = neurons[i]
            ii = int(i)
            if 0 <= ii < n:
                s_out[ii] = float(neuron.S)
                r_out[ii] = float(neuron.r)
                b_out[ii] = float(neuron.b)
                tref_out[ii] = float(neuron.t_ref)
                f_out[ii] = 1 if float(neuron.O) > 0 else 0
        return s_out, r_out, b_out, tref_out, f_out

    @staticmethod
    def _neuron_m01_arrays(ns: CElegansNervousSystem) -> tuple[list[float], list[float]]:
        """Parallel M_vector[0], M_vector[1] in paula_id order (same indexing as S)."""
        if ns._network is None:  # type: ignore[attr-defined]
            return [], []
        neurons = ns._network.network.neurons  # type: ignore[attr-defined]
        if not neurons:
            return [], []
        ids = sorted(neurons.keys(), key=int)
        n = int(ids[-1]) + 1
        m0_out = [0.0] * n
        m1_out = [0.0] * n
        for i in ids:
            neuron = neurons[i]
            ii = int(i)
            if not (0 <= ii < n):
                continue
            mvec = getattr(neuron, "M_vector", None)
            if mvec is None:
                continue
            try:
                arr = np.asarray(mvec, dtype=float).reshape(-1)
            except (TypeError, ValueError):
                continue
            if arr.size >= 1:
                m0_out[ii] = float(arr[0])
            if arr.size >= 2:
                m1_out[ii] = float(arr[1])
        return m0_out, m1_out

    # ------------------------------------------------------------------
    # Broadcast API

    def get_latest(self) -> LatestFrame | None:
        with self._latest_lock:
            if not self._latest.segments_mm:
                return None
            # Return a shallow copy (dataclass replace would be per-field).
            return LatestFrame(
                tick=self._latest.tick,
                running=bool(self._transport.running),
                com_mm=list(self._latest.com_mm),
                segments_mm=[list(row) for row in self._latest.segments_mm],
                neuron_s=list(self._latest.neuron_s),
                neuron_r=list(self._latest.neuron_r),
                neuron_b=list(self._latest.neuron_b),
                neuron_tref=list(self._latest.neuron_tref),
                neuron_fired=list(self._latest.neuron_fired),
                joint_angles=list(self._latest.joint_angles),
                joint_velocities=list(self._latest.joint_velocities),
                touch_forces=list(self._latest.touch_forces),
                muscle_activations=list(self._latest.muscle_activations),
                neuron_m0=list(self._latest.neuron_m0),
                neuron_m1=list(self._latest.neuron_m1),
                neuromod=self._latest.neuromod,
                free_energy=self._latest.free_energy,
            )

    def has_frame(self) -> bool:
        with self._latest_lock:
            return bool(self._latest.segments_mm)

    # ------------------------------------------------------------------
    # Statics (for hello frame & REST)

    def plate_radius_mm(self) -> float:
        return float(ENV_PLATE_RADIUS_M * 1000.0)

    def worm_radius_mm(self) -> float:
        return float(BODY_RADIUS_M * 1000.0)

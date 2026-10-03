"""Lab control and validation tests without building or changing the model."""

import asyncio
import queue
import threading
import time
import unittest
from types import SimpleNamespace
from typing import Callable
from unittest.mock import Mock, patch

import numpy as np
from pydantic import ValidationError

from lab.parameters.applicators import apply_patches
from lab.parameters.registry import ParameterRegistry, ParameterSpec
from lab.parameters.mujoco_engine_params import register_mujoco_engine_specs
from lab.rest_routes import (
    AppContext,
    BodyPatch,
    BodyPatchBody,
    NeuronParamPatch,
    NeuronPatchBody,
    PacingBody,
    build_rest_router,
)
from lab.server import build_app
from lab.sim_runtime import LabSimRuntime, LatestFrame, TransportState
from simulations.c_elegans.neuron_mapping import CElegansNervousSystem


def paused_runtime() -> LabSimRuntime:
    runtime = LabSimRuntime.__new__(LabSimRuntime)
    runtime._sim_lock = threading.RLock()
    runtime._patch_queue = queue.SimpleQueue()
    runtime._transport = TransportState(running=False, tick=7)
    runtime._running_flag = threading.Event()
    runtime._running_flag.set()
    runtime._latest_lock = threading.Lock()
    runtime._latest = LatestFrame(tick=7, segments_mm=[[0.0, 0.0, 0.0]])
    runtime._real_ms_per_physics_step = 0.0
    runtime._real_ms_per_neural_tick = 0.0
    runtime.engine = SimpleNamespace(real_ms_per_neural_tick=0.0)
    return runtime


class RuntimeTests(unittest.TestCase):
    def test_queued_edit_is_applied_without_stepping_a_paused_sim(self) -> None:
        runtime = paused_runtime()
        build_frame = Mock(side_effect=AssertionError("paused sim must not step"))
        runtime._build_frame = build_frame
        applied: list[str] = []

        def apply_and_stop() -> None:
            applied.append("edited")
            runtime.stop()

        runtime.enqueue_patch(apply_and_stop)
        runtime.run_loop()
        self.assertEqual(applied, ["edited"])
        self.assertEqual(runtime.transport_snapshot(), {"running": False, "tick": 7})
        build_frame.assert_not_called()

    def test_invalid_pacing_does_not_partially_apply(self) -> None:
        runtime = paused_runtime()
        for value in (-1.0, float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                runtime.set_pacing(
                    real_ms_per_physics_step=5.0,
                    real_ms_per_neural_tick=value,
                )
            self.assertEqual(runtime.pacing_snapshot(), {
                "real_ms_per_physics_step": 0.0,
                "real_ms_per_neural_tick": 0.0,
            })


class PatchValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = ParameterRegistry()
        self.applied: list[tuple[str, object]] = []
        self.queued: list[Callable[[], None]] = []
        self.ctx = SimpleNamespace(pending_patches={})
        for kind, apply in (("float", "live"), ("int", "rebuild"), ("bool", "live")):
            self.registry.register(ParameterSpec(
                path=kind, label=kind, group="test", kind=kind, apply=apply,
                getter=lambda ctx: 0,
                setter=lambda ctx, value, kind=kind: self.applied.append((kind, value)),
                min=0 if kind != "bool" else None,
                max=10 if kind != "bool" else None,
            ))

    def test_invalid_edits_are_neither_queued_nor_staged(self) -> None:
        edits = [
            {"path": "float", "value": "nan"},
            {"path": "float", "value": float("inf")},
            {"path": "float", "value": -1},
            {"path": "float", "value": 11},
            {"path": "int", "value": 1.5},
            {"path": "bool", "value": "false"},
            {"path": "missing", "value": 1},
        ]
        result = apply_patches(self.registry, self.ctx, edits, enqueue_live=self.queued.append)
        self.assertEqual(len(result.failed), len(edits))
        self.assertEqual(result.applied, [])
        self.assertEqual(result.pending, [])
        self.assertEqual(self.queued, [])
        self.assertEqual(self.ctx.pending_patches, {})

    def test_valid_values_keep_live_and_rebuild_routing(self) -> None:
        result = apply_patches(self.registry, self.ctx, [
            {"path": "float", "value": 2.5},
            {"path": "int", "value": 3},
            {"path": "bool", "value": False},
        ], enqueue_live=self.queued.append)
        self.assertEqual(result.applied, ["float", "bool"])
        self.assertEqual(result.pending, ["int"])
        self.assertEqual(result.failed, [])
        self.assertEqual(self.ctx.pending_patches, {"int": 3})
        for callback in self.queued:
            callback()
        self.assertEqual(self.applied, [("float", 2.5), ("bool", False)])

    def test_negative_model_indices_and_invalid_pacing_are_rejected(self) -> None:
        for key in ("id", "index"):
            with self.subTest(key=key), self.assertRaises(ValidationError):
                BodyPatch(target="body", field="mass", value=1, **{key: -1})
        for key in ("index", "vec_index"):
            with self.subTest(key=key), self.assertRaises(ValidationError):
                NeuronParamPatch(field="gamma", value=1, **{key: -1})
        for value in (-1, "nan", "inf"):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                PacingBody(real_ms_per_physics_step=value)

    def test_existing_gravity_component_patch_is_accepted(self) -> None:
        model = SimpleNamespace(opt=SimpleNamespace(gravity=np.array([0.0, 0.0, -9.81])))
        ctx = SimpleNamespace(
            runtime=SimpleNamespace(engine=SimpleNamespace(body=SimpleNamespace(model=model))),
            pending_patches={},
        )
        registry = ParameterRegistry()
        register_mujoco_engine_specs(registry)
        result = apply_patches(registry, ctx, [
            {"path": "sim.mujoco.opt.gravity[2]", "value": -8.0},
        ], enqueue_live=self.queued.append)
        self.assertEqual(result.failed, [])
        self.assertEqual(result.applied, ["sim.mujoco.opt.gravity[2]"])
        self.queued[0]()
        self.assertEqual(model.opt.gravity.tolist(), [0.0, 0.0, -8.0])

    def test_nonfinite_body_edit_does_not_mutate_or_recompute_model(self) -> None:
        model = SimpleNamespace(body_mass=np.array([0.0, 1.0]))
        runtime = SimpleNamespace(engine=SimpleNamespace(body=SimpleNamespace(model=model)),
                                  sim_lock=threading.RLock())
        router = build_rest_router(AppContext(runtime, self.registry))
        endpoint = next(r.endpoint for r in router.routes if r.path == "/api/body/patch")
        with patch("mujoco.mj_setTotalmass") as set_total_mass:
            result = endpoint(BodyPatchBody(patches=[
                BodyPatch(target="body", id=1, field="mass", value="nan"),
            ]))
        self.assertEqual(model.body_mass.tolist(), [0.0, 1.0])
        self.assertEqual(result["applied"], [])
        self.assertEqual(len(result["failed"]), 1)
        set_total_mass.assert_not_called()

    def test_nonfinite_neuron_edits_do_not_mutate_runtime_or_params(self) -> None:
        neuron = SimpleNamespace(S=0.25, params=SimpleNamespace(gamma=np.array([0.9, 0.8])))
        nervous = CElegansNervousSystem.__new__(CElegansNervousSystem)
        nervous.get_neuron_by_name = Mock(return_value=neuron)
        runtime = SimpleNamespace(engine=SimpleNamespace(nervous_system=nervous),
                                  sim_lock=threading.RLock())
        router = build_rest_router(AppContext(runtime, self.registry))
        endpoint = next(r.endpoint for r in router.routes if r.path == "/api/neurons/{name}/patch")
        result = endpoint("AVAL", NeuronPatchBody(patches=[
            NeuronParamPatch(field="S", value="inf"),
            NeuronParamPatch(field="gamma", value=[0.8, "nan"]),
        ]))
        self.assertEqual(neuron.S, 0.25)
        self.assertEqual(neuron.params.gamma.tolist(), [0.9, 0.8])
        self.assertEqual(result["applied"], [])
        self.assertEqual(len(result["failed"]), 2)


class LifespanTests(unittest.IsolatedAsyncioTestCase):
    async def test_startup_and_join_leave_event_loop_available(self) -> None:
        startup_ready = asyncio.Event()
        shutdown_ready = asyncio.Event()
        events: list[str] = []
        runtime = Mock()
        runtime.has_frame.side_effect = startup_ready.is_set
        runtime.transport_snapshot.return_value = {"tick": 1}
        thread = Mock()
        thread.is_alive.return_value = True

        def join(*, timeout: float) -> None:
            time.sleep(0.03)
            events.append("joined")
            thread.is_alive.return_value = False

        thread.join.side_effect = join
        runtime.stop.side_effect = shutdown_ready.set
        with patch("lab.server.LabSimRuntime", return_value=runtime), \
             patch("lab.server.threading.Thread", return_value=thread):
            app, _, _ = build_app()

        async def background_work() -> None:
            await asyncio.sleep(0.001)
            startup_ready.set()
            await shutdown_ready.wait()
            await asyncio.sleep(0.001)
            events.append("background")

        background = asyncio.create_task(background_work())
        async with app.router.lifespan_context(app):
            self.assertTrue(startup_ready.is_set())
        await background
        self.assertEqual(events, ["background", "joined"])
        runtime.stop.assert_called_once()

    async def test_cancelled_startup_stops_the_simulation_thread(self) -> None:
        runtime = Mock()
        runtime.has_frame.return_value = False
        thread = Mock()
        thread.is_alive.return_value = True
        with patch("lab.server.LabSimRuntime", return_value=runtime), \
             patch("lab.server.threading.Thread", return_value=thread):
            app, _, _ = build_app()
        context = app.router.lifespan_context(app)
        task = asyncio.create_task(context.__aenter__())
        await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        runtime.stop.assert_called_once()
        thread.join.assert_called_once_with(timeout=30.0)

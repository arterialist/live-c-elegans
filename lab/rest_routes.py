"""FastAPI REST routes for the lab server."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from simulations.c_elegans.neuron_mapping import CElegansNervousSystem

from lab.introspect.body_introspect import build_body_view
from lab.introspect.connectome_introspect import build_connectome_view
from lab.parameters import ParameterRegistry
from lab.parameters.applicators import apply_patches
from lab.sim_runtime import LabSimRuntime


class TransportAction(BaseModel):
    action: Literal["play", "pause", "step"]


class PacingBody(BaseModel):
    """Optional wall-clock pacing for the lab sim thread (milliseconds).

    ``0`` means no added delay for that axis (run as fast as the CPU allows).
    """

    real_ms_per_physics_step: float | None = None
    real_ms_per_neural_tick: float | None = None


class Patch(BaseModel):
    path: str
    value: Any


class PatchBody(BaseModel):
    patches: list[Patch] = Field(default_factory=list)


class NeuronParamPatch(BaseModel):
    """Patch neuron parameters, runtime state, or synaptic terminals.

    * **Params scalars** — ``field`` is ``r_base``, ``c``, … (see
      ``_NEURON_SCALAR_FIELDS``); ``index`` / ``subfield`` ignored.
    * **Params vectors** — ``field`` is ``gamma`` / ``w_r`` / ``w_b`` /
      ``w_tref``: either replace the whole vector (``value`` is a list,
      ``index`` is None) or set one slot (``index`` = element, ``value`` =
      number).
    * **Runtime** — ``field`` is ``S``, ``O``, ``r``, ``b``, ``t_ref``,
      ``F_avg``, ``t_last_fire``; scalar ``value`` on the live neuron.
    * **``M_vector``** — same pattern as params vectors but on the neuron
      object (length = ``num_neuromodulators``).
    * **Postsynaptic** — ``field`` = ``postsynaptic``, ``index`` = synapse
      slot id; ``subfield`` one of ``info``, ``plast``, ``potential``,
      ``adapt`` (``adapt`` requires ``vec_index``).
    * **Presynaptic** — ``field`` = ``presynaptic``, ``index`` = terminal id;
      ``subfield`` ``u_o_info``, ``u_i_retro``, or ``mod`` (``mod`` requires
      ``vec_index``).
    """

    field: str
    value: Any
    index: int | None = None
    subfield: str | None = None
    vec_index: int | None = None


class NeuronPatchBody(BaseModel):
    patches: list[NeuronParamPatch] = Field(default_factory=list)


class BodyPatch(BaseModel):
    """One live mjModel field edit.

    ``target`` selects the MuJoCo table (``joint``, ``actuator``, ``body``,
    ``pair`` or ``opt``); ``id`` indexes into that table and is omitted for
    ``opt``. ``field`` names the logical property; ``index`` is used when the
    property is a vector (forcerange, gear, inertia, gravity, friction).
    """

    target: Literal["joint", "actuator", "body", "pair", "opt"]
    field: str
    value: Any
    id: int | None = None
    index: int | None = None


class BodyPatchBody(BaseModel):
    patches: list[BodyPatch] = Field(default_factory=list)


_NEURON_SCALAR_FIELDS: dict[str, type] = {
    "r_base": float,
    "b_base": float,
    "c": int,
    "lambda_param": float,
    "p": float,
    "eta_post": float,
    "eta_retro": float,
    "delta_decay": float,
    "beta_avg": float,
}
_NEURON_VECTOR_FIELDS = ("gamma", "w_r", "w_b", "w_tref")
_NEURON_RUNTIME_FIELDS: dict[str, type] = {
    "S": float,
    "O": float,
    "r": float,
    "b": float,
    "t_ref": float,
    "F_avg": float,
    "t_last_fire": float,
}


class AppContext:
    """Container wired into FastAPI state at startup."""

    def __init__(self, runtime: LabSimRuntime, registry: ParameterRegistry) -> None:
        self.runtime = runtime
        self.registry = registry
        self.pending_patches: dict[str, Any] = {}


def build_rest_router(app_ctx: AppContext) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "tick": app_ctx.runtime.transport_snapshot()["tick"]}

    @router.get("/sim/transport")
    def get_transport() -> dict[str, Any]:
        return app_ctx.runtime.transport_snapshot()

    @router.post("/sim/transport")
    def set_transport(body: TransportAction) -> dict[str, Any]:
        if body.action == "play":
            return app_ctx.runtime.play()
        if body.action == "pause":
            return app_ctx.runtime.pause()
        if body.action == "step":
            return app_ctx.runtime.step_once()
        raise HTTPException(status_code=400, detail=f"unknown action: {body.action}")

    @router.get("/sim/pacing")
    def get_pacing() -> dict[str, Any]:
        return app_ctx.runtime.pacing_snapshot()

    @router.post("/sim/pacing")
    def set_pacing(body: PacingBody) -> dict[str, Any]:
        return app_ctx.runtime.set_pacing(
            real_ms_per_physics_step=body.real_ms_per_physics_step,
            real_ms_per_neural_tick=body.real_ms_per_neural_tick,
        )

    @router.get("/schema")
    def schema() -> dict[str, Any]:
        specs: list[dict[str, Any]] = []
        snap = app_ctx.registry.snapshot(app_ctx)
        for spec in app_ctx.registry.all():
            specs.append(
                {
                    "path": spec.path,
                    "label": spec.label,
                    "group": spec.group,
                    "kind": spec.kind,
                    "apply": spec.apply,
                    "min": spec.min,
                    "max": spec.max,
                    "step": spec.step,
                    "enum": list(spec.enum) if spec.enum else None,
                    "help": spec.help,
                    "value": snap.get(spec.path),
                }
            )
        return {"specs": specs, "pending": dict(app_ctx.pending_patches)}

    @router.get("/connectome")
    def connectome() -> dict[str, Any]:
        ns = app_ctx.runtime.engine.nervous_system
        if not isinstance(ns, CElegansNervousSystem):
            raise HTTPException(status_code=500, detail="nervous system missing")
        return build_connectome_view(ns._connectome, ns.get_neuron_names_paula_order())  # type: ignore[attr-defined]

    @router.get("/body")
    def body_view() -> dict[str, Any]:
        body = app_ctx.runtime.engine.body
        return build_body_view(body)  # type: ignore[arg-type]

    @router.get("/neurons/{name}")
    def neuron(name: str) -> dict[str, Any]:
        ns = app_ctx.runtime.engine.nervous_system
        if not isinstance(ns, CElegansNervousSystem):
            raise HTTPException(status_code=500, detail="nervous system missing")
        neuron = ns.get_neuron_by_name(name)
        if neuron is None:
            raise HTTPException(status_code=404, detail=f"unknown neuron: {name}")
        params = neuron.params
        id_to_name = {nid: nm for nm, nid in ns.name_to_id.items()}
        postsynaptic: list[dict[str, Any]] = []
        for sid in sorted(neuron.postsynaptic_points.keys()):
            pt = neuron.postsynaptic_points[sid]
            src = neuron.synapse_sources.get(sid)
            pre_name = id_to_name.get(src[0]) if src else None
            postsynaptic.append(
                {
                    "id": int(sid),
                    "pre_paula_id": int(src[0]) if src else None,
                    "pre_terminal": int(src[1]) if src else None,
                    "pre_name": pre_name,
                    "info": float(pt.u_i.info),
                    "plast": float(pt.u_i.plast),
                    "adapt": [float(x) for x in pt.u_i.adapt],
                    "potential": float(pt.potential),
                }
            )
        presynaptic: list[dict[str, Any]] = []
        for tid in sorted(neuron.presynaptic_points.keys()):
            pr = neuron.presynaptic_points[tid]
            presynaptic.append(
                {
                    "id": int(tid),
                    "u_o_info": float(pr.u_o.info),
                    "u_o_mod": [float(x) for x in pr.u_o.mod],
                    "u_i_retro": float(pr.u_i_retro),
                }
            )
        return {
            "name": name,
            "paula_id": int(neuron.id),
            "S": float(neuron.S),
            "O": float(neuron.O),
            "r": float(neuron.r),
            "b": float(neuron.b),
            "t_ref": float(neuron.t_ref),
            "F_avg": float(neuron.F_avg),
            "t_last_fire": float(neuron.t_last_fire),
            "M_vector": [float(x) for x in neuron.M_vector],
            "pq_len": int(len(neuron.propagation_queue)),
            "postsynaptic": postsynaptic,
            "presynaptic": presynaptic,
            "params": {
                "r_base": float(params.r_base),
                "b_base": float(params.b_base),
                "c": int(params.c),
                "lambda_param": float(params.lambda_param),
                "p": float(params.p),
                "eta_post": float(params.eta_post),
                "eta_retro": float(params.eta_retro),
                "delta_decay": float(params.delta_decay),
                "beta_avg": float(params.beta_avg),
                "gamma": [float(x) for x in params.gamma],
                "w_r": [float(x) for x in params.w_r],
                "w_b": [float(x) for x in params.w_b],
                "w_tref": [float(x) for x in params.w_tref],
                "num_neuromodulators": int(params.num_neuromodulators),
                "num_inputs": int(params.num_inputs),
            },
        }

    @router.post("/neurons/{name}/patch")
    def patch_neuron(name: str, body: NeuronPatchBody) -> dict[str, Any]:
        """Hot-patch one neuron's :class:`NeuronParameters` live.

        All edits are applied under ``sim_lock`` so a tick cannot run between
        a field update and the next simulation step.
        """
        ns = app_ctx.runtime.engine.nervous_system
        if not isinstance(ns, CElegansNervousSystem):
            raise HTTPException(status_code=500, detail="nervous system missing")
        neuron = ns.get_neuron_by_name(name)
        if neuron is None:
            raise HTTPException(status_code=404, detail=f"unknown neuron: {name}")

        import numpy as np

        from neuron.neuron import MAX_SYNAPTIC_WEIGHT, MIN_SYNAPTIC_WEIGHT

        applied: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        with app_ctx.runtime.sim_lock:
            params = neuron.params
            for patch in body.patches:
                try:
                    if patch.field in _NEURON_RUNTIME_FIELDS:
                        caster = _NEURON_RUNTIME_FIELDS[patch.field]
                        setattr(neuron, patch.field, caster(patch.value))
                        applied.append({"field": patch.field})
                    elif patch.field == "M_vector":
                        arr = neuron.M_vector
                        if patch.index is None:
                            new_arr = np.asarray(patch.value, dtype=float).reshape(
                                -1,
                            )
                            if new_arr.shape[0] != arr.shape[0]:
                                raise ValueError(
                                    f"M_vector length {new_arr.shape[0]} != {arr.shape[0]}"
                                )
                            neuron.M_vector = new_arr.astype(float, copy=True)
                            applied.append({"field": patch.field})
                        else:
                            if not (0 <= patch.index < arr.shape[0]):
                                raise IndexError(
                                    f"M_vector[{patch.index}] out of range"
                                )
                            arr[patch.index] = float(patch.value)
                            applied.append(
                                {"field": patch.field, "index": patch.index}
                            )
                    elif patch.field == "postsynaptic":
                        if patch.index is None:
                            raise ValueError("postsynaptic patch requires index (slot id)")
                        pt = neuron.postsynaptic_points.get(patch.index)
                        if pt is None:
                            raise KeyError(f"unknown postsynaptic slot {patch.index}")
                        sf = (patch.subfield or "info").lower().replace("u_i.", "")
                        if sf == "info":
                            v = float(patch.value)
                            pt.u_i.info = float(
                                np.clip(v, MIN_SYNAPTIC_WEIGHT, MAX_SYNAPTIC_WEIGHT)
                            )
                        elif sf == "plast":
                            pt.u_i.plast = float(patch.value)
                        elif sf == "potential":
                            pt.potential = float(patch.value)
                        elif sf == "adapt":
                            if patch.vec_index is None:
                                raise ValueError("adapt patch requires vec_index")
                            if not (0 <= patch.vec_index < pt.u_i.adapt.shape[0]):
                                raise IndexError("adapt vec_index out of range")
                            pt.u_i.adapt[patch.vec_index] = float(patch.value)
                        else:
                            raise KeyError(f"unknown postsynaptic subfield: {patch.subfield}")
                        applied.append(
                            {
                                "field": patch.field,
                                "index": patch.index,
                                "subfield": patch.subfield,
                                "vec_index": patch.vec_index,
                            }
                        )
                    elif patch.field == "presynaptic":
                        if patch.index is None:
                            raise ValueError("presynaptic patch requires index (terminal id)")
                        pr = neuron.presynaptic_points.get(patch.index)
                        if pr is None:
                            raise KeyError(f"unknown presynaptic terminal {patch.index}")
                        sf = (patch.subfield or "u_o_info").lower()
                        if sf in ("u_o_info", "info", "u_o.info"):
                            v = float(patch.value)
                            pr.u_o.info = float(
                                np.clip(v, MIN_SYNAPTIC_WEIGHT, MAX_SYNAPTIC_WEIGHT)
                            )
                        elif sf in ("u_i_retro", "retro"):
                            pr.u_i_retro = float(patch.value)
                        elif sf in ("mod", "u_o.mod"):
                            if patch.vec_index is None:
                                raise ValueError("mod patch requires vec_index")
                            if not (0 <= patch.vec_index < pr.u_o.mod.shape[0]):
                                raise IndexError("mod vec_index out of range")
                            pr.u_o.mod[patch.vec_index] = float(patch.value)
                        else:
                            raise KeyError(f"unknown presynaptic subfield: {patch.subfield}")
                        applied.append(
                            {
                                "field": patch.field,
                                "index": patch.index,
                                "subfield": patch.subfield,
                                "vec_index": patch.vec_index,
                            }
                        )
                    elif patch.field in _NEURON_SCALAR_FIELDS:
                        caster = _NEURON_SCALAR_FIELDS[patch.field]
                        setattr(params, patch.field, caster(patch.value))
                        applied.append({"field": patch.field})
                    elif patch.field in _NEURON_VECTOR_FIELDS:
                        arr = getattr(params, patch.field)
                        if patch.index is None:
                            new_arr = np.asarray(patch.value, dtype=float).reshape(
                                arr.shape
                            )
                            setattr(params, patch.field, new_arr)
                            applied.append({"field": patch.field})
                        else:
                            if not (0 <= patch.index < arr.shape[0]):
                                raise IndexError(
                                    f"{patch.field}[{patch.index}] out of range"
                                )
                            arr[patch.index] = float(patch.value)
                            applied.append(
                                {"field": patch.field, "index": patch.index}
                            )
                    else:
                        raise KeyError(f"unknown neuron field: {patch.field}")
                except Exception as exc:  # noqa: BLE001
                    failed.append({"field": patch.field, "error": str(exc)})
        return {"applied": applied, "failed": failed}

    @router.get("/muscles/{muscle_name}")
    def muscle(muscle_name: str) -> dict[str, Any]:
        body = app_ctx.runtime.engine.body
        import mujoco

        aid = mujoco.mj_name2id(body.model, mujoco.mjtObj.mjOBJ_ACTUATOR, muscle_name)
        if aid < 0:
            raise HTTPException(status_code=404, detail=f"unknown muscle: {muscle_name}")
        mj = body.model
        mj_data = body.data
        force_max = float(mj.actuator_forcerange[aid, 1]) or 1.0
        return {
            "name": muscle_name,
            "id": int(aid),
            "ctrl": float(mj_data.ctrl[aid]),
            "activation": float(mj_data.ctrl[aid]) / force_max if force_max else 0.0,
            "forcerange": [
                float(mj.actuator_forcerange[aid, 0]),
                float(mj.actuator_forcerange[aid, 1]),
            ],
            "gear": [float(x) for x in mj.actuator_gear[aid]],
            "target_joint_id": int(mj.actuator_trnid[aid, 0]),
        }

    @router.post("/body/patch")
    def patch_body(body: BodyPatchBody) -> dict[str, Any]:
        """Hot-patch mjModel fields live under ``sim_lock``.

        Only scalar-ish fields that MuJoCo re-reads each step are accepted
        (damping, armature, actuator forcerange/gear, body mass, contact pair
        friction/solref/solimp, opt gravity/viscosity/density).
        """
        import mujoco

        mj = app_ctx.runtime.engine.body.model
        applied: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []

        with app_ctx.runtime.sim_lock:
            for patch in body.patches:
                try:
                    if patch.target == "joint":
                        assert patch.id is not None
                        dof = int(mj.jnt_dofadr[patch.id])
                        if patch.field == "damping":
                            mj.dof_damping[dof] = float(patch.value)
                        elif patch.field == "armature":
                            mj.dof_armature[dof] = float(patch.value)
                        else:
                            raise KeyError(patch.field)
                    elif patch.target == "actuator":
                        assert patch.id is not None
                        if patch.field == "forcerange":
                            idx = patch.index if patch.index is not None else 1
                            mj.actuator_forcerange[patch.id, idx] = float(patch.value)
                        elif patch.field == "gear":
                            idx = patch.index if patch.index is not None else 0
                            mj.actuator_gear[patch.id, idx] = float(patch.value)
                        else:
                            raise KeyError(patch.field)
                    elif patch.target == "body":
                        assert patch.id is not None
                        if patch.field == "mass":
                            mj.body_mass[patch.id] = float(patch.value)
                        elif patch.field == "inertia":
                            assert patch.index is not None
                            mj.body_inertia[patch.id, patch.index] = float(patch.value)
                        else:
                            raise KeyError(patch.field)
                    elif patch.target == "pair":
                        assert patch.id is not None
                        if patch.field == "friction":
                            assert patch.index is not None
                            mj.pair_friction[patch.id, patch.index] = float(patch.value)
                        elif patch.field == "solref":
                            assert patch.index is not None
                            mj.pair_solref[patch.id, patch.index] = float(patch.value)
                        elif patch.field == "solimp":
                            assert patch.index is not None
                            mj.pair_solimp[patch.id, patch.index] = float(patch.value)
                        else:
                            raise KeyError(patch.field)
                    elif patch.target == "opt":
                        # Whitelist every writable mjOption field (mirrors
                        # lab.parameters.mujoco_engine_params).
                        _opt_float = {
                            "timestep",
                            "impratio",
                            "tolerance",
                            "noslip_tolerance",
                            "ls_tolerance",
                            "ccd_tolerance",
                            "sleep_tolerance",
                            "density",
                            "viscosity",
                            "o_margin",
                        }
                        _opt_int = {
                            "integrator",
                            "cone",
                            "jacobian",
                            "solver",
                            "iterations",
                            "noslip_iterations",
                            "sdf_iterations",
                            "ccd_iterations",
                            "ls_iterations",
                            "sdf_initpoints",
                            "disableflags",
                            "enableflags",
                            "disableactuator",
                            "enableactuator",
                        }
                        _opt_vec = ("gravity", "wind", "magnetic", "o_solref", "o_solimp", "o_friction")
                        if patch.field in _opt_float:
                            setattr(mj.opt, patch.field, float(patch.value))
                        elif patch.field in _opt_int:
                            setattr(mj.opt, patch.field, int(patch.value))
                        elif patch.field in _opt_vec:
                            assert patch.index is not None
                            getattr(mj.opt, patch.field)[patch.index] = float(
                                patch.value
                            )
                        else:
                            raise KeyError(patch.field)
                    else:
                        raise KeyError(f"unknown target: {patch.target}")

                    applied.append(
                        {
                            "target": patch.target,
                            "id": patch.id,
                            "field": patch.field,
                            "index": patch.index,
                        }
                    )
                except Exception as exc:  # noqa: BLE001
                    failed.append(
                        {
                            "target": patch.target,
                            "id": patch.id,
                            "field": patch.field,
                            "index": patch.index,
                            "error": str(exc),
                        }
                    )

            # Body mass changes invalidate composite rigid-body inertias; cheap to recompute.
            if any(p.target == "body" and p.field == "mass" for p in body.patches):
                mujoco.mj_setTotalmass(mj, float(mj.body_mass.sum()))

        return {"applied": applied, "failed": failed}

    @router.get("/pending")
    def get_pending() -> dict[str, Any]:
        return {"pending": dict(app_ctx.pending_patches)}

    @router.post("/patch")
    def patch(body: PatchBody) -> dict[str, Any]:
        result = apply_patches(
            app_ctx.registry,
            app_ctx,
            [{"path": p.path, "value": p.value} for p in body.patches],
            enqueue_live=app_ctx.runtime.enqueue_patch,
        )
        return {
            "applied": result.applied,
            "pending": result.pending,
            "failed": result.failed,
        }

    @router.post("/apply-pending")
    def apply_pending() -> dict[str, Any]:
        """Commit every pending rebuild patch, then reset the simulation."""
        stash = dict(app_ctx.pending_patches)
        applied: list[str] = []
        failed: list[dict[str, Any]] = []
        with app_ctx.runtime.sim_lock:
            for path, value in stash.items():
                try:
                    spec = app_ctx.registry.get(path)
                except Exception as exc:  # noqa: BLE001
                    failed.append({"path": path, "error": str(exc)})
                    continue
                try:
                    spec.setter(app_ctx, value)
                    applied.append(path)
                except Exception as exc:  # noqa: BLE001
                    failed.append({"path": path, "error": str(exc)})
            if applied:
                app_ctx.runtime.loop.reset()
        for k in applied:
            app_ctx.pending_patches.pop(k, None)
        return {"applied": applied, "failed": failed}

    @router.post("/reset")
    def reset_sim() -> dict[str, Any]:
        with app_ctx.runtime.sim_lock:
            app_ctx.runtime.loop.reset()
        return {"ok": True}

    return router

"""MuJoCo ``mjOption`` parameters exposed to the lab schema.

Every scalar and indexed vector entry on :attr:`mujoco.MjModel.opt` that is safe
to tweak at runtime is registered under ``sim.mujoco.opt.*`` so the web UI can
edit them without hand-writing ``/api/body/patch`` payloads.

Vector components use paths ``….<field>[i]`` matching the dotted convention used
elsewhere in the registry.
"""

from __future__ import annotations

from typing import Any

from lab.parameters.registry import ApplyTag, Kind, ParameterRegistry, ParameterSpec


def _engine(ctx: Any) -> Any:
    return ctx.runtime.engine


def _opt(ctx: Any) -> Any:
    return _engine(ctx).body.model.opt


def _make_opt_float(
    path: str,
    label: str,
    field: str,
    *,
    group: str,
    min: float,
    max: float,
    step: float,
    help: str,
    apply: ApplyTag = "live",
) -> ParameterSpec:
    def _get(ctx: Any) -> float:
        return float(getattr(_opt(ctx), field))

    def _set(ctx: Any, value: Any) -> None:
        setattr(_opt(ctx), field, float(value))

    return ParameterSpec(
        path=path,
        label=label,
        group=group,
        kind="float",
        apply=apply,
        getter=_get,
        setter=_set,
        help=help,
        min=min,
        max=max,
        step=step,
    )


def _make_opt_int(
    path: str,
    label: str,
    field: str,
    *,
    group: str,
    min: int,
    max: int,
    step: int,
    help: str,
    apply: ApplyTag = "live",
) -> ParameterSpec:
    def _get(ctx: Any) -> int:
        return int(getattr(_opt(ctx), field))

    def _set(ctx: Any, value: Any) -> None:
        setattr(_opt(ctx), field, int(value))

    return ParameterSpec(
        path=path,
        label=label,
        group=group,
        kind="int",
        apply=apply,
        getter=_get,
        setter=_set,
        help=help,
        min=float(min),
        max=float(max),
        step=float(step),
    )


def _make_opt_vec1(
    path: str,
    label: str,
    field: str,
    index: int,
    *,
    group: str,
    kind: Kind,
    min: float,
    max: float,
    step: float,
    help: str,
    apply: ApplyTag = "live",
) -> ParameterSpec:
    def _get(ctx: Any) -> float:
        return float(getattr(_opt(ctx), field)[index])

    def _set(ctx: Any, value: Any) -> None:
        arr = getattr(_opt(ctx), field)
        if kind == "int":
            arr[index] = int(value)
        else:
            arr[index] = float(value)

    return ParameterSpec(
        path=path,
        label=label,
        group=group,
        kind=kind,
        apply=apply,
        getter=_get,
        setter=_set,
        help=help,
        min=min,
        max=max,
        step=step,
    )


def register_mujoco_engine_specs(registry: ParameterRegistry) -> None:
    """Register all tunable :class:`mujoco.MjOption` fields."""

    specs: list[ParameterSpec] = []
    g_time = "MuJoCo · Timestep & integrator"
    g_solver = "MuJoCo · Solver & iterations"
    g_tol = "MuJoCo · Tolerances"
    g_fluid = "MuJoCo · Fluid medium"
    g_field = "MuJoCo · Gravity, wind, B-field"
    g_override = "MuJoCo · Global contact override"
    g_flags = "MuJoCo · Flags & bitmasks"

    specs.append(
        _make_opt_float(
            "sim.mujoco.opt.timestep",
            "timestep (s)",
            "timestep",
            group=g_time,
            min=1e-5,
            max=0.02,
            step=1e-4,
            help="Physics integration step (was sim.physics_timestep).",
        )
    )
    specs.append(
        _make_opt_int(
            "sim.mujoco.opt.integrator",
            "integrator",
            "integrator",
            group=g_time,
            min=0,
            max=2,
            step=1,
            help="0=Euler, 1=implicit fast, 2=RK4 (mjtIntegrator).",
        )
    )
    specs.append(
        _make_opt_float(
            "sim.mujoco.opt.impratio",
            "implicit ratio",
            "impratio",
            group=g_time,
            min=1.0,
            max=20.0,
            step=0.1,
            help="Implicit integrator mixing ratio (stiff / normal).",
        )
    )

    specs.append(
        _make_opt_int(
            "sim.mujoco.opt.cone",
            "friction cone",
            "cone",
            group=g_solver,
            min=0,
            max=1,
            step=1,
            help="0=pyramidal, 1=elliptic (mjtCone).",
        )
    )
    specs.append(
        _make_opt_int(
            "sim.mujoco.opt.jacobian",
            "Jacobian layout",
            "jacobian",
            group=g_solver,
            min=0,
            max=2,
            step=1,
            help="0=dense, 1=sparse, 2=auto (mjtJacobian).",
        )
    )
    specs.append(
        _make_opt_int(
            "sim.mujoco.opt.solver",
            "solver algorithm",
            "solver",
            group=g_solver,
            min=0,
            max=2,
            step=1,
            help="0=PGS, 1=Newton, 2=CG (mjtSolver).",
        )
    )
    specs.append(
        _make_opt_int(
            "sim.mujoco.opt.iterations",
            "main iterations",
            "iterations",
            group=g_solver,
            min=1,
            max=1000,
            step=1,
            help="Max constraint solver iterations per step.",
        )
    )
    specs.append(
        _make_opt_int(
            "sim.mujoco.opt.noslip_iterations",
            "noslip iterations",
            "noslip_iterations",
            group=g_solver,
            min=0,
            max=1000,
            step=1,
            help="Noslip solver iterations (0 disables that pass).",
        )
    )
    specs.append(
        _make_opt_int(
            "sim.mujoco.opt.sdf_iterations",
            "SDF iterations",
            "sdf_iterations",
            group=g_solver,
            min=0,
            max=1000,
            step=1,
            help="SDF collision refinement iterations.",
        )
    )
    specs.append(
        _make_opt_int(
            "sim.mujoco.opt.ccd_iterations",
            "CCD iterations",
            "ccd_iterations",
            group=g_solver,
            min=0,
            max=1000,
            step=1,
            help="Continuous collision detection iterations.",
        )
    )
    specs.append(
        _make_opt_int(
            "sim.mujoco.opt.ls_iterations",
            "line-search iterations",
            "ls_iterations",
            group=g_solver,
            min=0,
            max=100,
            step=1,
            help="Line-search iterations (Newton/CG).",
        )
    )
    specs.append(
        _make_opt_int(
            "sim.mujoco.opt.sdf_initpoints",
            "SDF init points",
            "sdf_initpoints",
            group=g_solver,
            min=1,
            max=100,
            step=1,
            help="Initial samples for SDF broad-phase.",
        )
    )

    specs.append(
        _make_opt_float(
            "sim.mujoco.opt.tolerance",
            "solver tolerance",
            "tolerance",
            group=g_tol,
            min=1e-15,
            max=1e-1,
            step=1e-8,
            help="Termination tolerance for the main constraint solver.",
        )
    )
    specs.append(
        _make_opt_float(
            "sim.mujoco.opt.noslip_tolerance",
            "noslip tolerance",
            "noslip_tolerance",
            group=g_tol,
            min=1e-15,
            max=1e-1,
            step=1e-8,
            help="Noslip solver termination tolerance.",
        )
    )
    specs.append(
        _make_opt_float(
            "sim.mujoco.opt.ls_tolerance",
            "line-search tolerance",
            "ls_tolerance",
            group=g_tol,
            min=1e-15,
            max=1.0,
            step=1e-6,
            help="Tolerance for the Newton/CG line search.",
        )
    )
    specs.append(
        _make_opt_float(
            "sim.mujoco.opt.ccd_tolerance",
            "CCD tolerance",
            "ccd_tolerance",
            group=g_tol,
            min=1e-15,
            max=1.0,
            step=1e-6,
            help="CCD termination tolerance.",
        )
    )
    specs.append(
        _make_opt_float(
            "sim.mujoco.opt.sleep_tolerance",
            "sleep tolerance",
            "sleep_tolerance",
            group=g_tol,
            min=0.0,
            max=1.0,
            step=0.001,
            help="Relative kinetic energy below which bodies sleep.",
        )
    )

    specs.append(
        _make_opt_float(
            "sim.mujoco.opt.density",
            "fluid density",
            "density",
            group=g_fluid,
            min=0.0,
            max=20000.0,
            step=10.0,
            help="Medium density (kg/m³). 0 disables buoyancy from fluid.",
        )
    )
    specs.append(
        _make_opt_float(
            "sim.mujoco.opt.viscosity",
            "fluid viscosity",
            "viscosity",
            group=g_fluid,
            min=0.0,
            max=10.0,
            step=0.01,
            help="Dynamic viscosity scale used by MuJoCo fluid forces.",
        )
    )

    for i, axis in enumerate("xyz"):
        specs.append(
            _make_opt_vec1(
                f"sim.mujoco.opt.gravity[{i}]",
                f"gravity {axis}",
                "gravity",
                i,
                group=g_field,
                kind="float",
                min=-50.0,
                max=50.0,
                step=0.1,
                help=f"Gravity vector component {axis} (m/s²).",
            )
        )
    for i, axis in enumerate("xyz"):
        specs.append(
            _make_opt_vec1(
                f"sim.mujoco.opt.wind[{i}]",
                f"wind {axis}",
                "wind",
                i,
                group=g_field,
                kind="float",
                min=-50.0,
                max=50.0,
                step=0.1,
                help=f"Uniform wind velocity {axis} (m/s).",
            )
        )
    for i, axis in enumerate("xyz"):
        specs.append(
            _make_opt_vec1(
                f"sim.mujoco.opt.magnetic[{i}]",
                f"magnetic {axis}",
                "magnetic",
                i,
                group=g_field,
                kind="float",
                min=-5.0,
                max=5.0,
                step=0.01,
                help=f"Global magnetic field {axis} (Tesla).",
            )
        )

    specs.append(
        _make_opt_float(
            "sim.mujoco.opt.o_margin",
            "override margin",
            "o_margin",
            group=g_override,
            min=0.0,
            max=1.0,
            step=0.001,
            help="Global contact margin override (m); 0 uses geom-specific.",
        )
    )
    for i in range(2):
        specs.append(
            _make_opt_vec1(
                f"sim.mujoco.opt.o_solref[{i}]",
                f"override solref[{i}]",
                "o_solref",
                i,
                group=g_override,
                kind="float",
                min=0.001,
                max=2.0,
                step=0.001,
                help="Global contact solref time constant / damping ratio.",
            )
        )
    for i in range(5):
        specs.append(
            _make_opt_vec1(
                f"sim.mujoco.opt.o_solimp[{i}]",
                f"override solimp[{i}]",
                "o_solimp",
                i,
                group=g_override,
                kind="float",
                min=0.0,
                max=1.0,
                step=0.001,
                help=f"Global contact solimp coefficient {i}.",
            )
        )
    for i in range(5):
        specs.append(
            _make_opt_vec1(
                f"sim.mujoco.opt.o_friction[{i}]",
                f"override friction[{i}]",
                "o_friction",
                i,
                group=g_override,
                kind="float",
                min=0.0,
                max=5.0,
                step=0.01,
                help="Global friction tuple entry (see MuJoCo docs).",
            )
        )

    specs.append(
        _make_opt_int(
            "sim.mujoco.opt.disableflags",
            "disable flags",
            "disableflags",
            group=g_flags,
            min=0,
            max=2**31 - 1,
            step=1,
            help="Bit mask mjDISABLE_* — disables engine features when bits set.",
        )
    )
    specs.append(
        _make_opt_int(
            "sim.mujoco.opt.enableflags",
            "enable flags",
            "enableflags",
            group=g_flags,
            min=0,
            max=2**31 - 1,
            step=1,
            help="Bit mask mjENABLE_* — enables optional engine features.",
        )
    )
    specs.append(
        _make_opt_int(
            "sim.mujoco.opt.disableactuator",
            "disable actuator id",
            "disableactuator",
            group=g_flags,
            min=-1,
            max=10_000,
            step=1,
            help="If ≥0, disable that actuator index; -1 disables none.",
        )
    )
    specs.append(
        _make_opt_int(
            "sim.mujoco.opt.enableactuator",
            "enable actuator id",
            "enableactuator",
            group=g_flags,
            min=-1,
            max=10_000,
            step=1,
            help="If ≥0, enable only that actuator; -1 enables all.",
        )
    )

    registry.extend(specs)

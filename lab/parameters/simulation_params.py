"""Simulation-level parameter specs.

Populates :class:`ParameterRegistry` with globals that affect the whole sim:
timing cadence, neuromodulation gains, environment, and sensorimotor scaling.
``live`` specs take effect immediately between ticks; ``rebuild`` specs
accumulate as pending changes (applied by Reset with the registered evol
config).
"""

from __future__ import annotations

from typing import Any

from simulations.c_elegans import config as aec
from simulations.c_elegans.neuron_mapping import CElegansNervousSystem

from lab.parameters.registry import ApplyTag, Kind, ParameterRegistry, ParameterSpec


def _rt(ctx: Any) -> Any:
    return ctx.runtime


def _ns(ctx: Any) -> CElegansNervousSystem:
    ns = _rt(ctx).engine.nervous_system
    if not isinstance(ns, CElegansNervousSystem):
        raise RuntimeError("lab requires CElegansNervousSystem")
    return ns


def _engine(ctx: Any) -> Any:
    return _rt(ctx).engine


def _make_ns_attr_spec(
    path: str,
    attr: str,
    label: str,
    *,
    group: str,
    kind: Kind = "float",
    apply: ApplyTag = "live",
    min: float | None = None,
    max: float | None = None,
    step: float | None = None,
    help: str = "",
) -> ParameterSpec:
    def _get(ctx: Any) -> Any:
        return getattr(_ns(ctx), attr)

    def _set(ctx: Any, value: Any) -> None:
        setattr(_ns(ctx), attr, _coerce(value, kind))

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


def _coerce(value: Any, kind: str) -> Any:
    if kind == "int":
        return int(value)
    if kind == "float":
        return float(value)
    if kind == "bool":
        return bool(value)
    return value


def register_simulation_specs(registry: ParameterRegistry) -> None:
    specs: list[ParameterSpec] = []

    # -- Timing -------------------------------------------------------------
    # MuJoCo timestep lives under ``sim.mujoco.opt.timestep`` (MuJoCo engine tab).

    def _get_neural_ticks(ctx: Any) -> int:
        return int(_engine(ctx).neural_ticks_per_physics_step)

    def _set_neural_ticks(ctx: Any, value: Any) -> None:
        _engine(ctx).neural_ticks_per_physics_step = max(1, int(value))

    specs.append(
        ParameterSpec(
            path="sim.neural_ticks_per_physics",
            label="Neural ticks / physics tick",
            group="Timing",
            kind="int",
            apply="live",
            getter=_get_neural_ticks,
            setter=_set_neural_ticks,
            min=1,
            max=32,
            step=1,
            help=(
                "PAULA sub-steps per MuJoCo step. Raising this increases"
                " neural resolution at the cost of CPU."
            ),
        )
    )

    # -- Neuromodulation ----------------------------------------------------

    NEUROMOD_SPECS: list[tuple[str, str, str, float, float, float]] = [
        (
            "K_STRESS_SYN",
            "K_STRESS_SYN",
            "Synaptic gain: stress (M0 fast arc).",
            0.0,
            10000.0,
            10.0,
        ),
        (
            "K_REWARD_SYN",
            "K_REWARD_SYN",
            "Synaptic gain: reward (M1 fast arc).",
            0.0,
            10000.0,
            10.0,
        ),
        (
            "K_VOL_STRESS",
            "K_VOL_STRESS",
            "Volume-broadcast gain: stress.",
            0.0,
            10000.0,
            10.0,
        ),
        (
            "K_VOL_REWARD",
            "K_VOL_REWARD",
            "Volume-broadcast gain: reward.",
            0.0,
            10000.0,
            10.0,
        ),
        (
            "STRESS_DEADZONE",
            "STRESS_DEADZONE",
            "Deadzone around delta-C below which no stress is emitted.",
            0.0,
            0.01,
            1e-5,
        ),
        (
            "CHEM_EMA_ALPHA_FAST",
            "CHEM_EMA_ALPHA_FAST",
            "Fast EMA coefficient for chemosensory bandpass.",
            0.0,
            1.0,
            0.01,
        ),
        (
            "CHEM_EMA_ALPHA_SLOW",
            "CHEM_EMA_ALPHA_SLOW",
            "Slow EMA coefficient for chemosensory bandpass.",
            0.0,
            1.0,
            0.005,
        ),
        (
            "TONIC_FWD_CMD",
            "TONIC_FWD_CMD",
            "Tonic drive injected into forward command interneurons.",
            0.0,
            1.0,
            0.01,
        ),
        (
            "TONIC_FWD_MOTOR",
            "TONIC_FWD_MOTOR",
            "Tonic drive injected into forward B-type motor neurons.",
            0.0,
            1.0,
            0.01,
        ),
        (
            "K_OFF_SUPPRESS",
            "K_OFF_SUPPRESS",
            "Gain mapping absolute chem concentration → M1 suppression.",
            0.0,
            20.0,
            0.1,
        ),
        (
            "TONIC_OFF_CELL",
            "TONIC_OFF_CELL",
            "Tonic S baseline for OFF-cell firing.",
            0.0,
            1.0,
            0.01,
        ),
        (
            "PROPRIO_MOTOR_GAIN",
            "PROPRIO_MOTOR_GAIN",
            "B-type motor neuron proprioception gain (Wen 2012).",
            0.0,
            1.0,
            0.005,
        ),
        (
            "PROPRIO_TAIL_DECAY",
            "PROPRIO_TAIL_DECAY",
            "Anterior→posterior taper on the proprioceptive gain. 0 = uniform, 1 = tail motor neurons receive no proprioception. Higher values suppress standing-wave reflection.",
            0.0,
            1.0,
            0.05,
        ),
        (
            "HEAD_CPG_FREQ_HZ",
            "HEAD_CPG_FREQ_HZ",
            "Head CPG frequency (Hz). Seeds the undulation rhythm at DB1/VB1.",
            0.0,
            5.0,
            0.05,
        ),
        (
            "HEAD_CPG_AMP",
            "HEAD_CPG_AMP",
            "Head CPG amplitude. 0 disables the CPG; higher values dominate the B-type drive.",
            0.0,
            2.0,
            0.01,
        ),
    ]
    for path_suffix, attr, help_text, lo, hi, step in NEUROMOD_SPECS:
        specs.append(
            _make_ns_attr_spec(
                path=f"sim.neuromod.{path_suffix}",
                attr=f"_{attr}",
                label=attr,
                group="Neuromodulation",
                kind="float",
                apply="live",
                min=lo,
                max=hi,
                step=step,
                help=help_text,
            )
        )

    # Toggles for neuromodulator channels (live).
    def _get_m0(ctx: Any) -> bool:
        return bool(_ns(ctx)._enable_m0)  # noqa: SLF001

    def _set_m0(ctx: Any, v: Any) -> None:
        _ns(ctx)._enable_m0 = bool(v)  # noqa: SLF001

    def _get_m1(ctx: Any) -> bool:
        return bool(_ns(ctx)._enable_m1)  # noqa: SLF001

    def _set_m1(ctx: Any, v: Any) -> None:
        _ns(ctx)._enable_m1 = bool(v)  # noqa: SLF001

    specs.extend(
        [
            ParameterSpec(
                path="sim.neuromod.enable_m0",
                label="Enable M0 (stress)",
                group="Neuromodulation",
                kind="bool",
                apply="live",
                getter=_get_m0,
                setter=_set_m0,
                help="Volume-transmit M0 (stress) on every tick.",
            ),
            ParameterSpec(
                path="sim.neuromod.enable_m1",
                label="Enable M1 (reward)",
                group="Neuromodulation",
                kind="bool",
                apply="live",
                getter=_get_m1,
                setter=_set_m1,
                help="Volume-transmit M1 (reward) on every tick.",
            ),
        ]
    )

    # -- Environment --------------------------------------------------------

    def _get_plate_radius(_ctx: Any) -> float:
        return float(aec.ENV_PLATE_RADIUS_M)

    def _set_plate_radius(_ctx: Any, value: Any) -> None:
        aec.ENV_PLATE_RADIUS_M = float(value)

    specs.append(
        ParameterSpec(
            path="sim.env.plate_radius",
            label="Agar plate radius (m)",
            group="Environment",
            kind="float",
            apply="rebuild",
            getter=_get_plate_radius,
            setter=_set_plate_radius,
            min=0.005,
            max=0.20,
            step=0.001,
            help="Radius of the plate geom; rebuild to re-generate the arena.",
        )
    )

    # -- Plate boundary wall ----------------------------------------------
    # The wall is a ring of static box geoms inserted into the MJCF at
    # body load time (see CElegansBody._load_model_with_wall). All four
    # geometry parameters are 'rebuild' because they reshape the model.

    def _get_wall_height(_ctx: Any) -> float:
        return float(aec.WALL_HEIGHT_M)

    def _set_wall_height(_ctx: Any, value: Any) -> None:
        aec.WALL_HEIGHT_M = float(value)

    specs.append(
        ParameterSpec(
            path="sim.env.wall_height_m",
            label="Plate wall height (m)",
            group="Environment",
            kind="float",
            apply="rebuild",
            getter=_get_wall_height,
            setter=_set_wall_height,
            min=0.0005,
            max=0.02,
            step=0.0001,
            help="Vertical extent of the boundary wall (rebuild).",
        )
    )

    def _get_wall_friction(_ctx: Any) -> float:
        return float(aec.WALL_FRICTION_TANGENT)

    def _set_wall_friction(_ctx: Any, value: Any) -> None:
        aec.WALL_FRICTION_TANGENT = float(value)

    specs.append(
        ParameterSpec(
            path="sim.env.wall_friction",
            label="Plate wall friction (tangent)",
            group="Environment",
            kind="float",
            apply="rebuild",
            getter=_get_wall_friction,
            setter=_set_wall_friction,
            min=0.0,
            max=2.0,
            step=0.01,
            help="Tangent-direction friction on the boundary wall (rebuild).",
        )
    )

    def _get_wall_segments(_ctx: Any) -> int:
        return int(aec.WALL_SEGMENTS_N)

    def _set_wall_segments(_ctx: Any, value: Any) -> None:
        aec.WALL_SEGMENTS_N = max(8, int(value))

    specs.append(
        ParameterSpec(
            path="sim.env.wall_segments_n",
            label="Plate wall segments",
            group="Environment",
            kind="int",
            apply="rebuild",
            getter=_get_wall_segments,
            setter=_set_wall_segments,
            min=8,
            max=256,
            step=1,
            help="Number of boxes around the plate ring (rebuild).",
        )
    )

    def _get_boundary_factor(_ctx: Any) -> float:
        return float(aec.BOUNDARY_TELEPORT_FACTOR)

    def _set_boundary_factor(_ctx: Any, value: Any) -> None:
        aec.BOUNDARY_TELEPORT_FACTOR = float(value)

    specs.append(
        ParameterSpec(
            path="sim.env.boundary_teleport_factor",
            label="Teleport safety factor (× R)",
            group="Environment",
            kind="float",
            apply="live",
            getter=_get_boundary_factor,
            setter=_set_boundary_factor,
            min=1.0,
            max=3.0,
            step=0.05,
            help=(
                "Recentre the worm only when it leaves the disk by this "
                "fraction of plate radius (1.2 = 20 % beyond). Numerical "
                "safety net only; wall contact does the real obstruction."
            ),
        )
    )

    def _get_fake_wall_obs(_ctx: Any) -> bool:
        return bool(aec.FAKE_WALL_OBSERVATION)

    def _set_fake_wall_obs(_ctx: Any, value: Any) -> None:
        aec.FAKE_WALL_OBSERVATION = bool(value)

    specs.append(
        ParameterSpec(
            path="sim.env.fake_wall_obs",
            label="Fake 'wall' observation channel",
            group="Environment",
            kind="bool",
            apply="live",
            getter=_get_fake_wall_obs,
            setter=_set_fake_wall_obs,
            help=(
                "Legacy: synthesise a 'wall' contact-force entry from "
                "radial distance. Off by default — real touch sensors "
                "fire on physical wall contact instead."
            ),
        )
    )

    # -- Sensorimotor scaling ----------------------------------------------

    def _get_joint_max(_ctx: Any) -> float:
        return float(aec.JOINT_ANGLE_MAX_RAD)

    def _set_joint_max(_ctx: Any, value: Any) -> None:
        aec.JOINT_ANGLE_MAX_RAD = float(value)

    specs.append(
        ParameterSpec(
            path="sim.joints.angle_max",
            label="Joint angle max (rad)",
            group="Sensorimotor",
            kind="float",
            apply="rebuild",
            getter=_get_joint_max,
            setter=_set_joint_max,
            min=0.1,
            max=2.0,
            step=0.01,
            help="Hinge travel in the MuJoCo model (requires rebuild).",
        )
    )

    def _get_muscle_alpha(ctx: Any) -> float:
        ns = _ns(ctx)
        return float(getattr(ns, "_muscle_filter_alpha", aec.MUSCLE_FILTER_ALPHA))

    def _set_muscle_alpha(ctx: Any, value: Any) -> None:
        ns = _ns(ctx)
        setattr(ns, "_muscle_filter_alpha", float(value))

    specs.append(
        ParameterSpec(
            path="sim.muscles.filter_alpha",
            label="Muscle LP-filter α",
            group="Sensorimotor",
            kind="float",
            apply="live",
            getter=_get_muscle_alpha,
            setter=_set_muscle_alpha,
            min=0.0,
            max=1.0,
            step=0.01,
            help="Low-pass smoothing on motor outputs (0 = no smoothing).",
        )
    )

    def _get_nmj_scale(ctx: Any) -> float:
        return float(getattr(_ns(ctx), "_nmj_scale", 1.0 / 20.0))

    def _set_nmj_scale(ctx: Any, value: Any) -> None:
        setattr(_ns(ctx), "_nmj_scale", float(value))

    def _get_nmj_threshold(ctx: Any) -> float:
        return float(getattr(_ns(ctx), "_nmj_threshold", 0.0))

    def _set_nmj_threshold(ctx: Any, value: Any) -> None:
        setattr(_ns(ctx), "_nmj_threshold", float(value))

    specs.append(
        ParameterSpec(
            path="sim.muscles.nmj_scale",
            label="NMJ Strength Scale",
            group="Sensorimotor",
            kind="float",
            apply="live",
            getter=_get_nmj_scale,
            setter=_set_nmj_scale,
            min=0.0,
            max=5.0,
            step=0.01,
            help="Multiplier for mapping neuron potentials to muscle forces.",
        )
    )

    specs.append(
        ParameterSpec(
            path="sim.muscles.nmj_threshold",
            label="NMJ Threshold",
            group="Sensorimotor",
            kind="float",
            apply="live",
            getter=_get_nmj_threshold,
            setter=_set_nmj_threshold,
            min=0.0,
            max=1.0,
            step=0.01,
            help="Threshold before a neuron activates a muscle.",
        )
    )

    # -- Thermodynamics ----------------------------------------------------

    def _get_gap_diffusion(ctx: Any) -> float:
        return float(getattr(_ns(ctx), "_gap_diffusion_rate", 0.0002))

    def _set_gap_diffusion(ctx: Any, value: Any) -> None:
        setattr(_ns(ctx), "_gap_diffusion_rate", float(value))

    specs.append(
        ParameterSpec(
            path="sim.thermo.gap_diffusion_rate",
            label="Gap Junction Diffusion k",
            group="Thermodynamics",
            kind="float",
            apply="live",
            getter=_get_gap_diffusion,
            setter=_set_gap_diffusion,
            min=0.0,
            max=0.05,
            step=0.0001,
            help="Continuous analog potential diffusion across gap junctions.",
        )
    )

    def _get_tonic_heat(ctx: Any) -> float:
        return float(getattr(_ns(ctx), "_tonic_metabolic_heat", 0.05))

    def _set_tonic_heat(ctx: Any, value: Any) -> None:
        setattr(_ns(ctx), "_tonic_metabolic_heat", float(value))

    specs.append(
        ParameterSpec(
            path="sim.thermo.tonic_metabolic_heat",
            label="Pacemaker Tonic Heat",
            group="Thermodynamics",
            kind="float",
            apply="live",
            getter=_get_tonic_heat,
            setter=_set_tonic_heat,
            min=0.0,
            max=0.5,
            step=0.001,
            help="Basal analog leak driving the oscillator limit cycle.",
        )
    )

    registry.extend(specs)

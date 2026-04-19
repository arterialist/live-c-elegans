"""Extract a UI-friendly view of the MuJoCo body model.

Phase 1 exposes the minimum the frontend needs to index into the per-tick
``ja``/``jv``/``ma``/``tc`` arrays. Phase 4 extends this with per-body mass
and inertia, contact-pair friction, etc.
"""

from __future__ import annotations

from typing import Any

import mujoco

from simulations.c_elegans.body import CElegansBody


def build_body_view(body: CElegansBody) -> dict[str, Any]:
    m = body.model

    bodies: list[dict[str, Any]] = []
    for i in range(m.nbody):
        name = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_BODY, i)
        if not name:
            continue
        bodies.append(
            {
                "id": int(i),
                "name": name,
                "mass": float(m.body_mass[i]),
                "inertia": [float(x) for x in m.body_inertia[i]],
            }
        )

    joints: list[dict[str, Any]] = []
    for i in range(m.njnt):
        name = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_JOINT, i)
        if not name or "root" in name:
            continue
        dof = int(m.jnt_dofadr[i])
        joints.append(
            {
                "id": int(i),
                "name": name,
                "range": [float(m.jnt_range[i, 0]), float(m.jnt_range[i, 1])],
                "damping": float(m.dof_damping[dof]) if dof >= 0 else 0.0,
                "armature": float(m.dof_armature[dof]) if dof >= 0 else 0.0,
            }
        )

    actuators: list[dict[str, Any]] = []
    for i in range(m.nu):
        name = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_ACTUATOR, i)
        if not name:
            continue
        actuators.append(
            {
                "id": int(i),
                "name": name,
                "forcerange": [
                    float(m.actuator_forcerange[i, 0]),
                    float(m.actuator_forcerange[i, 1]),
                ],
                "gear": [float(x) for x in m.actuator_gear[i]],
                "target_joint_id": int(m.actuator_trnid[i, 0]),
            }
        )

    sensors: list[dict[str, Any]] = []
    for i in range(m.nsensor):
        name = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_SENSOR, i)
        if not name:
            continue
        sensors.append(
            {
                "id": int(i),
                "name": name,
                "dim": int(m.sensor_dim[i]),
            }
        )

    contact_pairs: list[dict[str, Any]] = []
    for i in range(m.npair):
        contact_pairs.append(
            {
                "id": int(i),
                "friction": [float(x) for x in m.pair_friction[i]],
                "solref": [float(x) for x in m.pair_solref[i]],
                "solimp": [float(x) for x in m.pair_solimp[i]],
            }
        )

    return {
        "opt": {
            "timestep": float(m.opt.timestep),
            "gravity": [float(x) for x in m.opt.gravity],
            "viscosity": float(m.opt.viscosity),
            "density": float(m.opt.density),
        },
        "bodies": bodies,
        "joints": joints,
        "actuators": actuators,
        "sensors": sensors,
        "contact_pairs": contact_pairs,
    }

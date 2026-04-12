"""Periodic worm checkpoint: MuJoCo, food, PAULA runtime, tick — JSON on disk."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import numpy as np
from loguru import logger

from simulations.c_elegans.body import CElegansBody
from simulations.c_elegans.environment import AgarPlateEnvironment
from simulations.c_elegans.neuron_mapping import CElegansNervousSystem
from simulations.engine import SimulationEngine
from simulations.sensorimotor_loop import FreeEnergyTrace, SensorimotorLoop

CHECKPOINT_VERSION = 1


def _jsonify(obj: Any) -> Any:
    """Recursively convert numpy types to JSON-serialisable Python values."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, np.generic):
        return obj.item()
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, dict):
        return {str(k): _jsonify(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonify(x) for x in obj]
    raise TypeError(f"not JSON-serialisable: {type(obj)!r}")


def load_evol_config_json(path: str | None) -> dict[str, Any] | None:
    """Same rules as scripts/run_c_elegans.py: checkpoint or flat evolved config."""
    if not path:
        return None
    p = Path(path)
    with p.open() as f:
        data = json.load(f)
    return data.get("config", data.get("best_config", data))


def export_worm_checkpoint(engine: SimulationEngine) -> dict[str, Any]:
    body = engine.body
    if not isinstance(body, CElegansBody):
        raise TypeError("checkpoint requires CElegansBody")
    qpos, qvel = body.export_mujoco_state()
    env = engine.environment
    if not isinstance(env, AgarPlateEnvironment):
        raise TypeError("checkpoint requires AgarPlateEnvironment")
    food = [list(map(float, p)) for p in env.get_active_food_positions()]
    ns = engine.nervous_system
    if not isinstance(ns, CElegansNervousSystem):
        raise TypeError("checkpoint requires CElegansNervousSystem")
    nervous_blob = ns.export_live_checkpoint()
    return {
        "checkpoint_version": CHECKPOINT_VERSION,
        "saved_at_unix": float(time.time()),
        "tick": int(engine.tick),
        "qpos": [float(x) for x in qpos],
        "qvel": [float(x) for x in qvel],
        "food_m": food,
        "nervous": _jsonify(nervous_blob),
    }


def import_worm_checkpoint(
    engine: SimulationEngine,
    loop: SensorimotorLoop,
    data: dict[str, Any],
) -> None:
    if int(data.get("checkpoint_version", 0)) != CHECKPOINT_VERSION:
        raise ValueError("unsupported checkpoint_version")
    body = engine.body
    if not isinstance(body, CElegansBody):
        raise TypeError("checkpoint requires CElegansBody")
    body.import_mujoco_state(list(data["qpos"]), list(data["qvel"]))
    env = engine.environment
    if not isinstance(env, AgarPlateEnvironment):
        raise TypeError("checkpoint requires AgarPlateEnvironment")
    food_tuples = [tuple(float(x) for x in p) for p in data["food_m"]]
    env.replace_food_sources(food_tuples)
    ns = engine.nervous_system
    if not isinstance(ns, CElegansNervousSystem):
        raise TypeError("checkpoint requires CElegansNervousSystem")
    ns.import_live_checkpoint(data["nervous"])
    engine.restore_physics_tick(int(data["tick"]))
    bs = body.get_state()
    env.sync_head_position(np.asarray(bs.head_position, dtype=float))
    loop.free_energy_trace = FreeEnergyTrace()
    logger.info("Restored worm checkpoint at tick {}", data["tick"])


def write_checkpoint_atomic(engine: SimulationEngine, path: Path) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = export_worm_checkpoint(engine)
    text = json.dumps(blob, separators=(",", ":"))
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    logger.info("Wrote worm checkpoint {} bytes -> {}", len(text), path)


def try_load_checkpoint(engine: SimulationEngine, loop: SensorimotorLoop, path: Path | None) -> bool:
    if path is None or not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        import_worm_checkpoint(engine, loop, data)
        return True
    except Exception:
        logger.exception("Failed to load worm checkpoint from {}; starting fresh", path)
        return False

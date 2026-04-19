"""WebSocket streaming: one endpoint at ``/ws/state``.

Frames extend the demo's v3 protocol (see docstring in
``celegans_live_demo/server.py``) with lab-specific fields documented in
``lab/wire.py``.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger

from lab import wire
from lab.connectome_layout import body_aligned_layout
from lab.rest_routes import AppContext
from lab.sim_runtime import LabSimRuntime


_NEURON_KIND_WIRE = {"sensory": "s", "motor": "m", "interneuron": "i", "unknown": "u"}


def _hello_payload(runtime: LabSimRuntime) -> dict[str, Any]:
    ns = runtime.engine.nervous_system
    names = list(runtime.neuron_names)
    ax, ay = body_aligned_layout(names)
    meta: list[dict[str, Any]] = []
    for name in names:
        info = ns._connectome.name_to_info.get(name)  # type: ignore[attr-defined]
        if info is None:
            meta.append({"k": "u", "ic": 0, "ig": 0, "oc": 0, "og": 0})
            continue
        meta.append(
            {
                "k": _NEURON_KIND_WIRE.get(info.neuron_type, "u"),
                "ic": int(info.in_degree_chem),
                "ig": int(info.in_degree_gap),
                "oc": int(info.out_degree_chem),
                "og": int(info.out_degree_gap),
            }
        )
    return {
        "p": wire.PROTOCOL_VERSION,
        "t": "h",
        "m": "lab v1: ja,jv,tc,ma,nm01,fe,z; Si,Ri,Bi,Trefi÷1e4; Fb bits",
        "L": {"nm": names, "ax": ax, "ay": ay},
        "M": meta,
        "L_body": {
            "joints": list(runtime.joint_names),
            "muscles": list(runtime.muscle_names),
            "touch": list(runtime.touch_sensor_names),
        },
    }


def _state_payload(runtime: LabSimRuntime) -> dict[str, Any] | None:
    frame = runtime.get_latest()
    if frame is None:
        return None
    sm: list[int] = []
    for row in frame.segments_mm:
        sm.extend([wire.mm_to_nm_int(row[0]), wire.mm_to_nm_int(row[1])])
    out: dict[str, Any] = {
        "p": wire.PROTOCOL_VERSION,
        "t": "s",
        "k": int(frame.tick),
        "sm": sm,
        "cm": [wire.mm_to_nm_int(frame.com_mm[0]), wire.mm_to_nm_int(frame.com_mm[1])],
        "Si": wire.scaled_int(frame.neuron_s, scale=wire.NEURAL_INT_SCALE),
        "Ri": wire.scaled_int(frame.neuron_r, scale=wire.NEURAL_INT_SCALE),
        "Bi": wire.scaled_int(frame.neuron_b, scale=wire.NEURAL_INT_SCALE),
        "Trefi": wire.scaled_int(frame.neuron_tref, scale=wire.NEURAL_INT_SCALE),
        "Fb": wire.pack_bits(frame.neuron_fired),
        "ja": wire.scaled_int(frame.joint_angles, scale=wire.JOINT_INT_SCALE),
        "jv": wire.scaled_int(frame.joint_velocities, scale=wire.JOINT_INT_SCALE),
        "tc": wire.scaled_int(frame.touch_forces, scale=wire.TOUCH_INT_SCALE),
        "ma": wire.scaled_int(frame.muscle_activations, scale=wire.MUSCLE_INT_SCALE),
        "nm01": [wire.wire_float(frame.neuromod[0]), wire.wire_float(frame.neuromod[1])],
        "fe": wire.wire_float(frame.free_energy),
    }
    if not frame.running:
        out["z"] = 1
    return out


def build_ws_router(app_ctx: AppContext, *, broadcast_hz: float = 60.0) -> APIRouter:
    router = APIRouter()
    interval = 1.0 / max(broadcast_hz, 1.0)

    @router.websocket("/ws/state")
    async def ws_state(ws: WebSocket) -> None:
        await ws.accept()
        try:
            hello = _hello_payload(app_ctx.runtime)
            await ws.send_text(json.dumps(hello, separators=(",", ":")))

            next_wake = time.monotonic()
            while True:
                next_wake += interval
                delay = next_wake - time.monotonic()
                if delay > 0:
                    try:
                        await asyncio.wait_for(ws.receive_text(), timeout=delay)
                    except asyncio.TimeoutError:
                        pass
                    except WebSocketDisconnect:
                        return
                while next_wake < time.monotonic():
                    next_wake += interval
                payload = _state_payload(app_ctx.runtime)
                if payload is None:
                    continue
                await ws.send_text(json.dumps(payload, separators=(",", ":")))
        except WebSocketDisconnect:
            return
        except Exception:
            logger.exception("WebSocket /ws/state handler crashed")

    return router

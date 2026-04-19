"""Entrypoint: ``celegans-lab-server``.

Starts a FastAPI app on ``localhost:8765`` with:
    GET  /api/health
    GET  /api/schema
    POST /api/patch
    GET  /api/connectome
    GET  /api/body
    GET  /api/neurons/{name}
    GET  /api/muscles/{muscle_name}
    GET  /api/sim/transport
    POST /api/sim/transport
    WS   /ws/state
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from lab.parameters import ParameterRegistry
from lab.parameters.body_params import register_body_specs
from lab.parameters.connectome_params import register_connectome_specs
from lab.parameters.mujoco_engine_params import register_mujoco_engine_specs
from lab.parameters.simulation_params import register_simulation_specs
from lab.rest_routes import AppContext, build_rest_router
from lab.sim_runtime import LabSimRuntime
from lab.ws_routes import build_ws_router


def _configure_logging(level: str = "INFO") -> None:
    """Single stderr sink; consistent with the demo server."""
    logger.remove()
    logger.add(
        sys.stderr,
        format="<green>{time:HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | {message}",
        level=level,
        colorize=True,
        filter=_stderr_filter,
    )


def _stderr_filter(record) -> bool:  # type: ignore[no-untyped-def]
    try:
        name = str(record["name"])
    except (KeyError, TypeError):
        return True
    if name.startswith("neuron."):
        try:
            return int(record["level"].no) >= 30
        except (KeyError, TypeError, AttributeError):
            return False
    return True


def build_app(
    *,
    body_settle_steps: int | None = None,
    evol_config: dict | None = None,
    broadcast_hz: float = 60.0,
    cors_origins: tuple[str, ...] = ("http://localhost:5173",),
) -> tuple[FastAPI, AppContext, threading.Thread]:
    runtime = LabSimRuntime(
        body_settle_steps=body_settle_steps,
        evol_config=evol_config,
    )
    registry = ParameterRegistry()
    register_simulation_specs(registry)
    register_mujoco_engine_specs(registry)
    register_body_specs(registry)
    register_connectome_specs(registry)

    ctx = AppContext(runtime, registry)
    sim_thread = threading.Thread(
        target=runtime.run_loop, name="lab-sim", daemon=True
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        sim_thread.start()
        # Wait for the first frame so clients connecting immediately get data.
        for _ in range(600):
            if runtime.has_frame():
                break
            time.sleep(0.05)
        if not runtime.has_frame():
            logger.warning("Sim did not produce a frame in time (continuing)")
        else:
            logger.info(
                "Lab sim ready (first tick={})",
                runtime.transport_snapshot()["tick"],
            )
        try:
            yield
        finally:
            runtime.stop()
            sim_thread.join(timeout=30.0)

    app = FastAPI(title="C. elegans Virtual Lab", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(cors_origins),
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=False,
    )
    app.include_router(build_rest_router(ctx))
    app.include_router(build_ws_router(ctx, broadcast_hz=broadcast_hz))
    return app, ctx, sim_thread


def main() -> None:
    parser = argparse.ArgumentParser(description="C. elegans virtual lab server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8811)
    parser.add_argument("--broadcast-hz", type=float, default=60.0)
    parser.add_argument("--body-settle-steps", type=int, default=None)
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR"),
    )
    parser.add_argument(
        "--cors-origin",
        action="append",
        default=None,
        help="Repeatable; default http://localhost:5173",
    )
    args = parser.parse_args()

    _configure_logging(args.log_level)
    logger.info("Building lab simulation…")
    origins = tuple(args.cors_origin) if args.cors_origin else ("http://localhost:5173",)
    app, _, _ = build_app(
        body_settle_steps=args.body_settle_steps,
        broadcast_hz=args.broadcast_hz,
        cors_origins=origins,
    )
    # neuron-model rewires loguru during PAULA build; restore our sink.
    _configure_logging(args.log_level)
    logger.info("Lab server listening on http://{}:{}", args.host, args.port)
    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level.lower())


if __name__ == "__main__":
    main()

"""
WebSocket server: one simulation thread (MuJoCo + PAULA), asyncio for I/O.

Run from repo: cd celegans-live-demo && uv run celegans-demo-server
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import queue
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

import numpy as np
from websockets.asyncio.server import ServerConnection, serve
from loguru import logger

from simulations.c_elegans.body import CElegansBody
from simulations.c_elegans.config import (
    BODY_RADIUS_M,
    ENV_PLATE_RADIUS_M,
    N_BODY_SEGMENTS,
)
from simulations.c_elegans.environment import AgarPlateEnvironment
from simulations.c_elegans.simulation import build_c_elegans_simulation

from celegans_live_demo.worm_snapshot import (
    load_evol_config_json,
    try_load_checkpoint,
    write_checkpoint_atomic,
)

# --- Compact WebSocket JSON protocol v2 (short keys) ---
# p  = protocol version (int)
# t  = message type: "h" hello, "s" state, "e" error, "o" pong (server→client)
#      client→server: "a" add_food, "v" remove_food, "i" ping
# State payload (t=="s"):
# k  = tick (simulation step)
# r  = plate_radius_mm
# w  = worm_radius_mm
# s  = segments_mm — list of 13 [x,y] in mm
# f  = food_mm — list of [x,y] in mm
# c  = com_mm — centre of mass [x,y] in mm (client builds trajectory locally)
# Hello: m = message (human hint)
# Error: m = message
# Client add/remove: x, y = position in mm
PROTOCOL_VERSION = 2
BROADCAST_HZ = 60.0
# Client display does not need float64 text; cap at 10 significant digits (~vs 16).
WIRE_FLOAT_SIG_DIGITS = 10
MAX_CLIENTS = 50
# Global command rate (add_food + remove_food) per rolling window
RATE_WINDOW_S = 5.0
RATE_MAX_COMMANDS = 60


def _stderr_sink_filter(record: Any) -> bool:
    """Drop PAULA per-tick chatter while honoring ``--log-level`` elsewhere.

    ``build_c_elegans_simulation(..., log_level="WARNING")`` passes that into
    ``Neuron(..., log_level=...)`` → ``setup_neuron_logger``, so the *global*
    loguru sink used to sit at WARNING and ``logger.debug`` inside neurons did
    not print. After we replace sinks, ``--log-level DEBUG`` would admit those
    DEBUG lines; cap ``neuron.*`` the same way the interactive sim does.
    Evolution uses ``log_level="ERROR"`` plus ``logger.add(..., level="ERROR")``
    for an even stricter ceiling.
    """
    try:
        name = str(record["name"])
    except (KeyError, TypeError):
        return True
    if name.startswith("neuron."):
        try:
            return int(record["level"].no) >= 30  # WARNING, ERROR, CRITICAL
        except (KeyError, TypeError, AttributeError):
            return False
    return True


def _configure_console_logging(level: str = "INFO") -> None:
    """Single stderr sink; readable timestamps for operator console.

    PAULA's ``neuron.setup_neuron_logger`` calls ``logger.remove()`` when neurons
    are constructed, which drops any earlier sinks. Call this again after the
    simulation (and network stack) are ready so demo server logs stay visible.

    The sink filter keeps ``neuron.*`` at WARNING+ so behaviour matches the
    default simulation build even when ``--log-level DEBUG``.
    """
    logger.remove()
    logger.add(
        sys.stderr,
        format="<green>{time:HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | {message}",
        level=level,
        colorize=True,
        filter=_stderr_sink_filter,
    )


def _ws_peer(ws: ServerConnection) -> str:
    try:
        addr = ws.remote_address
        if addr is None:
            return "?"
        return f"{addr[0]}:{addr[1]}"
    except Exception:
        return "?"


def _plate_radius_mm() -> float:
    return float(ENV_PLATE_RADIUS_M * 1000.0)


def _worm_radius_mm() -> float:
    return float(BODY_RADIUS_M * 1000.0)


def _wire_float(x: float) -> float:
    """Round for JSON wire format: WIRE_FLOAT_SIG_DIGITS significant digits."""
    xf = float(x)
    if not math.isfinite(xf):
        return xf
    return float(f"{xf:.{WIRE_FLOAT_SIG_DIGITS}g}")


def _quantize_wire_payload(obj: Any) -> Any:
    """Recursively trim floats for WebSocket state (ints and structure preserved)."""
    if isinstance(obj, float):
        return _wire_float(obj)
    if isinstance(obj, int) and not isinstance(obj, bool):
        return obj
    if isinstance(obj, list):
        return [_quantize_wire_payload(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _quantize_wire_payload(v) for k, v in obj.items()}
    return obj


class SimRuntime:
    """Owned exclusively by the simulation thread."""

    def __init__(
        self,
        *,
        body_settle_steps: int | None = None,
        evol_config: dict[str, Any] | None = None,
        snapshot_path: Path | None = None,
        snapshot_interval_s: float = 60.0,
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
        self._snapshot_path = snapshot_path
        self._snapshot_interval_s = float(snapshot_interval_s)
        self._last_disk_save = time.monotonic()
        if snapshot_path and try_load_checkpoint(self.engine, self.loop, snapshot_path):
            logger.info("Continuing worm from checkpoint {}", snapshot_path)
        else:
            self.loop.reset()
            if snapshot_path:
                logger.info(
                    "Fresh simulation start (checkpoint missing, invalid, or unloadable): {}",
                    snapshot_path,
                )
            else:
                logger.info("Fresh simulation start (no --snapshot-path)")
        self._cmd_queue: queue.SimpleQueue[dict[str, Any]] = queue.SimpleQueue()
        self._snapshot_lock = threading.Lock()
        self._latest: dict[str, Any] = {}
        self._running = threading.Event()
        self._running.set()

    def command_queue(self) -> queue.SimpleQueue[dict[str, Any]]:
        return self._cmd_queue

    def stop(self) -> None:
        self._running.clear()

    def _drain_commands(self) -> None:
        env = self.engine.environment
        if not isinstance(env, AgarPlateEnvironment):
            return
        while True:
            try:
                cmd = self._cmd_queue.get_nowait()
            except queue.Empty:
                break
            ctype = cmd.get("type")
            if ctype == "add_food":
                x_mm = float(cmd["x_mm"])
                y_mm = float(cmd["y_mm"])
                pos_m = np.array([x_mm / 1000.0, y_mm / 1000.0, 0.0])
                if env.is_on_plate(pos_m):
                    env.add_food((float(pos_m[0]), float(pos_m[1]), float(pos_m[2])))
                    logger.info(
                        "Food added at ({:.3f}, {:.3f}) mm ({} pellets)",
                        x_mm,
                        y_mm,
                        len(env.get_active_food_positions()),
                    )
                else:
                    logger.info(
                        "Food add rejected (off plate) at ({:.3f}, {:.3f}) mm",
                        x_mm,
                        y_mm,
                    )
            elif ctype == "remove_food":
                x_mm = float(cmd["x_mm"])
                y_mm = float(cmd["y_mm"])
                env.remove_food_near((x_mm / 1000.0, y_mm / 1000.0, 0.0))
                logger.info(
                    "Food remove near ({:.3f}, {:.3f}) mm ({} pellets)",
                    x_mm,
                    y_mm,
                    len(env.get_active_food_positions()),
                )

    def _build_snapshot(self) -> dict[str, Any]:
        step = self.engine.step()
        body = self.engine.body
        bs = step.body_state
        com = bs.position
        com_mm = [float(com[0] * 1000.0), float(com[1] * 1000.0)]

        segments_mm: list[list[float]] = []
        if isinstance(body, CElegansBody):
            shape = body.get_body_shape()
            for i in range(min(N_BODY_SEGMENTS, shape.shape[0])):
                segments_mm.append(
                    [float(shape[i, 0] * 1000.0), float(shape[i, 1] * 1000.0)]
                )
        else:
            hx, hy = float(com[0] * 1000.0), float(com[1] * 1000.0)
            segments_mm = [[hx, hy] for _ in range(N_BODY_SEGMENTS)]

        env = self.engine.environment
        food_mm: list[list[float]] = []
        if isinstance(env, AgarPlateEnvironment):
            for p in env.get_active_food_positions():
                food_mm.append([float(p[0] * 1000.0), float(p[1] * 1000.0)])

        return {
            "p": PROTOCOL_VERSION,
            "t": "s",
            "k": int(step.tick),
            "r": _plate_radius_mm(),
            "w": _worm_radius_mm(),
            "s": segments_mm,
            "f": food_mm,
            "c": com_mm,
        }

    def run_loop(self) -> None:
        try:
            while self._running.is_set():
                self._drain_commands()
                snap = self._build_snapshot()
                with self._snapshot_lock:
                    self._latest = snap
                if self._snapshot_path is not None:
                    now = time.monotonic()
                    if now - self._last_disk_save >= self._snapshot_interval_s:
                        try:
                            write_checkpoint_atomic(self.engine, self._snapshot_path)
                        except Exception:
                            logger.exception("Periodic worm checkpoint failed")
                        self._last_disk_save = now
        except Exception:
            logger.exception("Simulation thread crashed")
            self._running.clear()
            raise

    def get_snapshot(self) -> dict[str, Any]:
        with self._snapshot_lock:
            return dict(self._latest)

    def has_snapshot(self) -> bool:
        with self._snapshot_lock:
            return bool(self._latest)


def _sim_thread_main(rt: SimRuntime) -> None:
    rt.run_loop()


class RateLimiter:
    def __init__(self, window_s: float, max_events: int) -> None:
        self._window = window_s
        self._max = max_events
        self._times: deque[float] = deque()
        self._lock = threading.Lock()

    def allow(self) -> bool:
        now = time.monotonic()
        with self._lock:
            while self._times and self._times[0] < now - self._window:
                self._times.popleft()
            if len(self._times) >= self._max:
                return False
            self._times.append(now)
            return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="C. elegans live WebSocket demo server"
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bind address")
    parser.add_argument("--port", type=int, default=8765, help="WebSocket port")
    parser.add_argument(
        "--body-settle-steps",
        type=int,
        default=None,
        metavar="N",
        help="Override MuJoCo gravity-settle steps (default from model; lower e.g. 200 for quicker dev smoke)",
    )
    parser.add_argument(
        "--evol-config",
        type=str,
        default=None,
        metavar="PATH",
        help="Evolved neuromod / neuron_params JSON (checkpoint with config/best_config or flat dict)",
    )
    parser.add_argument(
        "--snapshot-path",
        type=str,
        default=None,
        metavar="PATH",
        help="Worm state JSON: load on startup if file exists; append periodic saves",
    )
    parser.add_argument(
        "--snapshot-interval-sec",
        type=float,
        default=60.0,
        metavar="SEC",
        help="How often to write --snapshot-path (default 60)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR"),
        help="Console log level (loguru)",
    )
    args = parser.parse_args()

    _configure_console_logging(args.log_level)

    evol = load_evol_config_json(args.evol_config)
    snap_path = Path(args.snapshot_path).expanduser() if args.snapshot_path else None

    logger.info(
        "Server config: host={} port={} broadcast_hz={} max_clients={} evol_config={} snapshot_path={} snapshot_interval_s={} body_settle_steps={}",
        args.host,
        args.port,
        BROADCAST_HZ,
        MAX_CLIENTS,
        args.evol_config or "(none)",
        str(snap_path) if snap_path else "(none)",
        args.snapshot_interval_sec,
        args.body_settle_steps,
    )
    logger.info("Building simulation (first run may download connectome) …")
    rt = SimRuntime(
        body_settle_steps=args.body_settle_steps,
        evol_config=evol,
        snapshot_path=snap_path,
        snapshot_interval_s=args.snapshot_interval_sec,
    )
    # neuron-model reconfigures loguru during PAULA build; restore our stderr sink.
    _configure_console_logging(args.log_level)
    sim_thread = threading.Thread(target=_sim_thread_main, args=(rt,), daemon=True)
    sim_thread.start()
    # Wait until first snapshot exists
    for _ in range(600):
        if rt.has_snapshot():
            break
        time.sleep(0.05)
    if not rt.has_snapshot():
        logger.error("Simulation did not produce a snapshot in time")
        raise SystemExit(1)
    tick0 = rt.get_snapshot().get("k")
    logger.info("Simulation stepping (first snapshot tick={})", tick0)

    clients: set[ServerConnection] = set()
    clients_lock = asyncio.Lock()
    cmd_limiter = RateLimiter(RATE_WINDOW_S, RATE_MAX_COMMANDS)

    async def register(ws: ServerConnection) -> bool:
        async with clients_lock:
            if len(clients) >= MAX_CLIENTS:
                return False
            clients.add(ws)
            return True

    async def unregister(ws: ServerConnection) -> None:
        peer = _ws_peer(ws)
        async with clients_lock:
            clients.discard(ws)
            n = len(clients)
        logger.info("WebSocket disconnected {} ({} clients remain)", peer, n)

    async def handler(ws: ServerConnection) -> None:
        peer = _ws_peer(ws)
        if not await register(ws):
            logger.warning(
                "WebSocket rejected {} (server full, max {})", peer, MAX_CLIENTS
            )
            await ws.close(1013, "Server full")
            return
        async with clients_lock:
            n = len(clients)
        logger.info("WebSocket connected {} ({} clients)", peer, n)
        try:
            await ws.send(
                json.dumps(
                    {
                        "p": PROTOCOL_VERSION,
                        "t": "h",
                        "m": "t=a|v|i  x,y mm  (add food, remove food, ping)",
                    }
                )
            )
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning("Invalid JSON from {} ({} bytes)", peer, len(raw))
                    await ws.send(
                        json.dumps(
                            {"p": PROTOCOL_VERSION, "t": "e", "m": "invalid JSON"}
                        )
                    )
                    continue
                if msg.get("p") != PROTOCOL_VERSION:
                    logger.warning(
                        "Unsupported protocol from {}: got p={!r}",
                        peer,
                        msg.get("p"),
                    )
                    await ws.send(
                        json.dumps(
                            {
                                "p": PROTOCOL_VERSION,
                                "t": "e",
                                "m": "unsupported protocol version",
                            }
                        )
                    )
                    continue
                mtype = msg.get("t")
                if mtype == "i":
                    logger.debug("Ping from {}", peer)
                    await ws.send(json.dumps({"p": PROTOCOL_VERSION, "t": "o"}))
                    continue
                if mtype == "a":
                    cmd_name = "add_food"
                elif mtype == "v":
                    cmd_name = "remove_food"
                else:
                    logger.warning("Unknown message type from {}: {!r}", peer, mtype)
                    await ws.send(
                        json.dumps(
                            {
                                "p": PROTOCOL_VERSION,
                                "t": "e",
                                "m": f"unknown t: {mtype!r}",
                            }
                        )
                    )
                    continue
                if mtype in ("a", "v"):
                    if not cmd_limiter.allow():
                        logger.warning(
                            "Food command rate limited for {} (max {} per {:.0f}s)",
                            peer,
                            RATE_MAX_COMMANDS,
                            RATE_WINDOW_S,
                        )
                        await ws.send(
                            json.dumps(
                                {"p": PROTOCOL_VERSION, "t": "e", "m": "rate limited"}
                            )
                        )
                        continue
                    try:
                        x_mm = float(msg["x"])
                        y_mm = float(msg["y"])
                        rt.command_queue().put(
                            {
                                "type": cmd_name,
                                "x_mm": x_mm,
                                "y_mm": y_mm,
                            }
                        )
                    except (KeyError, TypeError, ValueError):
                        logger.warning(
                            "Malformed food command from {} (expected x,y): {!r}",
                            peer,
                            msg,
                        )
                        await ws.send(
                            json.dumps(
                                {"p": PROTOCOL_VERSION, "t": "e", "m": "expected x,y"}
                            )
                        )
                    continue
        finally:
            await unregister(ws)

    # Per-client: slow send times out so we never block the 60 Hz cadence on one peer.
    broadcast_send_timeout_s = 0.05

    async def broadcast_loop() -> None:
        interval = 1.0 / BROADCAST_HZ
        next_wake = time.monotonic()
        while True:
            next_wake += interval
            delay = next_wake - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            # If we fell behind (slow sends / load), advance the schedule without emitting backlog.
            while next_wake < time.monotonic():
                next_wake += interval
            snap = rt.get_snapshot()
            if not snap:
                continue
            payload = json.dumps(_quantize_wire_payload(snap), separators=(",", ":"))
            async with clients_lock:
                snapshot_clients = list(clients)
            dead: list[ServerConnection] = []
            for c in snapshot_clients:
                try:
                    await asyncio.wait_for(
                        c.send(payload),
                        timeout=broadcast_send_timeout_s,
                    )
                except TimeoutError:
                    logger.debug(
                        "Broadcast send skipped (timeout {:.0f} ms) for {}",
                        broadcast_send_timeout_s * 1000,
                        _ws_peer(c),
                    )
                except Exception as exc:
                    logger.warning(
                        "Broadcast send failed for {}: {}: {}",
                        _ws_peer(c),
                        type(exc).__name__,
                        exc,
                    )
                    dead.append(c)
            for c in dead:
                async with clients_lock:
                    clients.discard(c)

    async def run() -> None:
        broadcast_task = asyncio.create_task(broadcast_loop())
        try:
            # In case any import-time code touched loguru before the event loop ran.
            _configure_console_logging(args.log_level)
            async with serve(handler, args.host, args.port):
                logger.info(
                    "WebSocket listening ws://{}:{} (protocol v{})",
                    args.host,
                    args.port,
                    PROTOCOL_VERSION,
                )
                await asyncio.Future()
        finally:
            broadcast_task.cancel()
            try:
                await broadcast_task
            except asyncio.CancelledError:
                pass

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        rt.stop()
        logger.info("Shutdown requested")


if __name__ == "__main__":
    main()

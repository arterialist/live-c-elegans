"""
WebSocket server: one simulation thread (MuJoCo + PAULA), asyncio for I/O.

Run from repo: cd celegans-live-demo && uv run celegans-demo-server
"""

from __future__ import annotations

import argparse
import asyncio
import base64
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
from websockets.datastructures import Headers
from loguru import logger

from simulations.c_elegans.body import CElegansBody
from simulations.c_elegans.config import (
    BODY_RADIUS_M,
    ENV_PLATE_RADIUS_M,
    N_BODY_SEGMENTS,
)
from simulations.c_elegans.environment import AgarPlateEnvironment
from simulations.c_elegans.neuron_mapping import CElegansNervousSystem
from simulations.c_elegans.simulation import build_c_elegans_simulation

from celegans_live_demo.connectome_layout import side_view_layout_normalized
from celegans_live_demo.worm_snapshot import (
    load_evol_config_json,
    try_load_checkpoint,
    write_checkpoint_atomic,
)

# --- Compact WebSocket JSON protocol v2 (short keys) ---
# p  = protocol version (int)
# t  = message type: "h" hello, "s" state, "e" error, "o" pong, "u" presence (server→client)
#      Food events (separate JSON frames after "s", same p): "fa" add, "fr" remove, "fe" eaten
#      n = pellet count since last broadcast (aggregated across sim ticks in that window)
#      client→server: "a" add_food, "v" remove_food, "i" ping
# Presence (t=="u"): n = concurrent WebSocket client count
# State payload (t=="s") — simulation only (no food action attribution):
# k  = tick (simulation step)
# r  = plate_radius_mm
# w  = worm_radius_mm
# s  = segments_mm — list of 13 [x,y] in mm
# f  = food_mm — list of [x,y] in mm
# c  = com_mm — centre of mass [x,y] in mm (client builds trajectory locally)
# S  = membrane (PAULA S) per paula_id, 4 decimal places; F = 0/1 fired (O>0)
# R  = dynamic primary threshold r (same units as S), 4 decimals — for per-neuron UI scaling
# Hello optional L = {nm, ax, ay} static layout (Cook order AP + name D/V proxy)
# Hello optional M = parallel list to nm: {k,ic,ig,oc,og} Cook connectome metadata
#   k = neuron class: s sensory, m motor, i interneuron, u unknown
#   ic,ig,oc,og = in/out chemical & gap-junction degree (synapse counts in Cook data)
# Hello: m = message (human hint)
# Error: m = message
# Client add/remove: x, y = position in mm
#
# Protocol v3 (compact state):
#   sm = segments — flattened [x,y,…] in nanometres as int (round(mm * 1e6)); length 2 * N_BODY_SEGMENTS
#   fm = food — flattened pairs in nm (round(mm * 1e6)); length 2 * n_food
#   cm = centre of mass [cx_nm, cy_nm] ints (same scale as sm)
#   Si, Ri = membrane S and threshold R: int = round(float * 1e4) (client ÷ 1e4)
#   Fb = ceil(n/8) base64, bit i = neuron i fired (1) or not (0)
PROTOCOL_VERSION = 3
BROADCAST_HZ = 60.0
# Client display does not need float64 text; cap at 10 significant digits (~vs 16).
WIRE_FLOAT_SIG_DIGITS = 10
# Spine `s` (segments_mm): tighter payload; 6 significant figures is enough at ~mm scale.
WIRE_SEGMENT_SIG_DIGITS = 6
MAX_CLIENTS = 50
# Global command rate (add_food + remove_food) per rolling window
RATE_WINDOW_S = 5.0
RATE_MAX_COMMANDS = 60

_NEURON_KIND_WIRE = {"sensory": "s", "motor": "m", "interneuron": "i", "unknown": "u"}


def _wire_neuron_meta_list(ns: CElegansNervousSystem) -> list[dict[str, Any]]:
    """Compact per-neuron facts from :class:`ConnectomeData` (Cook order = PAULA id order)."""
    names = ns.get_neuron_names_paula_order()
    nm_to = ns._connectome.name_to_info
    out: list[dict[str, Any]] = []
    for name in names:
        info = nm_to.get(name)
        if info is None:
            out.append({"k": "u", "ic": 0, "ig": 0, "oc": 0, "og": 0})
            continue
        k = _NEURON_KIND_WIRE.get(info.neuron_type, "u")
        out.append(
            {
                "k": k,
                "ic": int(info.in_degree_chem),
                "ig": int(info.in_degree_gap),
                "oc": int(info.out_degree_chem),
                "og": int(info.out_degree_gap),
            }
        )
    return out


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


def _headers_first_line(headers: Headers, name: str) -> str | None:
    """First header line for ``name`` (case-insensitive), stripped, or None."""
    vals = headers.get_all(name)
    if not vals:
        return None
    v = vals[0].strip()
    return v or None


def _xff_leftmost_host(value: str) -> str | None:
    """Leftmost host in an ``X-Forwarded-For`` chain (first client hop)."""
    first = value.split(",")[0].strip()
    if not first:
        return None
    if len(first) >= 2 and first[0] == '"' and first[-1] == '"':
        first = first[1:-1].strip()
    if first.startswith("["):
        end = first.find("]")
        if end != -1:
            inner = first[1:end].strip()
            return inner or None
    # Possible "IPv4:port" (uncommon in XFF)
    if first.count(":") == 1 and "." in first:
        host, _, maybe_port = first.rpartition(":")
        if maybe_port.isdigit():
            return host
    return first


def _forwarded_client_ip(headers: Headers) -> tuple[str | None, str | None]:
    """Best-effort original client IP from proxy headers.

    Returns ``(ip, header_name)`` when a trusted-style header is present;
    otherwise ``(None, None)``. Precedence: CF-Connecting-IP, True-Client-IP,
    X-Real-IP, then leftmost hop of X-Forwarded-For.
    """
    for hdr in ("CF-Connecting-IP", "True-Client-IP", "X-Real-IP"):
        raw = _headers_first_line(headers, hdr)
        if not raw:
            continue
        ip = raw.split(",")[0].strip()
        if ip:
            return ip, hdr
    xff = _headers_first_line(headers, "X-Forwarded-For")
    if xff:
        ip = _xff_leftmost_host(xff)
        if ip:
            return ip, "X-Forwarded-For"
    return None, None


def _client_log_label(ws: ServerConnection) -> str:
    """Stable id + effective client IP (from forward headers when present) + TCP peer."""
    remote = _ws_peer(ws)
    cid = str(ws.id)
    req = ws.request
    if req is None:
        return f"{cid} (remote {remote})"
    fwd_ip, via = _forwarded_client_ip(req.headers)
    if fwd_ip and via:
        return f"{cid} client_ip={fwd_ip} (via {via}; remote {remote})"
    return f"{cid} (remote {remote})"


def _plate_radius_mm() -> float:
    return float(ENV_PLATE_RADIUS_M * 1000.0)


def _worm_radius_mm() -> float:
    return float(BODY_RADIUS_M * 1000.0)


def _wire_float(x: float, *, sig_digits: int = WIRE_FLOAT_SIG_DIGITS) -> float:
    """Round for JSON wire format to ``sig_digits`` significant figures."""
    xf = float(x)
    if not math.isfinite(xf):
        return xf
    return float(f"{xf:.{sig_digits}g}")


def _quantize_wire_payload(
    obj: Any, *, float_sig_digits: int = WIRE_FLOAT_SIG_DIGITS
) -> Any:
    """Recursively trim floats for WebSocket state (ints and structure preserved)."""
    if isinstance(obj, float):
        return _wire_float(obj, sig_digits=float_sig_digits)
    if isinstance(obj, int) and not isinstance(obj, bool):
        return obj
    if isinstance(obj, list):
        return [
            _quantize_wire_payload(v, float_sig_digits=float_sig_digits) for v in obj
        ]
    if isinstance(obj, dict):
        return {
            k: _quantize_wire_payload(v, float_sig_digits=float_sig_digits)
            for k, v in obj.items()
        }
    return obj


def _quantize_snapshot_for_wire(snap: dict[str, Any]) -> dict[str, Any]:
    """Like :func:`_quantize_wire_payload` but ``S`` stays 4-decimal; ``s`` uses segment sigfigs."""
    out: dict[str, Any] = {}
    for k, v in snap.items():
        if k == "S" or k == "R":
            out[k] = v
        elif k == "s":
            out[k] = _quantize_wire_payload(v, float_sig_digits=WIRE_SEGMENT_SIG_DIGITS)
        else:
            out[k] = _quantize_wire_payload(v)
    return out


def _scaled_int_wire(values: list[float], *, scale: float = 1e4) -> list[int]:
    """Fixed-scale integers for JSON (smaller than long float text; compresses well)."""
    return [int(round(float(x) * scale)) for x in values]


def _mm_to_nm_int(mm: float) -> int:
    """1 nm resolution from mm (matches 6 sigfig wire for segment coords)."""
    return int(round(float(mm) * 1e6))


def _b64_fired_bits(fired: list[int]) -> str:
    """Pack 0/1 per neuron into bytes; bit ``i`` is ``fired[i]`` (LSB-first within each byte)."""
    if not fired:
        return ""
    n = len(fired)
    n_bytes = (n + 7) // 8
    buf = bytearray(n_bytes)
    for i, v in enumerate(fired):
        if v:
            buf[i >> 3] |= 1 << (i & 7)
    return base64.b64encode(bytes(buf)).decode("ascii")


def _snapshot_dict_to_wire(snap: dict[str, Any]) -> dict[str, Any]:
    """Quantize floats, then replace dense arrays with compact v3 wire fields."""
    q = _quantize_snapshot_for_wire(snap)
    out: dict[str, Any] = {
        k: v for k, v in q.items() if k not in ("s", "f", "c", "S", "F", "R")
    }
    if "s" in q:
        sm: list[int] = []
        for row in q["s"]:
            sm.extend([_mm_to_nm_int(row[0]), _mm_to_nm_int(row[1])])
        out["sm"] = sm
    if "f" in q:
        fm: list[int] = []
        for row in q["f"]:
            fm.extend([_mm_to_nm_int(row[0]), _mm_to_nm_int(row[1])])
        out["fm"] = fm
    if "c" in q:
        c = q["c"]
        out["cm"] = [_mm_to_nm_int(c[0]), _mm_to_nm_int(c[1])]
    if "S" in q and "R" in q and "F" in q:
        s_list = [float(x) for x in q["S"]]
        r_list = [float(x) for x in q["R"]]
        f_list = [int(x) for x in q["F"]]
        if len(s_list) != len(r_list) or len(s_list) != len(f_list):
            raise RuntimeError("S / R / F length mismatch in snapshot")
        out["Si"] = _scaled_int_wire(s_list)
        out["Ri"] = _scaled_int_wire(r_list)
        out["Fb"] = _b64_fired_bits(f_list)
    return out


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
        self._neural_static: dict[str, Any] | None = None
        self._neuron_meta: list[dict[str, Any]] | None = None
        ns0 = self.engine.nervous_system
        if isinstance(ns0, CElegansNervousSystem):
            names = ns0.get_neuron_names_paula_order()
            ax, ay = side_view_layout_normalized(names)
            self._neural_static = {"nm": names, "ax": ax, "ay": ay}
            self._neuron_meta = _wire_neuron_meta_list(ns0)
        # Counts reset each sim tick in run_loop before draining the command queue.
        self._food_cmd_add = 0
        self._food_cmd_remove = 0
        # Aggregated for take_latest_for_broadcast (sim may outpace BROADCAST_HZ).
        self._food_evt_accum_fr = 0
        self._food_evt_accum_fe = 0
        self._food_evt_accum_fa = 0
        self._n_pre_food_for_tick = 0

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
            client = str(cmd.get("client") or "unknown")
            if ctype == "add_food":
                x_mm = float(cmd["x_mm"])
                y_mm = float(cmd["y_mm"])
                pos_m = np.array([x_mm / 1000.0, y_mm / 1000.0, 0.0])
                if env.is_on_plate(pos_m):
                    env.add_food((float(pos_m[0]), float(pos_m[1]), float(pos_m[2])))
                    self._food_cmd_add += 1
                    logger.info(
                        "Food added by {} at ({:.3f}, {:.3f}) mm ({} pellets)",
                        client,
                        x_mm,
                        y_mm,
                        len(env.get_active_food_positions()),
                    )
                else:
                    logger.info(
                        "Food add rejected (off plate) by {} at ({:.3f}, {:.3f}) mm",
                        client,
                        x_mm,
                        y_mm,
                    )
            elif ctype == "remove_food":
                x_mm = float(cmd["x_mm"])
                y_mm = float(cmd["y_mm"])
                removed = env.remove_food_near((x_mm / 1000.0, y_mm / 1000.0, 0.0))
                if removed:
                    self._food_cmd_remove += 1
                    logger.info(
                        "Food removed by {} near ({:.3f}, {:.3f}) mm ({} pellets)",
                        client,
                        x_mm,
                        y_mm,
                        len(env.get_active_food_positions()),
                    )
                else:
                    logger.info(
                        "Food remove by {} near ({:.3f}, {:.3f}) mm — no pellet in range ({} pellets)",
                        client,
                        x_mm,
                        y_mm,
                        len(env.get_active_food_positions()),
                    )

    def _build_snapshot(self) -> dict[str, Any]:
        env0 = self.engine.environment
        n_pre_food = 0
        if isinstance(env0, AgarPlateEnvironment):
            n_pre_food = len(env0.get_active_food_positions())
        self._n_pre_food_for_tick = n_pre_food

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

        out: dict[str, Any] = {
            "p": PROTOCOL_VERSION,
            "t": "s",
            "k": int(step.tick),
            "r": _plate_radius_mm(),
            "w": _worm_radius_mm(),
            "s": segments_mm,
            "f": food_mm,
            "c": com_mm,
        }
        ns = self.engine.nervous_system
        if isinstance(ns, CElegansNervousSystem):
            s_raw, f_raw, r_raw = ns.get_compact_neural_snapshot()
            out["S"] = [round(float(x), 4) for x in s_raw]
            out["F"] = [int(x) for x in f_raw]
            out["R"] = [round(float(x), 4) for x in r_raw]
        return out

    def _food_evt_triplet_this_tick(self) -> tuple[int, int, int]:
        """(manual_removes, eaten, manual_adds) for this sim tick on agar; else zeros."""
        env = self.engine.environment
        if not isinstance(env, AgarPlateEnvironment):
            return (0, 0, 0)
        n_post = len(env.get_active_food_positions())
        eaten = max(0, int(self._n_pre_food_for_tick) - n_post)
        return (int(self._food_cmd_remove), eaten, int(self._food_cmd_add))

    def run_loop(self) -> None:
        try:
            while self._running.is_set():
                self._food_cmd_add = 0
                self._food_cmd_remove = 0
                self._drain_commands()
                snap = self._build_snapshot()
                fr, fe, fa = self._food_evt_triplet_this_tick()
                if fe:
                    logger.info(
                        "Worm ate {} pellet(s) (tick {})",
                        fe,
                        snap.get("k"),
                    )
                with self._snapshot_lock:
                    self._latest = snap
                    self._food_evt_accum_fr += fr
                    self._food_evt_accum_fe += fe
                    self._food_evt_accum_fa += fa
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
        if self._snapshot_path is not None:
            try:
                self._drain_commands()
                write_checkpoint_atomic(self.engine, self._snapshot_path)
            except Exception:
                logger.exception("Shutdown worm checkpoint failed")

    def get_snapshot(self) -> dict[str, Any]:
        with self._snapshot_lock:
            return dict(self._latest)

    def take_latest_for_broadcast(
        self,
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        """Atomically copy latest state and drain aggregated food events (fa/fr/fe)."""
        with self._snapshot_lock:
            if not self._latest:
                return None, []
            snap = dict(self._latest)
            events: list[dict[str, Any]] = []
            if self._food_evt_accum_fr:
                events.append(
                    {
                        "p": PROTOCOL_VERSION,
                        "t": "fr",
                        "n": int(self._food_evt_accum_fr),
                    }
                )
                self._food_evt_accum_fr = 0
            if self._food_evt_accum_fe:
                events.append(
                    {
                        "p": PROTOCOL_VERSION,
                        "t": "fe",
                        "n": int(self._food_evt_accum_fe),
                    }
                )
                self._food_evt_accum_fe = 0
            if self._food_evt_accum_fa:
                events.append(
                    {
                        "p": PROTOCOL_VERSION,
                        "t": "fa",
                        "n": int(self._food_evt_accum_fa),
                    }
                )
                self._food_evt_accum_fa = 0
            return snap, events

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
    broadcast_send_timeout_s = 0.05

    async def broadcast_online_count() -> None:
        """Notify all clients of current connection count (drops dead peers, retries)."""
        for _ in range(MAX_CLIENTS + 2):
            async with clients_lock:
                n_online = len(clients)
                payload = json.dumps(
                    {"p": PROTOCOL_VERSION, "t": "u", "n": n_online},
                    separators=(",", ":"),
                )
                snapshot = list(clients)
            if not snapshot:
                return
            dead: list[ServerConnection] = []
            for c in snapshot:
                try:
                    await asyncio.wait_for(
                        c.send(payload),
                        timeout=broadcast_send_timeout_s,
                    )
                except TimeoutError:
                    logger.debug(
                        "Presence send skipped (timeout {:.0f} ms) for {}",
                        broadcast_send_timeout_s * 1000,
                        _client_log_label(c),
                    )
                except Exception:
                    dead.append(c)
            if not dead:
                return
            async with clients_lock:
                for c in dead:
                    clients.discard(c)

    async def register(ws: ServerConnection) -> bool:
        async with clients_lock:
            if len(clients) >= MAX_CLIENTS:
                return False
            clients.add(ws)
            return True

    async def unregister(ws: ServerConnection) -> None:
        client = _client_log_label(ws)
        async with clients_lock:
            clients.discard(ws)
            n = len(clients)
        logger.info("Client disconnected: {} ({} clients remain)", client, n)
        await broadcast_online_count()

    async def handler(ws: ServerConnection) -> None:
        if not await register(ws):
            logger.warning(
                "Client connection rejected (server full, max {}): {}",
                MAX_CLIENTS,
                _client_log_label(ws),
            )
            await ws.close(1013, "Server full")
            return
        client = _client_log_label(ws)
        async with clients_lock:
            n = len(clients)
        logger.info("Client connected: {} ({} clients)", client, n)
        try:
            hello: dict[str, Any] = {
                "p": PROTOCOL_VERSION,
                "t": "h",
                "m": "v3 t=s: sm,fm,cm nm; Si,Ri÷1e4; Fb bits; t=a|v|i; fa|fr|fe",
            }
            if rt._neural_static is not None:
                hello["L"] = rt._neural_static
            if rt._neuron_meta is not None:
                hello["M"] = rt._neuron_meta
            await ws.send(json.dumps(hello, separators=(",", ":")))
            await broadcast_online_count()
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning("Invalid JSON from {} ({} bytes)", client, len(raw))
                    await ws.send(
                        json.dumps(
                            {"p": PROTOCOL_VERSION, "t": "e", "m": "invalid JSON"}
                        )
                    )
                    continue
                if msg.get("p") != PROTOCOL_VERSION:
                    logger.warning(
                        "Unsupported protocol from {}: got p={!r}",
                        client,
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
                    logger.debug("Ping from {}", client)
                    await ws.send(json.dumps({"p": PROTOCOL_VERSION, "t": "o"}))
                    continue
                if mtype == "a":
                    cmd_name = "add_food"
                elif mtype == "v":
                    cmd_name = "remove_food"
                else:
                    logger.warning("Unknown message type from {}: {!r}", client, mtype)
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
                            client,
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
                                "client": client,
                            }
                        )
                    except (KeyError, TypeError, ValueError):
                        logger.warning(
                            "Malformed food command from {} (expected x,y): {!r}",
                            client,
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
            snap, food_events = rt.take_latest_for_broadcast()
            if not snap:
                continue
            payload = json.dumps(_snapshot_dict_to_wire(snap), separators=(",", ":"))
            food_payloads = [
                json.dumps(ev, separators=(",", ":")) for ev in food_events
            ]
            async with clients_lock:
                snapshot_clients = list(clients)
            dead: list[ServerConnection] = []
            for c in snapshot_clients:
                try:
                    await asyncio.wait_for(
                        c.send(payload),
                        timeout=broadcast_send_timeout_s,
                    )
                    for fp in food_payloads:
                        await asyncio.wait_for(
                            c.send(fp),
                            timeout=broadcast_send_timeout_s,
                        )
                except TimeoutError:
                    logger.debug(
                        "Broadcast send skipped (timeout {:.0f} ms) for {}",
                        broadcast_send_timeout_s * 1000,
                        _client_log_label(c),
                    )
                except Exception as exc:
                    logger.warning(
                        "Broadcast send failed for {}: {}: {}",
                        _client_log_label(c),
                        type(exc).__name__,
                        exc,
                    )
                    dead.append(c)
            for c in dead:
                async with clients_lock:
                    clients.discard(c)
            if dead:
                await broadcast_online_count()

    async def run() -> None:
        broadcast_task = asyncio.create_task(broadcast_loop())
        try:
            # In case any import-time code touched loguru before the event loop ran.
            _configure_console_logging(args.log_level)
            async with serve(
                handler,
                args.host,
                args.port,
                compression="deflate",
            ):
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
        logger.info("Shutdown requested")
    finally:
        rt.stop()
        sim_thread.join(timeout=120.0)
        if sim_thread.is_alive():
            logger.warning(
                "Simulation thread still running after {:.0f}s (shutdown checkpoint may be incomplete)",
                120.0,
            )


if __name__ == "__main__":
    main()

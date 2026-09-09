"""Shared HTTP + WebSocket helpers for virtual-lab analysis scripts.

Environment (optional; defaults match ``celegans-lab-server``):

* ``CELEGANS_LAB_REST`` — REST base, e.g. ``http://127.0.0.1:8811``
* ``CELEGANS_LAB_WS`` — state WebSocket URL, e.g. ``ws://127.0.0.1:8811/ws/state``
"""
from __future__ import annotations

import base64
import json
import os
import urllib.request
from typing import Any

import numpy as np

LAB_REST = os.environ.get("CELEGANS_LAB_REST", "http://127.0.0.1:8811").rstrip("/")


def _default_ws_for_rest(rest: str) -> str:
    if rest.startswith("https://"):
        return "wss://" + rest[len("https://") :] + "/ws/state"
    if rest.startswith("http://"):
        return "ws://" + rest[len("http://") :] + "/ws/state"
    return rest + "/ws/state"


LAB_WS = os.environ.get("CELEGANS_LAB_WS", _default_ws_for_rest(LAB_REST))


def post_json(path: str, body: dict[str, Any], *, timeout: float = 20.0) -> Any:
    req = urllib.request.Request(
        f"{LAB_REST}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def get_json(path: str, *, timeout: float = 20.0) -> Any:
    req = urllib.request.Request(f"{LAB_REST}{path}")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def unpack_bits(b64: str, n: int) -> np.ndarray:
    """Decode base64-packed neuron firing bitmap to ``uint8`` length ``n``."""
    if not b64:
        return np.zeros(n, dtype=np.uint8)
    raw = base64.b64decode(b64)
    out = np.zeros(n, dtype=np.uint8)
    for i in range(n):
        if raw[i >> 3] & (1 << (i & 7)):
            out[i] = 1
    return out

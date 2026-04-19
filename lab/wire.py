"""Compact wire encoding helpers for the lab WebSocket stream.

Kept separate from the demo server's inline helpers so the lab can evolve the
wire format independently (adds ``Bi``, ``Trefi``, ``ja``, ``jv``, ``tc``,
``ma``, ``nm01``, ``M0i``, ``M1i`` per-neuron M_vector components, ``fe``,
``z``) while reusing the same quantization rules.
"""

from __future__ import annotations

import base64
import math
from typing import Any, Iterable

PROTOCOL_VERSION = 6
WIRE_FLOAT_SIG_DIGITS = 10
WIRE_SEGMENT_SIG_DIGITS = 6
NEURAL_INT_SCALE = 1e4
JOINT_INT_SCALE = 1e4
MUSCLE_INT_SCALE = 1e4
TOUCH_INT_SCALE = 1e6


def wire_float(x: float, *, sig_digits: int = WIRE_FLOAT_SIG_DIGITS) -> float:
    xf = float(x)
    if not math.isfinite(xf):
        return xf
    return float(f"{xf:.{sig_digits}g}")


def scaled_int(values: Iterable[float], *, scale: float = NEURAL_INT_SCALE) -> list[int]:
    return [int(round(float(x) * scale)) for x in values]


def mm_to_nm_int(mm: float) -> int:
    return int(round(float(mm) * 1e6))


def pack_bits(flags: list[int]) -> str:
    if not flags:
        return ""
    n = len(flags)
    buf = bytearray((n + 7) // 8)
    for i, v in enumerate(flags):
        if v:
            buf[i >> 3] |= 1 << (i & 7)
    return base64.b64encode(bytes(buf)).decode("ascii")


def quantize(obj: Any, *, sig_digits: int = WIRE_FLOAT_SIG_DIGITS) -> Any:
    if isinstance(obj, float):
        return wire_float(obj, sig_digits=sig_digits)
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, (list, tuple)):
        return [quantize(v, sig_digits=sig_digits) for v in obj]
    if isinstance(obj, dict):
        return {k: quantize(v, sig_digits=sig_digits) for k, v in obj.items()}
    return obj

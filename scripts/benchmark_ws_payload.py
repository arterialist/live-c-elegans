#!/usr/bin/env python3
"""Compare WebSocket state JSON size: legacy dense arrays vs v3 base64 compaction.

Run from ``celegans-live-demo``::

    uv run python scripts/benchmark_ws_payload.py

Optional: pass a captured v2 JSON file (single object with ``t``==``s``)::

    uv run python scripts/benchmark_ws_payload.py /path/to/state.json

Uses the same helpers as :mod:`celegans_live_demo.server`. ``zlib`` size is a
rough proxy for ``permessage-deflate`` savings (actual WebSocket compression
uses raw deflate without zlib headers; ratios are comparable).
"""

from __future__ import annotations

import json
import argparse
import zlib
from pathlib import Path
from typing import Any

from celegans_live_demo.server import (
    PROTOCOL_VERSION,
    _snapshot_dict_to_wire,
    _quantize_snapshot_for_wire,
)


def _synthetic_v2_snapshot() -> dict[str, Any]:
    """Roughly match a live 60 Hz frame (302 neurons, 13 segments, ~17 food)."""
    n_n = 302
    n_seg = 13
    n_food = 17
    return {
        "p": 2,
        "t": "s",
        "k": 4_701_602,
        "r": 50.0,
        "w": 0.04,
        "s": [[11.1041 + 0.001 * i, -1.21938 - 0.01 * i] for i in range(n_seg)],
        "f": [[21.0 + 0.1 * i, 1.2 - 0.05 * i] for i in range(n_food)],
        "c": [11.10411435, -1.219376956],
        "S": [
            round(0.0001 * (i * 17 % 1000) + 0.0001 * (i % 7), 4) for i in range(n_n)
        ],
        "F": [1 if i % 47 == 0 or i % 113 == 1 else 0 for i in range(n_n)],
        "R": [round(0.5 + 0.001 * (i % 40), 4) for i in range(n_n)],
    }


def _dumps_compact(obj: dict[str, Any]) -> str:
    return json.dumps(obj, separators=(",", ":"))


def _zlib_bytes(s: str) -> bytes:
    return zlib.compress(s.encode("utf-8"), level=6)


def payloads(raw: dict[str, Any]) -> tuple[str, str]:
    """Encode the same legacy state through the current server helpers."""
    if not isinstance(raw, dict) or raw.get("t") != "s":
        raise ValueError("expected a legacy state JSON object with t='s'")
    required = {"s", "f", "c", "S", "F", "R"}
    missing = required.difference(raw)
    if missing:
        raise ValueError(f"missing legacy state fields: {', '.join(sorted(missing))}")

    # Legacy path: quantized JSON arrays only (what v2 sent after quantization).
    legacy = _quantize_snapshot_for_wire(
        {k: v for k, v in raw.items() if k not in ("p", "t")}
    )
    legacy_full = {"p": raw.get("p", 3), "t": "s", **legacy}
    wire_legacy = _dumps_compact(legacy_full)

    compact = _snapshot_dict_to_wire(
        {k: v for k, v in raw.items() if k not in ("p", "t")}
    )
    compact_full = {"p": PROTOCOL_VERSION, "t": "s", **compact}
    wire_compact = _dumps_compact(compact_full)
    return wire_legacy, wire_compact


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", nargs="?", type=Path, help="captured legacy state JSON")
    args = parser.parse_args()
    try:
        raw = (
            json.loads(args.capture.expanduser().read_text(encoding="utf-8"))
            if args.capture else _synthetic_v2_snapshot()
        )
        wire_legacy, wire_compact = payloads(raw)
    except (OSError, ValueError, TypeError) as exc:
        parser.error(str(exc))

    z_legacy = _zlib_bytes(wire_legacy)
    z_compact = _zlib_bytes(wire_compact)

    n_legacy = len(wire_legacy.encode("utf-8"))
    n_compact = len(wire_compact.encode("utf-8"))
    ratio = n_compact / max(n_legacy, 1)
    z_ratio = len(z_compact) / max(len(z_legacy), 1)

    print("WebSocket state payload benchmark (UTF-8 byte lengths)")
    print(f"  Legacy JSON (quantized arrays):     {n_legacy:6d} B")
    print(
        f"  v3 compact (sm,fm,cm,Si,Ri,Fb):     {n_compact:6d} B  ({ratio:.2%} of legacy)"
    )
    print(f"  zlib(level=6) legacy:               {len(z_legacy):6d} B")
    print(
        f"  zlib(level=6) v3:                   {len(z_compact):6d} B  ({z_ratio:.2%} of zlib legacy)"
    )
    print()
    hz = 60.0
    sec_per_month = 30 * 24 * 3600
    frames = sec_per_month * hz
    print(
        "Rough monthly egress at 60 Hz, one viewer (single direction, state frames only):"
    )
    print("  Payload-only estimate; excludes transport headers and does not measure simulation speed.")
    print(f"  Legacy JSON:     {frames * n_legacy / 1e9:.2f} GB")
    print(f"  v3 JSON:         {frames * n_compact / 1e9:.2f} GB")
    print(f"  zlib legacy:     {frames * len(z_legacy) / 1e9:.2f} GB")
    print(f"  zlib v3:         {frames * len(z_compact) / 1e9:.2f} GB")


if __name__ == "__main__":
    main()

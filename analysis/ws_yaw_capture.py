"""Capture WS state with focus on yaw joint dynamics & DB/VB drive over time."""

from __future__ import annotations

import asyncio
import json
import sys

import websockets

from analysis.lib.lab_client import LAB_WS as URL

SECONDS = float(sys.argv[1]) if len(sys.argv) > 1 else 8.0


async def main() -> None:
    async with websockets.connect(URL, max_size=2**24) as ws:
        hello = json.loads(await ws.recv())
        names = hello["L"]["nm"]
        joints = hello["L_body"]["joints"]
        # find idx of yaws
        yaw_idx = [i for i, jn in enumerate(joints) if "yaw" in jn]
        yaw_names = [joints[i] for i in yaw_idx]
        # idx of DB1, VB1
        db1 = names.index("DB1") if "DB1" in names else -1
        vb1 = names.index("VB1") if "VB1" in names else -1

        deadline = asyncio.get_event_loop().time() + SECONDS
        first_tick = None
        rows: list[tuple[int, float, float, list[float], list[float]]] = []
        while asyncio.get_event_loop().time() < deadline:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
            except asyncio.TimeoutError:
                break
            d = json.loads(msg)
            if d.get("t") != "s":
                continue
            tick = d.get("k", 0)
            if first_tick is None:
                first_tick = tick
            ja = [v / 1e4 for v in d.get("ja", [])]
            ma = [v / 1e4 for v in d.get("ma", [])]
            Si = d.get("Si", [])
            db_s = (Si[db1] / 1e4) if 0 <= db1 < len(Si) else 0.0
            vb_s = (Si[vb1] / 1e4) if 0 <= vb1 < len(Si) else 0.0
            rows.append((tick, db_s, vb_s, ja, ma))

        if not rows:
            print("no frames")
            return

        n = len(rows)
        print(f"captured {n} frames (ticks {rows[0][0]}..{rows[-1][0]})")
        print(f"\nyaw joint trajectory (every ~50 frames):")
        sampled = [rows[i] for i in range(0, n, max(1, n // 20))]
        header = "tick   DB1.S   VB1.S  | " + "  ".join(f"{nm[:6]:>6s}" for nm in yaw_names) + "  | seg1_DL seg1_VL"
        print(header)
        for tick, db_s, vb_s, ja, ma in sampled:
            yaws = [ja[i] for i in yaw_idx]
            seg1_dl = ma[0] if len(ma) > 0 else 0.0  # muscle_seg1_DL
            seg1_vl = ma[2] if len(ma) > 2 else 0.0  # muscle_seg1_VL
            yaw_str = "  ".join(f"{y:+.3f}" for y in yaws)
            print(f"{tick:6d} {db_s:+.3f} {vb_s:+.3f}  | {yaw_str}  | {seg1_dl:.3f}  {seg1_vl:.3f}")


if __name__ == "__main__":
    asyncio.run(main())

"""Capture lab WS state for ~N seconds and print a per-tick analysis."""

from __future__ import annotations

import asyncio
import json
import sys
from collections import defaultdict

import websockets

from analysis.lib.lab_client import LAB_WS as URL, unpack_bits

SECONDS = float(sys.argv[1]) if len(sys.argv) > 1 else 6.0


async def main() -> None:
    async with websockets.connect(URL, max_size=2**24) as ws:
        hello_raw = await ws.recv()
        hello = json.loads(hello_raw)
        names = hello["L"]["nm"]
        joints = hello["L_body"]["joints"]
        muscles = hello["L_body"]["muscles"]
        n_neurons = len(names)
        print(f"hello: nm={n_neurons}, joints={len(joints)}, muscles={len(muscles)}")
        # Interesting motor & command neurons:
        targets = [
            "DB1", "DB2", "DB3", "DB4", "DB5", "DB6", "DB7",
            "VB1", "VB2", "VB3", "VB4", "VB5", "VB6", "VB7", "VB8", "VB9", "VB10", "VB11",
            "DD1", "DD2", "DD3",
            "VD1", "VD2", "VD3",
            "DA1", "DA2", "DA3",
            "VA1", "VA2", "VA3",
            "AVBL", "AVBR", "AVAL", "AVAR",
        ]
        idx = {nm: i for i, nm in enumerate(names) if nm in targets}

        # First-tick sample fields, then accumulate
        traces: dict[str, list[float]] = defaultdict(list)
        ticks: list[int] = []
        joint_traces: list[list[float]] = []
        muscle_traces: list[list[float]] = []
        free_energy: list[float] = []
        global_m0: list[float] = []
        global_m1: list[float] = []
        fired_targets: dict[str, list[int]] = defaultdict(list)

        deadline = asyncio.get_event_loop().time() + SECONDS
        n_msg = 0
        while asyncio.get_event_loop().time() < deadline:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
            except asyncio.TimeoutError:
                break
            d = json.loads(msg)
            if d.get("t") != "s":
                continue
            n_msg += 1
            tick = d.get("k", 0)
            ticks.append(tick)
            Si = d.get("Si", [])
            ja = d.get("ja", [])
            ma = d.get("ma", [])
            fb_b64 = d.get("Fb", "")
            fired = unpack_bits(fb_b64, n_neurons)
            for nm, i in idx.items():
                if i < len(Si):
                    traces[f"S:{nm}"].append(Si[i] / 1e4)
                fired_targets[nm].append(int(fired[i]))
            joint_traces.append([v / 1e4 for v in ja])
            muscle_traces.append([v / 1e4 for v in ma])
            nm01 = d.get("nm01", [0.0, 0.0])
            global_m0.append(float(nm01[0]))
            global_m1.append(float(nm01[1]))
            free_energy.append(float(d.get("fe", 0.0)))

        if not ticks:
            print("no frames received")
            return

        n_t = len(ticks)
        print(f"received {n_msg} state frames over ~{SECONDS}s, ticks {ticks[0]}..{ticks[-1]} (Δ={ticks[-1]-ticks[0]})")
        # Neuron stats
        for k, v in sorted(traces.items()):
            mn, mx, mean = min(v), max(v), sum(v) / len(v)
            stddev = (sum((x - mean) ** 2 for x in v) / len(v)) ** 0.5
            print(f"  {k:15s}  min={mn:+.3f} max={mx:+.3f} mean={mean:+.3f} std={stddev:.3f}")

        for nm, fired in sorted(fired_targets.items()):
            cnt = sum(fired)
            print(f"  fired:{nm:8s}  count={cnt}/{n_t} rate={cnt/n_t:.2%}")

        # Joints
        print("\njoints (mean / range / std) over capture:")
        for j_idx, jname in enumerate(joints):
            col = [row[j_idx] for row in joint_traces if j_idx < len(row)]
            if not col:
                continue
            mean = sum(col) / len(col)
            mn, mx = min(col), max(col)
            std = (sum((x - mean) ** 2 for x in col) / len(col)) ** 0.5
            print(f"  {jname:14s}  mean={mean:+.4f} min={mn:+.4f} max={mx:+.4f} std={std:.4f}")

        # Muscles
        print("\nmuscles per-segment dorsal-ventral push (mean):")
        # 12 segs × {DL,DR,VL,VR}; index into ma assumed 0..47
        for seg in range(12):
            base = seg * 4
            if base + 3 >= len(muscle_traces[0]):
                break
            dl = sum(row[base + 0] for row in muscle_traces) / n_t
            dr = sum(row[base + 1] for row in muscle_traces) / n_t
            vl = sum(row[base + 2] for row in muscle_traces) / n_t
            vr = sum(row[base + 3] for row in muscle_traces) / n_t
            print(f"  seg{seg+1:2d}  DL={dl:.3f} DR={dr:.3f} VL={vl:.3f} VR={vr:.3f}  D-V={(dl+dr)/2 - (vl+vr)/2:+.3f}")

        # Time evolution of seg1 (D and V) muscles to see oscillation
        print("\nseg1 muscle time-trace (last ~30 ticks, every 5):")
        m = muscle_traces
        last = m[-min(30, len(m)):]
        for j, row in enumerate(last):
            if j % 3 != 0:
                continue
            print(
                f"  t-{len(last)-j:3d}  "
                f"DL={row[0]:.3f} DR={row[1]:.3f} VL={row[2]:.3f} VR={row[3]:.3f}  "
                f"j01_pitch={joint_traces[len(joint_traces)-len(last)+j][0]:+.4f} j01_yaw={joint_traces[len(joint_traces)-len(last)+j][1]:+.4f}"
            )

        # DB1 / VB1 oscillation snippet
        print("\nDB1 vs VB1 S over last ~40 ticks:")
        s_db = traces.get("S:DB1", [])
        s_vb = traces.get("S:VB1", [])
        if s_db and s_vb:
            tail = list(zip(s_db[-40:], s_vb[-40:]))
            for j, (a, b) in enumerate(tail):
                print(f"  t-{len(tail)-j:3d}  DB1.S={a:+.4f}  VB1.S={b:+.4f}")

        print(f"\nneuromod m0 mean={sum(global_m0)/n_t:.4f} m1 mean={sum(global_m1)/n_t:.4f}")
        print(f"free_energy mean={sum(free_energy)/n_t:.4f}")


if __name__ == "__main__":
    asyncio.run(main())

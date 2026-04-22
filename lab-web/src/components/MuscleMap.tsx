import { useEffect, useRef } from "react";
import { useBodyStore } from "../state/body";
import { useLabStore } from "../state/store";

const SIDES = ["DL", "DR", "VL", "VR"] as const;
type Side = (typeof SIDES)[number];

interface MuscleCell {
  side: Side;
  seg: number;
  id: number;
  name: string;
}

const MUSCLE_NAME_RE = /^muscle_seg(\d+)_(DL|DR|VL|VR)$/;

function parseMuscles(actuators: { id: number; name: string }[]): MuscleCell[] {
  const cells: MuscleCell[] = [];
  for (const a of actuators) {
    const m = MUSCLE_NAME_RE.exec(a.name);
    if (!m) continue;
    cells.push({
      side: m[2] as Side,
      seg: Number(m[1]),
      id: a.id,
      name: a.name,
    });
  }
  return cells;
}

function activationColor(a: number): string {
  const c = Math.max(-1, Math.min(1, a));
  if (c >= 0) {
    // Positive: orange/red
    const t = c;
    const r = Math.round(40 + 215 * t);
    const g = Math.round(40 + 80 * t);
    return `rgb(${r}, ${g}, 40)`;
  } else {
    const t = -c;
    const b = Math.round(40 + 215 * t);
    const g = Math.round(40 + 150 * t);
    return `rgb(40, ${g}, ${b})`;
  }
}

export function MuscleMap() {
  const view = useBodyStore((s) => s.view);
  const selection = useBodyStore((s) => s.selection);
  const select = useBodyStore((s) => s.select);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rafRef = useRef<number | null>(null);

  const cells = view ? parseMuscles(view.actuators) : [];
  const segCount = cells.reduce((m, c) => Math.max(m, c.seg), 0);

  // Hit-testing table: cell index → {id, name}.
  const cellIndexRef = useRef<MuscleCell[]>(cells);
  cellIndexRef.current = cells;

  useEffect(() => {
    if (!view) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const draw = () => {
      const dpr = window.devicePixelRatio || 1;
      const rect = canvas.getBoundingClientRect();
      canvas.width = rect.width * dpr;
      canvas.height = rect.height * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      const W = rect.width;
      const H = rect.height;
      ctx.clearRect(0, 0, W, H);

      const padL = 48;
      const padT = 20;
      const padR = 8;
      const padB = 20;
      const gx = (W - padL - padR) / Math.max(segCount, 1);
      const gy = (H - padT - padB) / SIDES.length;

      ctx.font = "11px ui-monospace, monospace";
      ctx.textBaseline = "middle";
      ctx.fillStyle = "#8ba3c7";
      for (let s = 0; s < SIDES.length; s++) {
        ctx.fillText(SIDES[s], 4, padT + gy * (s + 0.5));
      }
      ctx.textAlign = "center";
      for (let seg = 1; seg <= segCount; seg++) {
        ctx.fillText(String(seg), padL + gx * (seg - 0.5), padT - 8);
      }

      const latest = useLabStore.getState().latest;
      const ma = latest?.ma ?? null;

      for (const cell of cellIndexRef.current) {
        const sIdx = SIDES.indexOf(cell.side);
        const col = cell.seg - 1;
        const x = padL + gx * col;
        const y = padT + gy * sIdx;

        const a = ma ? ma[cell.id] ?? 0 : 0;
        ctx.fillStyle = activationColor(a);
        ctx.fillRect(x + 1, y + 1, gx - 2, gy - 2);

        if (selection && selection.kind === "muscle" && selection.id === cell.id) {
          ctx.strokeStyle = "#7ab6ff";
          ctx.lineWidth = 2;
          ctx.strokeRect(x + 1, y + 1, gx - 2, gy - 2);
        }
      }

      ctx.textAlign = "start";
      rafRef.current = requestAnimationFrame(draw);
    };

    rafRef.current = requestAnimationFrame(draw);
    return () => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
    };
  }, [view, selection, segCount]);

  const handleClick = (evt: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas || !view) return;
    const rect = canvas.getBoundingClientRect();
    const mx = evt.clientX - rect.left;
    const my = evt.clientY - rect.top;

    const padL = 48;
    const padT = 20;
    const padR = 8;
    const padB = 20;
    const gx = (rect.width - padL - padR) / Math.max(segCount, 1);
    const gy = (rect.height - padT - padB) / SIDES.length;
    const col = Math.floor((mx - padL) / gx) + 1;
    const row = Math.floor((my - padT) / gy);
    if (col < 1 || col > segCount || row < 0 || row >= SIDES.length) return;
    const side = SIDES[row];
    const cell = cellIndexRef.current.find((c) => c.seg === col && c.side === side);
    if (!cell) return;
    if (selection && selection.kind === "muscle" && selection.id === cell.id) {
      select(null);
      return;
    }
    select({ kind: "muscle", id: cell.id, name: cell.name });
  };

  if (!view) {
    return (
      <div className="flex h-full items-center justify-center text-zinc-500 text-xs">
        Loading body…
      </div>
    );
  }

  return (
    <div className="relative h-full w-full">
      <canvas
        ref={canvasRef}
        onClick={handleClick}
        className="h-full w-full cursor-pointer"
      />
    </div>
  );
}

import { useEffect, useRef } from "react";
import { useBodyStore } from "../state/body";
import { useLabStore } from "../state/store";

const MUSCLE_NAME_RE = /^muscle_seg(\d+)_(DL|DR|VL|VR)$/;

interface MuscleLookup {
  // For each segment (1-based index), record actuator ids for DL/DR/VL/VR.
  [seg: number]: { DL?: number; DR?: number; VL?: number; VR?: number };
}

function buildLookup(actuators: { id: number; name: string }[]): {
  lookup: MuscleLookup;
  segCount: number;
} {
  const lookup: MuscleLookup = {};
  let segCount = 0;
  for (const a of actuators) {
    const m = MUSCLE_NAME_RE.exec(a.name);
    if (!m) continue;
    const seg = Number(m[1]);
    const side = m[2] as "DL" | "DR" | "VL" | "VR";
    if (!lookup[seg]) lookup[seg] = {};
    lookup[seg][side] = a.id;
    if (seg > segCount) segCount = seg;
  }
  return { lookup, segCount };
}

function activationIntensity(a: number): number {
  return Math.min(1, Math.max(0, Math.abs(a)));
}

function activationColor(a: number, base: string): string {
  const t = activationIntensity(a);
  if (t < 0.02) return base;
  const [r, g, b] = a >= 0 ? [235, 120, 60] : [60, 180, 235];
  const [br, bg, bb] = base === "#1e1e26" ? [60, 60, 70] : [90, 90, 100];
  const R = Math.round(br + (r - br) * t);
  const G = Math.round(bg + (g - bg) * t);
  const B = Math.round(bb + (b - bb) * t);
  return `rgb(${R}, ${G}, ${B})`;
}

export function BodyWYSIWYG() {
  const view = useBodyStore((s) => s.view);
  const selection = useBodyStore((s) => s.selection);
  const select = useBodyStore((s) => s.select);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    if (!view) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const { lookup, segCount } = buildLookup(view.actuators);

    const draw = () => {
      const dpr = window.devicePixelRatio || 1;
      const rect = canvas.getBoundingClientRect();
      canvas.width = rect.width * dpr;
      canvas.height = rect.height * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      const W = rect.width;
      const H = rect.height;
      ctx.clearRect(0, 0, W, H);

      const padX = 24;
      const padY = 36;
      const usableW = W - 2 * padX;
      const segW = usableW / Math.max(segCount, 1);
      const midY = H / 2;
      const halfH = Math.min(60, (H - 2 * padY) / 2);

      const latest = useLabStore.getState().latest;
      const ma = latest?.ma ?? null;

      ctx.font = "10px ui-monospace, monospace";
      ctx.textBaseline = "alphabetic";
      ctx.fillStyle = "#8ba3c7";
      ctx.textAlign = "left";
      ctx.fillText("anterior", padX, padY - 12);
      ctx.textAlign = "right";
      ctx.fillText("posterior", W - padX, padY - 12);
      ctx.textAlign = "start";

      for (let seg = 1; seg <= segCount; seg++) {
        const x = padX + segW * (seg - 1);
        const ids = lookup[seg] ?? {};

        const draws = [
          { y: midY - halfH, h: halfH / 2, side: "DL" as const, label: "DL" },
          { y: midY - halfH / 2, h: halfH / 2, side: "DR" as const, label: "DR" },
          { y: midY, h: halfH / 2, side: "VL" as const, label: "VL" },
          { y: midY + halfH / 2, h: halfH / 2, side: "VR" as const, label: "VR" },
        ];
        for (const d of draws) {
          const aid = ids[d.side];
          const a = aid != null && ma ? ma[aid] ?? 0 : 0;
          const isSelected =
            selection && selection.kind === "muscle" && selection.id === aid;
          ctx.fillStyle = activationColor(a, "#1e1e26");
          ctx.fillRect(x + 1, d.y, segW - 2, d.h - 1);
          if (isSelected) {
            ctx.strokeStyle = "#7ab6ff";
            ctx.lineWidth = 2;
            ctx.strokeRect(x + 1, d.y, segW - 2, d.h - 1);
          }
        }

        // Separator between D and V
        ctx.strokeStyle = "#2a2a34";
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(x, midY);
        ctx.lineTo(x + segW, midY);
        ctx.stroke();

        ctx.fillStyle = "#8ba3c7";
        ctx.textAlign = "center";
        ctx.fillText(String(seg), x + segW / 2, midY + halfH + 14);
      }

      ctx.textAlign = "left";
      ctx.fillStyle = "#8ba3c7";
      ctx.fillText("D (dorsal)", 4, midY - halfH - 4);
      ctx.fillText("V (ventral)", 4, midY + halfH + 14);

      rafRef.current = requestAnimationFrame(draw);
    };

    rafRef.current = requestAnimationFrame(draw);
    return () => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
    };
  }, [view, selection]);

  const handleClick = (evt: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas || !view) return;
    const rect = canvas.getBoundingClientRect();
    const mx = evt.clientX - rect.left;
    const my = evt.clientY - rect.top;

    const { lookup, segCount } = buildLookup(view.actuators);
    const padX = 24;
    const padY = 36;
    const usableW = rect.width - 2 * padX;
    const segW = usableW / Math.max(segCount, 1);
    const midY = rect.height / 2;
    const halfH = Math.min(60, (rect.height - 2 * padY) / 2);

    const seg = Math.floor((mx - padX) / segW) + 1;
    if (seg < 1 || seg > segCount) return;
    const sideRow = Math.floor((my - (midY - halfH)) / (halfH / 2));
    if (sideRow < 0 || sideRow >= 4) return;
    const side = (["DL", "DR", "VL", "VR"] as const)[sideRow];
    const aid = lookup[seg]?.[side];
    if (aid != null) {
      const name = `muscle_seg${seg}_${side}`;
      select({ kind: "muscle", id: aid, name });
    }
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

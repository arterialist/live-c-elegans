import { useEffect, useMemo, useRef } from "react";
import { clsx } from "clsx";
import { useConnectomeStore } from "../state/connectome";
import { useLabStore } from "../state/store";

/** Body-aligned WYSIWYG view of the 302-neuron connectome. */
const BASE_RADIUS = 2.5;
const BASE_RADIUS_SELECTED = 5;

export type ConnectomeClassHighlight = "s" | "m" | "i" | null;

export function NeuronMap({
  showEdges,
  edgeOpacity,
  neuronScale,
  highlightClass,
}: {
  showEdges: boolean;
  edgeOpacity: number;
  /** 1 = default radii; up to 2 doubles dot size for readability. */
  neuronScale: number;
  /** When set, other classes render at half opacity for quick visual grouping. */
  highlightClass: ConnectomeClassHighlight;
}) {
  const neurons = useConnectomeStore((s) => s.neurons);
  const edges = useConnectomeStore((s) => s.edges);
  const selected = useConnectomeStore((s) => s.selected);
  const select = useConnectomeStore((s) => s.select);
  const helloNames = useLabStore((s) => s.hello?.L.nm ?? []);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const hostRef = useRef<HTMLDivElement | null>(null);

  // Name → paula_id once hello is in.
  const idxOf = useMemo(() => {
    const m = new Map<string, number>();
    helloNames.forEach((n, i) => m.set(n, i));
    return m;
  }, [helloNames]);

  // Transform: map body coords x=[0..1], y=[-0.8..0.8] into [-1..1] x [-1..1].
  const points = useMemo(
    () =>
      neurons.map((n) => ({
        id: n.id,
        name: n.name,
        cls: n.class,
        x: n.layout_x * 2 - 1,
        y: n.layout_y / 0.85,
        paulaIdx: idxOf.get(n.name),
      })),
    [neurons, idxOf],
  );

  // Animate; pull latest state directly (avoid re-rendering whole tree).
  useEffect(() => {
    const canvas = canvasRef.current;
    const host = hostRef.current;
    if (!canvas || !host || neurons.length === 0) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let raf = 0;
    const draw = () => {
      const latest = useLabStore.getState().latest;
      const fired = latest?.fired;
      const S = latest?.S;

      const rect = host.getBoundingClientRect();
      const dpr = Math.max(1, window.devicePixelRatio || 1);
      const w = Math.max(100, Math.floor(rect.width));
      const h = Math.max(100, Math.floor(rect.height));
      if (canvas.width !== w * dpr || canvas.height !== h * dpr) {
        canvas.width = w * dpr;
        canvas.height = h * dpr;
        canvas.style.width = `${w}px`;
        canvas.style.height = `${h}px`;
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);

      // Transform: body coords → pixels. Pad 10% and keep aspect.
      const pad = 20;
      const innerW = w - pad * 2;
      const innerH = h - pad * 2;
      const toPx = (x: number, y: number) => [
        pad + ((x + 1) / 2) * innerW,
        pad + ((y + 1) / 2) * innerH,
      ];

      // Body centerline.
      ctx.strokeStyle = "rgba(120,120,140,0.25)";
      ctx.lineWidth = 1;
      ctx.beginPath();
      const [x0, y0] = toPx(-1, 0);
      const [x1, y1] = toPx(1, 0);
      ctx.moveTo(x0, y0);
      ctx.lineTo(x1, y1);
      ctx.stroke();

      // Edges (optional).
      if (showEdges && edges.length && edgeOpacity > 0) {
        ctx.strokeStyle = `rgba(86, 110, 140, ${edgeOpacity})`;
        ctx.lineWidth = 0.5;
        ctx.beginPath();
        for (const e of edges) {
          const a = points[e.pre_id];
          const b = points[e.post_id];
          if (!a || !b) continue;
          const [ax, ay] = toPx(a.x, a.y);
          const [bx, by] = toPx(b.x, b.y);
          ctx.moveTo(ax, ay);
          ctx.lineTo(bx, by);
        }
        ctx.stroke();
      }

      // Neuron nodes.
      const scale = Math.min(2, Math.max(1, neuronScale));
      for (const p of points) {
        const [px, py] = toPx(p.x, p.y);
        const idx = p.paulaIdx ?? p.id;
        const f = fired ? fired[idx] : 0;
        const s = S ? S[idx] : 0;
        const color = fillFor(p.cls, s, f, highlightClass);
        const r =
          (p.name === selected ? BASE_RADIUS_SELECTED : BASE_RADIUS) * scale;
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(px, py, r, 0, Math.PI * 2);
        ctx.fill();
        if (p.name === selected) {
          ctx.strokeStyle = "oklch(0.85 0.2 265)";
          ctx.lineWidth = 1.5 * scale;
          ctx.stroke();
        }
      }

      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [
    neurons.length,
    points,
    edges,
    showEdges,
    edgeOpacity,
    neuronScale,
    highlightClass,
    selected,
  ]);

  return (
    <div
      ref={hostRef}
      className="relative h-full min-h-[280px] w-full overflow-hidden rounded-md bg-zinc-950 ring-1 ring-zinc-800"
      onPointerDown={(e) => {
        const host = hostRef.current;
        if (!host || points.length === 0) return;
        const rect = host.getBoundingClientRect();
        const px = e.clientX - rect.left;
        const py = e.clientY - rect.top;
        const pad = 20;
        const innerW = rect.width - pad * 2;
        const innerH = rect.height - pad * 2;
        const scale = Math.min(2, Math.max(1, neuronScale));
        let best: { name: string; d2: number } | null = null;
        for (const p of points) {
          const nx = pad + ((p.x + 1) / 2) * innerW;
          const ny = pad + ((p.y + 1) / 2) * innerH;
          const d2 = (nx - px) ** 2 + (ny - py) ** 2;
          const hitR =
            (p.name === selected ? BASE_RADIUS_SELECTED : BASE_RADIUS) *
              scale +
            6;
          if (d2 > hitR ** 2) continue;
          if (!best || d2 < best.d2) best = { name: p.name, d2 };
        }
        if (best) {
          select(best.name);
        }
      }}
    >
      <canvas ref={canvasRef} className="absolute inset-0" />
      <div
        className={clsx(
          "pointer-events-none absolute right-3 top-2 rounded",
          "bg-zinc-900/80 px-2 py-1 font-mono text-[10px] text-zinc-400",
        )}
      >
        {neurons.length} neurons · {edges.length} edges
      </div>
    </div>
  );
}

function fillFor(
  cls: "s" | "m" | "i" | "u",
  S: number,
  fired: number,
  highlight: ConnectomeClassHighlight,
): string {
  const base =
    cls === "s"
      ? "190 70% 70%"
      : cls === "m"
        ? "25 80% 65%"
        : cls === "i"
          ? "265 60% 72%"
          : "0 0% 50%";
  const hueToken = base.split(" ")[0]!;
  const opacityMul =
    highlight !== null && cls !== highlight ? 0.5 : 1;

  if (fired) {
    const a = Math.min(1, 0.95 * opacityMul);
    return `hsl(${hueToken} 90% 88% / ${a})`;
  }
  const alpha =
    Math.max(0.25, Math.min(1.0, 0.25 + Math.abs(S) * 0.5)) * opacityMul;
  return `hsl(${base} / ${alpha})`;
}

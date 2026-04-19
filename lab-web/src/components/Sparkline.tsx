import { useEffect, useRef } from "react";
import { useAppSettings } from "../state/app-settings";
import { useLabStore } from "../state/store";

/** Minimal canvas sparkline fed from a ring-buffer sampler.
 *
 * ``sample()`` is invoked once per animation frame; the returned numbers are
 * plotted against a fixed time-window (``history`` points wide). Keeping the
 * subscription inside this component means the parent tree does not re-render
 * every tick, even at 60 fps.
 *
 * When the lab sim is **paused** (``latest.running === false``), the ring
 * buffer advances only when ``latest.tick`` changes (one point per **Step**
 * / next-tick), not on every animation frame.
 */
export function Sparkline({
  label,
  sample,
  markerSample,
  history,
  color = "oklch(0.85 0.2 265)",
  min,
  max,
  height = 36,
  format,
}: {
  label: string;
  sample: () => number | null;
  /** When provided, truthy samples draw a vertical marker at that history column (e.g. spikes). */
  markerSample?: () => number | null;
  history?: number;
  color?: string;
  min?: number;
  max?: number;
  height?: number;
  format?: (v: number) => string;
}) {
  const historyDefault = useAppSettings((s) => s.historyLength);
  const historySize = Math.max(16, history ?? historyDefault);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const valueRef = useRef<HTMLSpanElement | null>(null);
  const bufRef = useRef<Float32Array>(new Float32Array(historySize));
  const markRef = useRef<Uint8Array | null>(null);
  const headRef = useRef(0);
  const lenRef = useRef(0);
  const lastRef = useRef<number | null>(null);
  /** While paused, last sim tick we appended to the buffer (null = not latched yet). */
  const pauseHeldTickRef = useRef<number | null>(null);

  // Resize value ring buffer when history length changes; keep marker buffer aligned.
  useEffect(() => {
    if (bufRef.current.length !== historySize) {
      bufRef.current = new Float32Array(historySize);
      headRef.current = 0;
      lenRef.current = 0;
    }
    if (markerSample) {
      if (!markRef.current || markRef.current.length !== historySize) {
        markRef.current = new Uint8Array(historySize);
      }
    } else {
      markRef.current = null;
    }
  }, [historySize, markerSample]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    let raf = 0;
    const draw = () => {
      const latest = useLabStore.getState().latest;
      const pauseGated = !!(latest && !latest.running);
      const simTick = latest?.tick ?? null;

      if (!pauseGated) {
        pauseHeldTickRef.current = null;
      }

      let v: number | null = null;
      if (!pauseGated) {
        v = sample();
      } else if (simTick != null) {
        if (pauseHeldTickRef.current === null) {
          pauseHeldTickRef.current = simTick;
        } else if (pauseHeldTickRef.current !== simTick) {
          pauseHeldTickRef.current = simTick;
          v = sample();
        }
      }

      if (v != null && Number.isFinite(v)) {
        const buf = bufRef.current;
        const head = headRef.current;
        buf[head] = v;
        const marks = markRef.current;
        if (markerSample && marks) {
          const m = markerSample();
          marks[head] =
            m != null && Number.isFinite(m) && Math.abs(m) > 1e-6 ? 1 : 0;
        }
        headRef.current = (head + 1) % buf.length;
        lenRef.current = Math.min(buf.length, lenRef.current + 1);
        lastRef.current = v;
      }

      const rect = canvas.getBoundingClientRect();
      const dpr = Math.max(1, window.devicePixelRatio || 1);
      const w = Math.max(80, Math.floor(rect.width));
      const h = Math.max(20, Math.floor(rect.height));
      if (canvas.width !== w * dpr || canvas.height !== h * dpr) {
        canvas.width = w * dpr;
        canvas.height = h * dpr;
      }
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);

      const buf = bufRef.current;
      const len = lenRef.current;
      if (len > 1) {
        // Auto-range when bounds are not provided.
        let lo = min ?? Infinity;
        let hi = max ?? -Infinity;
        if (min == null || max == null) {
          for (let i = 0; i < len; i++) {
            const v = buf[(headRef.current - len + i + buf.length) % buf.length];
            if (v < lo) lo = v;
            if (v > hi) hi = v;
          }
          if (lo === hi) {
            lo -= 1;
            hi += 1;
          }
        }
        const range = hi - lo || 1;
        const stepX = w / (buf.length - 1);
        const marks = markRef.current;
        if (markerSample && marks) {
          ctx.save();
          ctx.strokeStyle = "rgb(220, 38, 38)";
          ctx.lineWidth = 1.125;
          ctx.lineCap = "butt";
          for (let i = 0; i < len; i++) {
            const idx = (headRef.current - len + i + buf.length) % buf.length;
            if (!marks[idx]) continue;
            const x = (buf.length - len + i) * stepX;
            ctx.beginPath();
            ctx.moveTo(x, 0);
            ctx.lineTo(x, h);
            ctx.stroke();
          }
          ctx.restore();
        }
        ctx.strokeStyle = color;
        ctx.lineWidth = 1.25;
        ctx.beginPath();
        for (let i = 0; i < len; i++) {
          const idx = (headRef.current - len + i + buf.length) % buf.length;
          const y = h - ((buf[idx] - lo) / range) * (h - 2) - 1;
          const x = (buf.length - len + i) * stepX;
          if (i === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
        ctx.stroke();
      }

      if (valueRef.current && lastRef.current != null) {
        valueRef.current.textContent = format
          ? format(lastRef.current)
          : formatNumber(lastRef.current);
      }

      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [sample, markerSample, color, min, max, format]);

  return (
    <div className="grid grid-cols-[80px_1fr_70px] items-center gap-2">
      <div className="font-mono text-[11px] text-zinc-400">{label}</div>
      <canvas
        ref={canvasRef}
        className="h-9 w-full rounded-sm bg-zinc-900 ring-1 ring-zinc-800"
        style={{ height }}
      />
      <span
        ref={valueRef}
        className="text-right font-mono text-[11px] tabular-nums text-zinc-200"
      />
    </div>
  );
}

function formatNumber(v: number): string {
  if (Math.abs(v) >= 100) return v.toFixed(0);
  if (Math.abs(v) >= 10) return v.toFixed(1);
  return v.toFixed(3);
}

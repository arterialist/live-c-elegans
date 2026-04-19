import { useEffect, useRef } from "react";
import { useAppSettings } from "../state/app-settings";

/** Minimal canvas sparkline fed from a ring-buffer sampler.
 *
 * ``sample()`` is invoked once per animation frame; the returned numbers are
 * plotted against a fixed time-window (``history`` points wide). Keeping the
 * subscription inside this component means the parent tree does not re-render
 * every tick, even at 60 fps.
 */
export function Sparkline({
  label,
  sample,
  history,
  color = "oklch(0.85 0.2 265)",
  min,
  max,
  height = 36,
  format,
}: {
  label: string;
  sample: () => number | null;
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
  const headRef = useRef(0);
  const lenRef = useRef(0);
  const lastRef = useRef<number | null>(null);

  // Resize ring buffer when the user changes history length.
  useEffect(() => {
    if (bufRef.current.length === historySize) return;
    bufRef.current = new Float32Array(historySize);
    headRef.current = 0;
    lenRef.current = 0;
  }, [historySize]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    let raf = 0;
    const draw = () => {
      const v = sample();
      if (v != null && Number.isFinite(v)) {
        const buf = bufRef.current;
        const head = headRef.current;
        buf[head] = v;
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
  }, [sample, color, min, max, format]);

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

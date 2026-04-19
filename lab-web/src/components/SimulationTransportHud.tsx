import { useEffect, useState } from "react";
import { clsx } from "clsx";
import { Pause, Play, SkipForward, RefreshCw } from "lucide-react";
import { getPacing, getTransport, resetSim, setPacing, setTransport } from "../api/http";
import { useLabStore } from "../state/store";
import { KeyHint } from "./ui/KeyHint";

export function SimulationTransportHud() {
  const latest = useLabStore((s) => s.latest);
  const connected = useLabStore((s) => s.connected);
  const [running, setRunning] = useState<boolean>(true);
  const [tick, setTick] = useState<number>(0);
  const [busy, setBusy] = useState<boolean>(false);
  const [phyMs, setPhyMs] = useState<string>("0");
  const [neuMs, setNeuMs] = useState<string>("0");
  const [pacingBusy, setPacingBusy] = useState(false);

  // Mirror transport state from REST + WS.
  useEffect(() => {
    let cancel = false;
    Promise.all([getTransport(), getPacing()])
      .then(([t, p]) => {
        if (cancel) return;
        setRunning(t.running);
        setTick(t.tick);
        setPhyMs(String(p.real_ms_per_physics_step));
        setNeuMs(String(p.real_ms_per_neural_tick));
      })
      .catch(() => undefined);
    return () => {
      cancel = true;
    };
  }, []);

  useEffect(() => {
    if (!latest) return;
    setRunning(latest.running);
    setTick(latest.tick);
  }, [latest]);

  const go = async (action: "play" | "pause" | "step") => {
    setBusy(true);
    try {
      const t = await setTransport(action);
      setRunning(t.running);
      setTick(t.tick);
    } finally {
      setBusy(false);
    }
  };

  const reset = async () => {
    setBusy(true);
    try {
      await resetSim();
    } finally {
      setBusy(false);
    }
  };

  const applyPacing = async () => {
    const phy = Number.parseFloat(phyMs);
    const neu = Number.parseFloat(neuMs);
    setPacingBusy(true);
    try {
      const p = await setPacing({
        real_ms_per_physics_step: Number.isFinite(phy) ? Math.max(0, phy) : 0,
        real_ms_per_neural_tick: Number.isFinite(neu) ? Math.max(0, neu) : 0,
      });
      setPhyMs(String(p.real_ms_per_physics_step));
      setNeuMs(String(p.real_ms_per_neural_tick));
    } finally {
      setPacingBusy(false);
    }
  };

  return (
    <div className="absolute inset-x-0 bottom-0 flex items-center justify-center pb-4 pointer-events-none">
      <div
        className={clsx(
          "pointer-events-auto flex max-w-[min(100vw-1rem,56rem)] flex-wrap items-center gap-1 rounded-full",
          "bg-zinc-900/80 px-2 py-1 shadow-lg ring-1 ring-zinc-800 backdrop-blur",
        )}
      >
        <HudButton
          aria-label={running ? "Pause simulation" : "Play simulation"}
          title={running ? "Pause (Space)" : "Play (Space)"}
          onClick={() => go(running ? "pause" : "play")}
          disabled={busy}
          hint="Space"
        >
          {running ? <Pause className="size-4" /> : <Play className="size-4" />}
        </HudButton>
        <HudButton
          aria-label="Step one tick"
          title="Step one tick (N)"
          onClick={() => go("step")}
          disabled={busy}
          hint="N"
        >
          <SkipForward className="size-4" />
        </HudButton>
        <HudButton
          aria-label="Reset simulation"
          title="Reset simulation (R)"
          onClick={reset}
          disabled={busy}
          hint="R"
        >
          <RefreshCw className="size-4" />
        </HudButton>
        <div className="mx-2 w-24 shrink-0 font-mono text-xs tabular-nums text-zinc-400">
          tick {tick.toString().padStart(6, " ")}
        </div>
        <div
          className="flex items-end gap-1 border-l border-zinc-700/80 pl-2"
          title="Wall-clock pacing: minimum real milliseconds per physics step (entire MuJoCo step) and per PAULA neural sub-tick. Use 0 for no added delay (maximum simulation speed)."
        >
          <label className="flex flex-col text-[9px] leading-none text-zinc-500">
            <span className="mb-0.5">phys ms</span>
            <input
              type="number"
              min={0}
              step={1}
              value={phyMs}
              onChange={(e) => setPhyMs(e.target.value)}
              disabled={pacingBusy}
              className="w-14 rounded border border-zinc-700 bg-zinc-950 px-1 py-0.5 font-mono text-[10px] text-zinc-200 focus:border-accent focus:outline-none disabled:opacity-40"
            />
          </label>
          <label className="flex flex-col text-[9px] leading-none text-zinc-500">
            <span className="mb-0.5">neur ms</span>
            <input
              type="number"
              min={0}
              step={0.5}
              value={neuMs}
              onChange={(e) => setNeuMs(e.target.value)}
              disabled={pacingBusy}
              className="w-14 rounded border border-zinc-700 bg-zinc-950 px-1 py-0.5 font-mono text-[10px] text-zinc-200 focus:border-accent focus:outline-none disabled:opacity-40"
            />
          </label>
          <button
            type="button"
            title="Apply pacing (Enter in field does not submit — use this button)"
            onClick={() => void applyPacing()}
            disabled={pacingBusy}
            className="rounded border border-zinc-600 bg-zinc-800 px-1.5 py-0.5 text-[9px] text-zinc-200 hover:bg-zinc-700 disabled:opacity-40"
          >
            Set
          </button>
        </div>
        <StatusDot connected={connected} running={running} />
      </div>
    </div>
  );
}

function HudButton({
  children,
  disabled,
  hint,
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { hint?: string }) {
  return (
    <button
      {...rest}
      disabled={disabled}
      className={clsx(
        "inline-flex flex-col items-center justify-center gap-0.5 rounded-full px-1.5 py-1",
        "text-zinc-300 transition-colors",
        "hover:bg-zinc-800 hover:text-zinc-50",
        "disabled:opacity-50",
        "focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent",
      )}
    >
      {children}
      {hint && <KeyHint size="xxs">{hint}</KeyHint>}
    </button>
  );
}

function StatusDot({
  connected,
  running,
}: {
  connected: boolean;
  running: boolean;
}) {
  const color = !connected
    ? "bg-red-500"
    : running
      ? "bg-emerald-400"
      : "bg-amber-400";
  const label = !connected
    ? "Disconnected"
    : running
      ? "Playing"
      : "Paused";
  return (
    <span
      className="mr-2 inline-flex items-center gap-2 text-xs text-zinc-400"
      aria-live="polite"
    >
      <span className={clsx("size-2 rounded-full", color)} />
      {label}
    </span>
  );
}

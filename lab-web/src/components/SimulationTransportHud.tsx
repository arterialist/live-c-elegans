import { useEffect, useState } from "react";
import { clsx } from "clsx";
import { Pause, Play, SkipForward, RefreshCw } from "lucide-react";
import { getTransport, resetSim, setTransport } from "../api/http";
import { useLabStore } from "../state/store";
import { KeyHint } from "./ui/KeyHint";

export function SimulationTransportHud() {
  const latest = useLabStore((s) => s.latest);
  const connected = useLabStore((s) => s.connected);
  const [running, setRunning] = useState<boolean>(true);
  const [tick, setTick] = useState<number>(0);
  const [busy, setBusy] = useState<boolean>(false);

  // Mirror transport state from REST + WS.
  useEffect(() => {
    let cancel = false;
    getTransport()
      .then((t) => {
        if (cancel) return;
        setRunning(t.running);
        setTick(t.tick);
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

  return (
    <div className="absolute inset-x-0 bottom-0 flex items-center justify-center pb-4 pointer-events-none">
      <div
        className={clsx(
          "pointer-events-auto flex items-center gap-1 rounded-full",
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
        <div className="mx-3 w-28 font-mono text-xs tabular-nums text-zinc-400">
          tick {tick.toString().padStart(6, " ")}
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

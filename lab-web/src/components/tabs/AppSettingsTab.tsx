import { useState } from "react";
import { clsx } from "clsx";
import { RotateCcw } from "lucide-react";
import { TabShell } from "./TabShell";
import { useLabStore } from "../../state/store";
import { useAppSettings, type AppSettings } from "../../state/app-settings";
import { resetSim } from "../../api/http";
import { GuideButton, type GuideContent } from "../ui/GuideModal";
import { KeyHint } from "../ui/KeyHint";

export function AppSettingsTab() {
  const hello = useLabStore((s) => s.hello);
  const connected = useLabStore((s) => s.connected);
  const latest = useLabStore((s) => s.latest);
  const settings = useAppSettings();
  const [busy, setBusy] = useState(false);

  const onReset = async () => {
    setBusy(true);
    try {
      settings.reset();
      await resetSim().catch(() => undefined);
    } finally {
      setBusy(false);
    }
  };

  return (
    <TabShell
      title="App settings"
      subtitle="Web-app configuration; does not change simulation state."
    >
      <div className="space-y-6 overflow-y-auto pr-1">
        <Section title="Connection">
          <Row
            label="WebSocket"
            value={connected ? "connected" : "reconnecting…"}
          />
          <Row label="Protocol" value={hello ? `v${hello.p}` : "—"} />
          <Row label="Tick" value={latest ? latest.tick.toString() : "—"} />
        </Section>

        <Section title="Stream sizes">
          <Row
            label="Neurons"
            value={hello ? hello.L.nm.length.toString() : "—"}
          />
          <Row
            label="Joints"
            value={hello ? hello.L_body.joints.length.toString() : "—"}
          />
          <Row
            label="Muscles"
            value={hello ? hello.L_body.muscles.length.toString() : "—"}
          />
          <Row
            label="Touch sensors"
            value={hello ? hello.L_body.touch.length.toString() : "—"}
          />
        </Section>

        <Section title="Rendering">
          <NumberRow
            label="Sparkline history"
            hint="Samples retained by each live chart. Bigger = smoother but slower."
            value={settings.historyLength}
            min={32}
            max={2048}
            step={32}
            onChange={(v) => settings.set("historyLength", v)}
            guide={GUIDES.historyLength}
          />
          <NumberRow
            label="Render FPS cap"
            hint="Soft ceiling on canvas updates. 0 disables the cap."
            value={settings.renderFpsCap}
            min={0}
            max={120}
            step={10}
            onChange={(v) => settings.set("renderFpsCap", v)}
            guide={GUIDES.renderFpsCap}
          />
        </Section>

        <Section title="Worm canvas overlays">
          <ToggleRow
            label="Background grid"
            value={settings.showGrid}
            onChange={(v) => settings.set("showGrid", v)}
            guide={GUIDES.showGrid}
          />
          <ToggleRow
            label="Tick / zoom / COM readout"
            value={settings.showHudText}
            onChange={(v) => settings.set("showHudText", v)}
            guide={GUIDES.showHudText}
          />
          <ToggleRow
            label="FE + neuromod panel"
            value={settings.showHudPanel}
            onChange={(v) => settings.set("showHudPanel", v)}
            guide={GUIDES.showHudPanel}
          />
          <ToggleRow
            label="COM motion trail"
            value={settings.showTrail}
            onChange={(v) => settings.set("showTrail", v)}
            guide={GUIDES.showTrail}
          />
        </Section>

        <Section title="Keyboard shortcuts">
          <KeyRow keys={["Space"]} label="Play / pause" />
          <KeyRow keys={["N"]} label="Step one tick" />
          <KeyRow keys={["R"]} label="Reset simulation" />
          <KeyRow keys={["1"]} label="Simulation settings tab" />
          <KeyRow keys={["2"]} label="MuJoCo engine tab" />
          <KeyRow keys={["3"]} label="Connectome tab" />
          <KeyRow keys={["4"]} label="Body tab" />
          <KeyRow keys={["5"]} label="App settings tab" />
        </Section>

        <div className="flex items-center justify-between rounded-lg border border-red-900/60 bg-red-950/20 px-4 py-3">
          <div className="flex items-start gap-2">
            <div>
              <div className="flex items-center gap-2">
                <div className="text-sm font-medium text-red-200">
                  Panic reset
                </div>
                <GuideButton title="Panic reset" guide={GUIDES.panicReset} />
              </div>
              <p className="text-xs text-red-300/80">
                Clears local UI settings and asks the simulation to reset to its
                initial state.
              </p>
            </div>
          </div>
          <button
            onClick={onReset}
            disabled={busy}
            className={clsx(
              "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium",
              "bg-red-900/70 text-red-100 ring-1 ring-red-800 hover:bg-red-800",
              "disabled:opacity-50",
            )}
          >
            <RotateCcw className="size-3.5" />
            Reset
          </button>
        </div>
      </div>
    </TabShell>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section>
      <h3 className="mb-2 text-xs font-semibold tracking-wider text-zinc-400 uppercase">
        {title}
      </h3>
      <div className="divide-y divide-zinc-800 rounded-lg border border-zinc-800 bg-zinc-900/40">
        {children}
      </div>
    </section>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between px-4 py-2.5">
      <span className="text-sm text-zinc-300">{label}</span>
      <span className="font-mono text-sm text-zinc-100">{value}</span>
    </div>
  );
}

function ToggleRow({
  label,
  value,
  onChange,
  guide,
}: {
  label: string;
  value: boolean;
  onChange: (v: boolean) => void;
  guide?: GuideContent;
}) {
  return (
    <div className="flex items-center justify-between px-4 py-2.5">
      <div className="flex items-center gap-2">
        <span className="text-sm text-zinc-300">{label}</span>
        {guide && <GuideButton title={label} guide={guide} />}
      </div>
      <button
        onClick={() => onChange(!value)}
        role="switch"
        aria-checked={value}
        aria-label={label}
        className={clsx(
          "relative inline-flex h-5 w-9 items-center rounded-full transition",
          value ? "bg-accent/80" : "bg-zinc-700",
        )}
      >
        <span
          className={clsx(
            "inline-block size-4 transform rounded-full bg-white transition",
            value ? "translate-x-4" : "translate-x-0.5",
          )}
        />
      </button>
    </div>
  );
}

function NumberRow({
  label,
  hint,
  value,
  min,
  max,
  step,
  onChange,
  guide,
}: {
  label: string;
  hint?: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (v: AppSettings["historyLength"]) => void;
  guide?: GuideContent;
}) {
  return (
    <div className="flex items-center justify-between gap-3 px-4 py-2.5">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <div className="text-sm text-zinc-300">{label}</div>
          {guide && <GuideButton title={label} guide={guide} />}
        </div>
        {hint && <p className="text-[11px] text-zinc-500">{hint}</p>}
      </div>
      <input
        type="number"
        value={value}
        min={min}
        max={max}
        step={step}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-24 rounded-md border border-zinc-700 bg-zinc-950 px-2 py-1 text-right font-mono text-xs text-zinc-100 focus:border-accent focus:outline-none"
      />
    </div>
  );
}

function KeyRow({ keys, label }: { keys: string[]; label: string }) {
  return (
    <div className="flex items-center justify-between px-4 py-2">
      <span className="text-sm text-zinc-300">{label}</span>
      <div className="flex gap-1">
        {keys.map((k) => (
          <KeyHint key={k}>{k}</KeyHint>
        ))}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ guides */

const GUIDES: Record<string, GuideContent> = {
  historyLength: {
    summary:
      "How many samples each live sparkline keeps in its ring buffer. Applies to every chart in the right-pane Status HUD, the Neuron Inspector, and the Muscle Inspector.",
    sections: [
      {
        heading: "What to expect",
        body: (
          <ul className="list-disc space-y-1 pl-5">
            <li>
              <span className="text-zinc-200">Longer history</span> shows more
              context and slower oscillations but spends more memory and makes
              each redraw slightly heavier.
            </li>
            <li>
              <span className="text-zinc-200">Shorter history</span> reacts
              faster visually but can miss slow drifts (e.g. ALARM recovery).
            </li>
            <li>
              Change is applied instantly; existing buffers are resized in place
              and cleared to avoid stale values.
            </li>
          </ul>
        ),
      },
    ],
  },
  renderFpsCap: {
    summary:
      "Soft ceiling on how often heavy canvases (the worm view, connectome map, body WYSIWYG, sparklines) redraw themselves.",
    sections: [
      {
        heading: "Suggested values",
        body: (
          <ul className="list-disc space-y-1 pl-5">
            <li>
              <span className="text-zinc-200">60</span> — default, matches most
              displays.
            </li>
            <li>
              <span className="text-zinc-200">30</span> — lower CPU/GPU use on
              laptops or when running the sim and the UI on the same machine.
            </li>
            <li>
              <span className="text-zinc-200">0</span> — uncapped; redraws on
              every animation frame. Useful for high-refresh-rate screens.
            </li>
          </ul>
        ),
      },
      {
        heading: "Notes",
        body: "The simulation tick rate is independent of this setting; it only affects how often you see updates, not how often the backend integrates.",
      },
    ],
  },
  showGrid: {
    summary:
      "Draws a 1 mm reference grid on the worm canvas, anchored to the center of mass.",
    sections: [
      {
        heading: "Why it matters",
        body: "The grid gives you an absolute scale (every line = 1 mm) while the camera stays locked on the worm. Without it, zooming can make the worm look the same size even when the body length or plate radius changes.",
      },
    ],
  },
  showHudText: {
    summary:
      "Shows the small textual readout in the top-left of the worm canvas: current tick, zoom level, and center-of-mass position.",
    sections: [
      {
        heading: "Tip",
        body: "If you are screen-recording the worm for a figure, turn this off together with the grid for a clean shot and keep it on while calibrating.",
      },
    ],
  },
  showHudPanel: {
    summary:
      "Toggles the floating top-right panel with live sparklines for free energy (FE) and the two global neuromodulators (M0 stress, M1 reward).",
    sections: [
      {
        heading: "What each chart shows",
        body: (
          <ul className="list-disc space-y-1 pl-5">
            <li>
              <span className="text-zinc-200">FE</span> — unit-free active
              inference surprise. Lower is better.
            </li>
            <li>
              <span className="text-zinc-200">M0 stress</span> — 0..1 global
              stress neuromodulator.
            </li>
            <li>
              <span className="text-zinc-200">M1 reward</span> — 0..1 global
              reward neuromodulator.
            </li>
          </ul>
        ),
      },
    ],
  },
  showTrail: {
    summary:
      "Paints a faint polyline of the last ~600 center-of-mass positions so you can see the worm's path even with the camera locked.",
    sections: [
      {
        heading: "When to use it",
        body: "Helpful for spotting drift, loops, and S-shape locomotion gait. Turn it off for calibration sessions where the trail would clutter screenshots.",
      },
    ],
  },
  panicReset: {
    summary:
      "Escape hatch if the UI or the simulation looks wedged. Two things happen, in order:",
    sections: [
      {
        heading: "1. Local UI settings are cleared",
        body: "Sparkline history, FPS cap, overlay toggles and the WebSocket override reset to their defaults. Nothing on the backend is touched by this step.",
      },
      {
        heading: "2. Simulation reset is requested",
        body: "The backend rebuilds the MuJoCo world, applies any queued rebuild parameters, and starts a fresh tick counter. Pending parameters remain queued; staged edits in the Simulation Settings tab are lost.",
      },
    ],
    shortcuts: [{ keys: ["R"], label: "Reset simulation only (no UI reset)" }],
  },
};

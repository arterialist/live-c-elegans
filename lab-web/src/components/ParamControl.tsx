import { clsx } from "clsx";
import type { ParameterSpec } from "../api/http";
import { GuideButton, type GuideContent } from "./ui/GuideModal";

interface Props {
  spec: ParameterSpec;
  value: unknown;
  dirty: boolean;
  pending: boolean;
  onChange: (v: unknown) => void;
}

export function ParamControl({ spec, value, dirty, pending, onChange }: Props) {
  return (
    <div
      className={clsx(
        "flex items-start gap-4 rounded-md px-3 py-2",
        dirty && "bg-amber-950/40 ring-1 ring-amber-700/40",
        pending && !dirty && "bg-blue-950/30 ring-1 ring-blue-800/40",
      )}
    >
      <div className="w-52 shrink-0">
        <div className="flex items-center gap-2">
          <label
            htmlFor={spec.path}
            className="font-mono text-xs text-zinc-200"
            title={spec.path}
          >
            {spec.label}
          </label>
          {spec.apply === "rebuild" && (
            <span
              className="rounded bg-zinc-800 px-1.5 text-[10px] uppercase tracking-wide text-amber-300"
              title="Queues as pending; requires Apply pending + reset."
            >
              rebuild
            </span>
          )}
          {spec.kind === "bool" && (
            <GuideButton title={spec.label} guide={buildParamGuide(spec)} />
          )}
        </div>
        {spec.help && (
          <p className="mt-1 text-[11px] leading-snug text-zinc-500">
            {spec.help}
          </p>
        )}
      </div>
      <div className="flex-1">
        {spec.kind === "bool" ? (
          <BoolInput
            id={spec.path}
            value={Boolean(value)}
            onChange={onChange}
          />
        ) : spec.kind === "int" || spec.kind === "float" ? (
          <NumberInput spec={spec} value={value} onChange={onChange} />
        ) : (
          <span className="font-mono text-xs text-zinc-500">
            (unsupported kind: {spec.kind})
          </span>
        )}
      </div>
    </div>
  );
}

function NumberInput({
  spec,
  value,
  onChange,
}: {
  spec: ParameterSpec;
  value: unknown;
  onChange: (v: unknown) => void;
}) {
  const num = Number(value);
  const hasRange = spec.min != null && spec.max != null;
  const coerce = (s: string) => {
    if (s === "" || s === "-") return s;
    const n = spec.kind === "int" ? parseInt(s, 10) : parseFloat(s);
    return Number.isFinite(n) ? n : s;
  };
  return (
    <div className="flex items-center gap-3">
      {hasRange && (
        <input
          type="range"
          min={spec.min ?? undefined}
          max={spec.max ?? undefined}
          step={spec.step ?? undefined}
          value={Number.isFinite(num) ? num : spec.min ?? 0}
          onChange={(e) => onChange(coerce(e.target.value))}
          className="h-1 flex-1 cursor-pointer accent-accent"
          aria-label={spec.label}
        />
      )}
      <input
        id={spec.path}
        type="number"
        inputMode="decimal"
        value={Number.isFinite(num) ? num : ""}
        step={spec.step ?? undefined}
        min={spec.min ?? undefined}
        max={spec.max ?? undefined}
        onChange={(e) => onChange(coerce(e.target.value))}
        className={clsx(
          "w-28 rounded-md border border-zinc-700 bg-zinc-900",
          "px-2 py-1 text-right font-mono text-xs text-zinc-100",
          "focus:outline focus:outline-2 focus:outline-accent",
        )}
      />
    </div>
  );
}

/** Build a guide modal body for a boolean parameter. Falls back to the generic
 *  "what does this switch do" explanation when the backend only provided a
 *  short ``help`` string, but always surfaces apply-semantics and the dotted
 *  path (useful when wiring scripts that call /api/schema). */
function buildParamGuide(spec: ParameterSpec): GuideContent {
  const rich = RICH_PARAM_GUIDES[spec.path];
  return {
    summary: rich?.summary ?? spec.help ?? `Toggle for ${spec.label}.`,
    sections: [
      ...(rich?.sections ?? []),
      {
        heading: "Apply semantics",
        body:
          spec.apply === "rebuild"
            ? "Tagged rebuild. Staging this value adds it to the pending queue; it only takes effect after you press Apply pending, which rebuilds the MuJoCo world and neural runtime."
            : "Tagged live. Submitting the form applies the value instantly without a reset; the simulation continues from the current tick.",
      },
      {
        heading: "Path",
        body: (
          <code className="rounded bg-zinc-900 px-1.5 py-0.5 font-mono text-[11px] text-zinc-300">
            {spec.path}
          </code>
        ),
      },
    ],
  };
}

/** Path-indexed rich descriptions for known boolean parameters. Extend as new
 *  toggles land. Unknown paths fall back to ``spec.help``. */
const RICH_PARAM_GUIDES: Record<string, { summary?: string; sections?: GuideContent["sections"] }> = {
  "sim.neuromod.enable_m0": {
    summary:
      "Turns the global M0 (stress) neuromodulator on or off for the whole connectome.",
    sections: [
      {
        heading: "What it affects",
        body: "When disabled, no neuron receives M0 input and M0-tagged gains drop out of the learning rule. The M0 sparkline in the top-right HUD flatlines at 0. Use this to isolate whether observed gait changes are driven by stress signaling.",
      },
    ],
  },
  "sim.neuromod.enable_m1": {
    summary:
      "Turns the global M1 (reward) neuromodulator on or off for the whole connectome.",
    sections: [
      {
        heading: "What it affects",
        body: "When disabled, reward is clamped to 0 and no plasticity term driven by M1 can update weights this tick. Helpful when you want to watch passive dynamics of the connectome without reinforcement signals.",
      },
    ],
  },
};

function BoolInput({
  id,
  value,
  onChange,
}: {
  id: string;
  value: boolean;
  onChange: (v: unknown) => void;
}) {
  return (
    <label className="inline-flex cursor-pointer items-center gap-2">
      <input
        id={id}
        type="checkbox"
        checked={value}
        onChange={(e) => onChange(e.target.checked)}
        className="size-4 cursor-pointer accent-accent"
      />
      <span className="font-mono text-xs text-zinc-300">
        {value ? "enabled" : "disabled"}
      </span>
    </label>
  );
}

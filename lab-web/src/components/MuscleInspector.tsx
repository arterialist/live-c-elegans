import { useCallback, useMemo, useState } from "react";
import { clsx } from "clsx";
import { patchBody, type BodyPatch } from "../api/http";
import { useBodyStore } from "../state/body";
import { useLabStore } from "../state/store";
import { Sparkline } from "./Sparkline";

interface StagedEdit {
  key: string;
  patch: BodyPatch;
  value: number;
}

export function MuscleInspector() {
  const view = useBodyStore((s) => s.view);
  const selection = useBodyStore((s) => s.selection);
  const mergeActuatorForcerange = useBodyStore((s) => s.mergeActuatorForcerange);
  const mergeActuatorGear = useBodyStore((s) => s.mergeActuatorGear);
  const mergeJointDamping = useBodyStore((s) => s.mergeJointDamping);
  const mergeJointArmature = useBodyStore((s) => s.mergeJointArmature);

  const [staged, setStaged] = useState<Record<string, StagedEdit>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const muscle = useMemo(() => {
    if (!view || !selection || selection.kind !== "muscle") return null;
    return view.actuators.find((a) => a.id === selection.id) ?? null;
  }, [view, selection]);

  const joint = useMemo(() => {
    if (!view || !muscle) return null;
    return view.joints.find((j) => j.id === muscle.target_joint_id) ?? null;
  }, [view, muscle]);

  const sampleAct = useCallback(() => {
    if (!muscle) return null;
    const ma = useLabStore.getState().latest?.ma;
    return ma ? ma[muscle.id] ?? null : null;
  }, [muscle]);

  const sampleJa = useCallback(() => {
    if (!joint || !view) return null;
    const idx = view.joints.findIndex((j) => j.id === joint.id);
    if (idx < 0) return null;
    const ja = useLabStore.getState().latest?.ja;
    return ja ? ja[idx] ?? null : null;
  }, [joint, view]);

  const sampleJv = useCallback(() => {
    if (!joint || !view) return null;
    const idx = view.joints.findIndex((j) => j.id === joint.id);
    if (idx < 0) return null;
    const jv = useLabStore.getState().latest?.jv;
    return jv ? jv[idx] ?? null : null;
  }, [joint, view]);

  if (!selection || selection.kind !== "muscle" || !muscle || !view) {
    return (
      <div className="rounded-md border border-dashed border-zinc-800 p-6 text-center text-sm text-zinc-500">
        Select a muscle from the WYSIWYG view or muscle map.
      </div>
    );
  }

  const stagedValue = (key: string, fallback: number): number => {
    return staged[key]?.value ?? fallback;
  };

  const stage = (patch: BodyPatch, value: number) => {
    const key = `${patch.target}:${patch.id ?? "-"}:${patch.field}:${patch.index ?? "-"}`;
    setStaged((s) => ({ ...s, [key]: { key, patch: { ...patch, value }, value } }));
  };

  const nDirty = Object.keys(staged).length;

  async function submit() {
    const patches = Object.values(staged).map((e) => e.patch);
    if (patches.length === 0) return;
    setBusy(true);
    setError(null);
    try {
      await patchBody(patches);
      const snapshot = view;
      for (const e of patches) {
        if (e.target === "actuator" && e.field === "forcerange" && snapshot) {
          const curAct = snapshot.actuators.find((a) => a.id === e.id);
          const curLo =
            e.index === 0 ? Number(e.value) : (curAct?.forcerange[0] ?? 0);
          const curHi =
            e.index === 1 ? Number(e.value) : (curAct?.forcerange[1] ?? 0);
          mergeActuatorForcerange(e.id!, curLo, curHi);
        } else if (e.target === "actuator" && e.field === "gear") {
          mergeActuatorGear(e.id!, e.index ?? 0, Number(e.value));
        } else if (e.target === "joint" && e.field === "damping") {
          mergeJointDamping(e.id!, Number(e.value));
        } else if (e.target === "joint" && e.field === "armature") {
          mergeJointArmature(e.id!, Number(e.value));
        }
      }
      setStaged({});
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      {error && (
        <div className="rounded-md bg-red-950/40 px-3 py-2 text-sm text-red-300 ring-1 ring-red-900/50">
          {error}
        </div>
      )}

      <section>
        <h3 className="mb-2 text-xs font-semibold tracking-wider text-zinc-400 uppercase">
          {muscle.name}
          <span className="ml-2 font-mono text-[10px] text-zinc-500">
            id={muscle.id} · target_joint={joint?.name ?? muscle.target_joint_id}
          </span>
        </h3>
        <div className="space-y-1.5 rounded-lg border border-zinc-800 bg-zinc-900/30 p-3">
          <Sparkline
            label="activation"
            sample={sampleAct}
            color="oklch(0.82 0.15 45)"
            min={-1}
            max={1}
          />
          {joint && (
            <>
              <Sparkline
                label={`${joint.name} angle`}
                sample={sampleJa}
                color="oklch(0.78 0.14 200)"
                format={(v) => v.toFixed(3)}
              />
              <Sparkline
                label={`${joint.name} velocity`}
                sample={sampleJv}
                color="oklch(0.78 0.14 140)"
                format={(v) => v.toFixed(3)}
              />
            </>
          )}
        </div>
      </section>

      <section>
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-xs font-semibold tracking-wider text-zinc-400 uppercase">
            Muscle properties (live)
          </h3>
          <div className="flex gap-2">
            <button
              onClick={() => setStaged({})}
              disabled={nDirty === 0}
              className={clsx(
                "rounded-md bg-zinc-800 px-3 py-1 text-xs text-zinc-200",
                "hover:bg-zinc-700 disabled:cursor-not-allowed disabled:opacity-40",
              )}
            >
              Discard
            </button>
            <button
              onClick={() => void submit()}
              disabled={nDirty === 0 || busy}
              className={clsx(
                "rounded-md bg-accent/80 px-3 py-1 text-xs font-medium text-zinc-950",
                "hover:bg-accent disabled:cursor-not-allowed disabled:opacity-40",
              )}
            >
              {busy ? "Applying…" : `Apply ${nDirty}`}
            </button>
          </div>
        </div>
        <div className="grid grid-cols-1 gap-1 rounded-lg border border-zinc-800 bg-zinc-900/30 p-2 md:grid-cols-2">
          <ScalarRow
            label="forcerange min"
            value={stagedValue(
              `actuator:${muscle.id}:forcerange:0`,
              muscle.forcerange[0],
            )}
            dirty={`actuator:${muscle.id}:forcerange:0` in staged}
            min={-20}
            max={0}
            step={0.1}
            onChange={(v) =>
              stage(
                { target: "actuator", id: muscle.id, field: "forcerange", index: 0, value: v },
                v,
              )
            }
          />
          <ScalarRow
            label="forcerange max"
            value={stagedValue(
              `actuator:${muscle.id}:forcerange:1`,
              muscle.forcerange[1],
            )}
            dirty={`actuator:${muscle.id}:forcerange:1` in staged}
            min={0}
            max={20}
            step={0.1}
            onChange={(v) =>
              stage(
                { target: "actuator", id: muscle.id, field: "forcerange", index: 1, value: v },
                v,
              )
            }
          />
          <ScalarRow
            label="gear[0]"
            value={stagedValue(`actuator:${muscle.id}:gear:0`, muscle.gear[0])}
            dirty={`actuator:${muscle.id}:gear:0` in staged}
            min={0}
            max={5}
            step={0.01}
            onChange={(v) =>
              stage(
                { target: "actuator", id: muscle.id, field: "gear", index: 0, value: v },
                v,
              )
            }
          />
        </div>
      </section>

      {joint && (
        <section>
          <h3 className="mb-2 text-xs font-semibold tracking-wider text-zinc-400 uppercase">
            Target joint (live)
          </h3>
          <div className="grid grid-cols-1 gap-1 rounded-lg border border-zinc-800 bg-zinc-900/30 p-2 md:grid-cols-2">
            <ScalarRow
              label="damping"
              value={stagedValue(`joint:${joint.id}:damping:-`, joint.damping)}
              dirty={`joint:${joint.id}:damping:-` in staged}
              min={0}
              max={20}
              step={0.05}
              onChange={(v) =>
                stage({ target: "joint", id: joint.id, field: "damping", value: v }, v)
              }
            />
            <ScalarRow
              label="armature"
              value={stagedValue(`joint:${joint.id}:armature:-`, joint.armature)}
              dirty={`joint:${joint.id}:armature:-` in staged}
              min={0}
              max={0.01}
              step={0.00001}
              onChange={(v) =>
                stage({ target: "joint", id: joint.id, field: "armature", value: v }, v)
              }
            />
            <div className="col-span-full px-2 py-1 text-[11px] text-zinc-500">
              range = [{joint.range[0].toFixed(3)}, {joint.range[1].toFixed(3)}] rad
            </div>
          </div>
        </section>
      )}
    </div>
  );
}

function ScalarRow({
  label,
  value,
  dirty,
  min,
  max,
  step,
  onChange,
}: {
  label: string;
  value: number;
  dirty: boolean;
  min: number;
  max: number;
  step: number;
  onChange: (v: number) => void;
}) {
  const coerce = (s: string) => {
    if (s === "" || s === "-") return value;
    const n = parseFloat(s);
    return Number.isFinite(n) ? n : value;
  };
  return (
    <div
      className={clsx(
        "flex items-center gap-2 rounded px-2 py-1",
        dirty && "bg-amber-950/30 ring-1 ring-amber-700/40",
      )}
    >
      <label className="w-28 shrink-0 font-mono text-[11px] text-zinc-300">
        {label}
      </label>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(coerce(e.target.value))}
        className="h-1 flex-1 cursor-pointer accent-accent"
      />
      <input
        type="number"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(coerce(e.target.value))}
        className="w-24 rounded bg-zinc-950 px-1.5 py-0.5 text-right font-mono text-[11px] text-zinc-100 ring-1 ring-zinc-800"
      />
    </div>
  );
}

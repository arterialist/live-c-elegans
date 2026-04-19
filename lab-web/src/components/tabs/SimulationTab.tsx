import { useEffect, useMemo } from "react";
import { clsx } from "clsx";
import { TabShell } from "./TabShell";
import { useSchemaStore } from "../../state/schema";
import { ParamControl } from "../ParamControl";
import type { ParameterSpec } from "../../api/http";

export function SimulationTab() {
  const specs = useSchemaStore((s) => s.specs);
  const pending = useSchemaStore((s) => s.pending);
  const dirty = useSchemaStore((s) => s.dirty);
  const loading = useSchemaStore((s) => s.loading);
  const error = useSchemaStore((s) => s.error);
  const lastResult = useSchemaStore((s) => s.lastResult);
  const load = useSchemaStore((s) => s.load);
  const stage = useSchemaStore((s) => s.stage);
  const clearDirty = useSchemaStore((s) => s.clearDirty);
  const submit = useSchemaStore((s) => s.submit);
  const commitPending = useSchemaStore((s) => s.commitPending);

  useEffect(() => {
    if (specs.length === 0 && !loading) void load();
  }, [specs.length, loading, load]);

  const groups = useMemo(() => groupByCategory(specs), [specs]);
  const nDirty = Object.keys(dirty).length;
  const nPending = Object.keys(pending).length;

  return (
    <TabShell
      title="Simulation settings"
      subtitle="Live parameters apply instantly; rebuild parameters queue until Apply pending."
    >
      <div className="space-y-5">
        {error && (
          <div className="rounded-md bg-red-950/40 px-3 py-2 text-sm text-red-300 ring-1 ring-red-900/50">
            {error}
          </div>
        )}
        <div className="sticky top-0 z-10 -mx-5 flex items-center justify-between border-b border-zinc-800/80 bg-zinc-950/85 px-5 py-2 backdrop-blur">
          <div className="text-xs text-zinc-500">
            {nDirty > 0 && (
              <span className="mr-3 font-medium text-amber-300">
                {nDirty} unsubmitted
              </span>
            )}
            {nPending > 0 && (
              <span className="font-medium text-blue-300">
                {nPending} pending rebuild
              </span>
            )}
            {nDirty === 0 && nPending === 0 && (
              <span className="text-zinc-500">All synced</span>
            )}
          </div>
          <div className="flex gap-2">
            <ActionButton
              onClick={() => clearDirty()}
              disabled={nDirty === 0}
              label="Discard"
            />
            <ActionButton
              onClick={() => void submit()}
              disabled={nDirty === 0}
              label="Submit"
              primary
            />
            <ActionButton
              onClick={() => void commitPending()}
              disabled={nPending === 0}
              label="Apply pending"
              variant="warn"
            />
          </div>
        </div>

        {groups.map(([groupName, groupSpecs]) => (
          <section key={groupName}>
            <h3 className="mb-2 text-xs font-semibold tracking-wider text-zinc-400 uppercase">
              {groupName}
            </h3>
            <div className="space-y-1 rounded-lg border border-zinc-800 bg-zinc-900/30 p-1.5">
              {groupSpecs.map((spec) => (
                <ParamControl
                  key={spec.path}
                  spec={spec}
                  value={spec.path in dirty ? dirty[spec.path] : spec.value}
                  dirty={spec.path in dirty}
                  pending={spec.path in pending}
                  onChange={(v) => stage(spec.path, v)}
                />
              ))}
            </div>
          </section>
        ))}

        {lastResult && (
          <div className="rounded-md bg-zinc-900/50 px-3 py-2 text-xs text-zinc-400">
            Last submit: {lastResult.applied.length} applied,{" "}
            {lastResult.pending.length} queued, {lastResult.failed.length}{" "}
            failed.
            {lastResult.failed.length > 0 && (
              <ul className="mt-1 text-red-300">
                {lastResult.failed.map((f) => (
                  <li key={f.path}>
                    {f.path}: {f.error}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
    </TabShell>
  );
}

function groupByCategory(specs: ParameterSpec[]): [string, ParameterSpec[]][] {
  const by = new Map<string, ParameterSpec[]>();
  for (const s of specs) {
    if (!s.path.startsWith("sim.")) continue;
    if (s.path.startsWith("sim.mujoco.")) continue;
    if (!by.has(s.group)) by.set(s.group, []);
    by.get(s.group)!.push(s);
  }
  return [...by.entries()];
}

function ActionButton({
  onClick,
  disabled,
  label,
  primary,
  variant,
}: {
  onClick: () => void;
  disabled: boolean;
  label: string;
  primary?: boolean;
  variant?: "warn";
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={clsx(
        "rounded-md px-3 py-1 text-xs font-medium transition-colors",
        "focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent",
        "disabled:cursor-not-allowed disabled:opacity-40",
        primary
          ? "bg-accent/80 text-zinc-950 hover:bg-accent"
          : variant === "warn"
            ? "bg-amber-600/80 text-zinc-950 hover:bg-amber-500"
            : "bg-zinc-800 text-zinc-200 hover:bg-zinc-700",
      )}
    >
      {label}
    </button>
  );
}

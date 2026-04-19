import { useEffect, useState } from "react";
import { clsx } from "clsx";
import { useBodyStore } from "../../state/body";
import { BodyWYSIWYG } from "../BodyWYSIWYG";
import { MuscleMap } from "../MuscleMap";
import { MuscleInspector } from "../MuscleInspector";
import { TabShell } from "./TabShell";

type Sub = "wysiwyg" | "map" | "inspector";

const SUBS: { id: Sub; label: string }[] = [
  { id: "wysiwyg", label: "WYSIWYG" },
  { id: "map", label: "Muscle Map" },
  { id: "inspector", label: "Inspector" },
];

export function BodyTab() {
  const view = useBodyStore((s) => s.view);
  const loading = useBodyStore((s) => s.loading);
  const error = useBodyStore((s) => s.error);
  const selection = useBodyStore((s) => s.selection);
  const load = useBodyStore((s) => s.load);
  const [sub, setSub] = useState<Sub>("wysiwyg");

  useEffect(() => {
    void load();
  }, [load]);

  // Auto-switch to inspector only from the map, not from WYSIWYG.
  useEffect(() => {
    if (!selection || selection.kind !== "muscle") return;
    if (sub === "map") setSub("inspector");
  }, [selection, sub]);

  const summary = view
    ? `${view.bodies.length - 1} segments · ${view.joints.length} joints · ${
        view.actuators.length
      } muscles`
    : loading
      ? "loading body…"
      : error
        ? `error: ${error}`
        : "";

  return (
    <TabShell
      title="Body"
      subtitle="MuJoCo model: segments, muscles, joints. Click a muscle to inspect and tune live."
    >
      <div className="flex min-h-0 flex-1 flex-col gap-3">
        <div className="flex items-center justify-between">
          <div className="flex gap-1 rounded-md bg-zinc-900/60 p-1">
            {SUBS.map((s) => (
              <button
                key={s.id}
                onClick={() => setSub(s.id)}
                className={clsx(
                  "rounded px-3 py-1 text-xs font-medium transition",
                  sub === s.id
                    ? "bg-zinc-800 text-zinc-100"
                    : "text-zinc-400 hover:text-zinc-200",
                )}
              >
                {s.label}
              </button>
            ))}
          </div>
          <div className="font-mono text-[11px] text-zinc-500">
            {summary}
            {selection && selection.kind === "muscle" && (
              <>
                <span className="mx-2 text-zinc-700">|</span>
                selected: <span className="text-accent">{selection.name}</span>
              </>
            )}
          </div>
        </div>

        <div className="min-h-0 flex-1">
          {sub === "wysiwyg" && (
            <div className="h-[300px] rounded-lg border border-zinc-800 bg-zinc-950">
              <BodyWYSIWYG />
            </div>
          )}
          {sub === "map" && (
            <div className="h-[240px] rounded-lg border border-zinc-800 bg-zinc-950">
              <MuscleMap />
            </div>
          )}
          {sub === "inspector" && <MuscleInspector />}
        </div>
      </div>
    </TabShell>
  );
}

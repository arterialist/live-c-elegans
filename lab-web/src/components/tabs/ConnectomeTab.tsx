import { useEffect, useRef, useState } from "react";
import { clsx } from "clsx";
import { TabShell } from "./TabShell";
import { useConnectomeStore } from "../../state/connectome";
import { NeuronMap } from "../NeuronMap";
import { NeuronTable } from "../NeuronTable";
import { NeuronInspector } from "../NeuronInspector";
import { GuideButton, type GuideContent } from "../ui/GuideModal";

type SubTab = "wysiwyg" | "table" | "inspector";

const SUB_TABS: { id: SubTab; label: string }[] = [
  { id: "wysiwyg", label: "WYSIWYG" },
  { id: "table", label: "Table" },
  { id: "inspector", label: "Inspector" },
];

export function ConnectomeTab() {
  const [sub, setSub] = useState<SubTab>("wysiwyg");
  const neurons = useConnectomeStore((s) => s.neurons);
  const loading = useConnectomeStore((s) => s.loading);
  const error = useConnectomeStore((s) => s.error);
  const load = useConnectomeStore((s) => s.load);
  const selected = useConnectomeStore((s) => s.selected);
  const [showEdges, setShowEdges] = useState(true);
  const [edgeAlpha, setEdgeAlpha] = useState(0.15);

  useEffect(() => {
    if (neurons.length === 0 && !loading) void load();
  }, [neurons.length, loading, load]);

  // Switch to the Inspector when the user clicks a row in the Table; clicks
  // on the WYSIWYG keep the map visible.
  const prevSelected = useRef<string | null>(null);
  useEffect(() => {
    if (selected && selected !== prevSelected.current && sub === "table") {
      setSub("inspector");
    }
    prevSelected.current = selected;
  }, [selected, sub]);

  return (
    <TabShell
      title="Connectome"
      subtitle="Body-aligned 2D view; click a neuron in the map or table to inspect."
    >
      <div className="flex h-full flex-col gap-3">
        <div className="flex items-center justify-between gap-4">
          <div className="flex gap-1 rounded-md bg-zinc-900/60 p-0.5 ring-1 ring-zinc-800">
            {SUB_TABS.map((t) => (
              <button
                key={t.id}
                onClick={() => setSub(t.id)}
                className={clsx(
                  "rounded px-3 py-1 text-xs font-medium",
                  sub === t.id
                    ? "bg-zinc-800 text-zinc-100"
                    : "text-zinc-400 hover:text-zinc-200",
                )}
              >
                {t.label}
              </button>
            ))}
          </div>
          <div className="text-[11px] text-zinc-500">
            {selected ? (
              <span>
                Selected:{" "}
                <span className="font-mono text-accent">{selected}</span>
              </span>
            ) : (
              <span>No neuron selected</span>
            )}
          </div>
        </div>

        {error && (
          <div className="rounded-md bg-red-950/40 px-3 py-2 text-sm text-red-300 ring-1 ring-red-900/50">
            {error}
          </div>
        )}

        <div className="min-h-0 flex-1">
          {sub === "wysiwyg" && (
            <div className="flex h-full flex-col gap-2">
              <div className="flex items-center gap-4 rounded-md bg-zinc-900/40 px-3 py-2 text-xs text-zinc-400">
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={showEdges}
                    onChange={(e) => setShowEdges(e.target.checked)}
                    className="size-3.5 cursor-pointer accent-accent"
                  />
                  show edges
                  <GuideButton title="Show edges" guide={GUIDE_SHOW_EDGES} />
                </label>
                <div className="flex items-center gap-2">
                  <span>edge α</span>
                  <input
                    type="range"
                    min={0}
                    max={0.5}
                    step={0.01}
                    value={edgeAlpha}
                    onChange={(e) => setEdgeAlpha(parseFloat(e.target.value))}
                    className="h-1 w-32 cursor-pointer accent-accent"
                  />
                  <span className="font-mono tabular-nums">
                    {edgeAlpha.toFixed(2)}
                  </span>
                  <GuideButton title="Edge opacity (α)" guide={GUIDE_EDGE_ALPHA} />
                </div>
                <div className="ml-auto flex items-center gap-3 text-[11px]">
                  <Swatch cls="s" label="sensory" />
                  <Swatch cls="i" label="interneuron" />
                  <Swatch cls="m" label="motor" />
                </div>
              </div>
              <div className="min-h-0 flex-1">
                <NeuronMap showEdges={showEdges} edgeOpacity={edgeAlpha} />
              </div>
            </div>
          )}
          {sub === "table" && (
            <div className="h-full">
              <NeuronTable />
            </div>
          )}
          {sub === "inspector" && (
            <div className="h-full overflow-auto pr-1">
              <NeuronInspector />
            </div>
          )}
        </div>
      </div>
    </TabShell>
  );
}

const GUIDE_SHOW_EDGES: GuideContent = {
  summary:
    "Draw synaptic connections between neurons on the WYSIWYG map. Edges are coloured faintly and drawn before neuron disks so cell bodies always sit on top.",
  sections: [
    {
      heading: "When to hide edges",
      body: "With ~4800 edges the map can feel busy. Turn edges off to read cell-body positions and class colouring at a glance, or while panning/zooming on a lower-end machine.",
    },
    {
      heading: "When to show edges",
      body: "Useful when you are inspecting motor-interneuron-sensory layering, tracing a specific partner of the selected neuron, or sanity-checking symmetry after a connectome edit.",
    },
  ],
};

const GUIDE_EDGE_ALPHA: GuideContent = {
  summary:
    "Per-edge opacity multiplier. Applied on top of the edge colour so you can dial in the density of the connectome without losing visual hierarchy.",
  sections: [
    {
      heading: "Suggested values",
      body: (
        <ul className="list-disc space-y-1 pl-5">
          <li>
            <span className="text-zinc-200">0.05–0.10</span> — very dense graphs
            (default for the full 302-neuron view).
          </li>
          <li>
            <span className="text-zinc-200">0.15</span> — balanced default; edges
            are visible but don't drown out neurons.
          </li>
          <li>
            <span className="text-zinc-200">0.30+</span> — strong edges; good for
            small filtered subgraphs.
          </li>
        </ul>
      ),
    },
    {
      heading: "Notes",
      body: "The slider only affects rendering. It does not alter weights or the underlying connectome.",
    },
  ],
};

function Swatch({ cls, label }: { cls: "s" | "i" | "m"; label: string }) {
  const color =
    cls === "s"
      ? "hsl(190 70% 70%)"
      : cls === "i"
        ? "hsl(265 60% 72%)"
        : "hsl(25 80% 65%)";
  return (
    <span className="flex items-center gap-1.5">
      <span
        className="inline-block size-2.5 rounded-full"
        style={{ background: color }}
      />
      {label}
    </span>
  );
}

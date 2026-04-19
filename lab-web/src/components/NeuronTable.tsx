import { useMemo, useState } from "react";
import { clsx } from "clsx";
import { useConnectomeStore } from "../state/connectome";

type SortKey =
  | "name"
  | "type"
  | "layout_x"
  | "degree_in_chem"
  | "degree_out_chem"
  | "degree_in_gap"
  | "degree_out_gap";

export function NeuronTable() {
  const neurons = useConnectomeStore((s) => s.neurons);
  const selected = useConnectomeStore((s) => s.selected);
  const select = useConnectomeStore((s) => s.select);
  const [query, setQuery] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("layout_x");
  const [desc, setDesc] = useState(false);

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = q
      ? neurons.filter(
          (n) =>
            n.name.toLowerCase().includes(q) ||
            n.type.toLowerCase().includes(q),
        )
      : neurons;
    const sorted = [...filtered].sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      if (typeof av === "string" && typeof bv === "string")
        return desc ? bv.localeCompare(av) : av.localeCompare(bv);
      return desc ? (bv as number) - (av as number) : (av as number) - (bv as number);
    });
    return sorted;
  }, [neurons, query, sortKey, desc]);

  function toggleSort(k: SortKey) {
    if (k === sortKey) setDesc(!desc);
    else {
      setSortKey(k);
      setDesc(false);
    }
  }

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-md border border-zinc-800">
      <div className="flex items-center gap-2 border-b border-zinc-800 bg-zinc-900/40 px-2 py-1.5">
        <input
          type="search"
          placeholder="Filter by name or type…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="flex-1 rounded bg-zinc-950 px-2 py-1 font-mono text-xs text-zinc-200 ring-1 ring-zinc-800 focus:outline focus:outline-2 focus:outline-accent"
        />
        <span className="text-[11px] text-zinc-500">{rows.length} rows</span>
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        <table className="w-full text-left font-mono text-xs text-zinc-300">
          <thead className="sticky top-0 bg-zinc-900/90 text-zinc-400 backdrop-blur">
            <tr>
              <Th k="name" sortKey={sortKey} desc={desc} onClick={toggleSort}>
                Name
              </Th>
              <Th k="type" sortKey={sortKey} desc={desc} onClick={toggleSort}>
                Type
              </Th>
              <Th k="layout_x" sortKey={sortKey} desc={desc} onClick={toggleSort}>
                AP
              </Th>
              <Th
                k="degree_in_chem"
                sortKey={sortKey}
                desc={desc}
                onClick={toggleSort}
              >
                ↓chem
              </Th>
              <Th
                k="degree_out_chem"
                sortKey={sortKey}
                desc={desc}
                onClick={toggleSort}
              >
                ↑chem
              </Th>
              <Th
                k="degree_in_gap"
                sortKey={sortKey}
                desc={desc}
                onClick={toggleSort}
              >
                ↓gap
              </Th>
              <Th
                k="degree_out_gap"
                sortKey={sortKey}
                desc={desc}
                onClick={toggleSort}
              >
                ↑gap
              </Th>
            </tr>
          </thead>
          <tbody>
            {rows.map((n) => (
              <tr
                key={n.id}
                className={clsx(
                  "cursor-pointer border-t border-zinc-900/80 hover:bg-zinc-800/40",
                  n.name === selected && "bg-accent/20 text-accent",
                )}
                onClick={() =>
                  select(selected === n.name ? null : n.name)
                }
              >
                <td className="px-2 py-1 text-zinc-100">{n.name}</td>
                <td className="px-2 py-1 text-zinc-400">{n.type}</td>
                <td className="px-2 py-1 text-right tabular-nums">
                  {n.layout_x.toFixed(2)}
                </td>
                <td className="px-2 py-1 text-right tabular-nums">
                  {n.degree_in_chem}
                </td>
                <td className="px-2 py-1 text-right tabular-nums">
                  {n.degree_out_chem}
                </td>
                <td className="px-2 py-1 text-right tabular-nums">
                  {n.degree_in_gap}
                </td>
                <td className="px-2 py-1 text-right tabular-nums">
                  {n.degree_out_gap}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Th({
  k,
  sortKey,
  desc,
  onClick,
  children,
}: {
  k: SortKey;
  sortKey: SortKey;
  desc: boolean;
  onClick: (k: SortKey) => void;
  children: React.ReactNode;
}) {
  const active = k === sortKey;
  return (
    <th
      onClick={() => onClick(k)}
      className={clsx(
        "cursor-pointer select-none px-2 py-1 text-left font-semibold",
        active && "text-accent",
      )}
    >
      {children} {active ? (desc ? "▼" : "▲") : ""}
    </th>
  );
}

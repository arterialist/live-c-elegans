import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { clsx } from "clsx";
import {
  getNeuron,
  patchNeuron,
  type NeuronDetail,
  type NeuronFieldPatch,
} from "../api/http";
import { useConnectomeStore } from "../state/connectome";
import { useLabStore } from "../state/store";
import { Sparkline } from "./Sparkline";

type FieldKey =
  | "r_base"
  | "b_base"
  | "c"
  | "lambda_param"
  | "p"
  | "eta_post"
  | "eta_retro"
  | "delta_decay"
  | "beta_avg";

const SCALAR_FIELDS: {
  key: FieldKey;
  label: string;
  min: number;
  max: number;
  step: number;
  kind: "int" | "float";
}[] = [
  { key: "r_base", label: "r_base", min: 0.0, max: 5.0, step: 0.01, kind: "float" },
  { key: "b_base", label: "b_base", min: 0.0, max: 5.0, step: 0.01, kind: "float" },
  { key: "c", label: "cooldown c", min: 1, max: 200, step: 1, kind: "int" },
  {
    key: "lambda_param",
    label: "lambda",
    min: 1.0,
    max: 200.0,
    step: 0.5,
    kind: "float",
  },
  { key: "p", label: "p", min: 0.0, max: 5.0, step: 0.01, kind: "float" },
  { key: "eta_post", label: "eta_post", min: 0.0, max: 1.0, step: 0.001, kind: "float" },
  { key: "eta_retro", label: "eta_retro", min: 0.0, max: 1.0, step: 0.001, kind: "float" },
  {
    key: "delta_decay",
    label: "delta_decay",
    min: 0.0,
    max: 1.0,
    step: 0.001,
    kind: "float",
  },
  { key: "beta_avg", label: "beta_avg", min: 0.0, max: 1.0, step: 0.001, kind: "float" },
];

const PARAM_VECTOR_FIELDS = ["gamma", "w_r", "w_b", "w_tref"] as const;

/** Stable key so one logical control maps to one staged patch (last edit wins). */
function patchKeyFrom(
  p: Pick<NeuronFieldPatch, "field" | "index" | "subfield" | "vec_index">,
): string {
  return `${p.field}:${p.index ?? ""}:${p.subfield ?? ""}:${p.vec_index ?? ""}`;
}

export function NeuronInspector() {
  const selected = useConnectomeStore((s) => s.selected);
  const [detail, setDetail] = useState<NeuronDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  /** Staged neuron patches (Apply sends all at once; keys from ``patchKeyFrom``). */
  const [staged, setStaged] = useState<Record<string, NeuronFieldPatch>>({});
  const [busy, setBusy] = useState(false);
  const nameRef = useRef<string>("");

  const helloNames = useLabStore((s) => s.hello?.L.nm ?? []);
  const paulaIdx = useMemo(() => {
    if (!selected) return -1;
    return helloNames.indexOf(selected);
  }, [helloNames, selected]);

  useEffect(() => {
    if (!selected) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    setStaged({});
    getNeuron(selected)
      .then((d) => {
        if (cancelled) return;
        setDetail(d);
        nameRef.current = d.name;
        setLoading(false);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : String(err));
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selected]);

  useEffect(() => {
    if (detail) nameRef.current = detail.name;
  }, [detail]);

  const fireRateRef = useRef(0);

  const sampleS = useCallback(() => {
    if (paulaIdx < 0) return null;
    const latest = useLabStore.getState().latest;
    if (!latest?.running) return null;
    const S = latest.S;
    return S ? S[paulaIdx] : null;
  }, [paulaIdx]);

  const sampleFiredFlag = useCallback(() => {
    if (paulaIdx < 0) return null;
    const latest = useLabStore.getState().latest;
    if (!latest?.running) return null;
    const f = latest.fired;
    if (!f) return null;
    return f[paulaIdx] ? 1 : 0;
  }, [paulaIdx]);

  const sampleR = useCallback(() => {
    if (paulaIdx < 0) return null;
    const latest = useLabStore.getState().latest;
    if (!latest?.running) return null;
    const R = latest.R;
    return R ? R[paulaIdx] : null;
  }, [paulaIdx]);

  const sampleB = useCallback(() => {
    if (paulaIdx < 0) return null;
    const latest = useLabStore.getState().latest;
    if (!latest?.running) return null;
    const B = latest.B;
    return B ? B[paulaIdx] : null;
  }, [paulaIdx]);

  const sampleTref = useCallback(() => {
    if (paulaIdx < 0) return null;
    const latest = useLabStore.getState().latest;
    if (!latest?.running) return null;
    const T = latest.Tref;
    return T ? T[paulaIdx] : null;
  }, [paulaIdx]);

  const sampleFire = useCallback(() => {
    if (paulaIdx < 0) return null;
    const latest = useLabStore.getState().latest;
    if (!latest?.running) return null;
    const f = latest.fired;
    if (!f) return null;
    const alpha = 0.05;
    fireRateRef.current += alpha * (f[paulaIdx] - fireRateRef.current);
    return fireRateRef.current;
  }, [paulaIdx]);

  const refreshDetail = useCallback(async () => {
    const name = nameRef.current;
    if (!name) return;
    setBusy(true);
    setError(null);
    try {
      setDetail(await getNeuron(name));
      setStaged({});
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }, []);

  const reconcileStage = useCallback((patch: NeuronFieldPatch, baseValue: number) => {
    const k = patchKeyFrom(patch);
    const nv = Number(patch.value);
    if (!Number.isFinite(nv)) return;
    setStaged((s) => {
      const next = { ...s };
      if (nv === baseValue) {
        delete next[k];
      } else {
        next[k] = { ...patch, value: nv };
      }
      return next;
    });
  }, []);

  const scalarDisplay = (k: FieldKey): number => {
    const pk = patchKeyFrom({ field: k });
    const v = staged[pk]?.value;
    return v !== undefined ? Number(v) : ((detail?.params[k] as number) ?? 0);
  };

  async function applyStaged() {
    if (!detail) return;
    const patches = Object.values(staged);
    if (patches.length === 0) return;
    setBusy(true);
    setError(null);
    try {
      const res = await patchNeuron(detail.name, patches);
      if (res.failed?.length) {
        setError(res.failed.map((x) => `${x.field}: ${x.error}`).join(" · "));
      }
      const fresh = await getNeuron(detail.name);
      setDetail(fresh);
      setStaged({});
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  if (!selected) {
    return (
      <div className="rounded-md border border-dashed border-zinc-800 p-6 text-center text-sm text-zinc-500">
        Select a neuron from the map or table to inspect its state.
      </div>
    );
  }

  if (loading || !detail) {
    return (
      <div className="rounded-md border border-zinc-800 p-6 text-sm text-zinc-500">
        Loading {selected}…
      </div>
    );
  }

  const nStaged = Object.keys(staged).length;
  const posts = detail.postsynaptic ?? [];
  const pres = detail.presynaptic ?? [];
  const p = detail.params;

  return (
    <div className="space-y-4">
      {error && (
        <div className="rounded-md bg-red-950/40 px-3 py-2 text-sm text-red-300 ring-1 ring-red-900/50">
          {error}
        </div>
      )}

      <section>
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-xs font-semibold tracking-wider text-zinc-400 uppercase">
            {detail.name}
            <span className="ml-2 font-mono text-[10px] text-zinc-500">
              paula_id={detail.paula_id}
            </span>
          </h3>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => void refreshDetail()}
              disabled={busy}
              className="rounded-md border border-zinc-700 bg-zinc-800 px-2 py-1 text-[11px] text-zinc-200 hover:bg-zinc-700 disabled:opacity-40"
            >
              Refresh state
            </button>
            <button
              type="button"
              onClick={() => setStaged({})}
              disabled={nStaged === 0 || busy}
              className={clsx(
                "rounded-md bg-zinc-800 px-2 py-1 text-[11px] text-zinc-200",
                "hover:bg-zinc-700 disabled:cursor-not-allowed disabled:opacity-40",
              )}
            >
              Discard
            </button>
            <button
              type="button"
              onClick={() => void applyStaged()}
              disabled={nStaged === 0 || busy}
              className={clsx(
                "rounded-md bg-accent/80 px-2 py-1 text-[11px] font-medium text-zinc-950",
                "hover:bg-accent disabled:cursor-not-allowed disabled:opacity-40",
              )}
            >
              {busy ? "Applying…" : `Apply ${nStaged}`}
            </button>
          </div>
        </div>
        <div className="space-y-1.5 rounded-lg border border-zinc-800 bg-zinc-900/30 p-3">
          <Sparkline
            label="S"
            sample={sampleS}
            markerSample={sampleFiredFlag}
            color="oklch(0.78 0.18 265)"
          />
          <Sparkline
            label="fire rate"
            sample={sampleFire}
            color="oklch(0.85 0.18 25)"
            min={0}
            max={1}
            format={(v) => v.toFixed(3)}
          />
          <Sparkline label="r" sample={sampleR} color="oklch(0.85 0.14 140)" />
          <Sparkline label="b" sample={sampleB} color="oklch(0.85 0.14 200)" />
          <Sparkline
            label="t_ref"
            sample={sampleTref}
            color="oklch(0.82 0.15 60)"
            min={0}
            format={(v) => v.toFixed(1)}
          />
          <div className="mt-2 border-t border-zinc-800 pt-2">
            <div className="mb-1 font-mono text-[10px] uppercase tracking-wide text-zinc-500">
              Global neuromodulators (wire)
            </div>
            <p className="mb-1.5 text-[10px] leading-snug text-zinc-600">
              Simulation-wide M0 / M1 from the live stream (same signals as the
              worm HUD). Distinct from this neuron’s local{" "}
              <span className="font-mono text-zinc-500">M_vector</span> below.
            </p>
            <Sparkline
              label="M0 stress"
              sample={() => {
                const latest = useLabStore.getState().latest;
                if (!latest?.running) return null;
                return latest.neuromod[0] ?? null;
              }}
              color="oklch(0.8 0.17 30)"
              min={0}
              max={1}
              format={(v) => v.toFixed(3)}
            />
            <Sparkline
              label="M1 reward"
              sample={() => {
                const latest = useLabStore.getState().latest;
                if (!latest?.running) return null;
                return latest.neuromod[1] ?? null;
              }}
              color="oklch(0.8 0.17 140)"
              min={0}
              max={1}
              format={(v) => v.toFixed(3)}
            />
          </div>
          <div className="mt-2 border-t border-zinc-800 pt-2">
            <div className="mb-1 font-mono text-[10px] uppercase tracking-wide text-zinc-500">
              pq_len (read-only)
            </div>
            <div className="font-mono text-xs text-zinc-300">{detail.pq_len}</div>
          </div>
        </div>
      </section>

      <section className="rounded-lg border border-zinc-800 bg-zinc-900/20 p-3">
        <h4 className="mb-2 text-[10px] font-semibold tracking-wider text-zinc-400 uppercase">
          Runtime state
        </h4>
        <p className="mb-2 text-[10px] text-zinc-500">
          Edit values, then <span className="text-zinc-400">Apply</span> above.
          Amber highlight = staged change. Matching the server value again
          removes the staging entry.
        </p>
        <div className="grid max-w-xl grid-cols-1 gap-1.5 sm:grid-cols-2">
          {(
            [
              ["S", detail.S],
              ["O", detail.O],
              ["r", detail.r],
              ["b", detail.b],
              ["t_ref", detail.t_ref],
              ["F_avg", detail.F_avg],
              ["t_last_fire", detail.t_last_fire],
            ] as const
          ).map(([k, v]) => (
            <LivePatchFloat
              key={k}
              label={k}
              field={k}
              baseValue={v}
              stagedMap={staged}
              disabled={busy}
              step={k === "t_last_fire" ? 1 : k === "O" ? 0.01 : 0.001}
              buildPatch={(nv) => ({ field: k, value: nv })}
              onStage={reconcileStage}
            />
          ))}
        </div>
        <div className="mt-3 space-y-1.5">
          <div className="text-[10px] font-semibold tracking-wide text-zinc-500 uppercase">
            M_vector (per-neuron neuromod state)
          </div>
          {detail.M_vector.map((mv, i) => (
            <LivePatchFloat
              key={i}
              label={`M[${i}]`}
              field="M_vector"
              index={i}
              baseValue={mv}
              stagedMap={staged}
              disabled={busy}
              step={0.001}
              buildPatch={(nv) => ({ field: "M_vector", index: i, value: nv })}
              onStage={reconcileStage}
            />
          ))}
        </div>
      </section>

      <section className="rounded-lg border border-zinc-800 bg-zinc-900/20 p-3">
        <h4 className="mb-2 text-[10px] font-semibold tracking-wider text-zinc-400 uppercase">
          Parameter vectors
        </h4>
        <div className="space-y-3">
          {PARAM_VECTOR_FIELDS.map((vk) => (
            <div key={vk}>
              <div className="mb-1 font-mono text-[10px] text-zinc-500">{vk}</div>
              <div className="flex flex-wrap gap-x-3 gap-y-1">
                {p[vk].map((cv, i) => (
                  <LivePatchFloat
                    key={`${vk}-${i}`}
                    label={`[${i}]`}
                    field={vk}
                    index={i}
                    baseValue={cv}
                    stagedMap={staged}
                    disabled={busy}
                    step={0.001}
                    className="min-w-[140px]"
                    buildPatch={(nv) => ({ field: vk, index: i, value: nv })}
                    onStage={reconcileStage}
                  />
                ))}
              </div>
            </div>
          ))}
        </div>
        <p className="mt-2 text-[10px] text-zinc-600">
          num_neuromodulators={p.num_neuromodulators} · num_inputs=
          {p.num_inputs} (read-only; resizing requires a network rebuild)
        </p>
      </section>

      <section>
        <h3 className="mb-2 text-xs font-semibold tracking-wider text-zinc-400 uppercase">
          Scalar parameters
        </h3>
        <p className="mb-2 text-[10px] text-zinc-500">
          Same staging rules — use the header <span className="text-zinc-400">Apply</span>{" "}
          / <span className="text-zinc-400">Discard</span>.
        </p>
        <div className="grid grid-cols-1 gap-1 rounded-lg border border-zinc-800 bg-zinc-900/30 p-2 md:grid-cols-2">
          {SCALAR_FIELDS.map((f) => (
            <ScalarRow
              key={f.key}
              label={f.label}
              value={scalarDisplay(f.key)}
              dirty={patchKeyFrom({ field: f.key }) in staged}
              min={f.min}
              max={f.max}
              step={f.step}
              kind={f.kind}
              onChange={(v) =>
                reconcileStage(
                  { field: f.key, value: v },
                  (detail.params[f.key] as number) ?? 0,
                )
              }
            />
          ))}
        </div>
      </section>

      <section className="rounded-lg border border-zinc-800 bg-zinc-900/20 p-3">
        <h4 className="mb-2 text-[10px] font-semibold tracking-wider text-zinc-400 uppercase">
          Postsynaptic weights (u_i)
        </h4>
        <p className="mb-2 text-[10px] text-zinc-500">
          Staged edits (amber cells); apply with the header{" "}
          <span className="text-zinc-400">Apply</span> button.
        </p>
        <div className="max-h-72 overflow-auto rounded border border-zinc-800/80">
          <table className="w-full min-w-[520px] border-collapse text-left text-[10px]">
            <thead className="sticky top-0 z-10 bg-zinc-950/95">
              <tr className="border-b border-zinc-800 text-zinc-500">
                <th className="px-1.5 py-1 font-medium">slot</th>
                <th className="px-1.5 py-1 font-medium">from</th>
                <th className="px-1.5 py-1 font-medium">info</th>
                <th className="px-1.5 py-1 font-medium">plast</th>
                <th className="px-1.5 py-1 font-medium">V</th>
                {Array.from(
                  {
                    length:
                      posts[0]?.adapt.length ??
                      detail.M_vector.length ??
                      p.num_neuromodulators,
                  },
                  (_, ai) => (
                    <th key={ai} className="px-1.5 py-1 font-medium">
                      adapt[{ai}]
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody>
              {posts.map((row) => (
                <tr
                  key={row.id}
                  className="border-b border-zinc-800/60 odd:bg-zinc-950/40"
                >
                  <td className="px-1.5 py-0.5 font-mono text-zinc-400">{row.id}</td>
                  <td className="max-w-[100px] truncate px-1.5 py-0.5 font-mono text-zinc-300">
                    {row.pre_name ?? "—"}
                  </td>
                  <td
                    className={clsx(
                      "p-0.5",
                      patchKeyFrom({
                        field: "postsynaptic",
                        index: row.id,
                        subfield: "info",
                      }) in staged &&
                        "bg-amber-950/30 ring-1 ring-amber-700/35 ring-inset",
                    )}
                  >
                    <TableNum
                      patchKey={patchKeyFrom({
                        field: "postsynaptic",
                        index: row.id,
                        subfield: "info",
                      })}
                      baseValue={row.info}
                      stagedMap={staged}
                      disabled={busy}
                      buildPatch={(nv) => ({
                        field: "postsynaptic",
                        index: row.id,
                        subfield: "info",
                        value: nv,
                      })}
                      onStage={reconcileStage}
                    />
                  </td>
                  <td
                    className={clsx(
                      "p-0.5",
                      patchKeyFrom({
                        field: "postsynaptic",
                        index: row.id,
                        subfield: "plast",
                      }) in staged &&
                        "bg-amber-950/30 ring-1 ring-amber-700/35 ring-inset",
                    )}
                  >
                    <TableNum
                      patchKey={patchKeyFrom({
                        field: "postsynaptic",
                        index: row.id,
                        subfield: "plast",
                      })}
                      baseValue={row.plast}
                      stagedMap={staged}
                      disabled={busy}
                      buildPatch={(nv) => ({
                        field: "postsynaptic",
                        index: row.id,
                        subfield: "plast",
                        value: nv,
                      })}
                      onStage={reconcileStage}
                    />
                  </td>
                  <td
                    className={clsx(
                      "p-0.5",
                      patchKeyFrom({
                        field: "postsynaptic",
                        index: row.id,
                        subfield: "potential",
                      }) in staged &&
                        "bg-amber-950/30 ring-1 ring-amber-700/35 ring-inset",
                    )}
                  >
                    <TableNum
                      patchKey={patchKeyFrom({
                        field: "postsynaptic",
                        index: row.id,
                        subfield: "potential",
                      })}
                      baseValue={row.potential}
                      stagedMap={staged}
                      disabled={busy}
                      buildPatch={(nv) => ({
                        field: "postsynaptic",
                        index: row.id,
                        subfield: "potential",
                        value: nv,
                      })}
                      onStage={reconcileStage}
                    />
                  </td>
                  {row.adapt.map((av, ai) => (
                    <td
                      key={ai}
                      className={clsx(
                        "p-0.5",
                        patchKeyFrom({
                          field: "postsynaptic",
                          index: row.id,
                          subfield: "adapt",
                          vec_index: ai,
                        }) in staged &&
                          "bg-amber-950/30 ring-1 ring-amber-700/35 ring-inset",
                      )}
                    >
                      <TableNum
                        patchKey={patchKeyFrom({
                          field: "postsynaptic",
                          index: row.id,
                          subfield: "adapt",
                          vec_index: ai,
                        })}
                        baseValue={av}
                        stagedMap={staged}
                        disabled={busy}
                        buildPatch={(nv) => ({
                          field: "postsynaptic",
                          index: row.id,
                          subfield: "adapt",
                          vec_index: ai,
                          value: nv,
                        })}
                        onStage={reconcileStage}
                      />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="rounded-lg border border-zinc-800 bg-zinc-900/20 p-3">
        <h4 className="mb-2 text-[10px] font-semibold tracking-wider text-zinc-400 uppercase">
          Presynaptic terminals (u_o)
        </h4>
        <p className="mb-2 text-[10px] text-zinc-500">
          Same staging as postsynaptic — header <span className="text-zinc-400">Apply</span>.
        </p>
        <div className="max-h-56 overflow-auto rounded border border-zinc-800/80">
          <table className="w-full min-w-[360px] border-collapse text-left text-[10px]">
            <thead className="sticky top-0 z-10 bg-zinc-950/95">
              <tr className="border-b border-zinc-800 text-zinc-500">
                <th className="px-1.5 py-1 font-medium">term</th>
                <th className="px-1.5 py-1 font-medium">u_o info</th>
                <th className="px-1.5 py-1 font-medium">u_i_retro</th>
                {Array.from(
                  { length: pres[0]?.u_o_mod.length ?? p.num_neuromodulators },
                  (_, mi) => (
                    <th key={mi} className="px-1.5 py-1 font-medium">
                      mod[{mi}]
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody>
              {pres.map((row) => (
                <tr
                  key={row.id}
                  className="border-b border-zinc-800/60 odd:bg-zinc-950/40"
                >
                  <td className="px-1.5 py-0.5 font-mono text-zinc-400">{row.id}</td>
                  <td
                    className={clsx(
                      "p-0.5",
                      patchKeyFrom({
                        field: "presynaptic",
                        index: row.id,
                        subfield: "u_o_info",
                      }) in staged &&
                        "bg-amber-950/30 ring-1 ring-amber-700/35 ring-inset",
                    )}
                  >
                    <TableNum
                      patchKey={patchKeyFrom({
                        field: "presynaptic",
                        index: row.id,
                        subfield: "u_o_info",
                      })}
                      baseValue={row.u_o_info}
                      stagedMap={staged}
                      disabled={busy}
                      buildPatch={(nv) => ({
                        field: "presynaptic",
                        index: row.id,
                        subfield: "u_o_info",
                        value: nv,
                      })}
                      onStage={reconcileStage}
                    />
                  </td>
                  <td
                    className={clsx(
                      "p-0.5",
                      patchKeyFrom({
                        field: "presynaptic",
                        index: row.id,
                        subfield: "u_i_retro",
                      }) in staged &&
                        "bg-amber-950/30 ring-1 ring-amber-700/35 ring-inset",
                    )}
                  >
                    <TableNum
                      patchKey={patchKeyFrom({
                        field: "presynaptic",
                        index: row.id,
                        subfield: "u_i_retro",
                      })}
                      baseValue={row.u_i_retro}
                      stagedMap={staged}
                      disabled={busy}
                      buildPatch={(nv) => ({
                        field: "presynaptic",
                        index: row.id,
                        subfield: "u_i_retro",
                        value: nv,
                      })}
                      onStage={reconcileStage}
                    />
                  </td>
                  {row.u_o_mod.map((mv, mi) => (
                    <td
                      key={mi}
                      className={clsx(
                        "p-0.5",
                        patchKeyFrom({
                          field: "presynaptic",
                          index: row.id,
                          subfield: "mod",
                          vec_index: mi,
                        }) in staged &&
                          "bg-amber-950/30 ring-1 ring-amber-700/35 ring-inset",
                      )}
                    >
                      <TableNum
                        patchKey={patchKeyFrom({
                          field: "presynaptic",
                          index: row.id,
                          subfield: "mod",
                          vec_index: mi,
                        })}
                        baseValue={mv}
                        stagedMap={staged}
                        disabled={busy}
                        buildPatch={(nv) => ({
                          field: "presynaptic",
                          index: row.id,
                          subfield: "mod",
                          vec_index: mi,
                          value: nv,
                        })}
                        onStage={reconcileStage}
                      />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function LivePatchFloat({
  label,
  field,
  index,
  subfield,
  vec_index,
  baseValue,
  stagedMap,
  disabled,
  step = 0.001,
  buildPatch,
  onStage,
  className,
}: {
  label: string;
  field: string;
  index?: number;
  subfield?: string;
  vec_index?: number;
  baseValue: number;
  stagedMap: Record<string, NeuronFieldPatch>;
  disabled?: boolean;
  step?: number | string;
  buildPatch: (v: number) => NeuronFieldPatch;
  onStage: (patch: NeuronFieldPatch, base: number) => void;
  className?: string;
}) {
  const pk = patchKeyFrom({ field, index, subfield, vec_index });
  const stagedVal = stagedMap[pk]?.value;
  const display = stagedVal !== undefined ? Number(stagedVal) : baseValue;
  const dirty = pk in stagedMap;
  const [text, setText] = useState(() => String(display));
  useEffect(() => {
    setText(String(display));
  }, [display]);
  const commit = () => {
    const n = Number(text);
    if (!Number.isFinite(n)) {
      setText(String(display));
      return;
    }
    onStage(buildPatch(n), baseValue);
  };
  return (
    <div
      className={clsx(
        "flex items-center gap-2 rounded px-1 py-0.5",
        dirty && "bg-amber-950/30 ring-1 ring-amber-700/40",
        className,
      )}
    >
      <span className="w-24 shrink-0 font-mono text-[10px] text-zinc-400">
        {label}
      </span>
      <input
        type="number"
        step={step}
        value={text}
        disabled={disabled}
        onChange={(e) => setText(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            commit();
          }
        }}
        className="w-full min-w-0 rounded border border-zinc-700 bg-zinc-950 px-1.5 py-0.5 font-mono text-[11px] text-zinc-100 focus:border-accent focus:outline-none disabled:opacity-40"
      />
    </div>
  );
}

function TableNum({
  patchKey,
  baseValue,
  stagedMap,
  disabled,
  buildPatch,
  onStage,
}: {
  patchKey: string;
  baseValue: number;
  stagedMap: Record<string, NeuronFieldPatch>;
  disabled?: boolean;
  buildPatch: (v: number) => NeuronFieldPatch;
  onStage: (patch: NeuronFieldPatch, base: number) => void;
}) {
  const stagedVal = stagedMap[patchKey]?.value;
  const display = stagedVal !== undefined ? Number(stagedVal) : baseValue;
  const [text, setText] = useState(() => String(display));
  useEffect(() => {
    setText(String(display));
  }, [display]);
  const commit = () => {
    const n = Number(text);
    if (!Number.isFinite(n)) {
      setText(String(display));
      return;
    }
    onStage(buildPatch(n), baseValue);
  };
  return (
    <input
      type="number"
      step={0.0001}
      value={text}
      disabled={disabled}
      onChange={(e) => setText(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          commit();
        }
      }}
      className="w-full min-w-[72px] rounded border border-zinc-700 bg-zinc-950 px-1 py-0.5 font-mono text-[10px] text-zinc-100 focus:border-accent focus:outline-none disabled:opacity-40"
    />
  );
}

function ScalarRow({
  label,
  value,
  dirty,
  min,
  max,
  step,
  kind,
  onChange,
}: {
  label: string;
  value: number;
  dirty: boolean;
  min: number;
  max: number;
  step: number;
  kind: "int" | "float";
  onChange: (v: number) => void;
}) {
  const coerce = (s: string) => {
    if (s === "" || s === "-") return value;
    const n = kind === "int" ? parseInt(s, 10) : parseFloat(s);
    return Number.isFinite(n) ? n : value;
  };
  return (
    <div
      className={clsx(
        "flex items-center gap-2 rounded px-2 py-1",
        dirty && "bg-amber-950/30 ring-1 ring-amber-700/40",
      )}
    >
      <label className="w-24 shrink-0 font-mono text-[11px] text-zinc-300">
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
        className="w-20 rounded bg-zinc-950 px-1.5 py-0.5 text-right font-mono text-[11px] text-zinc-100 ring-1 ring-zinc-800"
      />
    </div>
  );
}

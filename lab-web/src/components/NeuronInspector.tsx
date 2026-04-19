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

export function NeuronInspector() {
  const selected = useConnectomeStore((s) => s.selected);
  const [detail, setDetail] = useState<NeuronDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dirty, setDirty] = useState<Partial<Record<FieldKey, number>>>({});
  const [busy, setBusy] = useState(false);

  // Resolve paula_id from current hello order so we can index streamed arrays.
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
    setDirty({});
    getNeuron(selected)
      .then((d) => {
        if (cancelled) return;
        setDetail(d);
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

  // Fire-rate estimator: exponential moving average over the fired bit.
  const fireRateRef = useRef(0);

  const sampleS = useCallback(() => {
    if (paulaIdx < 0) return null;
    const S = useLabStore.getState().latest?.S;
    return S ? S[paulaIdx] : null;
  }, [paulaIdx]);

  const sampleR = useCallback(() => {
    if (paulaIdx < 0) return null;
    const R = useLabStore.getState().latest?.R;
    return R ? R[paulaIdx] : null;
  }, [paulaIdx]);

  const sampleB = useCallback(() => {
    if (paulaIdx < 0) return null;
    const B = useLabStore.getState().latest?.B;
    return B ? B[paulaIdx] : null;
  }, [paulaIdx]);

  const sampleTref = useCallback(() => {
    if (paulaIdx < 0) return null;
    const T = useLabStore.getState().latest?.Tref;
    return T ? T[paulaIdx] : null;
  }, [paulaIdx]);

  const sampleFire = useCallback(() => {
    if (paulaIdx < 0) return null;
    const f = useLabStore.getState().latest?.fired;
    if (!f) return null;
    const alpha = 0.05;
    fireRateRef.current += alpha * (f[paulaIdx] - fireRateRef.current);
    return fireRateRef.current;
  }, [paulaIdx]);

  const stage = (k: FieldKey, v: number) => setDirty({ ...dirty, [k]: v });
  const field = (k: FieldKey): number =>
    k in dirty ? (dirty[k] as number) : ((detail?.params[k] as number) ?? 0);

  async function submit() {
    if (!detail) return;
    const patches: NeuronFieldPatch[] = Object.entries(dirty).map(
      ([field, value]) => ({ field, value }),
    );
    if (patches.length === 0) return;
    setBusy(true);
    setError(null);
    try {
      await patchNeuron(detail.name, patches);
      const fresh = await getNeuron(detail.name);
      setDetail(fresh);
      setDirty({});
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

  const nDirty = Object.keys(dirty).length;

  return (
    <div className="space-y-4">
      {error && (
        <div className="rounded-md bg-red-950/40 px-3 py-2 text-sm text-red-300 ring-1 ring-red-900/50">
          {error}
        </div>
      )}

      <section>
        <h3 className="mb-2 text-xs font-semibold tracking-wider text-zinc-400 uppercase">
          {detail.name}
          <span className="ml-2 font-mono text-[10px] text-zinc-500">
            paula_id={detail.paula_id}
          </span>
        </h3>
        <div className="space-y-1.5 rounded-lg border border-zinc-800 bg-zinc-900/30 p-3">
          <Sparkline label="S" sample={sampleS} color="oklch(0.78 0.18 265)" />
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
              M_vector
            </div>
            {detail.M_vector.map((_, i) => (
              <Sparkline
                key={i}
                label={`M[${i}]`}
                sample={() => {
                  const m = useLabStore.getState().latest?.neuromod;
                  return m ? m[i] ?? null : null;
                }}
                color="oklch(0.85 0.12 340)"
                min={0}
                max={1}
              />
            ))}
            <Sparkline
              label="pq len"
              sample={() => detail.pq_len}
              color="oklch(0.7 0.1 0)"
              min={0}
              format={(v) => v.toFixed(0)}
            />
          </div>
        </div>
      </section>

      <section>
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-xs font-semibold tracking-wider text-zinc-400 uppercase">
            Parameters (live)
          </h3>
          <div className="flex gap-2">
            <button
              onClick={() => setDirty({})}
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
          {SCALAR_FIELDS.map((f) => (
            <ScalarRow
              key={f.key}
              label={f.label}
              value={field(f.key)}
              dirty={f.key in dirty}
              min={f.min}
              max={f.max}
              step={f.step}
              kind={f.kind}
              onChange={(v) => stage(f.key, v)}
            />
          ))}
        </div>
      </section>
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

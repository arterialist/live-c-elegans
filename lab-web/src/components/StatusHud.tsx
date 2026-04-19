import { useLabStore } from "../state/store";
import { useAppSettings } from "../state/app-settings";
import { Sparkline } from "./Sparkline";

/** Floating overlay on the worm canvas that shows free energy and the two
 *  global neuromodulators (M0 stress, M1 reward) with live sparklines. */
export function StatusHud() {
  const show = useAppSettings((s) => s.showHudPanel);
  if (!show) return null;

  return (
    <div className="pointer-events-none absolute top-3 right-3 w-[260px] rounded-lg border border-zinc-800 bg-zinc-950/80 p-2 shadow-lg ring-1 ring-black/40 backdrop-blur">
      <div className="mb-1 text-[10px] font-semibold tracking-wider text-zinc-400 uppercase">
        Status
      </div>
      <div className="flex flex-col gap-1">
        <Sparkline
          label="FE"
          sample={() => useLabStore.getState().latest?.fe ?? null}
          color="oklch(0.8 0.18 20)"
          format={(v) => v.toFixed(3)}
          height={24}
        />
        <Sparkline
          label="M0 stress"
          sample={() => useLabStore.getState().latest?.neuromod[0] ?? null}
          color="oklch(0.8 0.17 30)"
          min={0}
          max={1}
          format={(v) => v.toFixed(3)}
          height={20}
        />
        <Sparkline
          label="M1 reward"
          sample={() => useLabStore.getState().latest?.neuromod[1] ?? null}
          color="oklch(0.8 0.17 140)"
          min={0}
          max={1}
          format={(v) => v.toFixed(3)}
          height={20}
        />
      </div>
    </div>
  );
}

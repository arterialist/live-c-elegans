import { clsx } from "clsx";
import { WormCanvas } from "./WormCanvas";
import { WormCanvas3D } from "./WormCanvas3D";
import { SimulationTransportHud } from "./SimulationTransportHud";
import { StatusHud } from "./StatusHud";
import { useAppSettings, type WormViewMode } from "../state/app-settings";

export function RightPane() {
  const wormViewMode = useAppSettings((s) => s.wormViewMode);
  const setSetting = useAppSettings((s) => s.set);

  const setWormView = (mode: WormViewMode) => setSetting("wormViewMode", mode);

  return (
    <div className="relative flex h-full w-full flex-col bg-black">
      <div
        className="flex shrink-0 gap-0.5 border-b border-zinc-800 bg-zinc-950/90 px-2 pt-1.5"
        role="tablist"
        aria-label="Worm view"
      >
        {(["2d", "3d"] as const).map((mode) => (
          <button
            key={mode}
            type="button"
            role="tab"
            aria-selected={wormViewMode === mode}
            onClick={() => setWormView(mode)}
            className={clsx(
              "rounded-t-md px-3 py-1.5 text-xs font-medium tracking-wide uppercase transition",
              wormViewMode === mode
                ? "bg-zinc-900 text-zinc-100 ring-1 ring-zinc-700 ring-b-0"
                : "text-zinc-500 hover:text-zinc-300",
            )}
          >
            {mode === "2d" ? "2D" : "3D"}
          </button>
        ))}
      </div>
      {/* `relative` contains WormCanvas (`absolute inset-0`) so it cannot paint over the tab strip */}
      <div className="relative min-h-0 flex-1">
        {wormViewMode === "2d" ? <WormCanvas /> : <WormCanvas3D />}
      </div>
      <StatusHud />
      <SimulationTransportHud />
    </div>
  );
}

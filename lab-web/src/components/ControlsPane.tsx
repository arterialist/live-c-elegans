import { clsx } from "clsx";
import { useLabStore, type Tab } from "../state/store";
import { SimulationTab } from "./tabs/SimulationTab";
import { MujocoEngineTab } from "./tabs/MujocoEngineTab";
import { ConnectomeTab } from "./tabs/ConnectomeTab";
import { BodyTab } from "./tabs/BodyTab";
import { AppSettingsTab } from "./tabs/AppSettingsTab";
import { KeyHint } from "./ui/KeyHint";

const TABS: { id: Tab; label: string; key: string }[] = [
  { id: "sim", label: "Simulation settings", key: "1" },
  { id: "mujoco", label: "MuJoCo engine", key: "2" },
  { id: "connectome", label: "Connectome", key: "3" },
  { id: "body", label: "Body", key: "4" },
  { id: "app", label: "App settings", key: "5" },
];

export function ControlsPane() {
  const activeTab = useLabStore((s) => s.activeTab);
  const setTab = useLabStore((s) => s.setTab);
  return (
    <div className="flex h-full flex-col bg-zinc-950">
      <nav
        className="flex shrink-0 items-end gap-0 border-b border-zinc-800 px-3"
        role="tablist"
        aria-label="Lab sections"
      >
        {TABS.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={activeTab === t.id}
            onClick={() => setTab(t.id)}
            title={`${t.label} (press ${t.key})`}
            className={clsx(
              "flex items-center gap-2 px-4 py-2.5 text-sm transition-colors",
              "border-b-2 -mb-px",
              activeTab === t.id
                ? "border-accent text-zinc-100"
                : "border-transparent text-zinc-400 hover:text-zinc-200",
            )}
          >
            <span>{t.label}</span>
            <KeyHint size="xxs">{t.key}</KeyHint>
          </button>
        ))}
      </nav>
      <div className="min-h-0 flex-1 overflow-auto">
        {activeTab === "sim" && <SimulationTab />}
        {activeTab === "mujoco" && <MujocoEngineTab />}
        {activeTab === "connectome" && <ConnectomeTab />}
        {activeTab === "body" && <BodyTab />}
        {activeTab === "app" && <AppSettingsTab />}
      </div>
    </div>
  );
}

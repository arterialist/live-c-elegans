import { create } from "zustand";
import { persist } from "zustand/middleware";

export interface AppSettings {
  /** Default WebSocket URL lives on window.location; this overrides it. */
  wsUrlOverride: string;
  /** Samples retained in each sparkline (ring buffer). */
  historyLength: number;
  /** Soft cap on render FPS for heavy canvases. 0 = uncapped. */
  renderFpsCap: number;
  /** Overlay toggles on the worm canvas. */
  showGrid: boolean;
  showHudText: boolean;
  showHudPanel: boolean;
  showTrail: boolean;
}

interface AppSettingsStore extends AppSettings {
  set: <K extends keyof AppSettings>(key: K, value: AppSettings[K]) => void;
  reset: () => void;
}

const DEFAULTS: AppSettings = {
  wsUrlOverride: "",
  historyLength: 240,
  renderFpsCap: 60,
  showGrid: true,
  showHudText: true,
  showHudPanel: true,
  showTrail: false,
};

export const useAppSettings = create<AppSettingsStore>()(
  persist(
    (set) => ({
      ...DEFAULTS,
      set: (key, value) => set({ [key]: value } as Partial<AppSettingsStore>),
      reset: () => set({ ...DEFAULTS }),
    }),
    { name: "celegans-lab.app-settings/v1" },
  ),
);

import { create } from "zustand";
import {
  getConnectome,
  type EdgeInfo,
  type NeuronInfo,
} from "../api/http";

interface ConnectomeStore {
  neurons: NeuronInfo[];
  edges: EdgeInfo[];
  byId: Map<number, NeuronInfo>;
  byName: Map<string, NeuronInfo>;
  loading: boolean;
  error: string | null;
  load: () => Promise<void>;
  selected: string | null;
  select: (name: string | null) => void;
}

export const useConnectomeStore = create<ConnectomeStore>((set, get) => ({
  neurons: [],
  edges: [],
  byId: new Map(),
  byName: new Map(),
  loading: false,
  error: null,
  selected: null,
  load: async () => {
    if (get().loading) return;
    set({ loading: true, error: null });
    try {
      const r = await getConnectome();
      const byId = new Map<number, NeuronInfo>();
      const byName = new Map<string, NeuronInfo>();
      for (const n of r.neurons) {
        byId.set(n.id, n);
        byName.set(n.name, n);
      }
      set({
        neurons: r.neurons,
        edges: r.edges,
        byId,
        byName,
        loading: false,
      });
    } catch (err) {
      set({
        loading: false,
        error: err instanceof Error ? err.message : String(err),
      });
    }
  },
  select: (name) => set({ selected: name }),
}));

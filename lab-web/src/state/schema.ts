import { create } from "zustand";
import {
  applyPending,
  getSchema,
  postPatches,
  type ParameterSpec,
  type Patch,
  type PatchResult,
  type SchemaResponse,
} from "../api/http";

interface SchemaStore {
  specs: ParameterSpec[];
  pending: Record<string, unknown>;
  dirty: Record<string, unknown>;
  loading: boolean;
  error: string | null;
  lastResult: PatchResult | null;
  load: () => Promise<void>;
  stage: (path: string, value: unknown) => void;
  clearDirty: (path?: string) => void;
  submit: () => Promise<void>;
  commitPending: () => Promise<void>;
}

export const useSchemaStore = create<SchemaStore>((set, get) => ({
  specs: [],
  pending: {},
  dirty: {},
  loading: false,
  error: null,
  lastResult: null,
  load: async () => {
    set({ loading: true, error: null });
    try {
      const r: SchemaResponse = await getSchema();
      set({ specs: r.specs, pending: r.pending, loading: false });
    } catch (err) {
      set({ loading: false, error: errorMessage(err) });
    }
  },
  stage: (path, value) => {
    const dirty = { ...get().dirty, [path]: value };
    set({ dirty });
  },
  clearDirty: (path) => {
    if (path === undefined) {
      set({ dirty: {} });
      return;
    }
    const dirty = { ...get().dirty };
    delete dirty[path];
    set({ dirty });
  },
  submit: async () => {
    const dirty = get().dirty;
    const patches: Patch[] = Object.entries(dirty).map(([path, value]) => ({
      path,
      value,
    }));
    if (patches.length === 0) return;
    const result = await postPatches(patches);
    set({ lastResult: result, dirty: {} });
    await get().load();
  },
  commitPending: async () => {
    await applyPending();
    set({ lastResult: null });
    await get().load();
  },
}));

function errorMessage(err: unknown): string {
  if (err instanceof Error) return err.message;
  return String(err);
}

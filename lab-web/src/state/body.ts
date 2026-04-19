import { create } from "zustand";
import { getBody, type BodyView } from "../api/http";

export type BodySelection =
  | { kind: "muscle"; id: number; name: string }
  | { kind: "joint"; id: number; name: string }
  | { kind: "body"; id: number; name: string }
  | { kind: "pair"; id: number }
  | { kind: "opt" }
  | null;

interface BodyStore {
  view: BodyView | null;
  loading: boolean;
  error: string | null;
  selection: BodySelection;
  load: () => Promise<void>;
  refresh: () => Promise<void>;
  select: (s: BodySelection) => void;
  mergeActuatorForcerange: (id: number, lo: number, hi: number) => void;
  mergeActuatorGear: (id: number, index: number, v: number) => void;
  mergeJointDamping: (id: number, v: number) => void;
  mergeJointArmature: (id: number, v: number) => void;
  mergeBodyMass: (id: number, v: number) => void;
  mergeOpt: (field: "viscosity" | "density" | "timestep", v: number) => void;
  mergeGravity: (index: number, v: number) => void;
  mergePairFriction: (id: number, index: number, v: number) => void;
}

export const useBodyStore = create<BodyStore>((set, get) => ({
  view: null,
  loading: false,
  error: null,
  selection: null,
  async load() {
    if (get().view || get().loading) return;
    set({ loading: true, error: null });
    try {
      const view = await getBody();
      set({ view, loading: false });
    } catch (exc) {
      set({ loading: false, error: exc instanceof Error ? exc.message : String(exc) });
    }
  },
  async refresh() {
    set({ loading: true, error: null });
    try {
      const view = await getBody();
      set({ view, loading: false });
    } catch (exc) {
      set({ loading: false, error: exc instanceof Error ? exc.message : String(exc) });
    }
  },
  select(s) {
    set({ selection: s });
  },
  mergeActuatorForcerange(id, lo, hi) {
    const v = get().view;
    if (!v) return;
    const acts = v.actuators.map((a) =>
      a.id === id ? { ...a, forcerange: [lo, hi] } : a,
    );
    set({ view: { ...v, actuators: acts } });
  },
  mergeActuatorGear(id, index, val) {
    const v = get().view;
    if (!v) return;
    const acts = v.actuators.map((a) => {
      if (a.id !== id) return a;
      const gear = a.gear.slice();
      gear[index] = val;
      return { ...a, gear };
    });
    set({ view: { ...v, actuators: acts } });
  },
  mergeJointDamping(id, val) {
    const v = get().view;
    if (!v) return;
    const joints = v.joints.map((j) => (j.id === id ? { ...j, damping: val } : j));
    set({ view: { ...v, joints } });
  },
  mergeJointArmature(id, val) {
    const v = get().view;
    if (!v) return;
    const joints = v.joints.map((j) => (j.id === id ? { ...j, armature: val } : j));
    set({ view: { ...v, joints } });
  },
  mergeBodyMass(id, val) {
    const v = get().view;
    if (!v) return;
    const bodies = v.bodies.map((b) => (b.id === id ? { ...b, mass: val } : b));
    set({ view: { ...v, bodies } });
  },
  mergeOpt(field, val) {
    const v = get().view;
    if (!v) return;
    set({ view: { ...v, opt: { ...v.opt, [field]: val } } });
  },
  mergeGravity(index, val) {
    const v = get().view;
    if (!v) return;
    const gravity = v.opt.gravity.slice();
    gravity[index] = val;
    set({ view: { ...v, opt: { ...v.opt, gravity } } });
  },
  mergePairFriction(id, index, val) {
    const v = get().view;
    if (!v) return;
    const pairs = v.contact_pairs.map((p) => {
      if (p.id !== id) return p;
      const friction = p.friction.slice();
      friction[index] = val;
      return { ...p, friction };
    });
    set({ view: { ...v, contact_pairs: pairs } });
  },
}));

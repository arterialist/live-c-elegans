import { create } from "zustand";
import {
  decodeComMm,
  decodeFiredBits,
  decodeScaled,
  decodeSegmentsMm,
  JOINT_INT_SCALE,
  MUSCLE_INT_SCALE,
  NEURAL_INT_SCALE,
  TOUCH_INT_SCALE,
} from "../api/wire";

export type Tab = "sim" | "mujoco" | "connectome" | "body" | "app";

export interface HelloFrame {
  p: number;
  t: "h";
  m: string;
  L: { nm: string[]; ax: number[]; ay: number[] };
  M: {
    k: "s" | "m" | "i" | "u";
    ic: number;
    ig: number;
    oc: number;
    og: number;
  }[];
  L_body: { joints: string[]; muscles: string[]; touch: string[] };
}

export interface StateFrame {
  tick: number;
  running: boolean;
  segments_mm: Float32Array; // flat [x0,y0, x1,y1, …]
  com_mm: [number, number];
  S: Float32Array;
  R: Float32Array;
  B: Float32Array;
  Tref: Float32Array;
  fired: Uint8Array;
  ja: Float32Array;
  jv: Float32Array;
  tc: Float32Array;
  ma: Float32Array;
  neuromod: [number, number];
  fe: number;
}

interface LabStore {
  hello: HelloFrame | null;
  latest: StateFrame | null;
  connected: boolean;
  activeTab: Tab;
  setTab: (t: Tab) => void;
  onHello: (h: HelloFrame) => void;
  onState: (f: StateFrame) => void;
  setConnected: (c: boolean) => void;
}

export const useLabStore = create<LabStore>((set) => ({
  hello: null,
  latest: null,
  connected: false,
  activeTab: "sim",
  setTab: (t) => set({ activeTab: t }),
  onHello: (h) => set({ hello: h }),
  onState: (f) => set({ latest: f }),
  setConnected: (c) => set({ connected: c }),
}));

/** Decode one raw WS message, returning either hello, state, or null. */
export function decodeMessage(
  data: string,
  ctx: { nNeurons: number } | null,
): { hello: HelloFrame } | { state: StateFrame } | null {
  const obj = JSON.parse(data) as Record<string, unknown>;
  if (obj.t === "h") return { hello: obj as unknown as HelloFrame };
  if (obj.t === "s" && ctx) {
    const state: StateFrame = {
      tick: Number(obj.k),
      running: obj.z !== 1,
      segments_mm: decodeSegmentsMm(obj.sm as number[]),
      com_mm: decodeComMm(obj.cm as number[]),
      S: decodeScaled(obj.Si as number[], NEURAL_INT_SCALE),
      R: decodeScaled(obj.Ri as number[], NEURAL_INT_SCALE),
      B: decodeScaled(obj.Bi as number[], NEURAL_INT_SCALE),
      Tref: decodeScaled(obj.Trefi as number[], NEURAL_INT_SCALE),
      fired: decodeFiredBits(obj.Fb as string, ctx.nNeurons),
      ja: decodeScaled(obj.ja as number[], JOINT_INT_SCALE),
      jv: decodeScaled(obj.jv as number[], JOINT_INT_SCALE),
      tc: decodeScaled(obj.tc as number[], TOUCH_INT_SCALE),
      ma: decodeScaled(obj.ma as number[], MUSCLE_INT_SCALE),
      neuromod: [
        Number((obj.nm01 as number[])[0]),
        Number((obj.nm01 as number[])[1]),
      ],
      fe: Number(obj.fe),
    };
    return { state };
  }
  return null;
}

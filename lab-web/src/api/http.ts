import axios, { type AxiosInstance } from "axios";

export const http: AxiosInstance = axios.create({
  baseURL: "/api",
  timeout: 10_000,
  headers: { "Content-Type": "application/json" },
});

export interface TransportState {
  running: boolean;
  tick: number;
}

export type TransportAction = "play" | "pause" | "step";

export async function getTransport(): Promise<TransportState> {
  const r = await http.get<TransportState>("/sim/transport");
  return r.data;
}

export async function setTransport(action: TransportAction): Promise<TransportState> {
  const r = await http.post<TransportState>("/sim/transport", { action });
  return r.data;
}

export interface ParameterSpec {
  path: string;
  label: string;
  group: string;
  kind: "int" | "float" | "bool" | "enum" | "vec";
  apply: "live" | "rebuild";
  min: number | null;
  max: number | null;
  step: number | null;
  enum: string[] | null;
  help: string;
  value: unknown;
}

export interface SchemaResponse {
  specs: ParameterSpec[];
  pending: Record<string, unknown>;
}

export async function getSchema(): Promise<SchemaResponse> {
  const r = await http.get<SchemaResponse>("/schema");
  return r.data;
}

export interface NeuronInfo {
  id: number;
  name: string;
  type: string;
  class: "s" | "m" | "i" | "u";
  degree_in_chem: number;
  degree_out_chem: number;
  degree_in_gap: number;
  degree_out_gap: number;
  layout_x: number;
  layout_y: number;
}

export interface EdgeInfo {
  pre_id: number;
  post_id: number;
  type: "chemical" | "gap";
  weight: number;
}

export async function getConnectome(): Promise<{ neurons: NeuronInfo[]; edges: EdgeInfo[] }> {
  const r = await http.get<{ neurons: NeuronInfo[]; edges: EdgeInfo[] }>("/connectome");
  return r.data;
}

export interface NeuronDetail {
  name: string;
  paula_id: number;
  S: number;
  O: number;
  r: number;
  b: number;
  t_ref: number;
  M_vector: number[];
  pq_len: number;
  params: {
    r_base: number;
    b_base: number;
    c: number;
    lambda_param: number;
    p: number;
    eta_post: number;
    eta_retro: number;
    delta_decay: number;
    beta_avg: number;
    gamma: number[];
    w_r: number[];
    w_b: number[];
    w_tref: number[];
    num_neuromodulators: number;
    num_inputs: number;
  };
}

export async function getNeuron(name: string): Promise<NeuronDetail> {
  const r = await http.get<NeuronDetail>(`/neurons/${encodeURIComponent(name)}`);
  return r.data;
}

export interface NeuronFieldPatch {
  field: string;
  value: unknown;
  index?: number;
}

export async function patchNeuron(
  name: string,
  patches: NeuronFieldPatch[],
): Promise<{ applied: unknown[]; failed: { field: string; error: string }[] }> {
  const r = await http.post(`/neurons/${encodeURIComponent(name)}/patch`, {
    patches,
  });
  return r.data;
}

export interface BodyView {
  opt: { timestep: number; gravity: number[]; viscosity: number; density: number };
  bodies: { id: number; name: string; mass: number; inertia: number[] }[];
  joints: {
    id: number;
    name: string;
    range: number[];
    damping: number;
    armature: number;
  }[];
  actuators: {
    id: number;
    name: string;
    forcerange: number[];
    gear: number[];
    target_joint_id: number;
  }[];
  sensors: { id: number; name: string; dim: number }[];
  contact_pairs: {
    id: number;
    friction: number[];
    solref: number[];
    solimp: number[];
  }[];
}

export async function getBody(): Promise<BodyView> {
  const r = await http.get<BodyView>("/body");
  return r.data;
}

export interface MuscleDetail {
  name: string;
  id: number;
  ctrl: number;
  activation: number;
  forcerange: number[];
  gear: number[];
  target_joint_id: number;
}

export async function getMuscle(name: string): Promise<MuscleDetail> {
  const r = await http.get<MuscleDetail>(`/muscles/${encodeURIComponent(name)}`);
  return r.data;
}

export type BodyPatchTarget = "joint" | "actuator" | "body" | "pair" | "opt";

export interface BodyPatch {
  target: BodyPatchTarget;
  field: string;
  value: unknown;
  id?: number;
  index?: number;
}

export interface BodyPatchResult {
  applied: BodyPatch[];
  failed: (BodyPatch & { error: string })[];
}

export async function patchBody(patches: BodyPatch[]): Promise<BodyPatchResult> {
  const r = await http.post<BodyPatchResult>("/body/patch", { patches });
  return r.data;
}

export interface Patch {
  path: string;
  value: unknown;
}

export interface PatchResult {
  applied: string[];
  pending: string[];
  failed: { path: string; error: string }[];
}

export async function postPatches(patches: Patch[]): Promise<PatchResult> {
  const r = await http.post<PatchResult>("/patch", { patches });
  return r.data;
}

export interface ApplyPendingResult {
  applied: string[];
  failed: { path: string; error: string }[];
}

export async function applyPending(): Promise<ApplyPendingResult> {
  const r = await http.post<ApplyPendingResult>("/apply-pending");
  return r.data;
}

export async function resetSim(): Promise<{ ok: boolean }> {
  const r = await http.post<{ ok: boolean }>("/reset");
  return r.data;
}

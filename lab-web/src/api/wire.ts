/** WebSocket wire decode helpers, mirroring ``lab/wire.py``. */

export const PROTOCOL_VERSION = 5;
export const NEURAL_INT_SCALE = 1e4;
export const JOINT_INT_SCALE = 1e4;
export const MUSCLE_INT_SCALE = 1e4;
export const TOUCH_INT_SCALE = 1e6;
export const MM_INT_SCALE = 1e6;

export function decodeScaled(values: number[], scale: number): Float32Array {
  const out = new Float32Array(values.length);
  const inv = 1 / scale;
  for (let i = 0; i < values.length; i++) out[i] = values[i] * inv;
  return out;
}

/** Wire v5: ``sm`` is flat ``[x0,y0,z0, x1,y1,z1, …]`` in nm ints → mm floats. */
export function decodeSegmentsMm(sm: number[]): Float32Array {
  const n = Math.floor(sm.length / 3);
  const out = new Float32Array(n * 3);
  const inv = 1 / MM_INT_SCALE;
  for (let i = 0; i < n; i++) {
    out[i * 3] = sm[i * 3] * inv;
    out[i * 3 + 1] = sm[i * 3 + 1] * inv;
    out[i * 3 + 2] = sm[i * 3 + 2] * inv;
  }
  return out;
}

export function decodeComMm(cm: number[]): [number, number, number] {
  return [
    cm[0] / MM_INT_SCALE,
    cm[1] / MM_INT_SCALE,
    cm[2] / MM_INT_SCALE,
  ];
}

export function decodeFiredBits(b64: string, n: number): Uint8Array {
  const raw = atob(b64);
  const bytes = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
  const out = new Uint8Array(n);
  for (let i = 0; i < n; i++) out[i] = (bytes[i >> 3] >> (i & 7)) & 1;
  return out;
}

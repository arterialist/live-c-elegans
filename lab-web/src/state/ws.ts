import { useEffect } from "react";
import { decodeMessage, useLabStore } from "./store";

const WS_URL =
  typeof window !== "undefined"
    ? `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}/ws/state`
    : "";

/** Spin up a self-reconnecting WebSocket that feeds the store. */
export function useLabWebSocket(): void {
  const onHello = useLabStore((s) => s.onHello);
  const onState = useLabStore((s) => s.onState);
  const setConnected = useLabStore((s) => s.setConnected);

  useEffect(() => {
    let cancelled = false;
    let ws: WebSocket | null = null;
    let retry = 0;
    let nNeurons = 0;

    const connect = () => {
      if (cancelled) return;
      ws = new WebSocket(WS_URL);
      ws.binaryType = "arraybuffer";

      ws.onopen = () => {
        setConnected(true);
        retry = 0;
      };
      ws.onclose = () => {
        setConnected(false);
        if (cancelled) return;
        const delay = Math.min(5000, 200 * 2 ** retry++);
        setTimeout(connect, delay);
      };
      ws.onerror = () => {
        // onclose fires right after; handle reconnection there.
      };
      ws.onmessage = (ev) => {
        if (typeof ev.data !== "string") return;
        const decoded = decodeMessage(ev.data, nNeurons ? { nNeurons } : null);
        if (!decoded) return;
        if ("hello" in decoded) {
          nNeurons = decoded.hello.L.nm.length;
          onHello(decoded.hello);
        } else {
          onState(decoded.state);
        }
      };
    };

    connect();
    return () => {
      cancelled = true;
      ws?.close();
    };
  }, [onHello, onState, setConnected]);
}

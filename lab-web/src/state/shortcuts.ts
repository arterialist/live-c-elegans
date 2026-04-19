import { useEffect } from "react";
import { resetSim, setTransport } from "../api/http";
import { useLabStore, type Tab } from "./store";

const TAB_BY_KEY: Record<string, Tab> = {
  "1": "sim",
  "2": "mujoco",
  "3": "connectome",
  "4": "body",
  "5": "app",
};

/** Install global keyboard shortcuts for transport and tab switching.
 *
 *  - Space: toggle play/pause
 *  - N: step one tick
 *  - R: reset simulation
 *  - 1..5: simulation / MuJoCo engine / connectome / body / app tab
 *
 *  Key events are ignored while the user is typing inside an input, textarea
 *  or contenteditable element so sliders and number fields keep working.
 */
export function useGlobalShortcuts(): void {
  useEffect(() => {
    const isTyping = (el: EventTarget | null): boolean => {
      const node = el as HTMLElement | null;
      if (!node) return false;
      const tag = node.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
      if (node.isContentEditable) return true;
      return false;
    };

    const onKey = async (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (isTyping(e.target)) return;

      const key = e.key;
      if (key === " ") {
        e.preventDefault();
        const running = useLabStore.getState().latest?.running ?? true;
        await setTransport(running ? "pause" : "play").catch(() => undefined);
        return;
      }
      if (key === "n" || key === "N") {
        e.preventDefault();
        await setTransport("step").catch(() => undefined);
        return;
      }
      if (key === "r" || key === "R") {
        e.preventDefault();
        await resetSim().catch(() => undefined);
        return;
      }
      const tab = TAB_BY_KEY[key];
      if (tab) {
        e.preventDefault();
        useLabStore.getState().setTab(tab);
      }
    };

    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}

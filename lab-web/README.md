# C. elegans Virtual Lab (web)

React + Vite + TypeScript + Tailwind frontend for the lab backend at
`celegans-live-demo/lab/`. Paired with the `celegans-lab-server` script.

## Dev

```bash
# Terminal A: backend on :8765
cd ../celegans-live-demo
uv run celegans-lab-server

# Terminal B: frontend on :5173 (proxies /api and /ws to :8765)
cd lab-web
npm install
npm run dev
```

## Build

```bash
npm run build   # emits dist/
npm run preview # serves dist/
```

## Architecture

- `src/api/http.ts`: axios-only REST client. Native `fetch` is banned by
  `eslint.config.js` (`no-restricted-globals`) — use this file instead.
- `src/api/wire.ts`: WebSocket frame decoders mirroring `lab/wire.py`.
- `src/state/store.ts`: Zustand store + WS message decoder.
- `src/state/ws.ts`: reconnecting WebSocket hook.
- `src/state/app-settings.ts`: persisted UI preferences (sparkline history,
  overlays, panic reset).
- `src/state/shortcuts.ts`: global keyboard shortcuts.
- `src/components/`: shell (`ControlsPane`, `RightPane`) + tabs.
- `src/components/WormCanvas.tsx`: fixed-on-worm camera, scroll to zoom out
  up to 2× smaller.
- `src/components/StatusHud.tsx`: overlay with free-energy + neuromodulator
  sparklines pinned to the worm canvas.
- `src/components/SimulationTransportHud.tsx`: play / pause / step / reset.
- `src/components/ui/KeyHint.tsx`: tiny `<kbd>` pill shared by the tab bar,
  transport HUD, App settings reference panel, and guide modal footers.
- `src/components/ui/GuideModal.tsx`: `?`-button + modal pair wired into every
  toggle and overlay setting so each switch ships a detailed guide.

## Keyboard shortcuts

| Key       | Action                 |
| --------- | ---------------------- |
| `Space`   | toggle play / pause    |
| `N`       | step one tick          |
| `R`       | reset simulation       |
| `1`–`4`   | switch the active tab  |

Shortcuts are suspended while the focused element is an input, textarea,
select, or contenteditable block so sliders and number fields keep working.
Shortcut hints are also rendered inline: every top-level tab shows its digit
(`1`–`4`) and every transport button carries the matching `Space` / `N` / `R`
label so they can be learned without opening this file.

## In-app guides

Every toggle (Worm canvas overlays, Connectome `show edges`, Simulation
Settings boolean parameters such as `Enable M0 (stress)`), every rendering
setting, and the `Panic reset` action carries a small `?` button. Clicking it
opens a modal that summarises the control, explains when to use it, and — for
boolean simulation parameters — lists the apply semantics (`live` vs
`rebuild`) and the dotted `sim.*` path so scripts can reach the same knob
through `/api/schema`.

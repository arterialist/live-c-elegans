# C. elegans Virtual Lab (web)

A browser-based virtual lab for interactively dissecting a whole-organism
**Artificial Life (ALife)** simulation of _Caenorhabditis elegans_: a
302-neuron [PAULA](https://github.com/arterialist/neuron-model) spiking network
wired by the Cook connectome, embodied in a 13-segment MuJoCo worm, and driven
by the [active-inference / ALERM](https://github.com/arterialist/active-inference)
runtime. The frontend is a React + Vite + TypeScript single-page app that
pairs with the FastAPI lab backend at `celegans-live-demo/lab/` (served by
the `celegans-lab-server` script) over REST + a compact WebSocket protocol.

The lab is part of a broader research programme **Towards Artificial Life** —
an effort to build agents whose sensing, learning, and action all emerge from
the same local, biologically grounded update rule, rather than from
hand-engineered policies or gradient-trained end-to-end networks.

The canvas demo at **[jimmy.arteriali.st](https://jimmy.arteriali.st)** is the
read-only public viewer for the same simulation stack. This lab is the
read/write counterpart — you can pause the tick loop, inspect any cell, edit
neuron parameters, muscles, or MuJoCo engine options live, and watch the
downstream effect on behaviour within one tick.

---

## Screenshots

Main lab layout (left settings pane, worm view, status HUD, transport bar).

![Virtual lab — main layout](https://raw.githubusercontent.com/arterialist/live-c-elegans/main/images/home.png)

Connectome tab — full 302-neuron body-aligned map with live firing halos.

![Connectome — full map](https://raw.githubusercontent.com/arterialist/live-c-elegans/main/images/connectome_full.png)

Connectome with a neuron selected in the map.

![Connectome — selected neuron](https://raw.githubusercontent.com/arterialist/live-c-elegans/main/images/connectome_selected.png)

Per-cell neuron inspector (PAULA state, parameters, terminals).

![Connectome — neuron inspector](https://raw.githubusercontent.com/arterialist/live-c-elegans/main/images/connectome_neuron_inspector.png)

Neuron inspector with additional detail visible.

![Connectome — neuron inspector (expanded)](https://raw.githubusercontent.com/arterialist/live-c-elegans/main/images/connectome_neuron_inspector_more.png)

Three.js orbit view of the embodied worm / scene.

![3D worm scene](https://raw.githubusercontent.com/arterialist/live-c-elegans/main/images/connectome_3d_scene.png)

Body tab — segments, joints, and muscle map.

![Body — full layout](https://raw.githubusercontent.com/arterialist/live-c-elegans/main/images/body_full.png)

Per-muscle inspector with activation and joint sparklines.

![Body — muscle inspector](https://raw.githubusercontent.com/arterialist/live-c-elegans/main/images/muscle_inspector.png)

---

## What this lab is, scientifically

This is a whole-organism, _closed-loop_ **ALife** sandbox for **active
inference in a biologically grounded spiking substrate**. In the Artificial
Life lineage — Langton's soft/wet/hard trichotomy, Ray's _Tierra_, Sims'
evolved virtual creatures, Karl Sims / Reynolds / Grand / Bongard — the goal
has always been to study life-like behaviour by **synthesising** it, not by
reducing it. This lab continues that lineage in one specific direction:
instead of a cartoon morphology or a random neural controller, it pins the
experiment to a real animal's wiring diagram and a real physical body, and
makes every knob of both editable at 60 Hz from a browser. Four layers run
together:

1. **Body** — a 13-segment MuJoCo model of a nematode, with per-segment
   dorsal-left / dorsal-right / ventral-left / ventral-right muscles
   (`muscle_seg{n}_{DL|DR|VL|VR}`), joints with range / damping / armature,
   touch sensors, and a configurable low-Reynolds fluid regime.
2. **Connectome** — the published Cook hermaphrodite wiring diagram (302
   neurons, ~4800 chemical + gap edges), classed as sensory / interneuron /
   motor, with a body-aligned A→P × D/V layout.
3. **Neurons** — each node is a [**PAULA**](https://al.arteriali.st/blog/paula-paper)
   spiking unit: a leaky integrator with neuromodulator-shifted thresholds,
   a dendritic cable with exponential per-hop decay, per-terminal plasticity,
   and an EMA-driven homeostatic STDP window.
4. **Policy / learning** — the cell-level update rule is the concrete
   realisation of the [**ALERM**](https://al.arteriali.st/blog/alerm-framework)
   framework: a unified active-inference view of sensing, learning, and
   action, where each neuron minimises a local prediction-error vector and
   global neuromodulators (here **M0** stress-like, **M1** reward-like) bias
   thresholds, plasticity rates, and STDP window width.

Everything a human can edit in this UI is a knob that would, in a wet-lab
setting, correspond to **ablation, pharmacology, channelopathy, muscular
lesion, or mechanical perturbation** — but applied in-silico at 60 Hz with
zero physical turnaround.

---

## Running it

### Prerequisites

- **Sibling clones** of [`active-inference`](https://github.com/arterialist/active-inference)
  and [`neuron-model`](https://github.com/arterialist/neuron-model) next to
  `celegans-live-demo/` (see the top-level repo README for the exact layout;
  PAULA is loaded by path).
- Python 3.11+ with MuJoCo (provided via `uv sync` at the repo root).
- Node.js 20+ (current LTS) for this package.

### Dev

```bash
# Terminal A — lab backend on :8765 (or :8811 if you changed the default)
cd ../celegans-live-demo
uv run celegans-lab-server

# Terminal B — frontend on :5173, proxies /api and /ws to the backend
cd lab-web
npm install
npm run dev
```

### Build

```bash
npm run build   # emits dist/
npm run preview # serves dist/
```

Production: serve `dist/` behind the same origin that proxies `/api` and `/ws`
to `celegans-lab-server` (the dev proxy in `vite.config.ts` is dev-only).

---

## Architecture

### Data flow

```
celegans-lab-server (FastAPI + LabSimRuntime thread)
    │
    ├── REST /api/*        ─── axios → src/api/http.ts ─── Zustand stores
    │   (connectome, body, schema, neuron detail, transport, pacing, patches)
    │
    └── WS   /ws/state     ─── wire v5 frames → src/api/wire.ts
                                 └── decodeMessage → useLabStore.latest
```

### Source layout

| Path                                                                     | Role                                                                                                                                                |
| ------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/api/http.ts`                                                        | Axios-only REST client. `fetch` is banned by `eslint.config.js` (`no-restricted-globals`) so every HTTP call flows through a single, typed surface. |
| `src/api/wire.ts`                                                        | WebSocket frame decoders mirroring `lab/wire.py` (segment geometry, COM, neural summaries, joints/muscles, touch, neuromods, firing bits).          |
| `src/state/store.ts`                                                     | Main Zustand store + `decodeMessage` for hello / state frames (wire protocol **v5**).                                                               |
| `src/state/ws.ts`                                                        | Reconnecting WebSocket hook with exponential backoff.                                                                                               |
| `src/state/connectome.ts`, `state/body.ts`, `state/schema.ts`            | Lazy-loaded REST snapshots + staged-patch buffers.                                                                                                  |
| `src/state/app-settings.ts`                                              | Persisted UI preferences (sparkline history, FPS cap, overlay toggles, 2D/3D mode, connectome dot scale).                                           |
| `src/state/shortcuts.ts`                                                 | Global keyboard shortcuts (see below).                                                                                                              |
| `src/components/ControlsPane.tsx`                                        | Left pane with the five top-level tabs.                                                                                                             |
| `src/components/RightPane.tsx`                                           | Right pane with the worm view, status HUD, and transport HUD.                                                                                       |
| `src/components/WormCanvas.tsx`                                          | Fixed-on-worm 2D camera, scroll to zoom out up to 2× smaller.                                                                                       |
| `src/components/WormCanvas3D.tsx`                                        | Three.js orbit view of the 13-segment body with Z-exaggeration for sub-mm dorsal/ventral motion.                                                    |
| `src/components/StatusHud.tsx`                                           | Floating overlay with free-energy + M0 / M1 neuromodulator sparklines.                                                                              |
| `src/components/SimulationTransportHud.tsx`                              | Play / pause / step / reset + wall-clock pacing (ms per physics step, ms per neural tick).                                                          |
| `src/components/NeuronMap.tsx`, `NeuronTable.tsx`, `NeuronInspector.tsx` | Connectome WYSIWYG / table / per-cell inspector.                                                                                                    |
| `src/components/BodyWYSIWYG.tsx`, `MuscleMap.tsx`, `MuscleInspector.tsx` | Body view + muscle tuning.                                                                                                                          |
| `src/components/ui/GuideModal.tsx`                                       | `?`-button + modal pair wired into every toggle and overlay setting so each switch ships a detailed, context-aware guide.                           |
| `src/components/ui/KeyHint.tsx`                                          | Tiny `<kbd>` pill shared by tab bar, transport HUD, App-settings panel, and guide footers.                                                          |
| `src/components/tabs/ConnectomePaulaGuide.tsx`                           | In-app reference copy of the PAULA / ALERM parameter table, state variables, and tick phases.                                                       |

### Panes and tabs

The left pane (resizable via [Allotment](https://github.com/johnwalley/allotment))
holds five top-level tabs, selectable with keys `1`–`5`:

| #   | Tab                     | What it controls                                                                                                                                                                                                                                                                                                                                                     |
| --- | ----------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | **Simulation settings** | Non-MuJoCo simulation parameters — neuromodulator coupling strengths, food / arena config, PAULA global knobs — grouped by category. Live parameters apply instantly; rebuild parameters queue until **Apply pending**. Every boolean exposes `apply` semantics (`live` / `rebuild`) and its dotted `sim.*` path so scripts can hit the same knob via `/api/schema`. |
| 2   | **MuJoCo engine**       | All `mjOption` fields: timestep, integrator, solver, fluid, gravity, global contact overrides, and engine flags.                                                                                                                                                                                                                                                     |
| 3   | **Connectome**          | WYSIWYG body-aligned 2D view of all 302 cells (colour-coded by class, live firing halos), sortable table, per-cell **Inspector** for PAULA state + parameters + pre/post synaptic terminals, and an in-app **Guide** with the full parameter / state / tick-phase reference.                                                                                         |
| 4   | **Body**                | MuJoCo body: segments, joints, 52 muscles (13 segments × DL/DR/VL/VR). WYSIWYG, per-segment Muscle Map, and live Inspector with sparklines for activation / joint angle / joint velocity.                                                                                                                                                                            |
| 5   | **App settings**        | Frontend-only: WebSocket URL override, sparkline history length, render FPS cap, 2D/3D worm view, connectome dot scale, overlay toggles, **Panic reset**. Does not change simulation state except via an optional `resetSim()` call.                                                                                                                                 |

The right pane shows the worm itself (2D or 3D) with the status HUD (free
energy + M0 stress + M1 reward sparklines) and the transport bar pinned to the
bottom.

### Wire protocol (v5)

See `lab/wire.py` and `src/api/wire.ts`. One hello frame (`t: "h"`) carries
layout + per-neuron class/degree metadata and labels for joints, muscles, and
touch sensors; every subsequent state frame (`t: "s"`) packs:

- `sm` — flat `[x,y,z,…]` segment CoMs in nm ints (÷ 10⁶ → mm floats).
- `cm` — mass-weighted COM in nm ints.
- `Si`, `Ri`, `Bi`, `Trefi` — per-PAULA-neuron membrane state, dynamic
  thresholds, and STDP window (÷ 10⁴ → floats).
- `Fb` — base-64 bit-packed fired flags (1 bit per neuron, LSB first).
- `ja`, `jv`, `tc`, `ma` — joint angles, joint velocities, touch sensors,
  muscle activations (each with its own fixed scale).
- `nm01` — global neuromodulators `[M0, M1] ∈ [0, 1]`.
- `fe` — current free-energy estimate.
- `z` — paused flag (1 ⇒ paused).

Broadcast cadence is latest-state-only: the browser never queues stale frames,
so the UI reflects simulator now rather than simulator-N-ticks-ago.

---

## Keyboard shortcuts

| Key     | Action                                                                |
| ------- | --------------------------------------------------------------------- |
| `Space` | toggle play / pause                                                   |
| `N`     | step one tick                                                         |
| `R`     | reset simulation                                                      |
| `1`–`5` | switch the active tab (Simulation / MuJoCo / Connectome / Body / App) |

Shortcuts are suspended while the focused element is an input, textarea,
select, or contenteditable block so sliders and number fields keep working.
Hints are rendered inline: every top-level tab shows its digit, and every
transport button carries the matching `Space` / `N` / `R` label.

## In-app guides

Every toggle (worm-canvas overlays, Connectome `show edges`, simulation
booleans such as `Enable M0 (stress)`), every rendering setting, and the
**Panic reset** action carries a small `?` button. Clicking it opens a modal
that summarises the control, explains when to use it, and — for boolean
simulation parameters — lists the apply semantics (`live` vs `rebuild`) and
the dotted `sim.*` path so scripts can reach the same knob through
`/api/schema`. The **Connectome › Guide** sub-tab goes further: it's a
self-contained reference for PAULA’s `NeuronParameters` dataclass, its state
variables, the tick() phases, and the core update equations, with links back
to the paper and source.

---

## Scientific implications, potential, and use cases

This lab isn't a visualiser bolted onto a black-box sim — it's an **editor for
a spiking active-inference agent in closed loop with its body**, aimed at the
core Artificial Life question of **how life-like behaviour arises from local
rules**. The practical consequence is that a human (or a scripted agent) can
pose and test a mechanism question without leaving the browser.

### Use cases

- **Connectome-level perturbations.** Ablate, silence, or bias any of 302
  cells by hand: raise `r_base` to suppress firing, zero `p` to silence spike
  output, rebalance `w_r`/`w_b` to make a cell neuromodulator-locked. The
  loop closes in one tick, so the behavioural consequence on the worm body
  is visible immediately as segment kinematics.
- **Neuromodulator pharmacology in-silico.** M0 (stress) and M1 (reward) are
  global scalars coupled to every neuron via `gamma` (EMA decay) and
  `w_{r,b,tref}` (sensitivity). Shifting them is analogous to chemogenetic
  or pharmacological modulation of serotonin / dopamine / octopamine-like
  channels, and the status HUD plots the trace alongside free energy.
- **Plasticity experiments.** `eta_post`, `eta_retro`, `delta_decay`,
  `beta_avg`, and the homeostatic `t_ref` window are all live-editable per
  cell. This lets you test learning-rule variants (pure Hebbian, retrograde
  only, slow homeostasis) on the same connectome without retraining.
- **Body ↔ brain coupling.** The MuJoCo tab exposes the integrator, solver,
  fluid viscosity, timestep, and per-muscle forcerange / gear ratios. You
  can decouple locomotion failures into neural-drive problems vs
  actuator / physics problems by moving knobs on either side of the
  boundary.
- **Active-inference / free-energy research.** Because every cell implements
  the ALERM update locally, the global free-energy trace in the HUD is the
  sum of local prediction-error norms. Perturbations that raise FE in the
  trace are, by construction, moves away from the model’s preferred
  sensorimotor distribution — a direct visual handle on the free-energy
  principle applied to a whole organism.
- **Education and outreach.** The in-app PAULA/ALERM guide is authored to
  be enough to map any slider to the underlying biology and math, so the
  tool doubles as a teaching aid for computational neuroscience courses.
- **Agent-as-scientist experiments.** Every slider has a REST counterpart
  (`/api/patch`, `/api/neurons/{name}/patch`, `/api/body/patch`,
  `/api/sim/transport`, `/api/sim/pacing`, `/api/schema`), so an LLM or
  RL agent can be pointed at the same endpoints the browser uses and asked
  to run its own interventions.

### Where it matters

Modern ALife research oscillates between two poles: abstract agents in toy
worlds (fast to iterate, weak claims about biology) and high-fidelity
biophysics (strong claims, punishingly slow). The bottleneck is not the
availability of connectomes — it is the distance between a connectome and
an _embodied, behaving_ simulation that a researcher can manipulate. By
collapsing that distance into a single React UI over a 60 Hz closed loop,
the lab tries to land **in between**: enough biology to justify the claims,
enough interactivity to keep iteration cheap. It supports:

- **Hypothesis triage.** Cheap, reversible probes of which cells / synapses
  / modulator channels carry a given behaviour before a wet-lab experiment
  is designed.
- **Sanity checks on learning rules.** PAULA is one concrete instantiation
  of ALERM; the UI makes it straightforward to evaluate alternative rules
  on the same body + connectome and compare free-energy traces.
- **Reproducible protocols.** Because everything is a REST patch, a
  screencast or JSON log of a session is a fully replayable protocol.
- **A reference implementation of an active-inference agent at organism
  scale.** Most active-inference demos are grid-world toys; this one
  animates a MuJoCo nematode with its real wiring diagram.
- **An ALife platform with a real animal's prior.** Classic Artificial
  Life studies synthesise creatures from scratch (Sims, _Tierra_,
  _Framsticks_) and derive behaviour from open-ended search. This lab
  instead starts from a fixed, empirically grounded substrate and asks
  what behaviour the local ALERM rule sustains on it — complementary to
  evolutionary ALife rather than a replacement.

### Caveats

- **PAULA is a model, not a simulacrum.** It is a spiking active-inference
  unit fit to capture the behaviours of interest, not a biophysical
  reconstruction of a specific _C. elegans_ cell type. Treat results as
  predictions about the modelled dynamics.
- **The connectome edits you make are live but not persisted.** Reset
  restores published defaults; checkpointing is available on the canvas
  demo server (`--snapshot-path`).
- **Some simulation parameters are `rebuild`, not `live`.** They queue
  until **Apply pending**, which rebuilds the PAULA network or MuJoCo
  model; reset and unsaved dirty edits are surfaced in the sticky header
  of each settings tab.

---

## References and further reading

This lab is part of an ongoing research programme — **Towards Artificial
Life** — on active inference, spiking-network learning, and embodied
simulation. The primary references are the author’s own work:

- **PAULA (Predictive Adaptive Unsupervised Learning Agent)** — the spiking
  neuron model used here. Paper: [al.arteriali.st/blog/paula-paper](https://al.arteriali.st/blog/paula-paper).
  Reference implementation: [github.com/arterialist/neuron-model](https://github.com/arterialist/neuron-model).
- **ALERM framework** — the unified active-inference view of sensing,
  learning, and action that PAULA instantiates:
  [al.arteriali.st/blog/alerm-framework](https://al.arteriali.st/blog/alerm-framework).
- **active-inference (runtime + simulations)** — the driver library that
  builds the _C. elegans_ simulation, loads PAULA, and exposes
  `LabSimRuntime`: [github.com/arterialist/active-inference](https://github.com/arterialist/active-inference).
- **celegans-live-demo (this repo)** — hosts both the canvas demo
  (`celegans-demo-server` + static `web/`) and the virtual lab
  (`celegans-lab-server` + `lab-web/`, i.e. this package).
- **Public canvas viewer** — [jimmy.arteriali.st](https://jimmy.arteriali.st)
  (read-only; same simulator, no patch surface).

External building blocks: the **Cook hermaphrodite connectome**, **MuJoCo**
(body and fluid), **React 19 + Vite + TypeScript + Tailwind** (UI),
**Zustand** (state), **Three.js** (3D worm view), **Allotment** (resizable
panes), **axios** (REST), and **FastAPI** (backend).

If you use this tool in published work, please cite the PAULA paper and
link this repository.

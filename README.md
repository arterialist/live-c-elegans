# C. elegans live WebSocket demo

Runs the [active-inference](https://github.com/arterialist/active-inference) simulation on your machine and streams state to a static **canvas** page over **WebSockets**. Food add/remove matches the matplotlib interactive viewer (left / right click).

**Public viewer:** [https://jimmy.arteriali.st](https://jimmy.arteriali.st) (static `web/` build). The browser uses the WebSocket URL from the `ws` query parameter if set, otherwise `DEFAULT_WS_URL` in `web/app.js`—point that constant or `?ws=` at a reachable **`wss://`** server running `celegans-demo-server`.

## Repository layout (local dev)

This package depends on **`active-inference`** as an editable path dependency (`../active-inference` in `pyproject.toml`). That simulation, in turn, loads PAULA from a **sibling directory** named **`neuron-model`** (see `active-inference/simulations/paula_loader.py`, which prepends `…/neuron-model` to `sys.path`). For `uv sync` / imports to work the same way as a typical local checkout, clone repos **side by side** under a common parent, for example:

```text
your-workspace/
  celegans-live-demo/    # this repo
  active-inference/      # required — editable dep
  neuron-model/          # required — PAULA ([arterialist/neuron-model](https://github.com/arterialist/neuron-model))
```

If your PAULA checkout lives under another folder name, symlink or rename it to **`neuron-model`** next to **`active-inference`** so the loader path matches.

## Prerequisites

- Same environment expectations as `active-inference` (Python 3.11+, MuJoCo, connectome cache after first run).
- **`neuron-model`** and **`active-inference`** available as above; running only from a lone `celegans-live-demo` clone without those siblings will not satisfy the path dependency or PAULA import path.

## Run the server

From this directory:

```bash
uv sync
uv run celegans-demo-server --host 127.0.0.1 --port 8765
```

Bind `0.0.0.0` if you need LAN access. First startup loads the connectome and settles the MuJoCo body (can take a minute). Server lifecycle, WebSocket clients, food commands (applied in the sim thread), protocol errors, and broadcast failures are logged to stderr with **loguru**; use `--log-level DEBUG` for pings and per-client broadcast timeouts. **Note:** PAULA’s `neuron.setup_neuron_logger` replaces loguru sinks while neurons are built; the demo server reapplies its stderr sink after the simulation is constructed. The new sink uses a **filter** so `neuron.*` logs stay at **WARNING+** (same effect as `build_c_elegans_simulation(..., log_level="WARNING")`: per-tick neuron traffic is mostly `DEBUG` and is suppressed). `--log-level DEBUG` applies to server and `simulations.*` code, not PAULA tick spam.

### Evolved neuromod / params JSON

Use the same JSON shape as `scripts/run_c_elegans.py`: a checkpoint object with `config` or `best_config`, or a flat dict of overrides.

```bash
uv run celegans-demo-server --evol-config /path/to/evolved_checkpoint.json
```

### Worm checkpoint (survive restarts)

If `--snapshot-path` points at a **valid** checkpoint JSON from a previous run (same `checkpoint_version`), startup **imports** MuJoCo pose/velocity, food, PAULA runtime slice, and tick, then continues stepping. If the path is missing or invalid JSON, the sim **resets** as usual. While running, the server **creates or overwrites** that path atomically every `--snapshot-interval-sec` (default **60**).

```bash
uv run celegans-demo-server --snapshot-path ./worm_state.json --snapshot-interval-sec 60
```

On a **first** run the file may not exist yet: the worm starts fresh, and the first disk write happens after one interval (or sooner if you lower the interval for testing).

Checkpoint JSON includes `checkpoint_version` (currently **1**), `tick`, `qpos` / `qvel`, `food_m` (metres), `nervous` (from `export_live_checkpoint` — not full synaptic plasticity), and `saved_at_unix`. In-flight wheel events are cleared on restore; propagation queues are restored and re-heapified.

## Run the static client locally

```bash
cd web && python -m http.server 8080
```

Open `http://127.0.0.1:8080/` and pass your local server, for example:

```
http://127.0.0.1:8080/?ws=ws://127.0.0.1:8765
```

(Otherwise the page uses the checked-in `DEFAULT_WS_URL` in `app.js`, which is set for a public **WSS** tunnel in production builds.)

## How to deploy

1. Deploy the `web/` folder to any static host (GitHub Pages, Netlify, Vercel, etc.). The project’s public static build is served at **[https://jimmy.arteriali.st](https://jimmy.arteriali.st)**.
2. Set `DEFAULT_WS_URL` in `app.js` to your public **`wss://`** endpoint (Cloudflare Tunnel, ngrok, …) pointing at this server’s port, or rely on `?ws=` for ad-hoc backends.
3. Keep `celegans-demo-server` + tunnel running while the “live worm” should be visible.

## Protocol (version 3, compact wire)

Wire format uses short keys. **`p` must be `3`** on every frame; otherwise the server replies with `t: "e"` (`unsupported protocol version`). There is **no server-side trajectory**: the client appends each centre-of-mass sample to a local trail (max 2000 points).

### Message types (`t`)

| `t` | Direction | Role |
|-----|-----------|------|
| `h` | server→client | Hello after connect |
| `s` | server→client | Simulation snapshot (geometry + neural summary) |
| `e` | server→client | Error (`m` text) |
| `o` | server→client | Pong (reply to client `i`) |
| `u` | server→client | Presence: `n` = concurrent WebSocket client count |
| `fa` | server→client | Food **added** by viewers — `n` = pellet count since last broadcast window (aggregated; **separate JSON frame**, sent after `s` when non-zero) |
| `fr` | server→client | Food **removed** by viewers — `n` count (same rules as `fa`) |
| `fe` | server→client | Food **eaten** by the worm — `n` count (same rules as `fa`) |
| `a` | client→server | Add food at `x`, `y` (mm) |
| `v` | client→server | Remove food near `x`, `y` (mm) |
| `i` | client→server | Ping |

### State frame (`t` = `s`)

| Key | Meaning |
|-----|---------|
| `p` | protocol version (`3`) |
| `t` | `"s"` |
| `k` | tick (simulation step index) |
| `r` | plate_radius_mm |
| `w` | worm_radius_mm |
| `sm` | Segments: flattened `[x,y,…]` in **nanometres** as integers, `round(mm × 10⁶)`; length `2 × N_BODY_SEGMENTS` (13 segments) |
| `fm` | Food pellets: flattened pairs in **nm** (same scale as `sm`) |
| `cm` | Centre of mass `[cx_nm, cy_nm]` in **nm** (same scale) |
| `Si` | Membrane `S` per PAULA neuron id: `round(float × 10⁴)` (client ÷ `10⁴`) |
| `Ri` | Dynamic primary threshold `r`, same integer encoding as `Si` |
| `Fb` | Fired flags: **base64** of a bit-packed byte string; bit *i* (LSB-first within each byte) is `1` if neuron *i* fired (`O > 0`), else `0` |

### Hello (`t` = `h`)

| Key | Meaning |
|-----|---------|
| `m` | Short human-readable hint (e.g. protocol summary) |
| `L` | Optional connectome layout `{ nm, ax, ay }` — Cook A→P as `ax`∈[0,1], D/V heuristic as `ay` (see `connectome_layout.py`) |
| `M` | Optional list parallel to `L.nm`: per neuron `{ k, ic, ig, oc, og }` — `k` = class (`s` sensory / `m` motor / `i` interneuron / `u` unknown); `ic`/`oc` = in/out chemical synapse degree, `ig`/`og` = gap junction degree (Cook connectome) |

### Food / presence aux frames

- `fa` / `fr` / `fe`: only `p`, `t`, and **`n`** (non-negative integer counts). Emitted **after** the `s` frame for that broadcast tick when any count is non-zero.
- `u`: `p`, `t`, **`n`** = online viewer count.

Broadcast cadence is **60 Hz** with **latest-state only**: if the sim runs faster, intermediate frames are not queued. If a client send blocks longer than the server timeout, that frame is skipped for that client (the next tick still carries fresh data).

- Client → server examples: `{ "p": 3, "t": "a", "x": 1.2, "y": -3.4 }`, `{ "p": 3, "t": "i" }`.

The bundled `web/app.js` can still interpret **legacy v2-style** keys on a state message (`c` / `s` / `f` / `S` / `F` / `R`) if they were ever present; the **server** currently emits **v3** fields above after internal snapshot conversion (`_snapshot_dict_to_wire` in `server.py`).

## Limits

- Global rate limit on food commands (see `server.py`).
- Max concurrent WebSocket clients (see `server.py`).

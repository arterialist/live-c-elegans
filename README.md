# C. elegans live WebSocket demo

Runs the [active-inference](https://github.com/arterialist/active-inference) simulation on your machine and streams state to a static **canvas** page over **WebSockets**. Food add/remove matches the matplotlib interactive viewer (left / right click).

## Prerequisites

- Same environment expectations as `active-inference` (Python 3.11+, MuJoCo, connectome cache after first run).

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

Open `http://127.0.0.1:8080/` — the default WebSocket URL is `ws://127.0.0.1:8765` (edit `DEFAULT_WS_URL` in `app.js` for production **WSS** behind your tunnel).

Override for testing:

```
http://127.0.0.1:8080/?ws=ws://127.0.0.1:9999
```

## How to deploy

1. Deploy the `web/` folder to any static host (GitHub Pages, Netlify, Vercel, etc.).
2. Set `DEFAULT_WS_URL` in `app.js` to your public **`wss://`** endpoint (Cloudflare Tunnel, ngrok, …) pointing at this server’s port.
3. Keep `celegans-demo-server` + tunnel running while the “live worm” should be visible.

## Protocol (version 2, compact keys)

Wire format uses short keys and **no server-side trajectory** (the client appends each `c` = centre-of-mass sample to a local trail, max 2000 points).

| Key | Meaning |
|-----|---------|
| `p` | protocol version (`2`) |
| `t` | type: server→client `h` hello, `s` state, `e` error, `o` pong; client→server `a` add food, `v` remove food, `i` ping |
| `k` | tick (simulation step index) |
| `r` | plate_radius_mm |
| `w` | worm_radius_mm |
| `s` | segments_mm — 13 × `[x,y]` mm |
| `f` | food_mm — list of `[x,y]` mm |
| `c` | com_mm — centre of mass `[x,y]` mm (one point per state; client builds trajectory) |
| `m` | message text (`h` / `e`) |
| `x`, `y` | position in mm (`a` / `v` from client) |

Broadcast cadence is **60 Hz** with **latest-state only**: if the sim runs faster, intermediate frames are not queued. If a client send blocks longer than the server timeout, that frame is skipped for that client (the next tick still carries fresh data).

- Client → server examples: `{ "p": 2, "t": "a", "x": 1.2, "y": -3.4 }`, `{ "p": 2, "t": "i" }`.

## Limits

- Global rate limit on food commands (see `server.py`).
- Max concurrent WebSocket clients (see `server.py`).

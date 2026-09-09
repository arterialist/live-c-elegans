# C. elegans virtual lab — analysis scripts

These tools inspect **`celegans-lab-server`** through REST and `/ws/state`, or run offline parity captures.

## Research status and safe use

These are preserved exploratory scripts, not an acceptance suite. Several probes
patch parameters and reset the connected server. Use a dedicated lab instance;
do not point them at a live session whose state you want to retain. Files named
`test_*.py` under `experiments/` are experiment drivers, not unit tests.

`parity_longrun.py` can create simulations without a server. Its report generator
contains interpretation text written for the original June 2026 runs; those
paragraphs are not recomputed from new observations and must not be treated as
evidence about a new run. Inspect the recorded measurements separately.

The publication check on 9 September 2026 covers Python syntax, shared URL and
bitmap helpers, and CLI loading only. It does not certify locomotion, biological
fidelity, or compatibility of every historical parameter sweep with the current
engine. Raw recordings, plots, and worm checkpoints remain local. The two
`pi_upgrade_20260531/evolved_food_seeking_config*.json` files are retained as
historical run configurations, not validated defaults.

## Installation

```bash
cd celegans-live-demo
uv sync --extra analysis
```

## Configuration

| Environment variable | Default | Purpose |
|----------------------|---------|---------|
| `CELEGANS_LAB_REST` | `http://127.0.0.1:8811` | REST API base URL |
| `CELEGANS_LAB_WS` | derived from REST + `/ws/state` | State WebSocket URL |

## Layout

| Path | Role |
|------|------|
| `analysis/lib/lab_client.py` | Shared `post_json`, `get_json`, `unpack_bits`, URL defaults |
| `analysis/capture/` | Long `.npz` recordings from the lab stream |
| `analysis/probes/` | Targeted captures / sweeps (fluid, angles, plasticity, …) |
| `analysis/experiments/` | Ad-hoc parameter experiments (`test_*.py` from `/tmp`) |
| Top-level `analysis/*.py` | Higher-level checks (`bio_validate`, `behavioral_repertoire`, `hypotheses`, `ws_capture`, …) |

## Run (examples)

From `celegans-live-demo/` with the lab server up:

```bash
uv run python -m analysis.behavioral_repertoire 500000
uv run python -m analysis.bio_validate
uv run python -m analysis.ws_capture 8
uv run python -m analysis.capture.full_state 60000 ./worm_capture.npz
uv run python -m analysis.probes.probe_speed
uv run python -m analysis.experiments.test_baseline
```

Captures and probe outputs default to **`./worm*.npz`** in the current working directory (override with CLI args where supported).

Offline plotting of `.npz` files lives under **`active-inference/analysis/plots/`** (same repo).

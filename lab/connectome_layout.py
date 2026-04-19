"""Body-aligned 2D layout for the 302-neuron C. elegans connectome.

Unlike the Cook-order-and-suffix proxy used by ``celegans_live_demo``, this
layout places every neuron at an anatomically meaningful ``(x, y)`` so the
connectome view maps onto the straightened worm. Positions are returned in
normalised body-fraction coordinates: ``x`` in ``[0, 1]`` (0 = nose,
1 = tail tip), ``y`` in roughly ``[-0.8, 0.8]`` (negative = ventral).
"""

from __future__ import annotations

from simulations.c_elegans.config import (
    COMMAND_INTERNEURONS_BACKWARD,
    COMMAND_INTERNEURONS_FORWARD,
    MOTOR_NEURON_POSITIONS,
)

# Named sensory clusters and their approximate AP positions.
_NOSE_CHEMOSENSORS = {
    "ASEL", "ASER",
    "AWCL", "AWCR",
    "AWBL", "AWBR",
    "ASHL", "ASHR",
    "ASJL", "ASJR",
    "ASGL", "ASGR",
    "ASIL", "ASIR",
    "ASKL", "ASKR",
    "ADFL", "ADFR",
    "ADLL", "ADLR",
    "AFDL", "AFDR",
    "AQR",
}
_HEAD_TOUCH = {"ALML", "ALMR", "AVM", "FLPL", "FLPR", "OLQDL", "OLQDR", "OLQVL", "OLQVR"}
_TAIL_TOUCH = {"PLML", "PLMR", "PVM", "PHAL", "PHAR", "PHBL", "PHBR", "PQR"}
_COMMAND_INTERNEURONS: set[str] = set(COMMAND_INTERNEURONS_FORWARD) | set(
    COMMAND_INTERNEURONS_BACKWARD
)


def _dv_offset(name: str) -> float:
    if not name:
        return 0.0
    last = name[-1]
    if last == "L":
        return 0.35
    if last == "R":
        return -0.35
    if last == "V":
        return -0.55
    if last == "D":
        return 0.55
    return 0.0


def _motor_dv_offset(name: str) -> float:
    """Motor neurons: bigger DV spread so rows are visually separable."""
    if name.startswith("DD"):
        return 0.50
    if name.startswith("DB"):
        return 0.70
    if name.startswith("DA"):
        return 0.60
    if name.startswith("AS"):
        return 0.40
    if name.startswith("VB"):
        return -0.70
    if name.startswith("VA"):
        return -0.60
    if name.startswith("VD"):
        return -0.50
    last = name[-1] if name else ""
    if last in ("L", "R"):
        return 0.0
    return 0.0


def body_aligned_layout(names: list[str]) -> tuple[list[float], list[float]]:
    """Return parallel ``(ax, ay)`` lists for ``names`` in body-fraction space."""
    n = len(names)
    if n == 0:
        return [], []

    ax: list[float] = [0.0] * n
    ay: list[float] = [0.0] * n

    # Sort unknown (non-motor, non-special) neurons into a stable AP bucket by
    # paula_id (which is already Cook order ≈ AP for many cells) and then
    # spread them across the body.
    generic_indices: list[int] = []
    n_sensory_head = 0
    for i, name in enumerate(names):
        if name in MOTOR_NEURON_POSITIONS:
            ax[i] = float(MOTOR_NEURON_POSITIONS[name])
            ay[i] = _motor_dv_offset(name)
            # Small left/right jitter to avoid overlap (reuse name suffix).
            if name.endswith("L"):
                ay[i] += 0.05
            elif name.endswith("R"):
                ay[i] -= 0.05
        elif name in _NOSE_CHEMOSENSORS:
            ax[i] = 0.01
            ay[i] = _dv_offset(name)
            n_sensory_head += 1
        elif name in _HEAD_TOUCH:
            ax[i] = 0.03
            ay[i] = _dv_offset(name)
        elif name in _COMMAND_INTERNEURONS:
            # Nerve ring band.
            ax[i] = 0.05 + (0.01 * (hash(name) % 5))
            ay[i] = _dv_offset(name) * 0.5
        elif name in _TAIL_TOUCH:
            ax[i] = 0.98
            ay[i] = _dv_offset(name)
        else:
            generic_indices.append(i)

    # Distribute generic neurons across the body according to their index
    # order (Cook order ≈ AP), biased toward the head/neck ring where most
    # interneurons live.
    if generic_indices:
        n_gen = len(generic_indices)
        for slot, i in enumerate(generic_indices):
            # Slight bias toward head (0.1..0.6) since most interneurons are
            # there, then tail ganglia (0.6..0.9).
            frac = 0.1 + 0.8 * (slot / max(1, n_gen - 1))
            ax[i] = round(frac, 4)
            ay[i] = round(_dv_offset(names[i]), 4)

    # Round everything for wire transport.
    ax = [round(v, 4) for v in ax]
    ay = [round(v, 4) for v in ay]
    return ax, ay

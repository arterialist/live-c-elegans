"""Side-view-ish layout for Cook-ordered neuron names (no 3D atlas in cache).

Cook ``PREFERRED_HERM_NEURON_NAMES_COOK`` order (PAULA id 0 = head ring) is used as
anterior–posterior (x).  Dorsal–ventral proxy uses common C. elegans name suffixes
(L/R/V/D) so bilaterals separate on y — schematic, not EM coordinates.
"""

from __future__ import annotations


def side_view_layout_normalized(names: list[str]) -> tuple[list[float], list[float]]:
    """Return ``(ax, ay)`` in [0, 1] × roughly [-0.6, 0.6] for each neuron index."""
    n = len(names)
    if n == 0:
        return [], []
    ax: list[float] = []
    ay: list[float] = []
    denom = max(1, n - 1)
    for i, name in enumerate(names):
        ax.append(round(i / denom, 5))
        ay.append(round(_dv_offset(name), 5))
    return ax, ay


def _dv_offset(name: str) -> float:
    if not name:
        return 0.0
    last = name[-1]
    if last == "L":
        return 0.38
    if last == "R":
        return -0.38
    if last == "V":
        return -0.58
    if last == "D":
        return 0.58
    return 0.0

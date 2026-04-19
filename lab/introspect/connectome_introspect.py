"""Static connectome view assembled for the /api/connectome REST endpoint.

Only depends on :class:`ConnectomeData`, so it is safe to call during
application startup without touching the PAULA runtime.
"""

from __future__ import annotations

from typing import Any

from simulations.connectome_loader import ConnectomeData

from lab.connectome_layout import body_aligned_layout


_NEURON_KIND_WIRE = {"sensory": "s", "motor": "m", "interneuron": "i", "unknown": "u"}


def build_connectome_view(
    connectome: ConnectomeData, neuron_names_paula_order: list[str]
) -> dict[str, Any]:
    """Return the REST payload consumed by the WYSIWYG + table views."""
    ax, ay = body_aligned_layout(neuron_names_paula_order)
    nm_to = connectome.name_to_info

    neurons: list[dict[str, Any]] = []
    for idx, name in enumerate(neuron_names_paula_order):
        info = nm_to.get(name)
        if info is None:
            neurons.append(
                {
                    "id": int(idx),
                    "name": name,
                    "type": "unknown",
                    "class": "u",
                    "degree_in_chem": 0,
                    "degree_out_chem": 0,
                    "degree_in_gap": 0,
                    "degree_out_gap": 0,
                    "layout_x": float(ax[idx]),
                    "layout_y": float(ay[idx]),
                }
            )
            continue
        neurons.append(
            {
                "id": int(info.paula_id),
                "name": name,
                "type": info.neuron_type,
                "class": _NEURON_KIND_WIRE.get(info.neuron_type, "u"),
                "degree_in_chem": int(info.in_degree_chem),
                "degree_out_chem": int(info.out_degree_chem),
                "degree_in_gap": int(info.in_degree_gap),
                "degree_out_gap": int(info.out_degree_gap),
                "layout_x": float(ax[idx]),
                "layout_y": float(ay[idx]),
            }
        )

    name_to_id = {n["name"]: n["id"] for n in neurons}
    edges: list[dict[str, Any]] = []
    for edge in connectome.chemical_edges:
        pre = name_to_id.get(edge.pre_name)
        post = name_to_id.get(edge.post_name)
        if pre is None or post is None:
            continue
        edges.append(
            {
                "pre_id": int(pre),
                "post_id": int(post),
                "type": "chemical",
                "weight": float(edge.weight),
            }
        )
    for edge in connectome.gap_junction_edges:
        pre = name_to_id.get(edge.pre_name)
        post = name_to_id.get(edge.post_name)
        if pre is None or post is None:
            continue
        edges.append(
            {
                "pre_id": int(pre),
                "post_id": int(post),
                "type": "gap",
                "weight": float(edge.weight),
            }
        )

    return {"neurons": neurons, "edges": edges}

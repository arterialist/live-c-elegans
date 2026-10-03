"""Live vs rebuild applicators (phase 2 fills in real behaviour)."""

from __future__ import annotations

import math
from typing import Any, Callable

from lab.parameters.registry import ApplyError, ParameterRegistry, ParameterSpec, PatchResult


def _validated_value(spec: ParameterSpec, value: Any) -> Any:
    """Check the schema contract before an edit is queued or staged."""
    if spec.kind == "bool":
        if not isinstance(value, bool):
            raise ApplyError("expected a boolean")
        return value
    if spec.kind == "enum":
        if spec.enum is not None and value not in spec.enum:
            raise ApplyError(f"expected one of {spec.enum}")
        return value
    if spec.kind == "vec":
        if not isinstance(value, (list, tuple)):
            raise ApplyError("expected a numeric vector")
        values = [float(v) for v in value]
    else:
        if isinstance(value, bool):
            raise ApplyError("expected a number")
        values = [float(value)]
    for number in values:
        if not math.isfinite(number):
            raise ApplyError("expected finite numbers")
        if spec.min is not None and number < spec.min:
            raise ApplyError(f"value must be >= {spec.min}")
        if spec.max is not None and number > spec.max:
            raise ApplyError(f"value must be <= {spec.max}")
    if spec.kind == "vec":
        return values
    if spec.kind == "int":
        if not values[0].is_integer():
            raise ApplyError("expected an integer")
        return int(values[0])
    return values[0]


def apply_patches(
    registry: ParameterRegistry,
    ctx: Any,
    patches: list[dict[str, Any]],
    *,
    enqueue_live: Callable[[Callable[[], None]], None],
) -> PatchResult:
    """Route each patch to the right applicator by its ``apply`` tag.

    ``enqueue_live`` is called for live patches: it receives a callable that
    performs the setter and is expected to run it from the sim thread (between
    ticks) with the sim lock held. The runtime's ``enqueue_patch`` is the
    standard wiring.
    """
    result = PatchResult()
    pending_stash: dict[str, Any] = getattr(ctx, "pending_patches", None) or {}
    if not hasattr(ctx, "pending_patches"):
        ctx.pending_patches = pending_stash

    for patch in patches:
        path = str(patch.get("path", ""))
        value = patch.get("value")
        try:
            spec = registry.get(path)
            value = _validated_value(spec, value)
        except (ApplyError, TypeError, ValueError, OverflowError) as exc:
            result.failed.append({"path": path, "error": str(exc)})
            continue
        if spec.apply == "live":
            def _run(spec=spec, value=value) -> None:
                spec.setter(ctx, value)
            enqueue_live(_run)
            result.applied.append(path)
        else:
            pending_stash[path] = value
            result.pending.append(path)

    ctx.pending_patches = pending_stash
    return result

"""Live vs rebuild applicators (phase 2 fills in real behaviour)."""

from __future__ import annotations

from typing import Any

from lab.parameters.registry import ApplyError, ParameterRegistry, PatchResult


def apply_patches(
    registry: ParameterRegistry,
    ctx: Any,
    patches: list[dict[str, Any]],
    *,
    enqueue_live: callable,  # type: ignore[valid-type]
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
        except ApplyError as exc:
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

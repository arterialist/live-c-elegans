"""Parameter registry: single source of truth for UI + REST + applicators.

Phase 1 ships the dataclass + registry plumbing only; concrete specs for
Simulation / Body / Connectome land in phase 2 (``simulation_params.py``,
``body_params.py``, ``connectome_params.py``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Literal


class ApplyError(RuntimeError):
    """Raised when a setter rejects a value (bad range, rebuild-only, …)."""


Kind = Literal["int", "float", "bool", "enum", "vec"]
ApplyTag = Literal["live", "rebuild"]


@dataclass(frozen=True)
class ParameterSpec:
    path: str
    label: str
    group: str
    kind: Kind
    apply: ApplyTag
    getter: Callable[[Any], Any]
    setter: Callable[[Any, Any], None]
    help: str = ""
    min: float | None = None
    max: float | None = None
    step: float | None = None
    enum: tuple[str, ...] | None = None


@dataclass
class PatchResult:
    applied: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)
    failed: list[dict[str, Any]] = field(default_factory=list)


class ParameterRegistry:
    """Flat, ordered map of dotted path -> :class:`ParameterSpec`."""

    def __init__(self) -> None:
        self._specs: dict[str, ParameterSpec] = {}

    def register(self, spec: ParameterSpec) -> None:
        if spec.path in self._specs:
            raise ValueError(f"duplicate parameter path: {spec.path}")
        self._specs[spec.path] = spec

    def extend(self, specs: Iterable[ParameterSpec]) -> None:
        for spec in specs:
            self.register(spec)

    def get(self, path: str) -> ParameterSpec:
        try:
            return self._specs[path]
        except KeyError as exc:
            raise ApplyError(f"unknown parameter: {path}") from exc

    def all(self) -> list[ParameterSpec]:
        return list(self._specs.values())

    def snapshot(self, ctx: Any) -> dict[str, Any]:
        """Current value of every parameter (skips getters that throw)."""
        out: dict[str, Any] = {}
        for spec in self._specs.values():
            try:
                out[spec.path] = spec.getter(ctx)
            except Exception:
                # Ignore unavailable (e.g. network not yet built) values;
                # the UI will surface them as "—".
                continue
        return out

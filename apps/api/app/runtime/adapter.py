"""Aware Care runtime interface only; no model-serving implementation is supplied.

Contract refs: R24, R26, R27, R34, R37, R38, R40.
Implement providers behind this interface. Do not instantiate this Protocol as a
working runtime or return synthetic content when local mode is unavailable.
"""
from typing import Any, Mapping, Protocol, TypedDict, Literal

class RuntimeHealth(TypedDict):
    status: Literal["ready", "unavailable"]
    provider: Literal["mock", "zrt"]
    model_id: str | None
    reason_code: str | None

class RuntimeAdapter(Protocol):
    async def generate_json(
        self, task: str, prompt_version: str,
        input_snapshot: Mapping[str, Any], schema_id: str, timeout_s: float,
    ) -> Mapping[str, Any]:
        """Return schema-validated data; typed transport/validation errors propagate.

        The owning service still validates fact/evidence IDs, support, urgency,
        revision, ownership, and tombstones before publishing anything.
        """
        ...

    async def health(self) -> RuntimeHealth:
        """Reflect the actual selected provider; never infer readiness from GPU load."""
        ...

    async def manifest(self) -> Mapping[str, Any]:
        """Return pinned actual model/runtime provenance; unknown fields remain null."""
        ...

"""Shared inference decisions and post-execution policy hooks."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Protocol

from PIL import Image

from player1.agents.backend import GenerationResult


@dataclass(frozen=True)
class PolicyStep:
    """One policy decision and the evidence needed to audit it."""

    control_action: dict[str, Any]
    valid: bool
    invalid_reason: str | None
    generation: GenerationResult
    request_evidence: dict[str, Any]
    parsed_evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["generation"] = self.generation.to_dict()
        return payload


class EnvironmentStep(Protocol):
    """Post-step observation returned by a successful Player-1 transition."""

    image: Image.Image
    reward: float
    terminated: bool
    truncated: bool
    info: dict[str, Any]


__all__ = [
    "EnvironmentStep",
    "PolicyStep",
]

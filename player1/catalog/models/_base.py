"""Typed model catalog records."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ...agents.history_context import require_history_context_mode
from ...agents.actions.serialization import require_action_format
from ...agents.actions.control import require_action_space_mode

from .._yaml import require_mapping, require_nonempty_text, validate_mapping_fields


_MODEL_FIELDS = {
    "action_format",
    "action_space_mode",
    "history_context_mode",
    "model_name",
}


@dataclass(slots=True)
class ModelProfile:
    """Model-specific configuration loaded from catalog YAML."""

    model_name: str
    action_format: str
    action_space_mode: str
    history_context_mode: str

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> ModelProfile:
        """Parse a model profile from YAML data."""
        raw = require_mapping(data, owner="Model profile")
        validate_mapping_fields(raw, owner="Model profile", supported_fields=_MODEL_FIELDS)
        model_name = (
            require_nonempty_text(raw["model_name"], owner="model.model_name") if "model_name" in raw else None
        )
        if not model_name:
            raise ValueError("Model profile missing required field: model_name")

        action_format = (
            require_nonempty_text(raw["action_format"], owner="model.action_format")
            if "action_format" in raw
            else None
        )
        if not action_format:
            raise ValueError(f"Model profile '{model_name}' missing required field: action_format")
        try:
            action_format = require_action_format(action_format)
        except ValueError as exc:
            raise ValueError(
                f"Model profile '{model_name}' has unsupported action_format {action_format!r}; {exc}"
            ) from exc

        raw_action_space_mode = (
            require_nonempty_text(raw["action_space_mode"], owner="model.action_space_mode")
            if "action_space_mode" in raw
            else None
        )
        if not raw_action_space_mode:
            raise ValueError(f"Model profile '{model_name}' missing required field: action_space_mode")
        action_space_mode = require_action_space_mode(raw_action_space_mode)

        raw_history_context_mode = (
            require_nonempty_text(raw["history_context_mode"], owner="model.history_context_mode")
            if "history_context_mode" in raw
            else None
        )
        if not raw_history_context_mode:
            raise ValueError(f"Model profile '{model_name}' missing required field: history_context_mode")
        history_context_mode = require_history_context_mode(raw_history_context_mode)

        return cls(
            model_name=model_name,
            action_format=action_format,
            action_space_mode=action_space_mode,
            history_context_mode=history_context_mode,
        )


__all__ = [
    "ModelProfile",
]

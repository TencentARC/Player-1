"""Discover model variants and lazily load their agent adapters."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import cache
from importlib import import_module
from pathlib import Path
from types import ModuleType
from typing import Any

import yaml

from .base import BaseClient, BaseClientConfig

AGENT_ADAPTERS_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = AGENT_ADAPTERS_DIR.parent / "templates"
_MODEL_FILE_NAME = "models.yaml"
_ADAPTER_EXPORTS = ("Client", "Config", "PROMPT_TEMPLATE", "OUTPUT_FORMAT")


@dataclass(frozen=True, slots=True)
class ModelProfile:
    """One runnable model variant owned by an agent adapter."""

    model_id: str
    adapter_id: str
    source_path: Path
    enable_memory: bool = False
    config_overrides: dict[str, Any] = field(default_factory=dict)


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise ValueError(f"Agent model file root must be a mapping: {path}")
    return dict(raw)


def _parse_profile(
    *,
    model_id: str,
    adapter_id: str,
    raw_profile: Any,
    source_path: Path,
) -> ModelProfile:
    if raw_profile is None:
        profile = {}
    elif isinstance(raw_profile, Mapping):
        profile = dict(raw_profile)
    else:
        raise ValueError(
            f"Model '{model_id}' in {source_path} must define a mapping of overrides."
        )

    enable_memory = profile.pop("enable_memory", False)
    if not isinstance(enable_memory, bool):
        raise ValueError(f"Model '{model_id}' enable_memory must be a boolean.")

    return ModelProfile(
        model_id=model_id,
        adapter_id=adapter_id,
        enable_memory=enable_memory,
        config_overrides=profile,
        source_path=source_path,
    )


@cache
def _model_index() -> dict[str, ModelProfile]:
    index: dict[str, ModelProfile] = {}
    for path in sorted(AGENT_ADAPTERS_DIR.glob(f"*/{_MODEL_FILE_NAME}")):
        adapter_id = path.parent.name
        if not (path.parent / "__init__.py").is_file():
            raise ValueError(f"Agent adapter is missing __init__.py: {path.parent}")

        for raw_model_id, raw_profile in _load_yaml_mapping(path).items():
            model_id = str(raw_model_id).strip()
            if not model_id:
                raise ValueError(f"Empty model id in agent model file: {path}")
            if model_id in index:
                previous = index[model_id].source_path
                raise ValueError(
                    f"Duplicate model id '{model_id}' in {previous} and {path}."
                )
            index[model_id] = _parse_profile(
                model_id=model_id,
                adapter_id=adapter_id,
                raw_profile=raw_profile,
                source_path=path,
            )
    return index


def list_models() -> list[str]:
    """List all model ids declared by agent adapters."""
    return sorted(_model_index())


def load_model(model_id: str) -> ModelProfile:
    """Load one model profile by its benchmark-facing id."""
    model_key = str(model_id).strip()
    if not model_key:
        raise ValueError("Model id cannot be empty.")
    try:
        return _model_index()[model_key]
    except KeyError as exc:
        known_models = list_models()
        known = ", ".join(known_models[:8])
        suffix = ", ..." if len(known_models) > 8 else ""
        raise FileNotFoundError(
            f"Model profile not found for id: {model_id}. "
            f"Known examples: {known}{suffix}"
        ) from exc


@cache
def load_adapter(adapter_id: str) -> ModuleType:
    """Import and validate one agent adapter package."""
    adapter_key = str(adapter_id).strip()
    if not adapter_key:
        raise ValueError("Agent adapter id cannot be empty.")

    module = import_module(f"{__package__}.{adapter_key}")
    missing = [name for name in _ADAPTER_EXPORTS if not hasattr(module, name)]
    if missing:
        raise TypeError(
            f"Agent adapter '{adapter_key}' is missing exports: {', '.join(missing)}"
        )

    template_name = str(module.PROMPT_TEMPLATE).strip()
    if not template_name or not (TEMPLATES_DIR / template_name).is_file():
        raise ValueError(
            f"Agent adapter '{adapter_key}' has unknown prompt template: "
            f"{module.PROMPT_TEMPLATE}"
        )
    if module.OUTPUT_FORMAT is not None and not isinstance(module.OUTPUT_FORMAT, str):
        raise TypeError(
            f"Agent adapter '{adapter_key}' OUTPUT_FORMAT must be text or None."
        )
    return module


def build_config(profile: ModelProfile) -> BaseClientConfig:
    """Build a validated config from an adapter default and model overrides."""
    adapter = load_adapter(profile.adapter_id)
    config = adapter.Config()
    if not isinstance(config, BaseClientConfig):
        raise TypeError(
            f"Agent adapter '{profile.adapter_id}' Config must create BaseClientConfig."
        )

    for key, value in profile.config_overrides.items():
        if not hasattr(config, key):
            raise ValueError(
                f"Model '{profile.model_id}' has unsupported config override: {key}"
            )
        setattr(config, key, value)
    return config


def create_client(
    profile: ModelProfile,
    config: BaseClientConfig,
    **kwargs: Any,
) -> BaseClient:
    """Create a client using the adapter that owns a model profile."""
    adapter = load_adapter(profile.adapter_id)
    client = adapter.Client(config, **kwargs)
    if not isinstance(client, BaseClient):
        raise TypeError(
            f"Agent adapter '{profile.adapter_id}' Client must create BaseClient."
        )
    return client


__all__ = [
    "AGENT_ADAPTERS_DIR",
    "ModelProfile",
    "build_config",
    "create_client",
    "list_models",
    "load_adapter",
    "load_model",
]

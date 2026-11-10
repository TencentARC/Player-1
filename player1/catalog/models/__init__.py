"""Model catalog loader."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from .._yaml import format_known_ids, load_yaml_mapping
from ._base import ModelProfile

_MODELS_DIR = Path(__file__).parent


def _require_model_id(model_id: str) -> str:
    text = str(model_id).strip()
    if not text:
        raise ValueError("Model id cannot be empty.")
    return text


def _format_known_models() -> str:
    return format_known_ids(list_models())


def _iter_model_definition_paths() -> list[Path]:
    return sorted(path for path in _MODELS_DIR.rglob("*.yaml") if path.is_file())


@lru_cache(maxsize=1)
def _model_definition_index() -> dict[str, Path]:
    index: dict[str, Path] = {}
    for path in _iter_model_definition_paths():
        profile = ModelProfile.from_mapping(load_yaml_mapping(path))
        existing = index.get(profile.model_name)
        if existing is not None:
            raise ValueError(
                "Duplicate model_name in catalog: "
                f"{profile.model_name!r} is declared by both "
                f"{existing.relative_to(_MODELS_DIR)} and {path.relative_to(_MODELS_DIR)}."
            )
        index[profile.model_name] = path
    return index


def get_model_definition_path(model_id: str) -> Path:
    """Return the YAML path for a catalog model_name."""
    model_key = _require_model_id(model_id)
    path = _model_definition_index().get(model_key)
    if path is None:
        raise FileNotFoundError(
            f"Model profile not found for id: {model_id}. "
            "Model ids must match a model_name field in catalog YAML. "
            f"Known examples: {_format_known_models()}"
        )
    return path


def load_model(model_id: str) -> ModelProfile:
    """Load a model profile by model_name."""
    model_key = _require_model_id(model_id)
    profile = ModelProfile.from_mapping(load_yaml_mapping(get_model_definition_path(model_key)))
    if profile.model_name != model_key:
        raise ValueError(f"Model index mismatch for {model_key!r}: loaded {profile.model_name!r}.")
    return profile


def list_models() -> list[str]:
    """List all available model_name ids."""
    return sorted(_model_definition_index())

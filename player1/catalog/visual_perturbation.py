"""Appearance, camera, scene and control mixtures for training."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from ._mixture import (
    _reject_unknown_keys,
    _require_identifier,
    _require_mapping,
    _require_positive_weight,
    _smooth_fixed_count_order,
    allocate_weighted_counts,
)


PERTURBATION_PROFILE_OPTIONS = {
    "appearance": "domain_appearance_profile",
    "camera": "domain_camera_profile",
    "scene": "domain_scene_profile",
    "control": "control_response_profile",
}
_REQUIRED_DOMAINS = {"appearance", "camera", "scene"}
_PROFILES = {"default", "perturbed"}


@dataclass(frozen=True, slots=True)
class VisualPerturbationMode:
    """One named combination of Domain profiles."""

    mode_id: str
    weight: float
    domain_profiles: tuple[tuple[str, str], ...]

    def profiles(self) -> dict[str, str]:
        return dict(self.domain_profiles)


@dataclass(frozen=True, slots=True)
class VisualPerturbationConfig:
    """Training policy for visual-domain randomization."""

    visual_perturbation_id: str
    train_modes: tuple[VisualPerturbationMode, ...]

    def mode(self, mode_id: str) -> VisualPerturbationMode:
        for mode in self.train_modes:
            if mode.mode_id == mode_id:
                return mode
        raise KeyError(f"Unknown visual perturbation mode {mode_id!r}")


def load_visual_perturbation_config(path: str | Path) -> VisualPerturbationConfig:
    """Load and strictly validate a visual perturbation mixture."""

    config_path = Path(path).expanduser().resolve()
    try:
        raw = json.loads(config_path.read_text())
    except FileNotFoundError:
        raise FileNotFoundError(f"Visual perturbation config does not exist: {config_path}") from None
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in visual perturbation config {config_path}: {exc}") from exc

    config = _require_mapping(raw, field="visual perturbation config")
    _reject_unknown_keys(
        config,
        allowed={"visual_perturbation_id", "train_modes"},
        field="visual perturbation config",
    )
    config_id = _require_identifier(
        config.get("visual_perturbation_id"), field="visual_perturbation_id"
    )
    raw_modes = config.get("train_modes")
    if not isinstance(raw_modes, list) or not raw_modes:
        raise ValueError("visual perturbation config requires at least one train mode")

    modes: list[VisualPerturbationMode] = []
    seen_mode_ids: set[str] = set()
    for index, raw_mode in enumerate(raw_modes):
        field = f"train_modes[{index}]"
        mode = _require_mapping(raw_mode, field=field)
        _reject_unknown_keys(mode, allowed={"mode_id", "weight", "domain_profiles"}, field=field)
        mode_id = _require_identifier(mode.get("mode_id"), field=f"{field}.mode_id")
        if mode_id in seen_mode_ids:
            raise ValueError(f"Duplicate visual perturbation mode_id: {mode_id}")
        seen_mode_ids.add(mode_id)
        profiles = _require_mapping(mode.get("domain_profiles"), field=f"{field}.domain_profiles")
        _reject_unknown_keys(profiles, allowed=set(PERTURBATION_PROFILE_OPTIONS), field=f"{field}.domain_profiles")
        missing = sorted(_REQUIRED_DOMAINS - set(profiles))
        if missing:
            raise ValueError(f"{field}.domain_profiles is missing: {', '.join(missing)}")
        normalized_profiles: list[tuple[str, str]] = []
        for domain in PERTURBATION_PROFILE_OPTIONS:
            # Existing three-domain mixtures retain their native control response.
            profile = str(profiles.get(domain, "default") or "").strip().lower()
            if profile not in _PROFILES:
                raise ValueError(
                    f"{field}.domain_profiles.{domain} must be one of {sorted(_PROFILES)}, got {profile!r}"
                )
            normalized_profiles.append((domain, profile))
        modes.append(
            VisualPerturbationMode(
                mode_id=mode_id,
                weight=_require_positive_weight(mode.get("weight"), field=f"{field}.weight"),
                domain_profiles=tuple(normalized_profiles),
            )
        )

    return VisualPerturbationConfig(
        visual_perturbation_id=config_id,
        train_modes=tuple(modes),
    )


def compile_visual_perturbation_schedule(
    config: VisualPerturbationConfig,
    *,
    total_samples: int,
    batch_size: int,
) -> tuple[str, ...]:
    """Allocate exact per-batch mode counts and rotate placement across batches."""

    if total_samples < 0:
        raise ValueError(f"total_samples must be non-negative, got {total_samples}")
    if batch_size <= 0:
        raise ValueError(f"batch_size must be positive, got {batch_size}")

    weights = tuple(mode.weight for mode in config.train_modes)
    total_counts = allocate_weighted_counts(total_samples, weights)
    complete_order = _smooth_fixed_count_order(total_counts)
    mode_ids: list[str] = []
    for batch_index, start in enumerate(range(0, total_samples, batch_size)):
        batch_order = complete_order[start : start + batch_size]
        if batch_order:
            offset = (batch_index * 17) % len(batch_order)
            batch_order = batch_order[offset:] + batch_order[:offset]
        mode_ids.extend(config.train_modes[index].mode_id for index in batch_order)
    return tuple(mode_ids)


__all__ = [
    "PERTURBATION_PROFILE_OPTIONS",
    "VisualPerturbationConfig",
    "VisualPerturbationMode",
    "compile_visual_perturbation_schedule",
    "load_visual_perturbation_config",
]

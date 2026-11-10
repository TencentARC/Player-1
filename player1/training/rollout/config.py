"""Typed configuration for the Player-1 agent loop."""

from __future__ import annotations

import math
from collections.abc import Collection
from dataclasses import dataclass, field, fields
from typing import Any, Mapping

from omegaconf import DictConfig, OmegaConf

from player1.agents.history_context import COLLAPSED_HISTORY_CONTEXT_MODES
from player1.agents.prompting import DEFAULT_ACTION_PROMPT_TEXT
from player1.agents.vision import DEFAULT_AGENT_IMAGE_MAX_HEIGHT

from ._reward_sources import EPISODE_REWARD_SOURCES
from .loss_masking import RESPONSE_MASK_THINK_AND_ACTION, normalize_response_mask_mode


def configure_vllm_worker(rollout: DictConfig) -> None:
    """Select the Player-1 worker through vLLM's public engine configuration."""
    if rollout.get("name") == "vllm":
        rollout.engine_kwargs = OmegaConf.merge(
            {"vllm": {"worker_cls": "player1.training.vllm_worker.PlayerOneVLLMWorker"}},
            rollout.get("engine_kwargs", {}),
        )


def _require_bool(name: str, value: Any, *, optional: bool = False) -> None:
    if optional and value is None:
        return
    if not isinstance(value, bool):
        expected = "bool or None" if optional else "bool"
        raise TypeError(f"{name} must be {expected}, got {value!r}")


def _require_int(
    name: str,
    value: Any,
    *,
    minimum: int,
    optional: bool = False,
    maximum: int | None = None,
) -> None:
    if optional and value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int):
        expected = "int or None" if optional else "int"
        raise TypeError(f"{name} must be {expected}, got {value!r}")
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}, got {value!r}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} must be <= {maximum}, got {value!r}")


def _require_number(
    name: str,
    value: Any,
    *,
    minimum: float,
    optional: bool = False,
) -> None:
    if optional and value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        expected = "a finite number or None" if optional else "a finite number"
        raise TypeError(f"{name} must be {expected}, got {value!r}")
    if not math.isfinite(float(value)):
        raise ValueError(f"{name} must be finite, got {value!r}")
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}, got {value!r}")


def _require_string(name: str, value: Any) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be str, got {value!r}")


def _require_nonempty_string(name: str, value: Any) -> None:
    _require_string(name, value)
    if not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _normalized_choice(name: str, value: Any, choices: Collection[str]) -> str:
    _require_string(name, value)
    normalized = value.strip().lower()
    if normalized not in choices:
        expected = ", ".join(sorted(choices))
        raise ValueError(f"{name} must be one of {expected}, got {value!r}")
    return normalized


def _config_value(config: Any, key: str, default: Any = None) -> Any:
    getter = getattr(config, "get", None)
    if callable(getter):
        return getter(key, default)
    return getattr(config, key, default)


def _player1_config_section(
    trainer_config: Any,
    section: str,
) -> dict[str, Any]:
    actor_rollout_ref = _config_value(trainer_config, "actor_rollout_ref", {})
    rollout_config = _config_value(actor_rollout_ref, "rollout", {})
    custom_config = _config_value(rollout_config, "custom", {}) or {}
    player1_config = _config_value(custom_config, "player1", {}) or {}
    raw_config = _config_value(player1_config, section, None)
    config_path = f"actor_rollout_ref.rollout.custom.player1.{section}"
    if raw_config is None:
        raise ValueError(f"{config_path} must be configured")
    if isinstance(raw_config, DictConfig):
        values = OmegaConf.to_container(raw_config, resolve=True)
    elif isinstance(raw_config, Mapping):
        values = dict(raw_config)
    else:
        raise TypeError(f"{config_path} must be a mapping, got {type(raw_config).__name__}")
    if not isinstance(values, dict):
        raise TypeError(f"{config_path} must resolve to a mapping, got {type(values).__name__}")
    return values


@dataclass(frozen=True)
class PlayerOneRewardConfig:
    """Validated reward settings shared by the loop and reward computer."""

    terminal_fail_penalty: float = 0.0
    malformed_action_penalty: float = 1.0
    rescale_reward: bool = False
    reward_mode: str = "dense"
    episode_reward_source: str = "primary"
    episode_reward_target: float | None = None
    episode_reward_clip: bool = False

    def __post_init__(self) -> None:
        _require_number("terminal_fail_penalty", self.terminal_fail_penalty, minimum=0.0)
        _require_number("malformed_action_penalty", self.malformed_action_penalty, minimum=0.0)
        _require_bool("rescale_reward", self.rescale_reward)
        object.__setattr__(
            self,
            "reward_mode",
            _normalized_choice("reward_mode", self.reward_mode, frozenset({"dense", "episode"})),
        )
        object.__setattr__(
            self,
            "episode_reward_source",
            _normalized_choice("episode_reward_source", self.episode_reward_source, EPISODE_REWARD_SOURCES),
        )
        _require_number("episode_reward_target", self.episode_reward_target, minimum=1e-8, optional=True)
        _require_bool("episode_reward_clip", self.episode_reward_clip)


def _reward_config_from_values(values: Mapping[str, Any]) -> PlayerOneRewardConfig:
    known_fields = {config_field.name for config_field in fields(PlayerOneRewardConfig)}
    unknown_fields = sorted(set(values) - known_fields)
    if unknown_fields:
        raise ValueError(f"Unknown Player-1 reward config fields: {unknown_fields}")
    return PlayerOneRewardConfig(**values)


@dataclass(frozen=True)
class PlayerOneAgentLoopConfig:
    fallback_action_id: str = "wait"
    action_prompt_text: str = DEFAULT_ACTION_PROMPT_TEXT
    observe_remaining_turns: bool = True
    max_environment_steps: int | None = 50
    max_turn_tokens: int | None = 256
    history_context_turns: int | None = 2
    history_context_old_turns: int | None = 2
    history_context_old_mode: str | None = "a"
    history_context_sampling: str = "fixed"
    history_context_sampling_seed: int = 42
    headless: bool | None = None
    screenshot_max_height: int = DEFAULT_AGENT_IMAGE_MAX_HEIGHT
    response_mask_mode: str = RESPONSE_MASK_THINK_AND_ACTION
    think_max_tokens: int = 64
    think_length_penalty: float = 0.005
    think_length_penalty_max: float = 1.0
    reward: PlayerOneRewardConfig = field(default_factory=PlayerOneRewardConfig)
    format_retry_max: int = 0
    valid_rollout_retry_max: int = 1
    rollout_timeout_s: float | None = 600.0
    rollout_close_timeout_s: float = 15.0

    def __post_init__(self) -> None:
        """Validate launcher and trainer inputs through one runtime authority."""

        _require_nonempty_string("fallback_action_id", self.fallback_action_id)
        object.__setattr__(self, "fallback_action_id", self.fallback_action_id.strip())
        _require_nonempty_string("action_prompt_text", self.action_prompt_text)
        _require_bool("observe_remaining_turns", self.observe_remaining_turns)
        _require_int("max_environment_steps", self.max_environment_steps, minimum=1, optional=True)
        _require_int("max_turn_tokens", self.max_turn_tokens, minimum=1, optional=True)
        _require_int("history_context_turns", self.history_context_turns, minimum=0, optional=True)
        _require_int("history_context_old_turns", self.history_context_old_turns, minimum=0, optional=True)
        object.__setattr__(
            self, "history_context_sampling",
            _normalized_choice("history_context_sampling", self.history_context_sampling, ("fixed", "episode_uniform")),
        )
        _require_int("history_context_sampling_seed", self.history_context_sampling_seed, minimum=0)
        if self.history_context_sampling != "fixed" and (
            self.history_context_turns is None or self.history_context_old_turns is None
        ):
            raise ValueError("Random history requires finite history_context_turns and history_context_old_turns")
        if self.history_context_old_mode is not None:
            normalized_old_mode = _normalized_choice(
                "history_context_old_mode",
                self.history_context_old_mode,
                COLLAPSED_HISTORY_CONTEXT_MODES,
            )
            object.__setattr__(self, "history_context_old_mode", normalized_old_mode)
        old_layer_enabled = self.history_context_old_turns is None or self.history_context_old_turns > 0
        if old_layer_enabled and self.history_context_old_mode is None:
            raise ValueError("history_context_old_mode is required when the old history layer is enabled")
        if old_layer_enabled and self.history_context_turns is None:
            raise ValueError("history_context_turns cannot be null when the old history layer is enabled")
        _require_bool("headless", self.headless, optional=True)
        _require_int("screenshot_max_height", self.screenshot_max_height, minimum=64)
        _require_string("response_mask_mode", self.response_mask_mode)
        object.__setattr__(self, "response_mask_mode", normalize_response_mask_mode(self.response_mask_mode))
        _require_int("think_max_tokens", self.think_max_tokens, minimum=0)
        _require_number("think_length_penalty", self.think_length_penalty, minimum=0.0)
        _require_number("think_length_penalty_max", self.think_length_penalty_max, minimum=0.0)
        if not isinstance(self.reward, PlayerOneRewardConfig):
            raise TypeError(f"reward must be PlayerOneRewardConfig, got {type(self.reward).__name__}")
        _require_int("format_retry_max", self.format_retry_max, minimum=0)
        _require_int("valid_rollout_retry_max", self.valid_rollout_retry_max, minimum=0)
        _require_number("rollout_timeout_s", self.rollout_timeout_s, minimum=0.0, optional=True)
        _require_number("rollout_close_timeout_s", self.rollout_close_timeout_s, minimum=0.0)

    @classmethod
    def from_trainer_config(cls, trainer_config: Any) -> "PlayerOneAgentLoopConfig":
        values = _player1_config_section(trainer_config, "agent_loop")
        known_fields = {config_field.name for config_field in fields(cls)}
        unknown_fields = sorted(set(values) - known_fields)
        if unknown_fields:
            raise ValueError(f"Unknown Player-1 agent-loop config fields: {unknown_fields}")
        if "reward" not in values:
            reward = PlayerOneRewardConfig()
        else:
            raw_reward = values.pop("reward")
            if isinstance(raw_reward, PlayerOneRewardConfig):
                reward = raw_reward
            elif isinstance(raw_reward, DictConfig):
                reward_values = OmegaConf.to_container(raw_reward, resolve=True)
                if not isinstance(reward_values, dict):
                    raise TypeError(
                        "actor_rollout_ref.rollout.custom.player1.agent_loop.reward "
                        f"must resolve to a mapping, got {type(reward_values).__name__}"
                    )
                reward = _reward_config_from_values(reward_values)
            elif isinstance(raw_reward, Mapping):
                reward = _reward_config_from_values(dict(raw_reward))
            else:
                raise TypeError(
                    "actor_rollout_ref.rollout.custom.player1.agent_loop.reward must be a mapping, "
                    f"got {type(raw_reward).__name__}"
                )
        return cls(**values, reward=reward)


@dataclass(frozen=True)
class PlayerOneManagerConfig:
    train_num_workers: int
    actor_loss_agg_mode: str
    critic_loss_agg_mode: str
    advantage_normalization: str
    advantage_estimator: str

    def __post_init__(self):
        _require_int("train_num_workers", self.train_num_workers, minimum=1)
        if self.actor_loss_agg_mode != self.critic_loss_agg_mode:
            raise ValueError("actor and critic loss_agg_mode must match")
        if self.advantage_normalization not in {"global", "per_environment"}:
            raise ValueError("advantage_normalization must be global or per_environment")
        if self.advantage_normalization == "per_environment" and self.advantage_estimator != "gae":
            raise ValueError("per-environment whitening requires algorithm.adv_estimator=gae")

    @classmethod
    def from_trainer_config(cls, config):
        if not isinstance(config, DictConfig):
            raise TypeError("Player-1 trainer config must be DictConfig")
        return cls(
            train_num_workers=config.actor_rollout_ref.rollout.agent.num_workers,
            actor_loss_agg_mode=config.actor_rollout_ref.actor.loss_agg_mode,
            critic_loss_agg_mode=config.critic.loss_agg_mode,
            advantage_normalization=OmegaConf.select(
                config, "actor_rollout_ref.rollout.custom.player1.advantage_normalization", default="global",
            ),
            advantage_estimator=config.algorithm.adv_estimator,
        )

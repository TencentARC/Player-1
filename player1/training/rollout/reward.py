"""Generic reward computation for Player-1 agent loops.

中文说明：
这个文件集中放置 Player-1 rollout 的通用 reward 逻辑，避免把环境交互、
LLM 生成、trace 记录和 reward 计算混在同一个 agent loop 文件里。

Player-1 任务通过 task YAML 中的 training_reward_field 指定累计分数字段，
本文件读取其 delta 作为训练环境分数，所有游戏共用同一计算路径。

Reward component glossary / reward 分量说明：
- generic_metric_reward: 本 step 最终采用的环境分数信号。base 任务等显式声明
  training_reward_field 的任务使用该字段 delta。缺少 task 配置是配置错误；
  当前 state 缺少该字段也是运行时契约错误，会淘汰对应 rollout。
- training_score_delta: 显式 training_reward_field 的累计字段 delta。训练应使用
  这个值。
- primary_score_delta: state.metrics.primary_score 相比上一帧/上一步的变化。
  这是监控分量，不参与训练 reward 选择。
- env_reward_step_value: state.metrics.env_reward_step 的原始值。它表示环境
  已经按 step 给出的事件 reward；它是监控分量，不参与训练 reward 选择。
- env_reward_episode_delta: state.metrics.env_reward_episode 相比上一帧/上一步
  的变化。它是监控分量，不参与训练 reward 选择。
- game_score_delta: state.game_state.score 相比上一帧/上一步的变化。它是更
  原始的游戏内 score telemetry，不参与训练 reward 选择。
- terminal_penalty: 当前 transition 以失败终局结束时扣除。
- think_length_penalty: 模型单次输出的 thinking/prose token 超过
  PLAYER1_THINK_MAX_TOKENS 后按长度扣除；上限按单次输出 cap，再跨 step 求和。
- malformed_action_penalty: format retry 耗尽后仍没有可执行 action 时扣除。
- thinking_tokens: 本 step 被识别为 thinking/prose 的 token 数。
- action_tokens: 本 step response_mask 中 action/tool_call 部分的 token 数。
- output_tokens: 本 step 模型实际生成的 token 数。
- action_truncated: 本 step 输出达到 max_turn_tokens 且没有完整 action 时为 1。

English notes:
This module owns game-agnostic Player-1 reward computation. Task YAML is the
source of truth for the cumulative training score path and its optional fixed
training reward scale. The complete step reward, including penalties, is
converted to training units exactly once.

Each environment turn is emitted as its own exact-context AgentLoopOutput.
Rollout totals are aggregated from the step records produced by that rollout;
``rollout.response_length`` does not truncate a combined multi-turn trajectory
in the maintained TransferQueue training path.
"""

from __future__ import annotations

import math
from typing import Any

from ._reward_sources import EPISODE_REWARD_SOURCES
from .config import PlayerOneRewardConfig


def safe_float(value: Any, default: float = 0.0) -> float:
    """Convert numeric-like values safely.

    环境 state 里有些字段可能是 None、字符串或缺失；reward 计算不应该因此崩溃。
    State fields may be None, strings, or missing; reward math should
    degrade to a default instead of crashing.
    """

    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def optional_float(value: Any) -> float | None:
    """Return None for absent/non-numeric values instead of forcing 0.0.

    None 和 0.0 的语义不同；None 表示这个 reward 信号不存在。
    None means a signal is absent, which is different from an explicit
    zero reward signal.
    """

    try:
        if value is None:
            return None
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    except (TypeError, ValueError):
        return None


def get_nested_value(state: dict[str, Any] | None, *path: str) -> Any:
    """Read nested dictionaries without KeyError.

    Player-1 各游戏导出的 state schema 不完全一致，所以 reward 读取要宽容。
    Different games expose slightly different state schemas, so reward
    extraction must tolerate missing paths.
    """

    current: Any = state
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def get_field_path_value(state: dict[str, Any] | None, field_path: str) -> Any:
    """Read a dotted state path such as ``metrics.primary_score``."""

    parts = [part for part in str(field_path or "").split(".") if part]
    if not parts:
        return None
    return get_nested_value(state, *parts)


def extract_training_reward_field(config: Any | None) -> str:
    """Extract the explicit cumulative training score field from runtime config."""

    if config is None:
        return ""
    if isinstance(config, dict):
        value = config.get("training_reward_field")
    else:
        value = getattr(config, "training_reward_field", "")
    return str(value or "").strip()


def extract_task_start_score(config: Any | None) -> float:
    """Return the finite cumulative-score baseline declared by the task."""

    if isinstance(config, dict):
        value = config.get("task_start_score_field", 0.0)
    else:
        value = getattr(config, "task_start_score_field", 0.0)
    start_score = optional_float(value)
    if start_score is None:
        raise ValueError("Player-1 task_start_score_field must be a finite number")
    return start_score


def extract_training_reward_scale(config: Any | None) -> float | None:
    """Return the optional positive task-level training reward scale."""

    if isinstance(config, dict):
        value = config.get("training_reward_scale")
    else:
        value = getattr(config, "training_reward_scale", None)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Player-1 training_reward_scale must be a positive finite number")
    scale = float(value)
    if not math.isfinite(scale) or scale <= 0.0:
        raise ValueError("Player-1 training_reward_scale must be a positive finite number")
    return scale


class PlayerOneRewardComputer:
    """Stateful reward computer bound to a set of coefficients.

    这个类不持有环境对象，只持有 reward 系数；输入是 prev_state/current_state/
    eval_metrics/model formatting stats，输出是 reward 和可记录的 components。

    This class does not own the browser environment. It only owns reward
    coefficients and turns rollout state/format signals into rewards and
    loggable component dictionaries.
    """

    def __init__(self, config: PlayerOneRewardConfig):
        if not isinstance(config, PlayerOneRewardConfig):
            raise TypeError(f"config must be PlayerOneRewardConfig, got {type(config).__name__}")
        self.config = config

    @staticmethod
    def extract_common_reward_metrics(state: dict[str, Any] | None) -> dict[str, float | None]:
        """Extract common score-like signals.

        优先保留 raw metric 语义，不在这里做 reward 选择。
        This only extracts raw signals; priority/fallback selection is
        handled later by reward scoring.
        """

        metrics = state.get("metrics") if isinstance(state, dict) else None
        return {
            "primary_score": optional_float(get_nested_value(metrics, "primary_score")),
            "env_reward_step": optional_float(get_nested_value(metrics, "env_reward_step")),
            "env_reward_episode": optional_float(get_nested_value(metrics, "env_reward_episode")),
            "best_score": optional_float(
                get_nested_value(metrics, "best_score")
                if get_nested_value(metrics, "best_score") is not None
                else get_nested_value(metrics, "best_primary_score")
            ),
            "game_score": optional_float(get_nested_value(state, "game_state", "score")),
        }

    @staticmethod
    def extract_training_score_value(
        state: dict[str, Any] | None,
        *,
        config: Any | None = None,
    ) -> tuple[str, float | None]:
        """Return the configured cumulative training score, if present in state."""

        training_reward_field = extract_training_reward_field(config)
        if not training_reward_field:
            raise ValueError("Player-1 task must set task YAML training_reward_field")
        return training_reward_field, optional_float(get_field_path_value(state, training_reward_field))

    @classmethod
    def require_training_score_value(
        cls,
        state: dict[str, Any] | None,
        *,
        config: Any | None = None,
    ) -> float:
        """Return the configured finite score or reject the invalid rollout state."""

        training_reward_field, training_score = cls.extract_training_score_value(state, config=config)
        if training_score is None:
            raise ValueError(f"Player-1 state is missing the configured finite training score {training_reward_field!r}")
        return training_score

    def compute_generic_metric_reward(
        self,
        *,
        config: Any | None = None,
        prev_state: dict[str, Any] | None,
        state: dict[str, Any] | None,
    ) -> tuple[float, dict[str, float]]:
        """Compute per-step reward from common metrics.

        Tasks use an explicit cumulative score field from task YAML. Other
        score-like metrics are retained only as telemetry.
        """

        prev_metrics = self.extract_common_reward_metrics(prev_state)
        current_metrics = self.extract_common_reward_metrics(state)

        primary_score_delta = (current_metrics["primary_score"] or 0.0) - (prev_metrics["primary_score"] or 0.0)
        env_reward_episode_delta = (current_metrics["env_reward_episode"] or 0.0) - (
            prev_metrics["env_reward_episode"] or 0.0
        )
        game_score_delta = (current_metrics["game_score"] or 0.0) - (prev_metrics["game_score"] or 0.0)

        current_training_score = self.require_training_score_value(state, config=config)
        _, prev_training_score = self.extract_training_score_value(prev_state, config=config)
        previous_score_missing = prev_state is not None and prev_training_score is None
        previous_score_for_delta = (
            extract_task_start_score(config) if prev_training_score is None else prev_training_score
        )
        training_score_delta = current_training_score - previous_score_for_delta
        generic_metric_reward = training_score_delta

        return generic_metric_reward, {
            "generic_metric_reward": generic_metric_reward,
            "training_score_delta": training_score_delta,
            "training_score_missing": 1.0 if previous_score_missing else 0.0,
            "training_score_current_missing": 0.0,
            "training_score_previous_missing": 1.0 if previous_score_missing else 0.0,
            "primary_score_delta": primary_score_delta,
            "env_reward_step_value": (
                0.0 if current_metrics["env_reward_step"] is None else current_metrics["env_reward_step"]
            ),
            "env_reward_episode_delta": env_reward_episode_delta,
            "game_score_delta": game_score_delta,
        }

    def resolve_training_reward_scale(
        self,
        *,
        config: Any | None = None,
        state: dict[str, Any] | None = None,
    ) -> float:
        """Return the scale that converts raw game scores to training units."""

        del state
        if not self.config.rescale_reward:
            return 1.0
        return extract_training_reward_scale(config) or 1.0

    @staticmethod
    def rescale_reward_value(value: float, scale: float) -> float:
        return float(value) / float(scale)

    @staticmethod
    def clamp_reward_value(value: float, *, enabled: bool = False) -> float:
        if not enabled:
            return float(value)
        return min(max(float(value), 0.0), 1.0)

    def compute_step_reward(
        self,
        *,
        config: Any | None = None,
        prev_state: dict[str, Any] | None,
        state: dict[str, Any] | None,
        terminal_failed: bool,
        think_length_penalty: float = 0.0,
        malformed_action_penalty: float = 0.0,
    ) -> tuple[float, dict[str, float]]:
        """Per-environment-step reward.

        所有游戏都走同一套通用 metric delta，再统一扣除 retained-step penalties。
        All games use common metric deltas plus retained-step penalties.
        """

        raw_terminal_penalty = self.config.terminal_fail_penalty if terminal_failed else 0.0
        raw_think_length_penalty = max(0.0, safe_float(think_length_penalty))
        raw_malformed_action_penalty = max(0.0, safe_float(malformed_action_penalty))
        raw_generic_metric_reward, raw_generic_metric_components = self.compute_generic_metric_reward(
            config=config,
            prev_state=prev_state,
            state=state,
        )
        training_reward_scale = self.resolve_training_reward_scale(config=config, state=state)
        raw_step_reward = (
            raw_generic_metric_reward
            - raw_terminal_penalty
            - raw_think_length_penalty
            - raw_malformed_action_penalty
        )
        generic_metric_reward = self.rescale_reward_value(raw_generic_metric_reward, training_reward_scale)
        terminal_penalty = self.rescale_reward_value(raw_terminal_penalty, training_reward_scale)
        think_length_penalty = self.rescale_reward_value(raw_think_length_penalty, training_reward_scale)
        malformed_action_penalty = self.rescale_reward_value(raw_malformed_action_penalty, training_reward_scale)
        step_reward = self.rescale_reward_value(raw_step_reward, training_reward_scale)
        unscaled_component_keys = {
            "training_score_missing",
            "training_score_current_missing",
            "training_score_previous_missing",
        }
        normalized_metric_components = {}
        for key, value in raw_generic_metric_components.items():
            if key in unscaled_component_keys:
                normalized_metric_components[key] = float(value or 0.0)
            else:
                normalized_metric_components[key] = self.rescale_reward_value(value, training_reward_scale)
        normalized_metric_components["generic_metric_reward"] = generic_metric_reward
        raw_metric_components = {
            f"raw_{key}": value
            for key, value in raw_generic_metric_components.items()
            if key not in unscaled_component_keys
        }

        return step_reward, {
            "terminal_penalty": terminal_penalty,
            "think_length_penalty": think_length_penalty,
            "malformed_action_penalty": malformed_action_penalty,
            "training_reward_scale": training_reward_scale,
            "raw_step_reward": raw_step_reward,
            "raw_terminal_penalty": raw_terminal_penalty,
            "raw_think_length_penalty": raw_think_length_penalty,
            "raw_malformed_action_penalty": raw_malformed_action_penalty,
            **normalized_metric_components,
            **raw_metric_components,
        }

    @staticmethod
    def did_fail_terminal(*, eval_result: Any, state: dict[str, Any] | None) -> bool:
        """Whether the current transition ended in failure."""

        terminal = get_nested_value(state, "terminal")
        if isinstance(terminal, dict) and terminal.get("isTerminal"):
            return str(terminal.get("outcome") or "").lower() != "success"

        if eval_result is None:
            return False

        if getattr(eval_result, "status", None) == "success":
            return False

        return bool(getattr(eval_result, "should_stop", False) or getattr(eval_result, "should_reset", False))

    def extract_episode_game_score(self, state: dict[str, Any] | None, *, config: Any | None = None) -> float:
        """Extract final game score from the explicit training score field."""

        return self.require_training_score_value(state, config=config)

    def compute_reward_score(
        self,
        *,
        config: Any | None = None,
        task_succeeded: bool,
        eval_metrics: dict[str, Any],
        state: dict[str, Any] | None,
        turn_scores: list[float] | None = None,
        reward_component_totals: dict[str, float] | None = None,
    ) -> tuple[float, dict[str, float]]:
        """Final reward attached to the rollout sample.

        PPO/GRPO 最终看到的是这个 reward_score；components 进入日志和 trace。
        PPO/GRPO consumes this final reward_score, while components are logged
        for analysis and debugging.
        """

        eval_metrics = eval_metrics or {}
        optional_task_metric = optional_float(eval_metrics.get("score_best"))
        task_metric = 0.0 if optional_task_metric is None else optional_task_metric
        metrics = self.extract_common_reward_metrics(state)
        primary_score = metrics["primary_score"]
        env_reward_episode = metrics["env_reward_episode"]
        best_score = metrics["best_score"]
        game_score = self.require_training_score_value(state, config=config)
        dense_reward = float(sum(turn_scores or []))
        training_reward_scale = self.resolve_training_reward_scale(config=config, state=state)
        optional_normalized_task_metric = (
            None
            if optional_task_metric is None
            else self.rescale_reward_value(optional_task_metric, training_reward_scale)
        )
        normalized_task_metric = 0.0 if optional_normalized_task_metric is None else optional_normalized_task_metric
        dense_reward_score = dense_reward if turn_scores else normalized_task_metric
        episode_reward_source_index = self.config.episode_reward_source
        episode_reward_target = (
            None
            if self.config.episode_reward_target is None
            else float(self.config.episode_reward_target)
        )
        reward_mode = self.config.reward_mode
        if reward_mode == "dense":
            reward_score = dense_reward_score
            reward_mode_index = 0.0
            episode_reward_source_value = 0.0
            episode_reward_unclipped = 0.0
            episode_reward = 0.0
        else:
            source_values = {
                "success": 1.0 if task_succeeded else 0.0,
                "dense": dense_reward,
                "task_metric": optional_task_metric,
                "primary": primary_score,
                "env_episode": env_reward_episode,
                "game": game_score,
                "best": best_score,
            }
            selected_value = source_values[episode_reward_source_index.removeprefix("normalized_")]
            if selected_value is not None and episode_reward_source_index.startswith("normalized_"):
                selected_value = self.rescale_reward_value(selected_value, training_reward_scale)
            if selected_value is None or not math.isfinite(float(selected_value)):
                raise ValueError(
                    f"Episode reward source {episode_reward_source_index!r} is missing or non-finite in the terminal result"
                )
            episode_reward_source_value = float(selected_value)
            episode_reward_unclipped = (
                episode_reward_source_value
                if episode_reward_target is None
                else episode_reward_source_value / episode_reward_target
            )
            episode_reward = self.clamp_reward_value(
                episode_reward_unclipped,
                enabled=self.config.episode_reward_clip,
            )
            reward_score = episode_reward
            reward_mode_index = 1.0

        reward_components = {
            "task_metric": task_metric,
            "game_score": game_score,
            "primary_score": 0.0 if primary_score is None else primary_score,
            "env_reward_episode": 0.0 if env_reward_episode is None else env_reward_episode,
            "best_score": 0.0 if best_score is None else best_score,
            "dense_reward": dense_reward,
            "dense_reward_score": dense_reward_score,
            "episode_reward": episode_reward,
            "episode_reward_unclipped": episode_reward_unclipped,
            "episode_reward_source_value": episode_reward_source_value,
            "episode_reward_target": 0.0 if episode_reward_target is None else episode_reward_target,
            "reward_mode_index": reward_mode_index,
            "episode_reward_source_index": float(EPISODE_REWARD_SOURCES.index(episode_reward_source_index)),
            "training_reward_scale": training_reward_scale,
            "normalized_task_metric": normalized_task_metric,
        }
        if reward_component_totals:
            reward_components.update(reward_component_totals)
        return reward_score, reward_components


def empty_reward_component_totals() -> dict[str, float]:
    """Return all reward component totals with stable keys.

    保持 key 稳定可以避免指标聚合中途 KeyError。
    Stable keys prevent KeyError during metrics aggregation.
    """

    return {
        "generic_metric_reward_total": 0.0,
        "training_score_missing_total": 0.0,
        "terminal_penalty_total": 0.0,
        "think_length_penalty_total": 0.0,
        "malformed_action_penalty_total": 0.0,
        "thinking_token_total": 0.0,
        "malformed_action_total": 0.0,
        "action_token_total": 0.0,
        "output_token_total": 0.0,
        "action_truncated_total": 0.0,
    }


def aggregate_reward_component_totals(step_records: list[dict[str, Any]]) -> dict[str, float]:
    """Aggregate reward components across the environment turns in one rollout."""

    totals = empty_reward_component_totals()
    component_to_total = {
        "generic_metric_reward": "generic_metric_reward_total",
        "training_score_missing": "training_score_missing_total",
        "terminal_penalty": "terminal_penalty_total",
        "think_length_penalty": "think_length_penalty_total",
        "malformed_action_penalty": "malformed_action_penalty_total",
        "thinking_tokens": "thinking_token_total",
        "malformed_action": "malformed_action_total",
        "action_tokens": "action_token_total",
        "output_tokens": "output_token_total",
        "action_truncated": "action_truncated_total",
    }

    for record in step_records:
        reward_components = record.get("reward_components") or {}
        for component_key, total_key in component_to_total.items():
            totals[total_key] += float(reward_components.get(component_key, 0.0) or 0.0)

    return totals


__all__ = [
    "PlayerOneRewardComputer",
    "PlayerOneRewardConfig",
    "aggregate_reward_component_totals",
    "empty_reward_component_totals",
    "get_nested_value",
    "optional_float",
    "safe_float",
]

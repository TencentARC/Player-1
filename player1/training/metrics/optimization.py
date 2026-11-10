from __future__ import annotations

from typing import Any, Sequence

import numpy as np
import torch

_PLAYER1_DATA_SOURCE_PREFIX = "game-gym/"
_METRIC_PATHS = {
    "reward": "reward/total",
    "score": "score",
    "reward_score_gap": "reward/score_gap",
    "training_score_missing_total": "reward/missing/training_score_total",
    "terminal_penalty_total": "reward/penalty/terminal_total",
    "think_length_penalty_total": "reward/penalty/think_length_total",
    "malformed_action_penalty_total": "reward/penalty/malformed_action_total",
    "action_entropy": "action/entropy",
    "action_top_fraction": "action/top_fraction",
    "valid_action_rate": "action/valid_rate",
    "action_repeat_rate": "action/repeat_rate",
    "dual_channel_frame_count": "format/dual_channel_frame_count",
    "avg_output_tokens": "tokens/output/length_mean",
    "tokens_per_valid_action": "tokens/per_valid_action",
    "input_context_length_mean": "tokens/input/context_length_mean",
    "output_thinking_length_mean": "tokens/output/thinking_length_mean",
    "output_action_length_mean": "tokens/output/action_length_mean",
    "format_retry_count": "format/retry_count",
    "no_valid_action_generation_count": "format/no_valid_action_generation_count",
    "retained_step_count": "rollout/retained_step_count",
    "rollout_timeout": "rollout/timeout_rate",
    "rollout_attempt_count": "rollout/attempt_count",
    "invalid_rollout_attempt_count": "rollout/invalid_attempt_count",
    "rollout_retry_exhausted": "rollout/retry_exhausted_rate",
}
_STD_METRICS = {"reward", "score"}


def final_session_indices(keys: Sequence[str], tags: Sequence[dict[str, Any]]) -> list[int]:
    """Return the final non-padding output index for every successful session."""

    if len(keys) != len(tags):
        raise ValueError(f"keys/tags length mismatch: {len(keys)} != {len(tags)}")

    final_outputs: dict[str, tuple[int, int]] = {}
    for position, (key, tag) in enumerate(zip(keys, tags, strict=True)):
        if tag.get("is_padding", False):
            continue
        parts = str(key).rsplit("_", 2)
        if len(parts) == 3:
            session_key = f"{parts[0]}_{parts[1]}"
            try:
                output_index = int(parts[2])
            except ValueError:
                session_key = str(key)
                output_index = 0
        else:
            session_key = str(key)
            output_index = 0
        previous = final_outputs.get(session_key)
        if previous is None or output_index > previous[0]:
            final_outputs[session_key] = (output_index, position)

    return [position for _, position in sorted(final_outputs.values(), key=lambda item: item[1])]


def aggregate_training_metrics(
    *,
    data_sources: Sequence[Any],
    extra_fields: Sequence[Any],
    prefix: str = "train-aux",
) -> dict[str, float]:
    """Aggregate compact episode-level Player-1 metrics from final turn outputs."""

    if len(data_sources) != len(extra_fields):
        raise ValueError(f"data_sources/extra_fields length mismatch: {len(data_sources)} != {len(extra_fields)}")

    grouped: dict[str, dict[str, list[float]]] = {}
    target_groups: dict[str, dict[str, list[float]]] = {}
    for data_source, fields in zip(data_sources, extra_fields, strict=True):
        source = str(data_source)
        if not source.startswith(_PLAYER1_DATA_SOURCE_PREFIX) or not isinstance(fields, dict):
            continue
        reward_info = fields.get("reward_extra_info")
        if not isinstance(reward_info, dict):
            continue
        display_source = source.removeprefix(_PLAYER1_DATA_SOURCE_PREFIX)
        source_metrics = grouped.setdefault(display_source, {})
        for key in _METRIC_PATHS:
            value = reward_info.get(key)
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                continue
            if np.isfinite(numeric):
                source_metrics.setdefault(key, []).append(numeric)

        turn_indices = fields.get("training_turn_indices")
        training_targets = fields.get("training_turn_targets")
        if (
            isinstance(turn_indices, (list, tuple))
            and isinstance(training_targets, (list, tuple))
            and len(turn_indices) == len(training_targets)
            and training_targets
        ):
            try:
                index_array = np.asarray(turn_indices, dtype=np.float64)
                target_array = np.asarray(training_targets, dtype=np.float64)
            except (TypeError, ValueError):
                continue
            valid = np.isfinite(index_array) & np.isfinite(target_array)
            if valid.any():
                index_array = index_array[valid]
                target_array = target_array[valid]
                target_group = target_groups.setdefault(
                    display_source,
                    {"turn_index": [], "target": [], "first": [], "last": []},
                )
                target_group["turn_index"].extend(index_array.tolist())
                target_group["target"].extend(target_array.tolist())
                target_group["first"].append(float(target_array[0]))
                target_group["last"].append(float(target_array[-1]))

    metrics: dict[str, float] = {}
    for source, source_metrics in grouped.items():
        for key, values in source_metrics.items():
            metric_prefix = f"{prefix}/{source}/{_METRIC_PATHS[key]}"
            metrics[f"{metric_prefix}/mean"] = float(np.mean(values))
            if key in _STD_METRICS:
                metrics[f"{metric_prefix}/std"] = float(np.std(values))

    if grouped:
        metric_keys = {key for source_metrics in grouped.values() for key in source_metrics}
        for key in metric_keys:
            source_means = [
                float(np.mean(source_metrics[key])) for source_metrics in grouped.values() if source_metrics.get(key)
            ]
            if source_means:
                metrics[f"{prefix}/joint/{_METRIC_PATHS[key]}/macro_mean"] = float(np.mean(source_means))

    for source, target_group in target_groups.items():
        turn_indices = np.asarray(target_group["turn_index"], dtype=np.float64)
        targets = np.asarray(target_group["target"], dtype=np.float64)
        metric_prefix = f"{prefix}/{source}/training_target"
        metrics[f"{metric_prefix}/mean"] = float(np.mean(targets))
        metrics[f"{metric_prefix}/std"] = float(np.std(targets))
        metrics[f"{metric_prefix}/first_turn/mean"] = float(np.mean(target_group["first"]))
        metrics[f"{metric_prefix}/last_turn/mean"] = float(np.mean(target_group["last"]))

        target_variance = float(np.var(targets))
        turn_variance = float(np.var(turn_indices))
        if target_variance > 0.0 and turn_variance > 0.0:
            metrics[f"{metric_prefix}/turn_index/correlation"] = float(np.corrcoef(turn_indices, targets)[0, 1])
            predicted = np.empty_like(targets)
            for turn_index in np.unique(turn_indices):
                turn_mask = turn_indices == turn_index
                predicted[turn_mask] = np.mean(targets[turn_mask])
            residual_variance = float(np.mean(np.square(targets - predicted)))
            metrics[f"{metric_prefix}/turn_index/explained_variance"] = max(
                0.0, 1.0 - residual_variance / target_variance
            )
    return metrics


def _as_numpy_vector(value: Any) -> np.ndarray:
    if hasattr(value, "detach"):
        value = value.detach()
        if value.dtype == torch.bfloat16:
            value = value.float()
        value = value.cpu().numpy()
    return np.asarray(value).reshape(-1)


def whiten_advantages_by_environment(
    *,
    advantages: torch.Tensor,
    response_mask: torch.Tensor,
    data_sources: Sequence[str],
    prefix: str = "train-joint",
) -> tuple[torch.Tensor, dict[str, float]]:
    """Whiten masked GAE advantages independently within each Player-1 environment."""

    if advantages.shape != response_mask.shape:
        raise ValueError(
            f"advantages/response_mask shape mismatch: {tuple(advantages.shape)} != {tuple(response_mask.shape)}"
        )
    if advantages.ndim != 2:
        raise ValueError(f"environment advantage whitening expects a padded 2D tensor, got {advantages.ndim}D")
    if len(data_sources) != advantages.shape[0]:
        raise ValueError(f"data_sources/advantages row mismatch: {len(data_sources)} != {advantages.shape[0]}")

    environment_rows: dict[str, list[int]] = {}
    for row_index, data_source in enumerate(data_sources):
        source = str(data_source)
        has_trainable_tokens = bool(response_mask[row_index].bool().any().item())
        if not source.startswith(_PLAYER1_DATA_SOURCE_PREFIX):
            if has_trainable_tokens:
                raise ValueError(f"environment advantage whitening received a non-Player-1 row: {source}")
            continue
        if has_trainable_tokens:
            environment_id = source.removeprefix(_PLAYER1_DATA_SOURCE_PREFIX)
            environment_rows.setdefault(environment_id, []).append(row_index)

    if not environment_rows:
        raise ValueError("environment advantage whitening requires at least one active Player-1 row")

    normalized = advantages.clone()
    metrics: dict[str, float] = {}
    for environment_id, row_indices in sorted(environment_rows.items()):
        index = torch.tensor(row_indices, device=advantages.device, dtype=torch.long)
        environment_advantages = advantages.index_select(0, index)
        environment_mask = response_mask.index_select(0, index).bool()
        token_count = int(environment_mask.sum().item())
        if token_count < 2:
            raise ValueError(
                f"environment advantage whitening requires at least two trainable tokens for {environment_id!r}, "
                f"got {token_count}"
            )

        stats_advantages = environment_advantages.float()
        stats_mask = environment_mask.float()
        mean = (stats_advantages * stats_mask).sum() / token_count
        centered = stats_advantages - mean
        variance = (centered.square() * stats_mask).sum() / token_count
        variance = variance * token_count / (token_count - 1)
        whitened = centered * torch.rsqrt(variance + 1e-8)
        normalized_rows = torch.where(environment_mask, whitened.to(advantages.dtype), environment_advantages)
        normalized.index_copy_(0, index, normalized_rows)

        active_values = normalized_rows.float()[environment_mask]
        metric_prefix = f"{prefix}/{environment_id}/advantage/post_whiten"
        metrics[f"{metric_prefix}/mean"] = float(active_values.mean().item())
        metrics[f"{metric_prefix}/std"] = float(active_values.std(unbiased=True).item())

    return normalized, metrics


def aggregate_joint_optimization_metrics(
    *,
    data_sources: Sequence[Any],
    response_masks: Sequence[Any],
    values: Sequence[Any] | None = None,
    returns: Sequence[Any] | None = None,
    prefix: str = "train-joint",
) -> dict[str, float]:
    """Aggregate the minimal per-environment optimization diagnostics."""

    row_count = len(data_sources)
    if len(response_masks) != row_count:
        raise ValueError(f"data_sources/response_masks length mismatch: {row_count} != {len(response_masks)}")
    if (values is None) != (returns is None):
        raise ValueError("values and returns must either both be provided or both be omitted")
    if values is not None and (len(values) != row_count or len(returns) != row_count):
        raise ValueError("data_sources, values, and returns must have matching lengths")

    active_rows: dict[str, int] = {}
    residuals: dict[str, list[np.ndarray]] = {}
    target_returns: dict[str, list[np.ndarray]] = {}

    for index, (data_source, response_mask) in enumerate(zip(data_sources, response_masks, strict=True)):
        source = str(data_source)
        if not source.startswith(_PLAYER1_DATA_SOURCE_PREFIX):
            continue
        environment_id = source.removeprefix(_PLAYER1_DATA_SOURCE_PREFIX)
        mask = _as_numpy_vector(response_mask).astype(bool, copy=False)
        if not mask.any():
            continue
        active_rows[environment_id] = active_rows.get(environment_id, 0) + 1

        if values is None or returns is None:
            continue
        value_row = _as_numpy_vector(values[index]).astype(np.float64, copy=False)
        return_row = _as_numpy_vector(returns[index]).astype(np.float64, copy=False)
        if value_row.size != mask.size or return_row.size != mask.size:
            raise ValueError(
                f"optimization tensor length mismatch at row {index}: "
                f"mask={mask.size}, values={value_row.size}, returns={return_row.size}"
            )
        valid = mask & np.isfinite(value_row) & np.isfinite(return_row)
        if not valid.any():
            continue
        residuals.setdefault(environment_id, []).append(return_row[valid] - value_row[valid])
        target_returns.setdefault(environment_id, []).append(return_row[valid])

    total_active_rows = sum(active_rows.values())
    metrics: dict[str, float] = {}
    if total_active_rows:
        metrics[f"{prefix}/joint/weight/turn_rows/count"] = float(total_active_rows)
    for environment_id, count in active_rows.items():
        metrics[f"{prefix}/{environment_id}/weight/turn_rows/fraction"] = float(count / total_active_rows)
        metrics[f"{prefix}/{environment_id}/weight/loss/fraction"] = float(count / total_active_rows)

        environment_residuals = residuals.get(environment_id)
        environment_returns = target_returns.get(environment_id)
        if not environment_residuals or not environment_returns:
            continue
        residual = np.concatenate(environment_residuals)
        return_values = np.concatenate(environment_returns)
        metric_prefix = f"{prefix}/{environment_id}"
        metrics[f"{metric_prefix}/advantage/pre_whiten/mean"] = float(np.mean(residual))
        metrics[f"{metric_prefix}/advantage/pre_whiten/std"] = float(
            np.std(residual, ddof=1) if residual.size > 1 else 0.0
        )
        metrics[f"{metric_prefix}/value/residual/rmse"] = float(np.sqrt(np.mean(np.square(residual))))
        if residual.size > 1:
            residual_variance = float(np.var(residual, ddof=1))
            return_variance = float(np.var(return_values, ddof=1))
            metrics[f"{metric_prefix}/value/explained_variance"] = float(
                1.0 - residual_variance / (return_variance + 1e-5)
            )
    return metrics

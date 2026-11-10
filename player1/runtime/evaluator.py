"""Task evaluation helpers for Player-1."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .config import RuntimeConfig
from .types import Agent


@dataclass
class TaskEvaluationResult:
    """Outcome of one task evaluation pass."""

    status: str  # "success", "fail", "unknown", or "error"
    summary: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    should_stop: bool = False
    should_reset: bool = False
    stop_reason: str | None = None
    finalized: bool = False


EPISODE_METRIC_KEYS = (
    "score_current",
    "score_start",
    "score_best",
    "progress_current",
)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _to_float(value: Any) -> float | None:
    if not _is_number(value):
        return None
    return float(value)


def _get_nested_value(state: dict[str, Any] | None, path: str) -> tuple[bool, Any]:
    current: Any = state
    for key in path.split("."):
        if not isinstance(current, dict) or key not in current:
            return False, None
        current = current[key]
    return True, current


def _append_issue(bucket: list[str], message: str) -> None:
    if message not in bucket:
        bucket.append(message)


def _resolve_score(
    state: dict[str, Any] | None,
    config: dict[str, Any],
    *,
    config_errors: list[str],
    runtime_issues: list[str],
) -> float | None:
    aggregate_score_fields = config.get("aggregate_score_fields")
    if aggregate_score_fields is not None:
        if not isinstance(aggregate_score_fields, (list, tuple)) or not aggregate_score_fields:
            config_errors.append("evaluator_config.aggregate_score_fields must be a non-empty list when provided")
            return None

        total = 0.0
        for field_path in aggregate_score_fields:
            if not isinstance(field_path, str) or not field_path.strip():
                config_errors.append("evaluator_config.aggregate_score_fields must contain non-empty string paths")
                return None

            found, current = _get_nested_value(state, field_path)
            if not found:
                _append_issue(runtime_issues, f"missing aggregate score field '{field_path}'")
                return None
            if current is None:
                return None
            numeric_value = _to_float(current)
            if numeric_value is None:
                _append_issue(runtime_issues, f"aggregate score field '{field_path}' is not numeric")
                return None
            total += numeric_value
        return total

    score_field = config.get("score_field")
    if not isinstance(score_field, str) or not score_field.strip():
        config_errors.append("missing evaluator score source: set evaluator_config.score_field or aggregate_score_fields")
        return None

    found, current = _get_nested_value(state, score_field)
    if not found:
        _append_issue(runtime_issues, f"missing score field '{score_field}'")
        return None
    if current is None:
        return None

    score = _to_float(current)
    if score is None:
        _append_issue(runtime_issues, f"score field '{score_field}' is not numeric")
        return None
    return score


def _update_score_metrics(metrics: dict[str, Any], score: float | None, start_score: float) -> float | None:
    score_start = _to_float(metrics.get("score_start"))
    if score_start is None:
        score_start = start_score
        metrics["score_start"] = score_start
    else:
        metrics["score_start"] = score_start

    if score is None:
        return _to_float(metrics.get("score_best"))

    metrics["score_current"] = score

    previous_best = _to_float(metrics.get("score_best"))
    score_best = max(previous_best, score) if previous_best is not None else score
    metrics["score_best"] = score_best

    previous_run_best = _to_float(metrics.get("score_run_best"))
    score_run_best = max(previous_run_best, score) if previous_run_best is not None else score
    metrics["score_run_best"] = score_run_best
    metrics["score"] = score_run_best
    return score_best


def _update_progress_metrics(metrics: dict[str, Any], target_score: float | None) -> bool:
    score_start = _to_float(metrics.get("score_start"))
    score_best = _to_float(metrics.get("score_best"))
    target_reached = bool(metrics.get("target_reached"))

    if target_score is None or score_start is None or score_best is None:
        metrics.pop("progress_current", None)
        if "progress_best" not in metrics:
            metrics.pop("progress", None)
        metrics["target_reached"] = target_reached
        return target_reached

    if target_score <= score_start:
        progress_current = 1.0 if score_best >= target_score else 0.0
    else:
        progress_current = (score_best - score_start) / (target_score - score_start)
        if progress_current < 0.0:
            progress_current = 0.0
        elif progress_current > 1.0:
            progress_current = 1.0

    previous_progress_best = _to_float(metrics.get("progress_best"))
    progress_best = max(previous_progress_best, progress_current) if previous_progress_best is not None else progress_current

    metrics["progress_current"] = progress_current
    metrics["progress_best"] = progress_best
    metrics["progress"] = progress_best

    if score_best >= target_score:
        target_reached = True
    metrics["target_reached"] = target_reached
    return target_reached


def _copy_extra_metrics(metrics: dict[str, Any], state: dict[str, Any] | None, metric_fields: Any) -> None:
    if not isinstance(metric_fields, (list, tuple)):
        return

    for field_name in metric_fields:
        if not isinstance(field_name, str) or not field_name:
            continue
        found, current = _get_nested_value(state, field_name)
        metrics[field_name] = current if found else None


def _resolve_end_match(
    state: dict[str, Any] | None,
    config: dict[str, Any],
    *,
    config_errors: list[str],
    runtime_issues: list[str],
) -> tuple[bool, str]:
    raw_end_field = config.get("end_field", "")
    if raw_end_field in ("", None):
        return False, ""
    if not isinstance(raw_end_field, str) or not raw_end_field.strip():
        config_errors.append("evaluator_config.end_field must be a non-empty string when provided")
        return False, ""

    found, current = _get_nested_value(state, raw_end_field)
    if not found:
        _append_issue(runtime_issues, f"missing end field '{raw_end_field}'")
        return False, raw_end_field
    return current == config.get("end_value", True), raw_end_field


def _resolve_stop_reason(
    *,
    target_reached: bool,
    max_steps_hit: bool,
    end_match: bool,
    terminal_hit: bool,
    should_reset: bool,
) -> str | None:
    if should_reset:
        return "terminal_fail_reset"
    if target_reached:
        return "target_reached"
    if max_steps_hit:
        return "max_steps_exhausted"
    if end_match:
        return "end_field"
    if terminal_hit:
        return "game_terminal"
    return None


def _resolve_status(
    *,
    config_errors: list[str],
    runtime_issues: list[str],
    target_reached: bool,
    terminal_outcome: str | None,
    max_steps_hit: bool,
    end_match: bool,
    terminal_hit: bool,
    terminal_status: str,
    should_reset: bool,
) -> str:
    if config_errors:
        return "error"
    if runtime_issues:
        return "unknown"
    if target_reached:
        return "success"
    if should_reset:
        return "fail"
    if max_steps_hit:
        return "fail"
    if terminal_hit:
        if terminal_outcome in {"success", "fail"}:
            return terminal_outcome
        return terminal_status
    if end_match:
        return terminal_status
    return "unknown"


def _resolve_summary(
    *,
    config_errors: list[str],
    runtime_issues: list[str],
    status: str,
    should_stop: bool,
    should_reset: bool,
    stop_reason: str | None,
) -> str:
    if config_errors:
        visible = config_errors[:2]
        suffix = f"; +{len(config_errors) - len(visible)} more" if len(config_errors) > len(visible) else ""
        return f"evaluator config error: {'; '.join(visible)}{suffix}"

    if runtime_issues:
        visible = runtime_issues[:2]
        suffix = f"; +{len(runtime_issues) - len(visible)} more" if len(runtime_issues) > len(visible) else ""
        summary = f"evaluator unresolved fields: {'; '.join(visible)}{suffix}"
        if stop_reason == "max_steps_exhausted":
            summary = f"{summary}; step budget exhausted"
        return summary

    if should_reset:
        return "terminal fail; reset and continue"
    if not should_stop:
        return ""
    if status == "success":
        return "task complete"
    if stop_reason == "max_steps_exhausted":
        return "step budget exhausted"
    if status == "fail":
        return "task failed"
    return "task complete"


def _finalize_task_evaluation(
    *,
    state: dict[str, Any] | None,
    step_index: int,
    max_steps: int | None,
    target_score: float | None,
    metrics: dict[str, Any],
    config: dict[str, Any],
    start_score: float,
    continue_on_fail: bool,
    finalized: bool,
) -> TaskEvaluationResult:
    metrics = dict(metrics)
    if target_score is not None:
        metrics["task_target_score"] = target_score
    else:
        metrics.pop("task_target_score", None)

    config_errors: list[str] = []
    runtime_issues: list[str] = []

    score = _resolve_score(state, config, config_errors=config_errors, runtime_issues=runtime_issues)
    score_best = _update_score_metrics(metrics, score, start_score)
    target_reached = _update_progress_metrics(metrics, target_score)
    _copy_extra_metrics(metrics, state, config.get("metrics_fields"))

    end_match, end_field = _resolve_end_match(
        state,
        config,
        config_errors=config_errors,
        runtime_issues=runtime_issues,
    )

    terminal = state.get("terminal") if isinstance(state, dict) else None
    terminal_hit = isinstance(terminal, dict) and terminal.get("isTerminal") is True
    terminal_outcome = terminal.get("outcome") if isinstance(terminal, dict) else None
    if not isinstance(terminal_outcome, str) or not terminal_outcome:
        terminal_outcome = None

    max_steps_hit = isinstance(step_index, int) and isinstance(max_steps, int) and step_index >= max_steps
    terminal_status = str(config.get("terminal_status", "unknown"))

    if max_steps_hit and target_score is not None and score_best is None and not config_errors and not runtime_issues:
        if config.get("aggregate_score_fields") is not None:
            _append_issue(runtime_issues, "aggregate score fields never produced a numeric value")
        else:
            _append_issue(runtime_issues, f"score field '{config.get('score_field')}' never produced a numeric value")

    should_reset = (
        continue_on_fail
        and terminal_hit
        and terminal_outcome == "fail"
        and not target_reached
        and not max_steps_hit
        and not (end_match and end_field != "terminal.isTerminal")
    )
    if should_reset and end_field == "terminal.isTerminal":
        end_match = False

    stop_reason = _resolve_stop_reason(
        target_reached=target_reached,
        max_steps_hit=max_steps_hit,
        end_match=end_match,
        terminal_hit=terminal_hit,
        should_reset=should_reset,
    )
    should_stop = stop_reason is not None and stop_reason != "terminal_fail_reset"

    metrics["stop_reason"] = stop_reason
    metrics["finalized"] = finalized

    status = _resolve_status(
        config_errors=config_errors,
        runtime_issues=runtime_issues,
        target_reached=target_reached,
        terminal_outcome=terminal_outcome,
        max_steps_hit=max_steps_hit,
        end_match=end_match,
        terminal_hit=terminal_hit,
        terminal_status=terminal_status,
        should_reset=should_reset,
    )
    summary = _resolve_summary(
        config_errors=config_errors,
        runtime_issues=runtime_issues,
        status=status,
        should_stop=should_stop,
        should_reset=should_reset,
        stop_reason=stop_reason,
    )

    if config_errors:
        metrics["evaluation_config_errors"] = list(config_errors)
    else:
        metrics.pop("evaluation_config_errors", None)
    if runtime_issues:
        metrics["evaluation_runtime_issues"] = list(runtime_issues)
    else:
        metrics.pop("evaluation_runtime_issues", None)

    return TaskEvaluationResult(
        status=status,
        summary=summary,
        metrics=metrics,
        should_stop=should_stop,
        should_reset=should_reset,
        stop_reason=stop_reason,
        finalized=finalized,
    )


def reset_task_evaluator_episode_metrics(metrics: dict[str, Any] | None) -> dict[str, Any]:
    """Clear episode-local score/progress baselines after reset, keep run-wide bests."""
    if not isinstance(metrics, dict):
        return {}

    next_metrics = dict(metrics)
    for key in EPISODE_METRIC_KEYS:
        next_metrics.pop(key, None)

    score_run_best = _to_float(next_metrics.get("score_run_best"))
    if score_run_best is not None:
        next_metrics["score"] = score_run_best
    progress_best = _to_float(next_metrics.get("progress_best"))
    if progress_best is not None:
        next_metrics["progress"] = progress_best
    else:
        next_metrics.pop("progress", None)
    next_metrics["finalized"] = False
    next_metrics["stop_reason"] = None
    return next_metrics


class Evaluator:
    """Framework-neutral task evaluator for structured game states."""

    def __init__(self, config: RuntimeConfig):
        self.evaluator_id = config.evaluator_id
        self.evaluator_config = config.evaluator_config if isinstance(config.evaluator_config, dict) else {}
        self.start_score = float(config.task_start_score_field) if _is_number(config.task_start_score_field) else 0.0
        self.target_score = (
            float(config.task_target_score_field) if _is_number(config.task_target_score_field) else None
        )
        self.max_steps = config.max_steps
        self.continue_on_fail = bool(config.continue_on_fail)

    def _evaluate(
        self,
        agent: Agent,
        state: dict[str, Any] | None,
        *,
        finalized: bool,
    ) -> TaskEvaluationResult:
        if self.evaluator_id != "game_api_metric":
            return TaskEvaluationResult(
                status="unknown",
                metrics=agent.eval_metrics,
                should_stop=False,
                finalized=finalized,
            )
        return _finalize_task_evaluation(
            state=state if isinstance(state, dict) else None,
            step_index=agent.step_index,
            max_steps=self.max_steps,
            target_score=self.target_score,
            metrics=agent.eval_metrics,
            config=self.evaluator_config,
            start_score=self.start_score,
            continue_on_fail=self.continue_on_fail,
            finalized=finalized,
        )

    async def evaluate(self, agent: Agent, state: dict[str, Any] | None) -> TaskEvaluationResult:
        result = self._evaluate(agent, state, finalized=False)
        if result.metrics:
            agent.eval_metrics = dict(result.metrics)
        return result

    async def summarize(self, agent: Agent, state: dict[str, Any] | None) -> TaskEvaluationResult:
        result = self._evaluate(agent, state, finalized=True)
        if result.metrics:
            agent.eval_metrics = dict(result.metrics)
        return result

    def reset_metrics(self, metrics: dict[str, Any] | None) -> dict[str, Any]:
        return reset_task_evaluator_episode_metrics(metrics)


__all__ = [
    "Evaluator",
    "TaskEvaluationResult",
    "reset_task_evaluator_episode_metrics",
]

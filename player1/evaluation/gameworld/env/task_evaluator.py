"""Task evaluation helpers for GameWorld."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


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
    "progress_current",
    "objective_target_bests",
    "objective_target_results",
    "objective_targets_met",
    "objective_requirement_results",
    "objective_requirements_met",
    "target_reached",
)


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


def _format_issue_summary(prefix: str, issues: list[str]) -> str:
    visible = issues[:2]
    suffix = (
        f"; +{len(issues) - len(visible)} more" if len(issues) > len(visible) else ""
    )
    return f"{prefix}: {'; '.join(visible)}{suffix}"


def _set_optional_metric(metrics: dict[str, Any], key: str, value: Any) -> None:
    if value is None:
        metrics.pop(key, None)
    else:
        metrics[key] = value


def _finite_number(value: Any) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    numeric = float(value)
    if not math.isfinite(numeric):
        return None
    return numeric


def _parse_objective_target(
    field_path: str,
    raw_target: Any,
    *,
    config_errors: list[str],
) -> tuple[float, float] | None:
    label = f"evaluator_config.objective.reach['{field_path}']"
    if isinstance(raw_target, dict):
        if "target" not in raw_target:
            config_errors.append(f"{label}.target is required")
            return None
        start = _finite_number(raw_target.get("start", 0))
        target = _finite_number(raw_target.get("target"))
    else:
        start = 0.0
        target = _finite_number(raw_target)

    if start is None:
        config_errors.append(f"{label}.start must be a finite number")
        return None
    if target is None:
        config_errors.append(f"{label}.target must be a finite number")
        return None
    if target <= start:
        config_errors.append(f"{label}.target must be greater than start")
        return None
    return start, target


def _target_progress(best: float | None, start: float, target: float) -> float:
    if best is None:
        return 0.0
    progress = (best - start) / (target - start)
    return min(1.0, max(0.0, progress))


def _resolve_objective(
    state: dict[str, Any] | None,
    config: dict[str, Any],
    metrics: dict[str, Any],
    *,
    config_errors: list[str],
    runtime_issues: list[str],
) -> bool:
    raw_objective = config.get("objective")
    if not isinstance(raw_objective, dict):
        config_errors.append("evaluator_config.objective must be a mapping")
        return False

    raw_reach = raw_objective.get("reach")
    if not isinstance(raw_reach, dict) or not raw_reach:
        config_errors.append(
            "evaluator_config.objective.reach must be a non-empty mapping"
        )
        metrics["objective_target_results"] = []
        metrics["objective_targets_met"] = False
        return False

    episode_bests = metrics.get("objective_target_bests")
    if not isinstance(episode_bests, dict):
        episode_bests = {}
    else:
        episode_bests = dict(episode_bests)

    run_bests = metrics.get("objective_target_run_bests")
    if not isinstance(run_bests, dict):
        run_bests = {}
    else:
        run_bests = dict(run_bests)

    target_results: list[dict[str, Any]] = []
    target_progresses: list[float] = []
    all_targets_met = True

    for field_path, raw_target in raw_reach.items():
        if not isinstance(field_path, str) or not field_path.strip():
            config_errors.append(
                "evaluator_config.objective.reach keys must be non-empty field paths"
            )
            all_targets_met = False
            continue

        parsed = _parse_objective_target(
            field_path,
            raw_target,
            config_errors=config_errors,
        )
        if parsed is None:
            all_targets_met = False
            continue
        start, target = parsed

        found, current = _get_nested_value(state, field_path)
        current_number = _finite_number(current) if found else None
        if not found:
            _append_issue(
                runtime_issues, f"missing objective target field '{field_path}'"
            )
        elif current is not None and current_number is None:
            _append_issue(
                runtime_issues, f"objective target field '{field_path}' is not numeric"
            )

        previous_best = _finite_number(episode_bests.get(field_path))
        if current_number is None:
            best = previous_best
        else:
            best = (
                max(previous_best, current_number)
                if previous_best is not None
                else current_number
            )
            episode_bests[field_path] = best

        previous_run_best = _finite_number(run_bests.get(field_path))
        if current_number is not None:
            run_best = (
                max(previous_run_best, current_number)
                if previous_run_best is not None
                else current_number
            )
            run_bests[field_path] = run_best
        else:
            run_best = previous_run_best

        progress = _target_progress(best, start, target)
        met = best is not None and best >= target
        target_progresses.append(progress)
        all_targets_met = all_targets_met and met
        target_results.append(
            {
                "field": field_path,
                "start": start,
                "target": target,
                "actual": current if found else None,
                "best": best,
                "run_best": run_best,
                "progress": progress,
                "met": met,
            }
        )

    metrics["objective_target_bests"] = episode_bests
    metrics["objective_target_run_bests"] = run_bests
    metrics["objective_target_results"] = target_results
    metrics["objective_targets_met"] = all_targets_met and bool(target_results)

    if target_progresses:
        progress_current = sum(target_progresses) / len(target_progresses)
        previous_progress = _finite_number(metrics.get("progress"))
        progress = (
            max(previous_progress, progress_current)
            if previous_progress is not None
            else progress_current
        )
        metrics["progress_current"] = progress_current
        metrics["progress"] = progress

    if len(target_results) == 1:
        result = target_results[0]
        _set_optional_metric(metrics, "score", result["run_best"])
    else:
        metrics.pop("score", None)

    raw_requirements = raw_objective.get("require")
    if raw_requirements is None:
        metrics.pop("objective_requirement_results", None)
        metrics.pop("objective_requirements_met", None)
        requirements_met = True
    elif not isinstance(raw_requirements, dict) or not raw_requirements:
        config_errors.append(
            "evaluator_config.objective.require must be a non-empty mapping when provided"
        )
        metrics["objective_requirement_results"] = []
        metrics["objective_requirements_met"] = False
        requirements_met = False
    else:
        requirement_results: list[dict[str, Any]] = []
        requirements_met = True
        for field_path, expected in raw_requirements.items():
            if not isinstance(field_path, str) or not field_path.strip():
                config_errors.append(
                    "evaluator_config.objective.require keys must be non-empty field paths"
                )
                requirements_met = False
                continue
            found, current = _get_nested_value(state, field_path)
            if not found:
                _append_issue(
                    runtime_issues,
                    f"missing objective requirement field '{field_path}'",
                )
                met = False
            elif isinstance(current, bool) or isinstance(expected, bool):
                met = (
                    isinstance(current, bool)
                    and isinstance(expected, bool)
                    and current is expected
                )
            else:
                met = current == expected
            requirement_results.append(
                {
                    "field": field_path,
                    "value": expected,
                    "actual": current if found else None,
                    "met": met,
                }
            )
            requirements_met = requirements_met and met
        metrics["objective_requirement_results"] = requirement_results
        metrics["objective_requirements_met"] = requirements_met

    return metrics["objective_targets_met"] and requirements_met


def _copy_extra_metrics(
    metrics: dict[str, Any], state: dict[str, Any] | None, metric_fields: Any
) -> None:
    fields = metric_fields if isinstance(metric_fields, (list, tuple)) else ()

    for field_name in (*fields, "terminal.outcome", "terminal.isTerminal"):
        if not isinstance(field_name, str) or not field_name:
            continue
        found, current = _get_nested_value(state, field_name)
        metrics[field_name] = current if found else None


def _resolve_outcome(
    *,
    config_errors: list[str],
    runtime_issues: list[str],
    target_reached: bool,
    terminal_outcome: str | None,
    max_steps_hit: bool,
    terminal_hit: bool,
    should_reset: bool,
) -> tuple[str, str | None, bool]:
    if should_reset:
        stop_reason = "terminal_fail_reset"
    elif terminal_hit and terminal_outcome in {"fail", "aborted"}:
        stop_reason = "game_terminal"
    elif target_reached:
        stop_reason = "target_reached"
    elif max_steps_hit:
        stop_reason = "max_steps_exhausted"
    elif terminal_hit:
        stop_reason = "game_terminal"
    else:
        stop_reason = None

    should_stop = stop_reason not in {None, "terminal_fail_reset"}

    if config_errors:
        status = "error"
    elif runtime_issues:
        status = "unknown"
    elif should_reset:
        status = "fail"
    elif terminal_hit and terminal_outcome in {"fail", "aborted"}:
        status = "fail"
    elif target_reached:
        status = "success"
    elif max_steps_hit:
        status = "fail"
    elif terminal_hit:
        status = "fail"
    else:
        status = "unknown"

    return status, stop_reason, should_stop


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
        return _format_issue_summary("evaluator config error", config_errors)

    if runtime_issues:
        summary = _format_issue_summary("evaluator unresolved fields", runtime_issues)
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
    return "task ended without a resolved outcome"


def _finalize_task_evaluation(
    state: dict[str, Any] | None,
    step_index: int,
    metrics: dict[str, Any] | None,
    config: dict[str, Any] | None,
    *,
    max_steps: int = 400,
    finalized: bool,
) -> TaskEvaluationResult:
    config = config or {}
    metrics = dict(metrics or {})

    config_errors: list[str] = []
    runtime_issues: list[str] = []

    target_reached = _resolve_objective(
        state,
        config,
        metrics,
        config_errors=config_errors,
        runtime_issues=runtime_issues,
    )
    metrics["target_reached"] = target_reached
    _copy_extra_metrics(metrics, state, config.get("metrics_fields"))

    terminal = state.get("terminal") if isinstance(state, dict) else None
    terminal_hit = isinstance(terminal, dict) and terminal.get("isTerminal") is True
    terminal_outcome = terminal.get("outcome") if isinstance(terminal, dict) else None
    if not isinstance(terminal_outcome, str) or not terminal_outcome:
        terminal_outcome = None
    if terminal_hit and terminal_outcome not in {
        "success",
        "fail",
        "aborted",
        "unknown",
    }:
        _append_issue(
            runtime_issues,
            "terminal outcome must be one of success/fail/aborted/unknown",
        )

    max_steps_hit = (
        isinstance(step_index, int)
        and isinstance(max_steps, int)
        and step_index >= max_steps
    )

    should_reset = terminal_hit and terminal_outcome == "fail" and not max_steps_hit

    status, stop_reason, should_stop = _resolve_outcome(
        config_errors=config_errors,
        runtime_issues=runtime_issues,
        target_reached=target_reached,
        terminal_outcome=terminal_outcome,
        max_steps_hit=max_steps_hit,
        terminal_hit=terminal_hit,
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

    _set_optional_metric(
        metrics,
        "evaluation_config_errors",
        list(config_errors) if config_errors else None,
    )
    _set_optional_metric(
        metrics,
        "evaluation_runtime_issues",
        list(runtime_issues) if runtime_issues else None,
    )

    return TaskEvaluationResult(
        status=status,
        summary=summary,
        metrics=metrics,
        should_stop=should_stop,
        should_reset=should_reset,
        stop_reason=stop_reason,
        finalized=finalized,
    )


def reset_task_evaluator_episode_metrics(
    metrics: dict[str, Any] | None,
) -> dict[str, Any]:
    """Clear episode-local objective state after reset, keeping run-wide bests."""
    if not isinstance(metrics, dict):
        return {}

    next_metrics = dict(metrics)
    for key in EPISODE_METRIC_KEYS:
        next_metrics.pop(key, None)

    return next_metrics


def build_task_evaluator(
    evaluator_config: dict[str, Any] | None = None,
    max_steps: int = 400,
) -> Callable[..., Awaitable[TaskEvaluationResult]]:
    """Create a task evaluator closure with config baked in."""
    config = evaluator_config or {}

    async def run_step(
        state: dict[str, Any] | None,
        step_index: int,
        metrics: dict[str, Any],
        *,
        finalized: bool = False,
    ) -> TaskEvaluationResult:
        return _finalize_task_evaluation(
            state,
            step_index,
            metrics,
            config,
            max_steps=max_steps,
            finalized=finalized,
        )

    return run_step

import itertools
import math
import re
from collections import Counter
from collections.abc import Sequence
from typing import Any

from player1.agents.actions import is_control_action_space_mode
from player1.runtime.contracts import is_valid_action_outcome_payload

from ..rollout.reward import safe_float

ROLLOUT_TIMEOUT_PHASE_CODES = {
    "none": 0,
    "deadline": 1,
    "env_start": 2,
    "state_capture": 3,
    "pause_game": 4,
    "capture_screenshot": 5,
    "observation_chat_template": 6,
    "build_generation_context": 7,
    "render_chat_template": 8,
    "llm_generate": 9,
    "action_uses_virtual_time": 10,
    "resume_game": 11,
    "runtime_step": 12,
    "execute_and_capture": 12,  # Legacy trace compatibility.
    "evaluate_task": 13,
    "summarize_task": 14,
    "reset_game": 15,
    "close_game": 16,
}


def rollout_timeout_phase_code(phase: str | None) -> float:
    return float(ROLLOUT_TIMEOUT_PHASE_CODES.get(phase or "none", ROLLOUT_TIMEOUT_PHASE_CODES["deadline"]))


def build_rollout_timing_summary(
    *,
    timing: dict[str, float],
    step_records: list[dict[str, Any]],
    total_elapsed_s: float,
    generated_turns: int,
) -> dict[str, Any]:
    step_count = len(step_records)
    phase_totals = {key: float(value) for key, value in sorted(timing.items())}
    per_step_totals = [float(sum((record.get("timing") or {}).values())) for record in step_records]
    slowest_phase = max(phase_totals, key=phase_totals.get) if phase_totals else None
    avg_phase_per_step = {key: value / step_count for key, value in phase_totals.items() if step_count > 0}
    return {
        "total_s": float(total_elapsed_s),
        "step_count": step_count,
        "generated_turns": int(generated_turns),
        "steps_per_second": (step_count / total_elapsed_s) if total_elapsed_s > 0 else 0.0,
        "turns_per_second": (generated_turns / total_elapsed_s) if total_elapsed_s > 0 else 0.0,
        "phase_totals_s": phase_totals,
        "phase_avg_per_step_s": avg_phase_per_step,
        "step_total_s": {
            "min": min(per_step_totals) if per_step_totals else 0.0,
            "max": max(per_step_totals) if per_step_totals else 0.0,
            "mean": (sum(per_step_totals) / len(per_step_totals)) if per_step_totals else 0.0,
        },
        "slowest_phase": slowest_phase,
        "slowest_phase_s": phase_totals.get(slowest_phase, 0.0) if slowest_phase else 0.0,
    }


def _timing_metric_name(phase: str) -> str:
    return phase.removesuffix("_s")


def add_rollout_timing_metrics(
    metrics: dict[str, Any],
    *,
    timing: dict[str, float],
    timing_summary: dict[str, Any],
) -> None:
    for phase, elapsed_s in timing.items():
        metrics[_timing_metric_name(phase)] = float(elapsed_s)

    metrics.update(
        {
            "rollout_total": float(timing_summary.get("total_s", 0.0) or 0.0),
            "rollout_step_count": float(timing_summary.get("step_count", 0.0) or 0.0),
            "rollout_steps_per_second": float(timing_summary.get("steps_per_second", 0.0) or 0.0),
        }
    )


def aggregate_rollout_timing_metrics(
    extra_fields: Sequence[dict[str, Any]], *, prefix: str = "timing_s/agent_loop"
) -> dict[str, float]:
    """Summarize final-output episode timers, excluding nested browser-pool timers.

    Episodes run concurrently: these mean/max durations are not additive trainer
    wall time. Missing optional phases count as zero within a timed episode;
    outputs without a timing summary are excluded.
    """
    phases = (
        "env_start", "state_capture", "capture_screenshot", "build_generation_context",
        "llm_generate", "runtime_step", "evaluate_task", "reset_game", "env_close",
    )
    samples: dict[str, list[float]] = {name: [] for name in ("rollout_total", *phases)}
    for fields in extra_fields:
        summary = fields.get("rollout_timing") if isinstance(fields, dict) else None
        if not isinstance(summary, dict) or not isinstance(summary.get("phase_totals_s"), dict):
            continue
        total = safe_float(summary.get("total_s"), default=math.nan)
        if not math.isfinite(total) or total < 0:
            continue
        samples["rollout_total"].append(total)
        for phase in phases:
            elapsed = safe_float(summary["phase_totals_s"].get(f"{phase}_s", 0.0), default=math.nan)
            if math.isfinite(elapsed) and elapsed >= 0:
                samples[phase].append(elapsed)

    metrics: dict[str, float] = {}
    for name, values in samples.items():
        if values:
            metrics[f"{prefix}/{name}/mean"] = sum(values) / len(values)
            metrics[f"{prefix}/{name}/max"] = max(values)
    return metrics


def annotate_rollout_retry_output(
    output: Any,
    *,
    rollout_attempt_index: int,
    rollout_attempt_count: int,
    invalid_rollout_attempt_count: int,
) -> None:
    retry_info = {
        "rollout_attempt_index": float(rollout_attempt_index),
        "rollout_attempt_count": float(rollout_attempt_count),
        "invalid_rollout_attempt_count": float(invalid_rollout_attempt_count),
        "rollout_has_valid_loss": 1.0,
        "rollout_retry_exhausted": 0.0,
    }
    rollout_summary = output.extra_fields.setdefault("rollout_summary", {})
    if isinstance(rollout_summary, dict):
        rollout_summary.update(retry_info)
    reward_extra_info = output.extra_fields.get("reward_extra_info")
    if isinstance(reward_extra_info, dict):
        reward_extra_info.update(retry_info)


def _sanitize_action_metric_label(raw_label: Any) -> str:
    if not isinstance(raw_label, str) or not raw_label.strip():
        return "missing"
    label = re.sub(r"[^A-Za-z0-9]+", "_", raw_label.strip().lower()).strip("_")
    return label or "missing"


def _action_keys_label(raw_keys: Any) -> str | None:
    if isinstance(raw_keys, str):
        keys = [raw_keys.strip().lower()] if raw_keys.strip() else []
    elif isinstance(raw_keys, (list, tuple)):
        keys = [str(key).strip().lower() for key in raw_keys if str(key).strip()]
    else:
        keys = []
    return "+".join(keys) if keys else None


def _action_button_label(raw_button: Any) -> str | None:
    if raw_button is None:
        return None
    button = _sanitize_action_metric_label(str(raw_button))
    return button if button != "missing" else None


def action_label_from_value(value: Any) -> str:
    if isinstance(value, dict):
        tool_calls = value.get("tool_calls")
        action_space_mode = value.get("action_space_mode")
        if is_control_action_space_mode(action_space_mode) and isinstance(tool_calls, list):
            labels = [action_label_from_value(call) for call in tool_calls]
            labels = [label for label in labels if label != "missing"]
            return f"{action_space_mode}:{'|'.join(labels)}" if labels else f"{action_space_mode}:invalid"
        tool_name = _sanitize_action_metric_label(
            value.get("tool_name")
            or value.get("name")
            or value.get("action")
            or value.get("unified_action_tool")
            or value.get("id")
        )
        arguments = value.get("arguments") if isinstance(value.get("arguments"), dict) else {}
        if tool_name == "key_control":
            parts: list[str] = []
            for field_name, label in (("key_hold", "hold"), ("key_tap", "tap")):
                key_label = _action_keys_label(arguments.get(field_name, value.get(field_name)))
                if key_label:
                    parts.append(f"{label}-{key_label}")
            return f"key_control:{':'.join(parts)}" if parts else "key_control:empty"
        if tool_name == "mouse_control":
            parts: list[str] = []
            mouse = arguments.get("mouse_move", value.get("mouse"))
            if isinstance(mouse, dict):
                mode = _sanitize_action_metric_label(mouse.get("mode"))
                if mode != "missing":
                    parts.append(f"mouse-{mode}")
            for field_name, label in (("mouse_click", "click"), ("mouse_hold", "hold")):
                button = arguments.get(field_name)
                if isinstance(button, str):
                    button_label = _action_button_label(button)
                    if button_label:
                        parts.append(f"{label}-{button_label}")
            direction = arguments.get("mouse_scroll")
            if isinstance(direction, str):
                parts.append(f"scroll-{_sanitize_action_metric_label(direction)}")
            return f"mouse_control:{':'.join(parts)}" if parts else "mouse_control:empty"
        if tool_name == "control":
            parts: list[str] = []
            key_label = _action_keys_label(arguments.get("keys", value.get("keys")))
            if key_label:
                parts.append(f"keys-{key_label}")
            for field_name, label in (("key_hold", "hold"), ("key_tap", "tap")):
                key_label = _action_keys_label(arguments.get(field_name, value.get(field_name)))
                if key_label:
                    parts.append(f"{label}-{key_label}")
            mouse = arguments.get("mouse_move")
            if not isinstance(mouse, dict):
                mouse = value.get("mouse")
            if isinstance(mouse, dict):
                mode = _sanitize_action_metric_label(mouse.get("mode"))
                if mode != "missing":
                    parts.append(f"mouse-{mode}")
            mouse_click = arguments.get("mouse_click")
            if isinstance(mouse_click, str):
                button = _action_button_label(mouse_click)
                if button:
                    parts.append(f"click-{button}")
            mouse_hold = arguments.get("mouse_hold")
            if isinstance(mouse_hold, str):
                button = _action_button_label(mouse_hold)
                if button:
                    parts.append(f"hold-{button}")
            mouse_scroll = arguments.get("mouse_scroll")
            if isinstance(mouse_scroll, str):
                direction = _sanitize_action_metric_label(mouse_scroll)
                if direction != "missing":
                    parts.append(f"mouse-scroll-{direction}")
            return f"control:{':'.join(parts)}" if parts else "control:wait"
        return tool_name
    if isinstance(value, str):
        return _sanitize_action_metric_label(value)
    return "missing"


def _action_label_from_record(record: dict[str, Any]) -> str:
    return action_label_from_value(record.get("parsed_action"))


def _chosen_action_label_from_record(record: dict[str, Any]) -> str:
    label = action_label_from_value(record.get("chosen_action"))
    if label != "missing":
        return label
    return _action_label_from_record(record)


_GAME_ACTION_COMPONENTS = (
    "key",
    "mouse_move",
    "mouse_click",
    "mouse_hold",
    "mouse_scroll",
)


def compute_action_outcome_metrics(step_records: Sequence[dict[str, Any]]) -> dict[str, float]:
    """Aggregate a compact fixed set of v1 action-outcome diagnostics."""

    counts: Counter[str] = Counter()
    total_turns = len(step_records)
    for record in step_records:
        outcome = record.get("action_outcome") if isinstance(record, dict) else None
        if not is_valid_action_outcome_payload(outcome):
            continue

        admission = outcome.get("admission")
        provenance = outcome.get("provenance")
        admission_label = admission["status"]
        provenance_label = provenance["source"]

        counts["usable"] += 1
        counts[f"admission:{admission_label}"] += 1
        counts[f"provenance:{provenance_label}"] += 1

    denominator = float(total_turns)

    def fraction(key: str) -> float:
        return float(counts[key]) / denominator if total_turns else 0.0

    return {
        "action_outcome_coverage_fraction": fraction("usable"),
        "action_admission_parse_rejected_fraction": fraction("admission:parse_rejected"),
        "action_provenance_fallback_fraction": fraction("provenance:fallback"),
    }


def compute_action_collapse_metrics(step_records: list[dict[str, Any]]) -> dict[str, float]:
    labels = [_action_label_from_record(record) for record in step_records]
    total = len(labels)
    counts = Counter(labels)

    metrics = {
        "action_entropy": 0.0,
        "action_top_fraction": 0.0,
        "valid_action_rate": 0.0,
        "action_repeat_rate": 0.0,
        "multiple_control_block_count": 0.0,
        "action_call_count": 0.0,
        "dual_channel_frame_count": 0.0,
        "tokens_per_valid_action": 0.0,
        "input_context_length_mean": 0.0,
        "output_thinking_length_mean": 0.0,
        "output_action_length_mean": 0.0,
    }

    if total <= 0:
        return metrics

    for count in counts.values():
        probability = float(count) / float(total)
        if probability > 0.0:
            metrics["action_entropy"] -= probability * math.log(probability)

    metrics["action_top_fraction"] = float(max(counts.values())) / float(total)
    valid_records = [record for record in step_records if bool(record.get("has_valid_action"))]
    valid_count = len(valid_records)
    metrics["valid_action_rate"] = float(valid_count) / float(total)
    metrics["multiple_control_block_count"] = sum(
        safe_float(record.get("multiple_control_block_count")) for record in step_records
    )
    metrics["action_call_count"] = sum(safe_float(record.get("action_call_count")) for record in step_records)
    metrics["dual_channel_frame_count"] = sum(
        safe_float(record.get("dual_channel_frame_count")) for record in step_records
    )

    valid_labels = [_chosen_action_label_from_record(record) for record in valid_records]
    repeat_denominator = max(0, len(valid_labels) - 1)
    if repeat_denominator > 0:
        repeat_count = sum(1 for prev, current in itertools.pairwise(valid_labels) if prev == current)
        metrics["action_repeat_rate"] = float(repeat_count) / float(repeat_denominator)

    output_token_total = sum(safe_float(record.get("output_tokens")) for record in step_records)
    if valid_count > 0:
        metrics["tokens_per_valid_action"] = output_token_total / float(valid_count)
    metrics["input_context_length_mean"] = sum(
        safe_float(record.get("history_context_prompt_tokens")) for record in step_records
    ) / float(total)
    metrics["output_thinking_length_mean"] = sum(
        safe_float(record.get("thinking_tokens")) for record in step_records
    ) / float(total)
    metrics["output_action_length_mean"] = sum(
        safe_float(record.get("masked_action_tokens")) for record in step_records
    ) / float(total)
    return metrics


def build_rollout_summary_and_reward_extra_info(
    *,
    step_records: list[dict[str, Any]],
    reward_score: float,
    reward_components: dict[str, float],
    dense_turn_scores: list[float],
    format_retry_count: int,
    no_valid_action_count: int,
    timeout_phase: str | None,
) -> tuple[dict[str, float], dict[str, float]]:
    timeout_phase_code = rollout_timeout_phase_code(timeout_phase)
    rollout_summary = {
        "retained_step_count": float(len(step_records)),
        "format_retry_count": float(format_retry_count),
        "no_valid_action_generation_count": float(no_valid_action_count),
        "rollout_timeout": 1.0 if timeout_phase else 0.0,
        "rollout_timeout_phase_code": timeout_phase_code,
        **compute_action_collapse_metrics(step_records),
        **compute_action_outcome_metrics(step_records),
    }
    reward_extra_info = {
        "reward": reward_score,
        "score": reward_components["game_score"],
        "reward_score_gap": reward_components["game_score"] - reward_score,
        "training_score_missing_total": reward_components.get("training_score_missing_total", 0.0),
        "terminal_penalty_total": reward_components["terminal_penalty_total"],
        "think_length_penalty_total": reward_components["think_length_penalty_total"],
        "malformed_action_penalty_total": reward_components["malformed_action_penalty_total"],
        "avg_output_tokens": reward_components["output_token_total"] / len(dense_turn_scores)
        if dense_turn_scores
        else 0.0,
        **rollout_summary,
    }
    return rollout_summary, reward_extra_info

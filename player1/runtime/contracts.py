"""Shared action receipts and JSON-safe evidence for the episode controller."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Iterable, Mapping


ACTION_OUTCOME_VERSION = "game-gym.action_outcome.v1"
MODEL_RELATIVE_POINTER_NORMALIZED_LIMIT = 1000.0
MODEL_RELATIVE_POINTER_PROTOCOL = "normalized_viewport_delta_v1"

DEFAULT_STATE_FINGERPRINT_EXCLUDED_PATHS = (
    "timestampMs",
    "runId",
    "episodeId",
    "raw",
)
DEFAULT_ACTION_EFFECT_EXCLUDED_PATHS = (
    *DEFAULT_STATE_FINGERPRINT_EXCLUDED_PATHS,
    "gameTimeMs",
    "paused",
    "runtime_paused",
    "status",
)

ACTION_ADMISSION_STATUSES = frozenset({"accepted", "parse_rejected"})
ACTION_EXECUTION_STATUSES = frozenset({"executed", "runtime_rejected", "not_attempted"})
ACTION_PROVENANCE_SOURCES = frozenset({"model", "fallback"})
ACTION_EFFECT_STATUSES = frozenset({"confirmed", "valid_no_effect", "unverifiable"})
ACTION_OUTCOME_PRIMARY_LABELS = ACTION_EFFECT_STATUSES | frozenset(
    {"parse_rejected", "runtime_rejected", "fallback_used"}
)


class RuntimeContractError(ValueError):
    """Raised when a runtime contract payload violates its declared schema."""


def _require_nonempty_string(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeContractError(f"{field_name} must be a non-empty string")
    return value.strip()


def _require_optional_string(value: Any, *, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_nonempty_string(value, field_name=field_name)


def _require_bool(value: Any, *, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise RuntimeContractError(f"{field_name} must be a boolean")
    return value


def _require_mapping_frozen(value: Any, *, field_name: str) -> Mapping[str, Any]:
    frozen = _freeze_json(value)
    if not isinstance(frozen, Mapping):
        raise RuntimeContractError(f"{field_name} must be a mapping")
    return frozen


def _require_status(value: str, *, field_name: str, allowed: frozenset[str]) -> str:
    normalized = _require_nonempty_string(value, field_name=field_name)
    if normalized not in allowed:
        expected = ", ".join(sorted(allowed))
        raise RuntimeContractError(f"{field_name}={value!r} is invalid; expected one of: {expected}")
    return normalized


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    numeric = float(value)
    return numeric if math.isfinite(numeric) else None


def copy_json_value(value: Any, *, path: str = "$") -> Any:
    """Return a strict JSON-compatible deep copy or fail closed."""

    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise RuntimeContractError(f"{path} contains a non-finite float")
        return value
    if isinstance(value, Mapping):
        copied: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise RuntimeContractError(f"{path} contains a non-string mapping key: {key!r}")
            copied[key] = copy_json_value(item, path=f"{path}.{key}")
        return copied
    if isinstance(value, (list, tuple)):
        return [copy_json_value(item, path=f"{path}[{index}]") for index, item in enumerate(value)]
    raise RuntimeContractError(f"{path} contains a non-JSON value of type {type(value).__name__}")


def _freeze_json(value: Any, *, path: str = "$") -> Any:
    """Return a recursively immutable, strict JSON-compatible representation."""

    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise RuntimeContractError(f"{path} contains a non-finite float")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise RuntimeContractError(f"{path} contains a non-string mapping key: {key!r}")
            frozen[key] = _freeze_json(item, path=f"{path}.{key}")
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item, path=f"{path}[{index}]") for index, item in enumerate(value))
    raise RuntimeContractError(f"{path} contains a non-JSON value of type {type(value).__name__}")


def _canonical_json_from_copied_value(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _drop_path(value: Any, path: str) -> None:
    parts = [part for part in str(path or "").split(".") if part]
    if not parts:
        return
    current = value
    for part in parts[:-1]:
        if not isinstance(current, dict):
            return
        current = current.get(part)
    if isinstance(current, dict):
        current.pop(parts[-1], None)


def _project_state(
    state: Mapping[str, Any],
    *,
    excluded_paths: Iterable[str] = DEFAULT_STATE_FINGERPRINT_EXCLUDED_PATHS,
) -> dict[str, Any]:
    """Build the stable state projection used by fingerprints and semantic diffs."""

    projected = copy_json_value(state)
    if not isinstance(projected, dict):
        raise RuntimeContractError("state must be a mapping")
    for path in excluded_paths:
        _drop_path(projected, path)
    return projected


@dataclass(frozen=True, slots=True)
class ActionAdmission:
    """Whether the model output entered the environment action space."""

    status: str
    reason: str | None
    model_action: Any = None

    def __post_init__(self) -> None:
        status = _require_status(
            self.status,
            field_name="action admission status",
            allowed=ACTION_ADMISSION_STATUSES,
        )
        reason = _require_optional_string(self.reason, field_name="action admission reason")
        model_action = _freeze_json(self.model_action)
        if status == "accepted" and reason is not None:
            raise RuntimeContractError("accepted action admission cannot carry a rejection reason")
        if status == "parse_rejected" and reason is None:
            raise RuntimeContractError("parse-rejected action admission requires a reason")
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "model_action", model_action)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "model_action": copy_json_value(self.model_action),
        }


@dataclass(frozen=True, slots=True)
class ActionExecution:
    """Runtime acceptance and receipt for the action actually requested."""

    status: str
    reason: str | None
    requested_action: Any
    executed_action: Any = None
    runtime_reward: float | None = None
    environment_done: bool | None = None

    def __post_init__(self) -> None:
        status = _require_status(
            self.status,
            field_name="action execution status",
            allowed=ACTION_EXECUTION_STATUSES,
        )
        reason = _require_optional_string(self.reason, field_name="action execution reason")
        requested_action = _freeze_json(self.requested_action)
        executed_action = _freeze_json(self.executed_action)
        if self.runtime_reward is None:
            runtime_reward = None
        else:
            runtime_reward = _finite_number(self.runtime_reward)
            if runtime_reward is None:
                raise RuntimeContractError("action execution runtime_reward must be finite when present")
        environment_done = (
            _require_bool(self.environment_done, field_name="action execution environment_done")
            if self.environment_done is not None
            else None
        )
        if status == "executed" and reason is not None:
            raise RuntimeContractError("executed action cannot carry a rejection reason")
        if status == "executed" and requested_action is None:
            raise RuntimeContractError("executed action requires a requested_action")
        if status != "executed" and reason is None:
            raise RuntimeContractError("non-executed action requires a reason")
        if status != "executed" and executed_action is not None:
            raise RuntimeContractError("non-executed action cannot carry an executed_action receipt")
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "requested_action", requested_action)
        object.__setattr__(self, "executed_action", executed_action)
        object.__setattr__(self, "runtime_reward", runtime_reward)
        object.__setattr__(self, "environment_done", environment_done)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "requested_action": copy_json_value(self.requested_action),
            "executed_action": copy_json_value(self.executed_action),
            "runtime_reward": self.runtime_reward,
            "environment_done": self.environment_done,
        }


@dataclass(frozen=True, slots=True)
class ActionProvenance:
    """Whether the runtime request came from the model or a fallback policy."""

    source: str
    fallback_reason: str | None = None

    def __post_init__(self) -> None:
        source = _require_status(
            self.source,
            field_name="action provenance source",
            allowed=ACTION_PROVENANCE_SOURCES,
        )
        fallback_reason = _require_optional_string(
            self.fallback_reason,
            field_name="action provenance fallback_reason",
        )
        if source == "model" and fallback_reason is not None:
            raise RuntimeContractError("model action provenance cannot carry fallback_reason")
        if source == "fallback" and fallback_reason is None:
            raise RuntimeContractError("fallback action provenance requires fallback_reason")
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "fallback_reason", fallback_reason)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "fallback_reason": self.fallback_reason,
        }


@dataclass(frozen=True, slots=True)
class ActionEffectEvidence:
    """Observable transition evidence after a runtime action.

    A semantic state delta confirms an observable transition, but autonomous
    game simulation may also contribute.
    """

    status: str
    evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        status = _require_status(
            self.status,
            field_name="action effect status",
            allowed=ACTION_EFFECT_STATUSES,
        )
        if isinstance(self.evidence, (str, bytes)) or not isinstance(self.evidence, (tuple, list)):
            raise RuntimeContractError("action effect evidence must be a sequence of strings")
        evidence = tuple(
            _require_nonempty_string(value, field_name="action effect evidence item") for value in self.evidence
        )
        if len(set(evidence)) != len(evidence):
            raise RuntimeContractError("action effect evidence entries must be unique")
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "evidence", evidence)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "evidence": list(self.evidence),
        }


def _primary_action_label(
    *,
    admission_status: str,
    execution_status: str,
    provenance_source: str,
    effect_status: str,
) -> str:
    if execution_status == "runtime_rejected":
        return "runtime_rejected"
    if provenance_source == "fallback":
        return "fallback_used"
    if admission_status == "parse_rejected":
        return "parse_rejected"
    return effect_status


def _action_axis_consistency_error(
    *,
    admission_status: str,
    execution_status: str,
    provenance_source: str,
    effect_status: str,
) -> str | None:
    if execution_status != "executed" and effect_status != "unverifiable":
        return "a non-executed action can only have an unverifiable effect"
    if admission_status == "parse_rejected" and provenance_source == "model" and execution_status != "not_attempted":
        return "a parse-rejected model action cannot reach runtime execution without fallback provenance"
    return None


@dataclass(frozen=True, slots=True)
class ActionOutcome:
    """Complete multi-axis action result with a derived reporting label."""

    admission: ActionAdmission
    execution: ActionExecution
    provenance: ActionProvenance
    effect: ActionEffectEvidence

    def __post_init__(self) -> None:
        if not isinstance(self.admission, ActionAdmission):
            raise RuntimeContractError("action outcome admission must be ActionAdmission")
        if not isinstance(self.execution, ActionExecution):
            raise RuntimeContractError("action outcome execution must be ActionExecution")
        if not isinstance(self.provenance, ActionProvenance):
            raise RuntimeContractError("action outcome provenance must be ActionProvenance")
        if not isinstance(self.effect, ActionEffectEvidence):
            raise RuntimeContractError("action outcome effect must be ActionEffectEvidence")
        consistency_error = _action_axis_consistency_error(
            admission_status=self.admission.status,
            execution_status=self.execution.status,
            provenance_source=self.provenance.source,
            effect_status=self.effect.status,
        )
        if consistency_error is not None:
            raise RuntimeContractError(f"inconsistent action outcome axes: {consistency_error}")
        if self.effect.status in {"confirmed", "valid_no_effect"} and self.execution.executed_action is None:
            raise RuntimeContractError(f"{self.effect.status} action effect requires a runtime executed_action receipt")

    @property
    def primary_label(self) -> str:
        return _primary_action_label(
            admission_status=self.admission.status,
            execution_status=self.execution.status,
            provenance_source=self.provenance.source,
            effect_status=self.effect.status,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": ACTION_OUTCOME_VERSION,
            "admission": self.admission.to_dict(),
            "execution": self.execution.to_dict(),
            "provenance": self.provenance.to_dict(),
            "effect": self.effect.to_dict(),
            "primary_label": self.primary_label,
        }


def is_valid_action_outcome_payload(value: Any) -> bool:
    """Return whether a serialized value satisfies the v1 fixed-label envelope."""

    if not isinstance(value, Mapping) or value.get("schema_version") != ACTION_OUTCOME_VERSION:
        return False
    admission = value.get("admission")
    execution = value.get("execution")
    provenance = value.get("provenance")
    effect = value.get("effect")
    if not all(isinstance(axis, Mapping) for axis in (admission, execution, provenance, effect)):
        return False

    primary_label = value.get("primary_label")
    admission_status = admission.get("status")
    execution_status = execution.get("status")
    provenance_source = provenance.get("source")
    effect_status = effect.get("status")
    if (
        primary_label not in ACTION_OUTCOME_PRIMARY_LABELS
        or admission_status not in ACTION_ADMISSION_STATUSES
        or execution_status not in ACTION_EXECUTION_STATUSES
        or provenance_source not in ACTION_PROVENANCE_SOURCES
        or effect_status not in ACTION_EFFECT_STATUSES
    ):
        return False
    if (
        _action_axis_consistency_error(
            admission_status=admission_status,
            execution_status=execution_status,
            provenance_source=provenance_source,
            effect_status=effect_status,
        )
        is not None
    ):
        return False
    return primary_label == _primary_action_label(
        admission_status=admission_status,
        execution_status=execution_status,
        provenance_source=provenance_source,
        effect_status=effect_status,
    )


def _runtime_error_reason(error: BaseException | str | None) -> str | None:
    if error is None:
        return None
    if isinstance(error, BaseException):
        message = str(error).strip()
        return f"{type(error).__name__}: {message}" if message else type(error).__name__
    message = str(error).strip()
    return message or "runtime_error"


def _runtime_receipt(step_result: Mapping[str, Any] | None) -> Any:
    if not isinstance(step_result, Mapping):
        return None
    info = step_result.get("info")
    if not isinstance(info, Mapping):
        return None
    action = info.get("action")
    if not isinstance(action, Mapping):
        return None
    if not isinstance(action.get("type"), str) or not action["type"].strip():
        return None
    if not isinstance(action.get("id"), str) or not action["id"].strip():
        return None
    if "args" in action and not isinstance(action["args"], Mapping):
        return None
    return action


def classify_action_outcome(
    *,
    parse_valid: bool,
    parse_reason: str | None,
    fallback_used: bool,
    fallback_reason: str | None,
    model_action: Any,
    requested_action: Any,
    runtime_step_result: Mapping[str, Any] | None,
    runtime_error: BaseException | str | None,
    before_state: Mapping[str, Any] | None,
    after_state: Mapping[str, Any] | None,
    excluded_state_paths: Iterable[str] = DEFAULT_ACTION_EFFECT_EXCLUDED_PATHS,
) -> ActionOutcome:
    """Classify one action without changing reward or swallowing runtime errors."""

    admission = ActionAdmission(
        status="accepted" if parse_valid else "parse_rejected",
        reason=None if parse_valid else (parse_reason or "parse_rejected"),
        model_action=model_action,
    )
    provenance = ActionProvenance(
        source="fallback" if fallback_used else "model",
        fallback_reason=(fallback_reason or "fallback_used") if fallback_used else None,
    )

    error_reason = _runtime_error_reason(runtime_error)
    step_result = runtime_step_result if isinstance(runtime_step_result, Mapping) else None
    step_state = step_result.get("state") if step_result is not None else None
    receipt = _runtime_receipt(step_result)
    if error_reason is not None:
        execution_status = "runtime_rejected"
        execution_reason = error_reason
    elif requested_action is None:
        execution_status = "not_attempted"
        execution_reason = parse_reason or "no_runtime_action"
    elif not isinstance(step_state, Mapping):
        execution_status = "runtime_rejected"
        execution_reason = "missing_runtime_step_result"
    elif receipt is None:
        execution_status = "runtime_rejected"
        execution_reason = "missing_runtime_action_receipt"
    else:
        execution_status = "executed"
        execution_reason = None

    runtime_reward = _finite_number(step_result.get("reward")) if step_result is not None else None
    done = step_result.get("done") if step_result is not None else None
    environment_done = done if isinstance(done, bool) else None

    execution = ActionExecution(
        status=execution_status,
        reason=execution_reason,
        requested_action=requested_action,
        executed_action=receipt if execution_status == "executed" else None,
        runtime_reward=runtime_reward,
        environment_done=environment_done,
    )

    before_payload: bytes | None = None
    after_payload: bytes | None = None
    evidence: list[str] = []
    excluded_paths = tuple(excluded_state_paths)
    before_projection = (
        _project_state(before_state, excluded_paths=excluded_paths) if isinstance(before_state, Mapping) else None
    )
    after_projection = (
        _project_state(after_state, excluded_paths=excluded_paths) if isinstance(after_state, Mapping) else None
    )
    if before_projection is not None:
        before_payload = _canonical_json_from_copied_value(before_projection).encode("utf-8")
    if after_projection is not None:
        after_payload = _canonical_json_from_copied_value(after_projection).encode("utf-8")

    if execution_status != "executed":
        effect_status = "unverifiable"
        evidence.append("runtime_execution_unconfirmed")
    elif before_projection is None or after_projection is None:
        effect_status = "unverifiable"
        evidence.append("state_evidence_missing")
    else:
        state_changed = before_payload != after_payload
        if state_changed:
            effect_status = "confirmed"
            evidence.extend(("runtime_receipt", "state_changed"))
        else:
            effect_status = "valid_no_effect"
            evidence.extend(("runtime_receipt", "state_unchanged"))

    effect = ActionEffectEvidence(
        status=effect_status,
        evidence=tuple(evidence),
    )

    return ActionOutcome(
        admission=admission,
        execution=execution,
        provenance=provenance,
        effect=effect,
    )


__all__ = [
    "ACTION_ADMISSION_STATUSES",
    "ACTION_EFFECT_STATUSES",
    "ACTION_EXECUTION_STATUSES",
    "ACTION_OUTCOME_VERSION",
    "ACTION_OUTCOME_PRIMARY_LABELS",
    "ACTION_PROVENANCE_SOURCES",
    "DEFAULT_ACTION_EFFECT_EXCLUDED_PATHS",
    "DEFAULT_STATE_FINGERPRINT_EXCLUDED_PATHS",
    "MODEL_RELATIVE_POINTER_NORMALIZED_LIMIT",
    "MODEL_RELATIVE_POINTER_PROTOCOL",
    "ActionAdmission",
    "ActionEffectEvidence",
    "ActionExecution",
    "ActionOutcome",
    "ActionProvenance",
    "RuntimeContractError",
    "classify_action_outcome",
    "copy_json_value",
    "is_valid_action_outcome_payload",
]

"""Shared validation and scheduling helpers for environment mixtures."""

from __future__ import annotations

import math
import re
from typing import Any, Mapping, Sequence


_IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def _require_mapping(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be a JSON object")
    return value


def _reject_unknown_keys(value: Mapping[str, Any], *, allowed: set[str], field: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"{field} contains unsupported fields: {', '.join(unknown)}")


def _require_identifier(value: Any, *, field: str) -> str:
    identifier = str(value or "").strip()
    if not _IDENTIFIER_PATTERN.fullmatch(identifier):
        raise ValueError(
            f"{field} must start with a lowercase letter or digit and contain only lowercase letters, "
            f"digits, '_' or '-'; got {identifier!r}"
        )
    return identifier


def _require_positive_weight(value: Any, *, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a positive finite number")
    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be a positive finite number") from None
    if not math.isfinite(numeric_value) or numeric_value <= 0:
        raise ValueError(f"{field} must be a positive finite number")
    return numeric_value


def _smooth_fixed_count_order(counts: Sequence[int]) -> tuple[int, ...]:
    """Interleave fixed counts without changing their exact allocation."""

    total = sum(counts)
    if total == 0:
        return ()
    scores = [0] * len(counts)
    remaining = list(counts)
    order: list[int] = []
    for _ in range(total):
        for index, count in enumerate(counts):
            scores[index] += count
        selected = max(
            (index for index, count in enumerate(remaining) if count > 0),
            key=lambda index: (scores[index], -index),
        )
        order.append(selected)
        remaining[selected] -= 1
        scores[selected] -= total
    return tuple(order)


def allocate_weighted_counts(total: int, weights: Sequence[float]) -> tuple[int, ...]:
    """Allocate an exact integer total using deterministic largest remainders."""

    if total < 0:
        raise ValueError(f"total must be non-negative, got {total}")
    if not weights:
        raise ValueError("weights must be non-empty")
    numeric_weights = tuple(
        _require_positive_weight(weight, field=f"weights[{index}]") for index, weight in enumerate(weights)
    )
    weight_sum = sum(numeric_weights)
    quotas = [total * weight / weight_sum for weight in numeric_weights]
    counts = [math.floor(quota) for quota in quotas]
    remainder = total - sum(counts)
    order = sorted(range(len(weights)), key=lambda index: (-(quotas[index] - counts[index]), index))
    for index in order[:remainder]:
        counts[index] += 1
    return tuple(counts)

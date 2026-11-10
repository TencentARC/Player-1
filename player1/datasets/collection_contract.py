"""Portable provenance and session splits for a dataset."""

from __future__ import annotations

import json
import random
from collections.abc import Mapping
from typing import Any

COLLECTION_SCHEMA = "player1.dataset"
IDENTITY_FIELDS = ("adapter_id", "dataset_id", "source_revision", "session_id", "trajectory_id")


def identity_key(identity: Mapping[str, Any]) -> tuple[str, ...]:
    if set(identity) != set(IDENTITY_FIELDS) or any(
        not isinstance(identity[k], str) or not identity[k].strip() for k in IDENTITY_FIELDS
    ):
        raise ValueError("collection source trajectory identity is invalid")
    return tuple(identity[k] for k in IDENTITY_FIELDS)


def session_split(identity: Mapping[str, Any], seed: str, basis_points: int) -> str:
    """Stable under collection growth and input reordering; no content hashing."""
    if not isinstance(seed, str) or not seed or type(basis_points) is not int or not 0 <= basis_points <= 10_000:
        raise ValueError("collection split settings are invalid")
    key = json.dumps([seed, *identity_key(identity)[:4]], ensure_ascii=True, separators=(",", ":"))
    return "validation" if random.Random(key).randrange(10_000) < basis_points else "train"

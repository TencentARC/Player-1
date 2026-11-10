"""Validation and loading contracts for the compiled MineDojo task port.

The compiled artifact is intentionally a plain JSON mapping.  Keeping the
runtime contract JSON-native makes it usable by the existing MineStudio
runner, subprocess launchers, and external analysis scripts without importing
MineDojo or OmegaConf.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
EXPECTED_TASK_COUNT = 1_581
EXPECTED_CATEGORY_COUNTS = {
    "harvest": 895,
    "combat": 471,
    "techtree": 213,
    "survival": 2,
}
TARGET_KINDS = {"inventory_delta", "stat_delta", "stat_value"}


def _required_text(mapping: Mapping[str, Any], field: str, *, context: str) -> str:
    value = mapping.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{context} requires non-empty {field}")
    return value


def _validate_target(task_id: str, target: Any) -> None:
    if not isinstance(target, Mapping):
        raise ValueError(f"MineDojo ported task {task_id!r} target must be a mapping")
    kind = _required_text(target, "kind", context=f"MineDojo ported task {task_id!r} target")
    if kind not in TARGET_KINDS:
        raise ValueError(f"MineDojo ported task {task_id!r} has unsupported target kind {kind!r}")
    threshold = target.get("gte")
    if not isinstance(threshold, (int, float)) or threshold <= 0:
        raise ValueError(f"MineDojo ported task {task_id!r} target.gte must be positive")
    objects = target.get("objects")
    if not isinstance(objects, list) or not objects or not all(isinstance(item, str) and item for item in objects):
        raise ValueError(f"MineDojo ported task {task_id!r} target.objects must be a non-empty string list")
    if len(set(objects)) != len(objects):
        raise ValueError(f"MineDojo ported task {task_id!r} target.objects contains duplicates")
    if kind in {"stat_delta", "stat_value"}:
        _required_text(target, "stat", context=f"MineDojo ported task {task_id!r} target")


def _validate_task(raw: Any, *, index: int) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ValueError(f"MineDojo ported task {index} must be a mapping")
    task = dict(raw)
    task_id = _required_text(task, "task_id", context=f"MineDojo ported task {index}")
    category = _required_text(task, "category", context=f"MineDojo ported task {task_id!r}")
    if category not in EXPECTED_CATEGORY_COUNTS:
        raise ValueError(f"MineDojo ported task {task_id!r} has invalid category {category!r}")
    _required_text(task, "prompt", context=f"MineDojo ported task {task_id!r}")
    if task.get("guidance") is not None and not isinstance(task.get("guidance"), str):
        raise ValueError(f"MineDojo ported task {task_id!r} guidance must be a string or null")
    source_spec = task.get("source_spec")
    if not isinstance(source_spec, Mapping) or source_spec.get("__cls__") != category:
        raise ValueError(f"MineDojo ported task {task_id!r} has an invalid source_spec")
    provenance = task.get("provenance")
    if not isinstance(provenance, Mapping):
        raise ValueError(f"MineDojo ported task {task_id!r} provenance must be a mapping")
    _required_text(provenance, "template_id", context=f"MineDojo ported task {task_id!r} provenance")
    initialization = task.get("initialization")
    if not isinstance(initialization, Mapping):
        raise ValueError(f"MineDojo ported task {task_id!r} initialization must be a mapping")
    inventory = initialization.get("inventory")
    mobs = initialization.get("mobs")
    world = initialization.get("world")
    if not isinstance(inventory, list) or not isinstance(mobs, list) or not isinstance(world, Mapping):
        raise ValueError(f"MineDojo ported task {task_id!r} has malformed initialization")
    _validate_target(task_id, task.get("target"))
    return task


def validate_compiled_manifest(raw: Any) -> dict[str, Any]:
    """Validate a compiled artifact and return a shallow JSON-native copy."""

    if not isinstance(raw, Mapping):
        raise ValueError("MineDojo compiled manifest must be a mapping")
    manifest = dict(raw)
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"Unsupported MineDojo compiled manifest schema: {manifest.get('schema_version')!r}")
    _required_text(manifest, "suite_id", context="MineDojo compiled manifest")
    source = manifest.get("source")
    target_runtime = manifest.get("target_runtime")
    if not isinstance(source, Mapping) or not isinstance(target_runtime, Mapping):
        raise ValueError("MineDojo compiled manifest requires source and target_runtime mappings")
    _required_text(source, "repository", context="MineDojo compiled manifest source")
    _required_text(target_runtime, "minecraft_version", context="MineDojo compiled manifest target_runtime")

    raw_tasks = manifest.get("tasks")
    if not isinstance(raw_tasks, list):
        raise ValueError("MineDojo compiled manifest tasks must be a list")
    tasks = [_validate_task(task, index=index) for index, task in enumerate(raw_tasks)]
    if len(tasks) != EXPECTED_TASK_COUNT:
        raise ValueError(f"MineDojo compiled manifest expected {EXPECTED_TASK_COUNT} tasks, got {len(tasks)}")
    task_ids = [task["task_id"] for task in tasks]
    if len(set(task_ids)) != len(task_ids):
        raise ValueError("MineDojo compiled manifest task IDs must be unique")
    category_counts = Counter(task["category"] for task in tasks)
    if dict(category_counts) != EXPECTED_CATEGORY_COUNTS:
        raise ValueError(
            "MineDojo compiled manifest category counts differ from the pinned source: "
            f"{dict(category_counts)!r}"
        )
    declared_counts = manifest.get("counts")
    expected_counts = {"tasks": EXPECTED_TASK_COUNT, "categories": EXPECTED_CATEGORY_COUNTS}
    if declared_counts != expected_counts:
        raise ValueError(f"MineDojo compiled manifest counts must equal {expected_counts!r}")
    manifest["tasks"] = tasks
    return manifest


def load_manifest_file(path: str | Path) -> dict[str, Any]:
    """Read and validate a compiled MineDojo manifest from disk."""

    manifest_path = Path(path)
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    return validate_compiled_manifest(data)


__all__ = [
    "EXPECTED_CATEGORY_COUNTS",
    "EXPECTED_TASK_COUNT",
    "SCHEMA_VERSION",
    "load_manifest_file",
    "validate_compiled_manifest",
]

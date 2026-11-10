"""Named, versioned task selections over the MineDojo-ported catalog."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .manifest import DEFAULT_COMPILED_MANIFEST_PATH, load_compiled_manifest

SUITE_SCHEMA_VERSION = 1
MINEDOJO_FULL_SUITE_ID = "minedojo-full"
MINEDOJO_300_SUITE_ID = "minedojo-300"
MINEDOJO_300_SUITE_PATH = Path(__file__).resolve().parent / "data" / "minedojo_300.json"
MINEDOJO_PORTED_SUITE_IDS = (
    MINEDOJO_FULL_SUITE_ID,
    MINEDOJO_300_SUITE_ID,
)
_DIFFICULTY_SCORE_BANDS = {"easy": (0, 2), "medium": (3, 5), "hard": (6, 10)}


@dataclass(frozen=True)
class _SuiteContract:
    path: Path
    task_count: int
    category_counts: dict[str, int]
    difficulty_counts: dict[str, int]
    default_trials_per_task: int


_SUITE_CONTRACTS = {
    MINEDOJO_300_SUITE_ID: _SuiteContract(
        path=MINEDOJO_300_SUITE_PATH,
        task_count=300,
        category_counts={"combat": 200, "harvest": 100},
        difficulty_counts={"easy": 175, "medium": 25, "unclassified": 100},
        default_trials_per_task=8,
    ),
}


def _required_text(mapping: Mapping[str, Any], key: str, *, context: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} requires non-empty {key}")
    return value.strip()


@dataclass(frozen=True)
class MineDojoTaskSelection:
    task_id: str
    category: str
    difficulty: str
    difficulty_score: int | None
    stratum: str
    representative_features: dict[str, Any]
    selection_reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "category": self.category,
            "difficulty": self.difficulty,
            "difficulty_score": self.difficulty_score,
            "stratum": self.stratum,
            "representative_features": self.representative_features,
            "selection_reason": self.selection_reason,
        }


@dataclass(frozen=True)
class MineDojoPortedSuite:
    suite_id: str
    selection_version: int
    description: str
    source_suite_id: str
    path: Path
    default_trials_per_task: int
    tasks: tuple[MineDojoTaskSelection, ...]
    metadata: dict[str, Any]
    default_max_decisions: int | None = None

    @property
    def task_ids(self) -> tuple[str, ...]:
        return tuple(task.task_id for task in self.tasks)

    def identity(self) -> dict[str, Any]:
        categories = tuple(sorted({task.category for task in self.tasks}))
        return {
            "suite_id": self.suite_id,
            "selection_version": self.selection_version,
            "path": str(self.path),
            "source_suite_id": self.source_suite_id,
            "task_count": len(self.tasks),
            "category_counts": dict(Counter(task.category for task in self.tasks)),
            "difficulty_counts": dict(Counter(task.difficulty for task in self.tasks)),
            "category_difficulty_counts": {
                category: dict(Counter(task.difficulty for task in self.tasks if task.category == category))
                for category in categories
            },
            "default_trials_per_task": self.default_trials_per_task,
            "default_max_decisions": self.default_max_decisions,
            "seed_protocol": self.metadata["seed_protocol"],
            "sima2_exact": False,
        }


def _parse_task(raw: Any, *, suite_id: str, index: int, allow_unclassified: bool = False) -> MineDojoTaskSelection:
    if not isinstance(raw, Mapping):
        raise ValueError(f"{suite_id} task {index} must be a mapping")
    context = f"{suite_id} task {index}"
    features = raw.get("representative_features")
    if features is not None and not isinstance(features, Mapping):
        raise ValueError(f"{context} representative_features must be a mapping")
    score = raw.get("difficulty_score")
    difficulty = _required_text(raw, "difficulty", context=context)
    if difficulty == "unclassified" and allow_unclassified:
        if score is not None:
            raise ValueError(f"{context} unclassified difficulty_score must be null")
    else:
        if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 10:
            raise ValueError(f"{context} difficulty_score must be an integer in [0, 10]")
        try:
            lower, upper = _DIFFICULTY_SCORE_BANDS[difficulty]
        except KeyError as exc:
            raise ValueError(f"{context} has unsupported difficulty {difficulty!r}") from exc
        if not lower <= score <= upper:
            raise ValueError(f"{context} score {score} is outside the {difficulty} band [{lower}, {upper}]")
    return MineDojoTaskSelection(
        task_id=_required_text(raw, "task_id", context=context),
        category=_required_text(raw, "category", context=context),
        difficulty=difficulty,
        difficulty_score=score,
        stratum=str(raw.get("stratum") or "easy_focused_v1"),
        representative_features=dict(features or {}),
        selection_reason=str(raw.get("reason") or "Selected by the frozen easy-focused scoring protocol."),
    )


def load_minedojo_ported_suite(
    suite_id: str,
    *,
    suite_path: str | Path | None = None,
    manifest_path: str | Path = DEFAULT_COMPILED_MANIFEST_PATH,
) -> MineDojoPortedSuite:
    """Load and cross-check one fixed task selection against its source catalog."""

    if suite_id == MINEDOJO_FULL_SUITE_ID:
        if suite_path is not None:
            raise ValueError(f"{suite_id} is derived from manifest_path, not suite_path")
        path = Path(manifest_path).expanduser().resolve()
        manifest = load_compiled_manifest(path)
        return MineDojoPortedSuite(
            suite_id=suite_id, selection_version=1,
            description="All programmatic tasks in the compiled MineDojo catalog.",
            source_suite_id=manifest["suite_id"], path=path,
            default_trials_per_task=3,
            default_max_decisions=1_000,
            tasks=tuple(
                MineDojoTaskSelection(
                    task_id=task["task_id"], category=task["category"],
                    difficulty="unclassified", difficulty_score=None,
                    stratum="full_catalog", representative_features={},
                    selection_reason="Included from the complete compiled catalog.",
                )
                for task in manifest["tasks"]
            ),
            metadata={"seed_protocol": {"configurable_trials_per_task": True,
                                       "parameter": "trials_per_task"}},
        )
    contract = _SUITE_CONTRACTS.get(suite_id)
    if contract is None:
        raise ValueError(f"Unknown MineDojo-ported suite: {suite_id!r}")
    path = Path(suite_path or contract.path).expanduser().resolve()
    source_path = Path(manifest_path).expanduser().resolve()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"MineDojo-ported suite is unreadable: {path}") from exc
    if not isinstance(raw, Mapping):
        raise ValueError("MineDojo-ported suite must be a mapping")
    if raw.get("schema_version") != SUITE_SCHEMA_VERSION:
        raise ValueError(f"Unsupported MineDojo-ported suite schema: {raw.get('schema_version')!r}")
    if _required_text(raw, "suite_id", context="MineDojo-ported suite") != suite_id:
        raise ValueError("MineDojo-ported suite ID does not match the requested suite")
    selection_version = raw.get("selection_version")
    if isinstance(selection_version, bool) or not isinstance(selection_version, int) or selection_version <= 0:
        raise ValueError("MineDojo-ported selection_version must be a positive integer")
    source = raw.get("source")
    if not isinstance(source, Mapping):
        raise ValueError("MineDojo-ported suite requires source metadata")
    source_suite_id = _required_text(source, "suite_id", context="MineDojo-ported suite source")
    manifest = load_compiled_manifest(source_path)
    if manifest.get("suite_id") != source_suite_id:
        raise ValueError("MineDojo-ported suite source suite_id does not match the compiled manifest")

    raw_tasks = raw.get("tasks")
    if not isinstance(raw_tasks, list):
        raise ValueError("MineDojo-ported suite tasks must be a list")
    tasks = tuple(_parse_task(task, suite_id=suite_id, index=index,
                             allow_unclassified="unclassified" in contract.difficulty_counts)
                  for index, task in enumerate(raw_tasks))
    if len(tasks) != contract.task_count or len({task.task_id for task in tasks}) != len(tasks):
        raise ValueError(f"{suite_id} must contain exactly {contract.task_count} unique task IDs")
    by_id = {str(task["task_id"]): task for task in manifest["tasks"]}
    missing = sorted({task.task_id for task in tasks} - set(by_id))
    if missing:
        raise ValueError(f"{suite_id} contains unknown task IDs: {', '.join(missing)}")
    for task in tasks:
        if by_id[task.task_id]["category"] != task.category:
            raise ValueError(f"{suite_id} category disagrees with the source task: {task.task_id}")
        if task.difficulty not in contract.difficulty_counts:
            raise ValueError(f"{suite_id} has unsupported difficulty {task.difficulty!r}")
    category_counts = dict(Counter(task.category for task in tasks))
    difficulty_counts = dict(Counter(task.difficulty for task in tasks))
    matrix = {
        category: dict(Counter(task.difficulty for task in tasks if task.category == category))
        for category in contract.category_counts
    }
    if category_counts != contract.category_counts:
        raise ValueError(f"{suite_id} category counts must equal {contract.category_counts!r}")
    if difficulty_counts != contract.difficulty_counts:
        raise ValueError(f"{suite_id} difficulty counts must equal {contract.difficulty_counts!r}")

    declared_counts = raw.get("counts")
    expected_counts = {
        "tasks": contract.task_count,
        "categories": contract.category_counts,
        "difficulties": contract.difficulty_counts,
        "category_difficulty": matrix,
    }
    if declared_counts != expected_counts:
        raise ValueError(f"{suite_id} declared counts must equal {expected_counts!r}")
    default_trials = raw.get("default_trials_per_task")
    if default_trials != contract.default_trials_per_task:
        raise ValueError(
            f"{suite_id} default_trials_per_task must be exactly {contract.default_trials_per_task}"
        )
    seed_protocol = raw.get("seed_protocol")
    if not isinstance(seed_protocol, Mapping) or seed_protocol.get("configurable_trials_per_task") is not True:
        raise ValueError(f"{suite_id} must declare its configurable multi-seed protocol")
    paper = raw.get("paper_relationship")
    for key in ("selection_method", "difficulty_rubric", "candidate_pool_audit"):
        if not isinstance(raw.get(key), Mapping):
            raise ValueError(f"{suite_id} requires mapping metadata for {key}")

    metadata = {
        "selection_method": raw.get("selection_method"),
        "difficulty_rubric": raw.get("difficulty_rubric"),
        "candidate_pool_audit": raw.get("candidate_pool_audit"),
        "paper_relationship": dict(paper) if isinstance(paper, Mapping) else None,
        "seed_protocol": dict(seed_protocol),
    }
    return MineDojoPortedSuite(
        suite_id=suite_id,
        selection_version=selection_version,
        description=_required_text(raw, "description", context="MineDojo-ported suite"),
        source_suite_id=source_suite_id,
        path=path,
        default_trials_per_task=default_trials,
        tasks=tasks,
        metadata=metadata,
    )


__all__ = [
    "MINEDOJO_FULL_SUITE_ID",
    "MINEDOJO_300_SUITE_ID",
    "MINEDOJO_300_SUITE_PATH",
    "MINEDOJO_PORTED_SUITE_IDS",
    "MineDojoPortedSuite",
    "MineDojoTaskSelection",
    "load_minedojo_ported_suite",
]

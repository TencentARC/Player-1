"""Runtime logger for model interactions, state, and task evaluation."""

from __future__ import annotations

import logging
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from tools.runs.artifacts import (
    EVALUATION_FILENAME,
    INTERACTIONS_FILENAME,
    append_jsonl_object,
    write_json_object,
)

LOGGER = logging.getLogger(__name__)
_VALID_MEMORY_SCREENSHOT_MODES = {"path", "copy"}


# ---------- Trace / memory helpers ----------

_VALID_MEMORY_TYPES = {"text", "image"}
_VALID_MEMORY_ROLES = {"user", "assistant"}
MemoryEntry = dict[str, str | None]


def _read_field(item: Any, field: str) -> Any:
    if isinstance(item, dict):
        return item.get(field)
    return getattr(item, field, None)


def _normalize_memory_entries(raw_entries: Any) -> list[MemoryEntry]:
    if not isinstance(raw_entries, list):
        return []

    entries: list[MemoryEntry] = []
    for item in raw_entries:
        entry_type = _read_field(item, "type") or _read_field(item, "kind")
        role = _read_field(item, "role")
        if entry_type not in _VALID_MEMORY_TYPES or role not in _VALID_MEMORY_ROLES:
            continue

        raw_text = _read_field(item, "text")
        raw_image_path = _read_field(item, "image_path")

        text = raw_text if isinstance(raw_text, str) else None
        if isinstance(raw_image_path, Path):
            image_path = str(raw_image_path)
        elif isinstance(raw_image_path, str):
            image_path = raw_image_path
        else:
            image_path = None

        entries.append(
            {
                "type": str(entry_type),
                "role": str(role),
                "text": text,
                "image_path": image_path,
            }
        )

    return entries


def _memory_entries_to_text(entries: list[MemoryEntry]) -> str | None:
    lines: list[str] = []
    for entry in entries:
        role = str(entry.get("role") or "").title()
        if entry.get("type") == "text":
            text = entry.get("text")
            if text:
                lines.append(f"{role}: {text}")
            continue

        if entry.get("type") == "image":
            image_path = entry.get("image_path")
            if image_path:
                lines.append(f"{role} Image: {image_path}")

    return "\n".join(lines) if lines else None


def _build_prompt_text(
    *,
    system_prompt: str | None,
    memory_entries: list[MemoryEntry],
    user_prompt: str | None,
) -> str:
    system_text = (system_prompt or "").strip() if system_prompt is not None else ""
    memory_text = _memory_entries_to_text(memory_entries)
    user_text = (user_prompt or "").strip() if user_prompt is not None else ""

    sections = [
        f"# System Message\n{system_text if system_text else '(none)'}",
        f"# Action History\n{memory_text if memory_text else '(none)'}",
    ]
    if user_prompt is not None:
        sections.append(f"# User Message\n{user_text if user_text else '(empty)'}")
    return "\n\n".join(sections)


def _normalize_memory_screenshot_mode(value: Any) -> str:
    normalized = str(value or "path").strip().lower()
    if normalized in _VALID_MEMORY_SCREENSHOT_MODES:
        return normalized
    return "path"


# ---------- Record helpers ----------


def _build_interaction_record(
    *,
    interaction_id: int,
    timestamp: str,
    agent_id: str,
    model_name: str,
    screenshot: str | None,
    prompt: str,
    raw_message_sent: str,
    memory_context: str | None,
    memory_screenshots: list[str],
    raw_response: str,
    parsed_action: dict[str, Any] | None,
    error: str | None,
) -> dict[str, Any]:
    return {
        "interaction_id": interaction_id,
        "timestamp": timestamp,
        "agent_id": agent_id,
        "model_name": model_name,
        "input": {
            "screenshot": screenshot,
            "prompt": prompt,
            "raw_message_sent": raw_message_sent,
            "memory_context": memory_context,
            "memory_screenshots": memory_screenshots,
        },
        "output": {
            "raw_response": raw_response,
            "parsed_action": parsed_action,
            "action_validity": None,
            "executed_action": None,
            "error": error,
        },
        "frame_timing": None,
        "game_state": None,
        "task_evaluation": None,
    }


def _build_task_eval_record(
    *,
    agent_id: str,
    interaction_id: int,
    evaluation: dict[str, Any],
) -> dict[str, Any]:
    record = {
        "timestamp": datetime.now().isoformat(),
        "agent_id": agent_id,
        "interaction_id": interaction_id,
    }
    record.update(evaluation)
    return record


@dataclass
class _StepRef:
    interaction_id: int
    timestamp: str


class RuntimeLogger:
    """Persist per-agent runtime artifacts under one session/agent directory."""

    def __init__(
        self,
        log_dir: str | Path = "logs",
        agent_id: str = "agent",
        session_id: str | None = None,
        game_name: str | None = None,
        model_name: str | None = None,
        session_root: str | Path | None = None,
        memory_screenshot_mode: str = "path",
    ):
        self.log_dir = Path(log_dir)
        self.agent_id = agent_id
        self.session_id = session_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        self.game_name = game_name or "game"
        self.model_name = model_name or "model"
        self.memory_screenshot_mode = _normalize_memory_screenshot_mode(
            memory_screenshot_mode
        )

        if session_root:
            self.session_root = Path(session_root)
            self.session_root.mkdir(parents=True, exist_ok=True)
        else:
            self.session_root = self._create_session_root()
        self.session_dir = self.session_root / self.agent_id
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir = self.session_dir / "artifacts"
        self.screenshots_dir = self.artifacts_dir / "screenshots"
        self.memory_dir = self.artifacts_dir / "memory"
        self.evaluation_dir = self.session_dir / "evaluation"
        self.evaluation_path = self.evaluation_dir / EVALUATION_FILENAME
        self.interactions_path = self.session_dir / INTERACTIONS_FILENAME
        self._logged_screenshot_refs: dict[str, str] = {}

        self.interaction_count = 0
        self._pending_step: _StepRef | None = None
        self._pending_interaction: dict[str, Any] | None = None

    @staticmethod
    def _slugify(value: str, max_len: int = 50) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9]+", "_", value.strip().lower())
        cleaned = cleaned[:max_len].strip("_")
        return cleaned or "unknown"

    def _create_session_root(self) -> Path:
        session_name = (
            f"{self.session_id}_"
            f"{self._slugify(self.game_name)}_"
            f"{self._slugify(self.model_name)}"
        )
        session_dir = self.log_dir / session_name
        session_dir.mkdir(parents=True, exist_ok=True)
        return session_dir

    def _begin_step(self) -> _StepRef:
        if self._pending_interaction is not None:
            LOGGER.warning(
                "Finalizing incomplete interaction before starting the next one. agent_id=%s interaction_id=%s",
                self.agent_id,
                self._pending_step.interaction_id if self._pending_step else None,
            )
            self.finalize_step()
        self.interaction_count += 1
        step = _StepRef(
            interaction_id=self.interaction_count,
            timestamp=datetime.now().isoformat(),
        )
        self._pending_step = step
        return step

    @staticmethod
    def _step_stem(interaction_id: int) -> str:
        return f"step_{interaction_id:06d}"

    def _pending_output(self) -> dict[str, Any] | None:
        if not isinstance(self._pending_interaction, dict):
            return None
        output = self._pending_interaction.get("output")
        if isinstance(output, dict):
            return output
        self._pending_interaction["output"] = {}
        return self._pending_interaction["output"]

    @staticmethod
    def _source_key(path: Path | str | None) -> str | None:
        if not path:
            return None
        try:
            return str(Path(path).expanduser().resolve())
        except Exception:
            return str(Path(path))

    def _register_logged_screenshot(
        self, source_path: Path | str | None, rel_path: str | None
    ) -> None:
        key = self._source_key(source_path)
        if key and rel_path:
            self._logged_screenshot_refs[key] = rel_path

    def _session_relative_path(self, path: Path | str | None) -> str | None:
        if not path:
            return None

        candidate = Path(path)
        if not candidate.is_absolute():
            normalized = candidate.as_posix()
            target = (self.session_dir / candidate).resolve()
            if target.exists():
                return normalized
            return None

        try:
            return str(candidate.resolve().relative_to(self.session_dir.resolve()))
        except Exception:
            return None

    def _copy_memory_screenshot(self, step: _StepRef, source: Path, index: int) -> str:
        suffix = source.suffix or ".png"
        copied = (
            self.memory_dir
            / f"{self._step_stem(step.interaction_id)}_{index:02d}{suffix}"
        )
        copied.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, copied)
        return str(copied.relative_to(self.session_dir))

    def _resolve_memory_screenshot_path(
        self,
        step: _StepRef,
        source_path: str | None,
        index: int,
    ) -> str | None:
        if not source_path:
            return None

        source = Path(source_path)

        if self.memory_screenshot_mode == "path":
            registered = self._logged_screenshot_refs.get(
                self._source_key(source) or ""
            )
            if registered:
                return registered

            existing_relative = self._session_relative_path(source)
            if existing_relative:
                return existing_relative

            LOGGER.debug(
                "Skipping unresolved memory screenshot in path mode because no logged/session-relative path was found. agent_id=%s source=%s",
                self.agent_id,
                source,
            )
            return None

        if source.exists():
            return self._copy_memory_screenshot(step, source, index)

        return self._session_relative_path(source)

    def _materialize_memory_entries(
        self,
        step: _StepRef,
        memory_entries: list[MemoryEntry],
    ) -> tuple[list[MemoryEntry], list[str]]:
        resolved_entries: list[MemoryEntry] = []
        resolved_paths: list[str] = []
        image_index = 0

        for entry in memory_entries:
            if entry.get("type") != "image":
                resolved_entries.append(dict(entry))
                continue

            image_index += 1
            resolved_path = self._resolve_memory_screenshot_path(
                step,
                entry.get("image_path"),
                image_index,
            )
            if not resolved_path:
                continue

            updated_entry = dict(entry)
            updated_entry["image_path"] = resolved_path
            resolved_entries.append(updated_entry)
            resolved_paths.append(resolved_path)

        return resolved_entries, resolved_paths

    def _copy_screenshot(
        self, step: _StepRef, screenshot_path: Path | str | None
    ) -> str | None:
        if not screenshot_path:
            return
        source = Path(screenshot_path)
        if not source.exists():
            return None
        suffix = source.suffix or ".png"
        copied = (
            self.screenshots_dir / f"{self._step_stem(step.interaction_id)}{suffix}"
        )
        copied.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, copied)
        rel_path = str(copied.relative_to(self.session_dir))
        self._register_logged_screenshot(source, rel_path)
        return rel_path

    def log_interaction(
        self,
        screenshot_path: Path | str | None,
        prompt: str,
        raw_message_sent: str,
        raw_response: str,
        parsed_action: dict[str, Any] | None,
        model_name: str = "unknown",
        error: str | None = None,
        memory_entries: list[MemoryEntry] | None = None,
    ) -> None:
        step = self._begin_step()
        entries = _normalize_memory_entries(memory_entries)
        screenshot_rel = self._copy_screenshot(step, screenshot_path)
        materialized_entries, memory_paths = self._materialize_memory_entries(
            step, entries
        )
        memory_context = _memory_entries_to_text(materialized_entries)

        self._pending_interaction = _build_interaction_record(
            interaction_id=step.interaction_id,
            timestamp=step.timestamp,
            agent_id=self.agent_id,
            model_name=model_name,
            screenshot=screenshot_rel,
            prompt=prompt,
            raw_message_sent=raw_message_sent,
            memory_context=memory_context,
            memory_screenshots=memory_paths,
            raw_response=raw_response,
            parsed_action=parsed_action,
            error=error,
        )

    def log_interaction_from_trace(self, trace: dict[str, Any] | None) -> None:
        trace = trace or {}
        entries = _normalize_memory_entries(trace.get("memory_entries"))
        prompt = str(trace.get("prompt") or "")
        if not prompt:
            prompt = _build_prompt_text(
                system_prompt=trace.get("system_prompt"),
                memory_entries=entries,
                user_prompt=trace.get("user_prompt"),
            )

        self.log_interaction(
            screenshot_path=trace.get("screenshot_path"),
            prompt=prompt,
            raw_message_sent=str(trace.get("raw_message_sent") or ""),
            raw_response=str(trace.get("raw_response") or ""),
            parsed_action=trace.get("parsed_action"),
            model_name=str(trace.get("model_name") or "unknown"),
            error=trace.get("error"),
            memory_entries=entries,
        )

    def log_executed_action(self, action: dict[str, Any] | None) -> None:
        output = self._pending_output()
        if output is None:
            return
        output["executed_action"] = action

    def log_action_validity(self, validity: dict[str, Any] | None) -> None:
        output = self._pending_output()
        if output is None:
            return
        output["action_validity"] = validity

    def log_game_state(self, game_state: dict | None) -> None:
        if isinstance(self._pending_interaction, dict):
            self._pending_interaction["game_state"] = game_state

    def log_frame_timing(self, frame_timing: dict[str, Any] | None) -> None:
        if isinstance(self._pending_interaction, dict):
            self._pending_interaction["frame_timing"] = frame_timing

    def log_task_evaluation(self, evaluation: dict | None) -> None:
        if not evaluation or not self._pending_step:
            return

        record = _build_task_eval_record(
            agent_id=self.agent_id,
            interaction_id=self._pending_step.interaction_id,
            evaluation=evaluation,
        )
        write_json_object(self.evaluation_path, record)

        if isinstance(self._pending_interaction, dict):
            self._pending_interaction["task_evaluation"] = record

    def finalize_step(self) -> None:
        if not isinstance(self._pending_interaction, dict):
            self._pending_step = None
            return
        append_jsonl_object(self.interactions_path, self._pending_interaction)
        self._pending_interaction = None
        self._pending_step = None


__all__ = ["RuntimeLogger"]

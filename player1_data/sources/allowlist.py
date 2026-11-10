"""Strict identity-only allowlist for immutable desktop-MCAP sessions.

The exact schema contains only dataset, revision, session, and local-input
identities. Extra fields are rejected and never become projection authority.
"""

from __future__ import annotations

import json
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from player1_data.files import is_canonical_relative_posix_path

_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
DESKTOP_MCAP_SESSION_ALLOWLIST_SCHEMA = "game-gym.sft.desktop_mcap_session_allowlist"


class DesktopMcapSessionAllowlistError(ValueError):
    """Raised when a desktop-MCAP session allowlist is unsafe or malformed."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DesktopMcapSessionAllowlistError(message)


def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        _require(key not in result, f"desktop MCAP session allowlist repeats object key {key!r}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise DesktopMcapSessionAllowlistError(f"desktop MCAP session allowlist contains non-finite constant {value!r}")


def _path_is_reparse(path: Path) -> bool:
    info = path.lstat()
    return path.is_symlink() or bool(getattr(info, "st_file_attributes", 0) & _REPARSE_POINT)


def _text(value: Any, *, field: str) -> str:
    _require(isinstance(value, str) and bool(value), f"{field} must be non-empty")
    _require(value == value.strip(), f"{field} must not have leading or trailing whitespace")
    return value


def _relative_mcap(value: Any, *, field: str) -> str:
    raw = _text(value, field=field)
    _require(
        is_canonical_relative_posix_path(raw, suffix=".mcap"),
        f"{field} must be a relative POSIX .mcap path",
    )
    return raw


@dataclass(frozen=True, slots=True)
class DesktopMcapSessionAllowlist:
    """Validated source identities from one allowlist document."""

    path: Path
    source_root: Path
    dataset_id: str
    source_revision: str
    eligible_sources: frozenset[tuple[str, str]]

    def contains_source(
        self,
        *,
        dataset_id: str,
        source_revision: str,
        session_id: str,
        local_input: str,
    ) -> bool:
        _require(dataset_id == self.dataset_id, "allowlist dataset_id differs from the source")
        _require(source_revision == self.source_revision, "allowlist source_revision differs from the source")
        identity = (
            _text(session_id, field="session_id"),
            _relative_mcap(local_input, field="local_input"),
        )
        return identity in self.eligible_sources


def load_desktop_mcap_session_allowlist(
    path: Path,
    *,
    source_root: Path,
) -> DesktopMcapSessionAllowlist:
    """Load immutable source identities from an allowlist document."""

    raw_allowlist_path = path.expanduser()
    raw_root = source_root.expanduser()
    _require(raw_allowlist_path.is_absolute(), "desktop MCAP session allowlist path must be absolute")
    _require(raw_root.is_absolute(), "desktop MCAP source root must be absolute")
    _require(raw_allowlist_path.is_file(), f"desktop MCAP session allowlist is missing: {raw_allowlist_path}")
    _require(
        not _path_is_reparse(raw_allowlist_path),
        f"desktop MCAP session allowlist must not be a symlink or reparse point: {raw_allowlist_path}",
    )
    _require(raw_root.is_dir(), f"desktop MCAP source root is missing: {raw_root}")
    _require(
        not _path_is_reparse(raw_root),
        f"desktop MCAP source root must not be a symlink or reparse point: {raw_root}",
    )
    allowlist_path = raw_allowlist_path.resolve(strict=True)
    root = raw_root.resolve(strict=True)
    try:
        document = json.loads(
            allowlist_path.read_text(encoding="utf-8"),
            object_pairs_hook=_strict_json_object,
            parse_constant=_reject_json_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DesktopMcapSessionAllowlistError("desktop MCAP session allowlist is not valid UTF-8 JSON") from error
    _require(isinstance(document, dict), "desktop MCAP session allowlist must be an object")
    _require(
        set(document) == {"schema_version", "dataset_id", "source_revision", "records"},
        "desktop MCAP session allowlist has an invalid shape",
    )
    _require(
        document.get("schema_version") == DESKTOP_MCAP_SESSION_ALLOWLIST_SCHEMA,
        "desktop MCAP session allowlist schema is invalid",
    )
    dataset_id = _text(document.get("dataset_id"), field="allowlist.dataset_id")
    source_revision = _text(document.get("source_revision"), field="allowlist.source_revision")
    raw_records = document.get("records")
    _require(isinstance(raw_records, list) and bool(raw_records), "allowlist.records must be non-empty")
    eligible_sources: set[tuple[str, str]] = set()
    ordered_sources: list[tuple[str, str]] = []
    for index, raw_record in enumerate(raw_records):
        field = f"records[{index}]"
        _require(isinstance(raw_record, Mapping), f"{field} must be an object")
        _require(set(raw_record) == {"session_id", "local_input"}, f"{field} has an invalid shape")
        identity = (
            _text(raw_record.get("session_id"), field=f"{field}.session_id"),
            _relative_mcap(raw_record.get("local_input"), field=f"{field}.local_input"),
        )
        _require(identity not in eligible_sources, f"allowlist repeats source identity {identity!r}")
        eligible_sources.add(identity)
        ordered_sources.append(identity)
    _require(
        ordered_sources == sorted(ordered_sources),
        "allowlist.records must be sorted by session_id and local_input",
    )
    return DesktopMcapSessionAllowlist(
        path=allowlist_path,
        source_root=root,
        dataset_id=dataset_id,
        source_revision=source_revision,
        eligible_sources=frozenset(eligible_sources),
    )


__all__ = [
    "DESKTOP_MCAP_SESSION_ALLOWLIST_SCHEMA",
    "DesktopMcapSessionAllowlist",
    "DesktopMcapSessionAllowlistError",
    "load_desktop_mcap_session_allowlist",
]

"""Pure reader for compact Player-1 Control training releases."""

from __future__ import annotations

import json
import os
import stat
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

from player1.datasets.collection_contract import COLLECTION_SCHEMA, identity_key, session_split
from player1.datasets.release_contract import (
    _RELEASE_MEMBERS,
    SPLITS,
    ValidatedPlayerOneControlPathRecord,
    canonical_image_contract,
    player1_control_parquet_schema,
    validate_canonical_image_contract,
    validate_image_reference,
)
from player1.datasets.release_contract import (
    validate_player1_control_path_record as validate_compact_path_record,
)
from player1.datasets.storage import child, file_sizes, is_s3, location, open_input, read_bytes


def _nested_python(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _nested_python(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_nested_python(item) for item in value]
    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        converted = tolist()
        if converted is not value:
            return _nested_python(converted)
    return value


def _canonical_root(path: str | Path) -> Path | str:
    if is_s3(path):
        return location(path)
    candidate = Path(path).expanduser()
    if not candidate.is_absolute() or candidate.parent == candidate:
        raise ValueError("canonical image root must be a non-root absolute directory")
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    try:
        info = candidate.lstat()
        root = candidate.resolve(strict=True)
    except OSError as error:
        raise ValueError(f"cannot inspect canonical image root: {candidate}") from error
    if (
        not stat.S_ISDIR(info.st_mode)
        or candidate.is_symlink()
        or bool(getattr(info, "st_file_attributes", 0) & reparse)
    ):
        raise ValueError("canonical image root must be a regular non-reparse directory")
    return root


class CanonicalImageStore:
    """Resolve canonical-relative image references and enforce their declared size."""

    def __init__(self, image_contract: Mapping[str, Any], *, canonical_root: str | Path) -> None:
        self.contract = validate_canonical_image_contract(image_contract)
        self.root = _canonical_root(canonical_root)
        self._image_sizes: dict[str, int] | None = None
        self._cache: OrderedDict[str, bytes] = OrderedDict()
        self._cache_bytes = 0
        self._cache_pid = os.getpid()

    def _resolve(self, relative: str, size: int) -> Path:
        reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        parts = PurePosixPath(relative).parts
        try:
            current = self.root
            for index, part in enumerate(parts):
                current /= part
                info = current.lstat()
                if current.is_symlink() or bool(getattr(info, "st_file_attributes", 0) & reparse):
                    raise ValueError("canonical image reference traverses a reparse point")
                if index < len(parts) - 1 and not stat.S_ISDIR(info.st_mode):
                    raise ValueError("canonical image reference traverses a non-directory")
            resolved = current.resolve(strict=True)
            resolved.relative_to(self.root)
            info = resolved.lstat()
        except (OSError, ValueError) as error:
            raise ValueError("canonical image reference escapes or is absent from its frozen root") from error
        if (
            not stat.S_ISREG(info.st_mode)
            or resolved.is_symlink()
            or bool(getattr(info, "st_file_attributes", 0) & reparse)
        ):
            raise ValueError("canonical image reference must be a regular non-reparse file")
        if info.st_size != size:
            raise ValueError("canonical image size differs from its reference")
        return resolved

    def verify(self, value: Any) -> dict[str, Any]:
        relative, size = validate_image_reference(value)
        if is_s3(self.root):
            if self._image_sizes is None:
                self._image_sizes = file_sizes(self.root, recursive=True)
            if self._image_sizes.get(relative) != size:
                raise ValueError(f"canonical S3 image is missing or differs in size: {relative}")
        else:
            self._resolve(relative, size)
        return {"image": relative, "size_bytes": size}

    def read(self, value: Any) -> bytes:
        relative, size = validate_image_reference(value)
        if is_s3(self.root):
            if self._cache_pid != os.getpid():
                self._cache.clear()
                self._cache_bytes = 0
                self._cache_pid = os.getpid()
            payload = self._cache.get(relative)
            if payload is None:
                payload = read_bytes(child(self.root, relative))
                if len(payload) != size:
                    raise ValueError(f"canonical S3 image size differs from its reference: {relative}")
                if size <= 32 * 1024 * 1024:
                    self._cache[relative] = payload
                    self._cache_bytes += size
                    while self._cache_bytes > 32 * 1024 * 1024:
                        self._cache_bytes -= len(self._cache.popitem(last=False)[1])
            else:
                self._cache.move_to_end(relative)
            if len(payload) != size:
                raise ValueError("canonical S3 image has conflicting size references")
            return payload
        path = self._resolve(relative, size)
        try:
            payload = path.read_bytes()
        except OSError as error:
            raise ValueError("cannot read canonical image reference") from error
        if len(payload) != size:
            raise ValueError("canonical image size changed while it was read")
        return payload

    def __getstate__(self) -> dict[str, Any]:
        return {"contract": self.contract, "canonical_root": str(self.root)}

    def __setstate__(self, state: Mapping[str, Any]) -> None:
        self.__init__(state["contract"], canonical_root=state["canonical_root"])


def validate_player1_control_path_record(value: Mapping[str, Any]) -> ValidatedPlayerOneControlPathRecord:
    """Adapt Arrow/NumPy values and validate one compact current-turn row."""
    return validate_compact_path_record(_nested_python(value))


def validate_dataset_manifest(manifest: Any) -> dict[str, Any]:
    """Validate portable metadata without opening Parquet or listing images."""
    if (
        not isinstance(manifest, dict)
        or set(manifest) != {"schema_version", "split_seed", "validation_basis_points", "trajectories"}
        or manifest["schema_version"] != COLLECTION_SCHEMA
    ):
        raise ValueError("Invalid dataset manifest")
    trajectories = manifest["trajectories"]
    if not isinstance(trajectories, list) or not trajectories:
        raise ValueError("Dataset needs trajectory provenance")
    ids, identities = set(), set()
    groups = {split: {} for split in SPLITS}
    for trajectory in trajectories:
        if not isinstance(trajectory, dict) or set(trajectory) != {
            "id",
            "source",
            "mode",
            "split",
            "row_group",
            "rows",
            "annotation",
        }:
            raise ValueError("Invalid trajectory provenance")
        identity = identity_key(trajectory["source"])
        name = trajectory["id"]
        if (
            not isinstance(name, str)
            or not name
            or name in {".", ".."}
            or "/" in name
            or "\\" in name
            or name in ids
            or identity in identities
        ):
            raise ValueError("Invalid or duplicate trajectory identity")
        ids.add(name)
        identities.add(identity)
        rows, mode = trajectory["rows"], trajectory["mode"]
        if type(rows) is not int or not (mode == "gameplay" and rows == 50 or mode == "gui" and 25 <= rows <= 50):
            raise ValueError("Invalid complete trajectory length")
        split, ordinal = trajectory["split"], trajectory["row_group"]
        if (
            not isinstance(split, str)
            or split not in groups
            or type(ordinal) is not int
            or ordinal < 0
            or ordinal in groups[split]
        ):
            raise ValueError("Invalid or duplicate row group")
        if split != session_split(trajectory["source"], manifest["split_seed"], manifest["validation_basis_points"]):
            raise ValueError("Trajectory split differs from its source-session policy")
        annotation = trajectory["annotation"]
        if (
            not isinstance(annotation, dict)
            or set(annotation) != {"model", "procedure", "input_sha256"}
            or any(not isinstance(v, str) or not v.strip() for v in annotation.values())
            or len(annotation["input_sha256"]) != 64
            or any(c not in "0123456789abcdef" for c in annotation["input_sha256"])
        ):
            raise ValueError("Incomplete annotation provenance")
        groups[split][ordinal] = trajectory
    return manifest


def validate_dataset_structure(directory: str | Path, *, canonical_root: str | Path) -> dict[str, Any]:
    """Validate each trajectory, provenance, action and image against one manifest."""
    import pyarrow.parquet as pq

    root = location(directory)
    if is_s3(root):
        if set(file_sizes(root, recursive=True)) != _RELEASE_MEMBERS:
            raise ValueError("Dataset data directory has unexpected members")
    else:
        if Path(directory).is_symlink() or {p.name for p in root.iterdir()} != _RELEASE_MEMBERS:
            raise ValueError("Dataset data directory has unexpected members or is a symlink")
        reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024)
        if any(
            not p.is_file() or p.is_symlink() or getattr(p.lstat(), "st_file_attributes", 0) & reparse
            for p in root.iterdir()
        ):
            raise ValueError("Dataset members must be regular files")
    manifest = json.loads(read_bytes(child(root, "manifest.json")))
    validate_dataset_manifest(manifest)
    sample_ids, image_sizes = set(), {}
    groups = {split: {t["row_group"]: t for t in manifest["trajectories"] if t["split"] == split} for split in SPLITS}
    images = CanonicalImageStore(canonical_image_contract(), canonical_root=canonical_root)
    for split in SPLITS:
        with open_input(child(root, f"{split}.parquet")) as stream, pq.ParquetFile(stream) as parquet:
            if not parquet.schema_arrow.equals(player1_control_parquet_schema()):
                raise ValueError("Dataset Parquet schema changed")
            if set(groups[split]) != set(range(parquet.num_row_groups)):
                raise ValueError("Trajectory row-group coverage differs from Parquet")
            for ordinal in range(parquet.num_row_groups):
                trajectory = groups[split][ordinal]
                if parquet.metadata.row_group(ordinal).num_rows != trajectory["rows"]:
                    raise ValueError("Row group must contain one complete trajectory")
                records = [
                    validate_player1_control_path_record(row) for row in parquet.read_row_group(ordinal).to_pylist()
                ]
                initial, weight = records[0].messages[:2], records[0].source_weight
                for index, record in enumerate(records):
                    if record.sample_id in sample_ids:
                        raise ValueError("Duplicate sample identity")
                    sample_ids.add(record.sample_id)
                    if (
                        record.source_key != trajectory["source"]["adapter_id"]
                        or record.source_weight != weight
                        or record.messages[:2] != initial
                        or record.segment_turn_index != index
                    ):
                        raise ValueError("Trajectory changes source, weight, initial prompt or turn order")
                    for image in record.images:
                        parts = PurePosixPath(image["image"]).parts
                        if len(parts) < 3 or parts[:2] != ("trajectories", trajectory["id"]):
                            raise ValueError("Image differs from trajectory provenance")
                        if image_sizes.setdefault(image["image"], image["size_bytes"]) != image["size_bytes"]:
                            raise ValueError("Image has conflicting sizes")
                        images.verify(image)
    return manifest

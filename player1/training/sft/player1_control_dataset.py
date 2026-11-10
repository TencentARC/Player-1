"""Strict Qwen3.5 SFT loader for Player-1 Control Parquet."""

from __future__ import annotations

import os
from collections.abc import Iterator, Mapping, Sequence
from copy import copy
from functools import partial
from pathlib import Path
from types import MethodType
from typing import Any

import torch
from player1.agents.chat_template import qwen35_player1_chat_template_kwargs
from verl.utils.dataset.multiturn_sft_dataset import extract_system_prompt_and_generation

from player1.training.sft.player1_control_parquet import PlayerOneControlParquetRows
from player1.training.sft.player1_control_prompt import player1_control_rl_tools
from player1.datasets.release_reader import CanonicalImageStore
from player1.datasets.storage import location
from player1.training.sft.player1_control_training_contract import (
    PlayerOneControlTrainingContract,
    load_player1_control_training_contract,
)
from player1.training.sft.history_context_sampling import HistorySampleIndex
from player1.training.sft.qwen35_dataset import Qwen35SystemAwareSFTDataset


def player1_control_assistant_is_supervised(
    *,
    index: int,
    message: Mapping[str, Any],
    full_message: Sequence[Mapping[str, Any]],
) -> bool:
    """Return whether a message is the one frozen final-assistant loss target."""

    if not full_message or full_message[-1].get("role") != "assistant":
        raise ValueError("Player-1 Control SFT conversation must end with the current assistant")
    return index == len(full_message) - 1 and message.get("role") == "assistant"


def _validate_supervised_target(input_ids: torch.Tensor, loss_mask: torch.Tensor, end_think_id: int) -> None:
    supervised = loss_mask.bool()
    boundaries = ((input_ids == end_think_id) & supervised).nonzero().flatten()
    if len(boundaries) != 1:
        raise ValueError("Current SFT target must contain exactly one supervised </think> token")
    if not supervised[int(boundaries[0]) + 1 :].any():
        raise ValueError("Current SFT target has no supervised action after </think>")


class _SharedTools(Sequence[list[dict[str, Any]]]):
    """One immutable-by-contract tool value exposed for every dataset row."""

    def __init__(self, tools: list[dict[str, Any]], count: int) -> None:
        self._tools = tools
        self._count = count

    def __len__(self) -> int:
        return self._count

    def __getitem__(self, index: int | slice | HistorySampleIndex) -> list[dict[str, Any]] | list[list[dict[str, Any]]]:
        if isinstance(index, HistorySampleIndex):
            index = index.row_index
        if isinstance(index, slice):
            return [self._tools for _ in range(*index.indices(self._count))]
        normalized = index + self._count if index < 0 else index
        if not 0 <= normalized < self._count:
            raise IndexError("Player-1 Control tool row index is out of range")
        return self._tools


def _one_parquet_file(value: str | os.PathLike[str] | Sequence[str | os.PathLike[str]]) -> Path | str:
    if isinstance(value, (str, os.PathLike)):
        paths = [value]
    else:
        paths = list(value)
    if len(paths) != 1:
        raise ValueError("Player-1 Control dataset requires exactly one immutable Parquet split")
    return location(paths[0])


def _spawn_safe_processor(processor: Any) -> Any:
    """Preserve verl's instance-bound RoPE callbacks across DataLoader spawn."""
    original = processor
    processor = copy(processor)
    for name in ("get_rope_index", "get_vision_position_ids"):
        method = getattr(processor, name, None)
        if isinstance(method, MethodType) and method.__self__ is original:
            # Pickle restores MethodType through getattr(instance, name), but
            # these model methods are not members of the HF processor class.
            setattr(processor, name, partial(method.__func__, processor))
    return processor


class PlayerOneControlQwen35SFTDataset(Qwen35SystemAwareSFTDataset):
    """Train Qwen3.5 on strict Player-1 Control rows with current-assistant-only loss."""

    def __init__(
        self,
        parquet_files: str | list[str],
        tokenizer: Any,
        config: Mapping[str, Any],
        processor: Any = None,
        max_samples: int = -1,
    ) -> None:
        if processor is None:
            raise ValueError("Player-1 Control Qwen3.5 SFT requires a multimodal processor")
        processor = _spawn_safe_processor(processor)
        if max_samples != -1:
            raise ValueError("Player-1 Control trains the complete immutable split; publish a smaller release for a canary")
        dataset_config = dict(config or {})
        required_keys = {
            "messages_key": "messages",
            "image_key": "images",
            "truncation": "error",
            "shuffle": False,
        }
        for key, expected in required_keys.items():
            if dataset_config.get(key, expected) != expected:
                raise ValueError(f"Player-1 Control Qwen3.5 SFT requires data.{key}={expected!r}")
        if dataset_config.get("ignore_input_ids_mismatch", False):
            raise ValueError("Player-1 Control Qwen3.5 SFT forbids ignore_input_ids_mismatch")
        template_kwargs = dataset_config.get("apply_chat_template_kwargs", {})
        if not isinstance(template_kwargs, Mapping) or template_kwargs.get("enable_thinking") is not True:
            raise ValueError("Player-1 Control Qwen3.5 SFT requires enable_thinking=true")
        template_kwargs, self.qwen35_chat_template_contract = qwen35_player1_chat_template_kwargs(
            processor,
            dict(template_kwargs),
        )
        dataset_config["apply_chat_template_kwargs"] = template_kwargs
        self._release_contract: PlayerOneControlTrainingContract = load_player1_control_training_contract(dataset_config)
        self._image_store = CanonicalImageStore(
            self._release_contract.image_contract,
            canonical_root=self._release_contract.canonical_root,
        )
        requested_file = _one_parquet_file(parquet_files)
        if requested_file == self._release_contract.train_file:
            self._split = "train"
        elif requested_file == self._release_contract.validation_file:
            self._split = "validation"
        else:
            raise ValueError(f"Parquet file is not a split of the frozen Player-1 Control release: {requested_file}")
        super().__init__(
            parquet_files=parquet_files,
            tokenizer=tokenizer,
            config=dataset_config,
            processor=processor,
            max_samples=max_samples,
        )

        end_think_ids = tokenizer.encode("</think>", add_special_tokens=False)
        if len(end_think_ids) != 1:
            raise ValueError("Player-1 Control Qwen3.5 requires a single-token </think> delimiter")
        self._end_think_id = end_think_ids[0]

    def __getitem__(self, index: int | HistorySampleIndex) -> dict[str, Any]:
        item = super().__getitem__(index)
        _validate_supervised_target(
            item["input_ids"], item["loss_mask"], self._end_think_id,
        )
        return item

    def _download(self) -> None:
        # The release reader owns local and range-based S3 IO; never localize
        # a split through the generic VERL loader.
        pass

    def _read_files_and_process(self) -> None:
        parquet_file = _one_parquet_file(self.parquet_files)
        expected_file = (
            self._release_contract.train_file if self._split == "train" else self._release_contract.validation_file
        )
        if parquet_file != expected_file:
            raise ValueError("VERL changed the frozen Player-1 Control Parquet path while localizing it")
        snapshot = self._release_contract.snapshot_for(parquet_file)
        self._rows = PlayerOneControlParquetRows(
            snapshot,
            split=self._split,
            trajectories=self._release_contract.trajectories(self._split),
            image_store=self._image_store,
            history_config={
                "history_context_turns": self._release_contract.history_projection["recent"]["turns"],
                "history_context_old_turns": self._release_contract.history_projection["old"]["turns"],
            },
        )
        # These are the only dataframe-like surfaces used by VERL's map-style base.
        self.dataframe = self._rows
        self.messages = self._rows
        shared_tools = player1_control_rl_tools()
        self.tools = _SharedTools(shared_tools, len(self._rows))
        self.enable_thinking = None
        self.system_prompt, self.generation_prompt = extract_system_prompt_and_generation(
            self.tokenizer,
            **self.apply_chat_template_kwargs,
        )

    @property
    def source_weights(self) -> Sequence[float]:
        return self._rows.source_weights

    def iter_canonical_actions(self) -> Iterator[str]:
        return self._rows.iter_canonical_actions()

    @property
    def row_group_stops(self) -> tuple[int, ...]:
        return self._rows.row_group_stops

    def close(self) -> None:
        rows = getattr(self, "_rows", None)
        if rows is not None:
            rows.close()

    def _process_single_message(
        self,
        index: int,
        message: dict[str, Any],
        full_message: list,
        tools: list[dict[str, Any]] | None = None,
        enable_thinking: bool | None = None,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, dict[str, torch.Tensor]]:
        supervised = player1_control_assistant_is_supervised(
            index=index,
            message=message,
            full_message=full_message,
        )
        if message.get("role") == "assistant" and not supervised and isinstance(message.get("reasoning_content"), str):
            raise ValueError("Player-1 Control history assistants must not preserve reasoning_content")
        input_ids, loss_mask, attention_mask, inputs = super()._process_single_message(
            index=index,
            message=message,
            full_message=full_message,
            tools=tools,
            enable_thinking=enable_thinking,
        )
        if not supervised:
            loss_mask = torch.zeros_like(loss_mask)
        return input_ids, loss_mask, attention_mask, inputs


__all__ = [
    "PlayerOneControlQwen35SFTDataset",
    "player1_control_assistant_is_supervised",
]

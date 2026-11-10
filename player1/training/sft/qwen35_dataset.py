"""Qwen3.5 system-message support for verl's native multi-turn SFT dataset."""

from __future__ import annotations

from typing import Any, Optional

import torch
from verl.utils.dataset.multiturn_sft_dataset import MultiTurnSFTDataset


class Qwen35SystemAwareSFTDataset(MultiTurnSFTDataset):
    """Preserve a leading system role while satisfying Qwen3.5's user-query requirement.

    Qwen3.5 refuses to render a system-only message. Native MultiTurnSFTDataset
    tokenizes each role separately, so the system turn is rendered with a dummy
    empty user and that exact user suffix is removed. The inherited full-message
    sanity check proves that the reassembled token sequence is unchanged.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        thinking_prefix = self.tokenizer.encode("<think>\n", add_special_tokens=False)
        generation_prompt = list(self.generation_prompt)
        if not thinking_prefix or generation_prompt[-len(thinking_prefix) :] != thinking_prefix:
            raise AssertionError("Qwen3.5 generation prompt does not end with the enabled thinking prefix")
        historical_prompt = generation_prompt[: -len(thinking_prefix)]
        if not historical_prompt:
            raise AssertionError("Qwen3.5 historical assistant prompt is empty")
        self._historical_assistant_prompt = tuple(historical_prompt)

    def _process_single_message(
        self,
        index: int,
        message: dict[str, Any],
        full_message: list,
        tools: Optional[list[dict[str, Any]]] = None,
        enable_thinking: Optional[bool] = None,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, dict[str, torch.Tensor]]:
        if message["role"] == "assistant" and index < len(full_message) - 1:
            return self._process_non_final_assistant(
                message=message,
                tools=tools,
                enable_thinking=enable_thinking,
            )
        if message["role"] != "system":
            return super()._process_single_message(
                index=index,
                message=message,
                full_message=full_message,
                tools=tools,
                enable_thinking=enable_thinking,
            )
        if index != 0:
            raise ValueError("Qwen3.5 system messages must be the first conversation turn")

        processor = self.processor if self.processor is not None else self.tokenizer
        template_kwargs = {**self.apply_chat_template_kwargs}
        if enable_thinking is not None:
            template_kwargs["enable_thinking"] = enable_thinking
        dummy_user = {"role": "user", "content": [{"type": "text", "text": ""}]}

        combined = dict(
            processor.apply_chat_template(
                [message, dummy_user],
                tools=tools,
                add_generation_prompt=False,
                tokenize=True,
                return_dict=True,
                return_tensors="pt",
                **template_kwargs,
            )
        )
        dummy = dict(
            processor.apply_chat_template(
                [dummy_user],
                tools=None,
                add_generation_prompt=False,
                tokenize=True,
                return_dict=True,
                return_tensors="pt",
                **template_kwargs,
            )
        )
        suffix_ids = dummy["input_ids"]
        suffix_length = suffix_ids.shape[1]
        if suffix_length == 0 or combined["input_ids"].shape[1] <= suffix_length:
            raise AssertionError("Qwen3.5 dummy user did not produce a removable token suffix")
        if not torch.equal(combined["input_ids"][:, -suffix_length:], suffix_ids):
            raise AssertionError("Qwen3.5 dummy user tokens are not an exact suffix of the system rendering")

        sequence_length = combined["input_ids"].shape[1]
        for key, value in list(combined.items()):
            if isinstance(value, torch.Tensor) and value.ndim >= 2 and value.shape[1] == sequence_length:
                combined[key] = value[:, :-suffix_length]

        input_ids = combined.pop("input_ids")[0]
        attention_mask = combined.pop("attention_mask")[0]
        loss_mask = torch.zeros_like(attention_mask)
        return input_ids, loss_mask, attention_mask, combined

    def _process_non_final_assistant(
        self,
        *,
        message: dict[str, Any],
        tools: Optional[list[dict[str, Any]]],
        enable_thinking: Optional[bool],
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, dict[str, torch.Tensor]]:
        """Render an assistant in the same non-final position used by the full row.

        Verl normally renders one message at a time. Qwen3.5 then treats an
        isolated assistant as the answer to a synthetic user query and inserts
        an empty thinking block. Surrounding the assistant with two identical
        empty users makes it historical. Removing those exact token boundaries
        recovers the segment produced by the whole-conversation template.
        """

        if tools is not None:
            raise AssertionError("Qwen3.5 tools must only be attached to the leading system message")
        processor = self.processor if self.processor is not None else self.tokenizer
        template_kwargs = {**self.apply_chat_template_kwargs}
        if enable_thinking is not None:
            template_kwargs["enable_thinking"] = enable_thinking
        dummy_user = {"role": "user", "content": [{"type": "text", "text": ""}]}

        boundary = dict(
            processor.apply_chat_template(
                [dummy_user],
                tools=None,
                add_generation_prompt=False,
                tokenize=True,
                return_dict=True,
                return_tensors="pt",
                **template_kwargs,
            )
        )
        combined = dict(
            processor.apply_chat_template(
                [dummy_user, message, dummy_user],
                tools=None,
                add_generation_prompt=False,
                tokenize=True,
                return_dict=True,
                return_tensors="pt",
                **template_kwargs,
            )
        )
        boundary_ids = boundary["input_ids"]
        boundary_length = boundary_ids.shape[1]
        combined_ids = combined["input_ids"]
        if boundary_length == 0 or combined_ids.shape[1] <= 2 * boundary_length:
            raise AssertionError("Qwen3.5 non-final assistant did not produce removable user boundaries")
        if not torch.equal(combined_ids[:, :boundary_length], boundary_ids) or not torch.equal(
            combined_ids[:, -boundary_length:], boundary_ids
        ):
            raise AssertionError("Qwen3.5 non-final assistant user boundaries are not exact")

        sequence_length = combined_ids.shape[1]
        segment_end = sequence_length - boundary_length
        for key, value in list(combined.items()):
            if isinstance(value, torch.Tensor) and value.ndim == 1 and value.shape[0] == sequence_length:
                combined[key] = value[boundary_length:segment_end]
            elif isinstance(value, torch.Tensor) and value.ndim >= 2 and value.shape[1] == sequence_length:
                combined[key] = value[:, boundary_length:segment_end]

        input_ids = combined.pop("input_ids")[0]
        attention_mask = combined.pop("attention_mask")[0]
        historical_prompt = self._historical_assistant_prompt
        if input_ids[: len(historical_prompt)].tolist() != list(historical_prompt):
            raise AssertionError("Qwen3.5 non-final assistant is missing its exact prompt")
        loss_mask = torch.ones_like(attention_mask)
        loss_mask[: len(historical_prompt)] = 0
        return input_ids, loss_mask, attention_mask, combined

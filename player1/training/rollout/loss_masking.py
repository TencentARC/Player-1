"""Loss-mask construction helpers for Player-1 agent responses."""

from __future__ import annotations

import re
from typing import Any

from player1.agents.actions.parser import count_action_blocks, find_action_block_spans

RESPONSE_MASK_ACTION = "action"
RESPONSE_MASK_THINK_AND_ACTION = "think_and_action"

THINK_BLOCK_PATTERN = re.compile(r"<think>[\s\S]*?(?:</think>|$)", re.IGNORECASE)
_THINK_OPEN_PATTERN = re.compile(r"<think>", re.IGNORECASE)
_THINK_CLOSE_PATTERN = re.compile(r"</think>", re.IGNORECASE)


def normalize_response_mask_mode(mode: str | None) -> str:
    normalized = str(mode or RESPONSE_MASK_ACTION).strip().lower().replace("-", "_")
    if normalized in {"action", "action_only", "tool_call", "tool_call_only"}:
        return RESPONSE_MASK_ACTION
    if normalized in {"think_and_action", "thinking_and_action"}:
        return RESPONSE_MASK_THINK_AND_ACTION
    raise ValueError(f"Unsupported PLAYER1_RESPONSE_MASK_MODE {mode!r}; expected action or think_and_action.")


def _token_char_spans(tokenizer: Any, token_ids: list[int], text: str) -> list[tuple[int, int]] | None:
    if tokenizer is None:
        return None
    if not token_ids:
        return []

    try:
        encoded = tokenizer(text, add_special_tokens=False, return_offsets_mapping=True)
        encoded_ids = encoded.get("input_ids")
        offset_mapping = encoded.get("offset_mapping")
        if hasattr(encoded_ids, "tolist"):
            encoded_ids = encoded_ids.tolist()
        if encoded_ids == token_ids and offset_mapping is not None and len(offset_mapping) == len(token_ids):
            spans = []
            for start, end in offset_mapping:
                spans.append((int(start), int(end)))
            return spans
    except (AttributeError, KeyError, NotImplementedError, TypeError, ValueError):
        pass

    decoded_prefix = ""
    spans: list[tuple[int, int]] = []
    prefix_ids: list[int] = []
    for token_id in token_ids:
        prefix_ids.append(token_id)
        current_text = tokenizer.decode(prefix_ids, skip_special_tokens=True)
        if len(current_text) < len(decoded_prefix):
            return None
        spans.append((len(decoded_prefix), len(current_text)))
        decoded_prefix = current_text
    return spans


def _mask_from_token_char_spans(
    token_spans: list[tuple[int, int]] | None,
    char_spans: list[tuple[int, int]],
) -> list[int] | None:
    if token_spans is None:
        return None

    mask = [0] * len(token_spans)
    normalized_spans = [(max(0, start), max(0, end)) for start, end in char_spans if end > start]
    if not normalized_spans:
        return mask

    for idx, (token_start, token_end) in enumerate(token_spans):
        if token_end <= token_start:
            continue
        for span_start, span_end in normalized_spans:
            if token_end <= span_start or token_start >= span_end:
                continue
            mask[idx] = 1
            break
    return mask


def _count_mask(mask: list[int] | None) -> int:
    return int(sum(mask or []))


def find_think_block_spans(text: str) -> list[tuple[int, int]]:
    if not text:
        return []
    spans: list[tuple[int, int]] = []
    first_open = _THINK_OPEN_PATTERN.search(text)
    first_close = _THINK_CLOSE_PATTERN.search(text)
    if first_close is not None and (first_open is None or first_close.start() < first_open.start()):
        spans.append((0, first_close.end()))
    spans.extend(match.span() for match in THINK_BLOCK_PATTERN.finditer(text))
    return spans


def _strip_char_span(text: str, start: int, end: int) -> tuple[int, int] | None:
    start = max(0, start)
    end = min(len(text), max(start, end))
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return (start, end) if end > start else None


def _subtract_blocked_spans(
    text: str,
    spans: list[tuple[int, int]],
    blocked_spans: list[tuple[int, int]] | None,
) -> list[tuple[int, int]]:
    if not blocked_spans:
        return spans

    cleaned: list[tuple[int, int]] = []
    for start, end in spans:
        segments = [(start, end)]
        for block_start, block_end in blocked_spans:
            next_segments: list[tuple[int, int]] = []
            for segment_start, segment_end in segments:
                if block_end <= segment_start or block_start >= segment_end:
                    next_segments.append((segment_start, segment_end))
                    continue
                if segment_start < block_start:
                    next_segments.append((segment_start, block_start))
                if block_end < segment_end:
                    next_segments.append((block_end, segment_end))
            segments = next_segments
        for segment_start, segment_end in segments:
            stripped = _strip_char_span(text, segment_start, segment_end)
            if stripped is not None:
                cleaned.append(stripped)
    return cleaned


def _find_reasoning_content_spans(
    text: str,
    *,
    end: int | None = None,
    allow_plain_text: bool = True,
    blocked_spans: list[tuple[int, int]] | None = None,
) -> list[tuple[int, int]]:
    """Return generated reasoning/prose spans without think tags."""
    if not text:
        return []

    limit = len(text) if end is None else max(0, min(len(text), end))
    if limit <= 0:
        return []
    prefix = text[:limit]
    spans: list[tuple[int, int]] = []
    saw_think_markup = False

    first_open = _THINK_OPEN_PATTERN.search(prefix)
    first_close = _THINK_CLOSE_PATTERN.search(prefix)
    has_leading_close = first_close is not None and (first_open is None or first_close.start() < first_open.start())

    if has_leading_close or first_open is not None:
        # The real </think> is whichever close tag sits closest to the known
        # boundary (the action span, or end of text), not the first </think>
        # substring the model happens to type while describing the format.
        saw_think_markup = True
        content_start = first_open.end() if first_open is not None else 0
        close_matches = list(_THINK_CLOSE_PATTERN.finditer(prefix, content_start))
        content_end = close_matches[-1].start() if close_matches else len(prefix)
        span = _strip_char_span(prefix, content_start, content_end)
        if span is not None:
            spans.append(span)

    if allow_plain_text and not spans and not saw_think_markup:
        span = _strip_char_span(prefix, 0, limit)
        if span is not None:
            spans.append(span)

    return _subtract_blocked_spans(prefix, spans, blocked_spans)


def _find_generated_think_close_spans(text: str, *, end: int | None = None) -> list[tuple[int, int]]:
    """Return generated </think> delimiters, excluding opening <think> delimiters."""
    if not text:
        return []
    limit = len(text) if end is None else max(0, min(len(text), end))
    if limit <= 0:
        return []
    prefix = text[:limit]
    return [match.span() for match in _THINK_CLOSE_PATTERN.finditer(prefix)]


def _empty_mask_info() -> dict[str, Any]:
    return {
        "mode": "empty",
        "masked_tokens": 0,
        "masked_action_tokens": 0,
        "masked_thinking_tokens": 0,
        "masked_generated_think_close_tokens": 0,
        "thinking_tokens": 0,
        "think_block_tokens": 0,
        "output_tokens": 0,
        "has_action_span": False,
        "action_block_count": 0,
        "char_span_start": None,
        "char_span_end": None,
    }


def build_response_loss_mask(
    *,
    tokenizer: Any,
    token_ids: list[int],
    text: str,
    action_span: tuple[int, int] | None,
    action_block_pattern: re.Pattern[str],
    response_mask_mode: str | None,
) -> tuple[list[int], dict[str, Any]]:
    if not token_ids:
        return [], _empty_mask_info()

    response_mask_mode = normalize_response_mask_mode(response_mask_mode)
    token_spans = _token_char_spans(tokenizer, token_ids, text)
    action_block_count = count_action_blocks(text, action_block_pattern)
    action_mask = (
        _mask_from_token_char_spans(token_spans, [action_span])
        if action_span is not None
        else [0] * len(token_ids)
    )
    action_tokens = _count_mask(action_mask)

    reasoning_end = action_span[0] if action_span is not None else len(text)
    blocked_reasoning_spans = find_action_block_spans(text, action_block_pattern, end=reasoning_end)
    metric_thinking_content_spans = _find_reasoning_content_spans(
        text,
        end=reasoning_end,
        allow_plain_text=True,
        blocked_spans=blocked_reasoning_spans,
    )
    loss_thinking_content_spans = metric_thinking_content_spans if action_span is not None else []
    generated_think_close_spans = (
        _find_generated_think_close_spans(text, end=reasoning_end) if action_span is not None else []
    )
    reasoning_loss_spans = loss_thinking_content_spans + generated_think_close_spans
    reasoning_mask = (
        _mask_from_token_char_spans(token_spans, reasoning_loss_spans)
        if reasoning_loss_spans
        else [0] * len(token_ids)
    )
    thinking_content_mask = (
        _mask_from_token_char_spans(token_spans, metric_thinking_content_spans)
        if metric_thinking_content_spans
        else [0] * len(token_ids)
    )
    generated_think_close_mask = (
        _mask_from_token_char_spans(token_spans, generated_think_close_spans)
        if generated_think_close_spans
        else [0] * len(token_ids)
    )
    thinking_tokens = _count_mask(thinking_content_mask)
    masked_generated_think_close_tokens = _count_mask(generated_think_close_mask)
    think_block_mask = _mask_from_token_char_spans(token_spans, find_think_block_spans(text))
    think_block_tokens = _count_mask(think_block_mask)

    mask = list(action_mask) if action_mask is not None else [0] * len(token_ids)
    if response_mask_mode == RESPONSE_MASK_THINK_AND_ACTION and reasoning_mask is not None:
        mask = [
            1 if action_value or reasoning_value else 0
            for action_value, reasoning_value in zip(mask, reasoning_mask, strict=True)
        ]

    if any(mask):
        return mask, {
            "mode": (
                "action_block_span" if response_mask_mode == RESPONSE_MASK_ACTION else RESPONSE_MASK_THINK_AND_ACTION
            ),
            "masked_tokens": sum(mask),
            "masked_action_tokens": action_tokens,
            "masked_thinking_tokens": _count_mask(reasoning_mask)
            if response_mask_mode == RESPONSE_MASK_THINK_AND_ACTION
            else 0,
            "masked_generated_think_close_tokens": masked_generated_think_close_tokens
            if response_mask_mode == RESPONSE_MASK_THINK_AND_ACTION
            else 0,
            "thinking_tokens": thinking_tokens,
            "think_block_tokens": think_block_tokens,
            "output_tokens": len(token_ids),
            "has_action_span": action_span is not None,
            "action_block_count": action_block_count,
            "char_span_start": action_span[0] if action_span is not None else None,
            "char_span_end": action_span[1] if action_span is not None else None,
        }

    return mask, {
        "mode": "no_loss_no_valid_action",
        "masked_tokens": sum(mask),
        "masked_action_tokens": 0,
        "masked_thinking_tokens": 0,
        "masked_generated_think_close_tokens": 0,
        "thinking_tokens": thinking_tokens,
        "think_block_tokens": think_block_tokens,
        "output_tokens": len(token_ids),
        "has_action_span": False,
        "action_block_count": action_block_count,
        "char_span_start": None,
        "char_span_end": None,
    }


__all__ = [
    "RESPONSE_MASK_ACTION",
    "RESPONSE_MASK_THINK_AND_ACTION",
    "THINK_BLOCK_PATTERN",
    "build_response_loss_mask",
    "find_think_block_spans",
    "normalize_response_mask_mode",
]

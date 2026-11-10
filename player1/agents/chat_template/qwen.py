"""Shared Qwen chat-template selection for Player-1 model families."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from .qwen35 import qwen35_player1_chat_template_contract, qwen35_player1_chat_template_kwargs


QWEN38_CHAT_TEMPLATE_ID = "qwen3_8_official_preserved_thinking_low"
_QWEN38_TEMPLATE_MARKERS = (
    "reasoning_effort|default('xhigh')",
    "preserve_thinking is undefined or preserve_thinking is true",
    "Function calls MUST follow the specified format",
)
_THINK_ACTION_PATTERN = re.compile(r"\A<think>\s*(.*?)\s*</think>\s*(\S[\s\S]*)\Z", re.IGNORECASE | re.DOTALL)


def _qwen38_request_kwargs(base_kwargs: dict[str, Any] | None = None) -> dict[str, Any]:
    kwargs = dict(base_kwargs or {})
    configured_preserve_thinking = kwargs.get("preserve_thinking")
    if configured_preserve_thinking is not None and configured_preserve_thinking is not True:
        raise RuntimeError("Player-1 Qwen3.8 requires preserve_thinking=True")
    configured_reasoning_effort = kwargs.get("reasoning_effort")
    if configured_reasoning_effort is not None and configured_reasoning_effort != "low":
        raise RuntimeError("Player-1 Qwen3.8 requires reasoning_effort='low'")
    kwargs["preserve_thinking"] = True
    kwargs["reasoning_effort"] = "low"
    return kwargs


def _processing_chat_template(processing_class: Any) -> str:
    for owner in (processing_class, getattr(processing_class, "tokenizer", None)):
        template = getattr(owner, "chat_template", None)
        if isinstance(template, str) and template:
            return template
    raise RuntimeError("Qwen processing class does not expose a string chat_template")


def is_qwen38_chat_template(template: str) -> bool:
    """Return whether a model template exposes the Qwen3.8 reasoning contract."""

    return all(marker in template for marker in _QWEN38_TEMPLATE_MARKERS)


def qwen_player1_chat_template_kwargs(
    processing_class: Any,
    base_kwargs: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Select the exact Player-1 template contract for a loaded Qwen processor."""

    upstream_template = _processing_chat_template(processing_class)
    if not is_qwen38_chat_template(upstream_template):
        return qwen35_player1_chat_template_kwargs(processing_class, base_kwargs)

    kwargs = _qwen38_request_kwargs(base_kwargs)
    configured_template = kwargs.get("chat_template")
    if configured_template is not None and configured_template != upstream_template:
        raise RuntimeError("Player-1 refuses a conflicting Qwen3.8 chat_template")
    kwargs["chat_template"] = upstream_template
    return kwargs, {"id": QWEN38_CHAT_TEMPLATE_ID}


def qwen_player1_chat_template_contract(model: str) -> dict[str, str]:
    """Resolve the stable template identity for a served model name or path."""

    normalized = str(model or "").strip().lower().replace("_", ".")
    if "qwen3.8" in normalized:
        return {"id": QWEN38_CHAT_TEMPLATE_ID}
    return qwen35_player1_chat_template_contract()


def qwen_player1_request_chat_template_kwargs(
    model: str,
    base_kwargs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return server-side template kwargs for a served Qwen model."""

    if qwen_player1_chat_template_contract(model)["id"] == QWEN38_CHAT_TEMPLATE_ID:
        return _qwen38_request_kwargs(base_kwargs)
    return dict(base_kwargs or {})


def qwen_player1_prepare_messages(
    messages: Sequence[Mapping[str, Any]],
    chat_template_contract: Mapping[str, str],
) -> list[dict[str, Any]]:
    """Adapt trusted think/action history to Qwen3.8's structured reasoning field."""

    prepared = [dict(message) for message in messages]
    if chat_template_contract.get("id") != QWEN38_CHAT_TEMPLATE_ID:
        return prepared
    for message in prepared:
        content = message.get("content")
        if message.get("role") != "assistant" or not isinstance(content, str) or "reasoning_content" in message:
            continue
        match = _THINK_ACTION_PATTERN.fullmatch(content.strip())
        if match is None:
            continue
        message["reasoning_content"] = match.group(1).strip()
        message["content"] = match.group(2).strip()
    return prepared


__all__ = [
    "QWEN38_CHAT_TEMPLATE_ID",
    "is_qwen38_chat_template",
    "qwen_player1_chat_template_contract",
    "qwen_player1_chat_template_kwargs",
    "qwen_player1_prepare_messages",
    "qwen_player1_request_chat_template_kwargs",
]

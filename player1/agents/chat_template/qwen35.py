"""Qwen3.5 chat-template contract for Player-1 full-turn history context."""

from __future__ import annotations

from pathlib import Path
from typing import Any


QWEN35_CHAT_TEMPLATE_ID = "qwen3_5_player1_full_history"
_TEMPLATE_ROOT = Path(__file__).resolve().parent
QWEN35_PLAYER1_CHAT_TEMPLATE_PATH = _TEMPLATE_ROOT / f"{QWEN35_CHAT_TEMPLATE_ID}.jinja"
QWEN35_OFFICIAL_CHAT_TEMPLATE_PATH = _TEMPLATE_ROOT / "qwen3_5_official_chat_template.jinja"


def load_qwen35_player1_chat_template() -> str:
    """Load the fixed Player-1 Qwen3.5 full-history template."""

    template = QWEN35_PLAYER1_CHAT_TEMPLATE_PATH.read_text(encoding="utf-8")
    if "loop.index0 > ns.last_query_index or preserve_reasoning" not in template:
        raise RuntimeError("Player-1 Qwen3.5 template is missing full-history reasoning support")
    return template


def load_qwen35_official_chat_template() -> str:
    """Load the repository's fixed upstream Qwen3.5 comparison template."""

    return QWEN35_OFFICIAL_CHAT_TEMPLATE_PATH.read_text(encoding="utf-8")


def _processing_chat_template(processing_class: Any) -> str:
    for owner in (processing_class, getattr(processing_class, "tokenizer", None)):
        template = getattr(owner, "chat_template", None)
        if isinstance(template, str) and template:
            return template
    raise RuntimeError("Qwen3.5 processing class does not expose a string chat_template")


def qwen35_player1_chat_template_kwargs(
    processing_class: Any,
    base_kwargs: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Return the Player-1 template kwargs for a Qwen3.5 processing class."""

    _processing_chat_template(processing_class)

    template = load_qwen35_player1_chat_template()
    kwargs = dict(base_kwargs or {})
    configured_template = kwargs.get("chat_template")
    if configured_template is not None and configured_template != template:
        raise RuntimeError("Player-1 refuses a conflicting data.apply_chat_template_kwargs.chat_template")
    kwargs["chat_template"] = template
    return kwargs, {"id": QWEN35_CHAT_TEMPLATE_ID}


def qwen35_player1_chat_template_contract() -> dict[str, str]:
    """Return stable prompt-contract identity without loading a model."""

    load_qwen35_player1_chat_template()
    return {"id": QWEN35_CHAT_TEMPLATE_ID}


__all__ = [
    "QWEN35_CHAT_TEMPLATE_ID",
    "QWEN35_PLAYER1_CHAT_TEMPLATE_PATH",
    "QWEN35_OFFICIAL_CHAT_TEMPLATE_PATH",
    "load_qwen35_player1_chat_template",
    "load_qwen35_official_chat_template",
    "qwen35_player1_chat_template_contract",
    "qwen35_player1_chat_template_kwargs",
]

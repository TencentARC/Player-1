"""Public chat-template contracts for Player-1 model agents."""

from .qwen35 import (
    QWEN35_CHAT_TEMPLATE_ID,
    QWEN35_PLAYER1_CHAT_TEMPLATE_PATH,
    QWEN35_OFFICIAL_CHAT_TEMPLATE_PATH,
    load_qwen35_player1_chat_template,
    load_qwen35_official_chat_template,
    qwen35_player1_chat_template_contract,
    qwen35_player1_chat_template_kwargs,
)
from .qwen import (
    QWEN38_CHAT_TEMPLATE_ID,
    is_qwen38_chat_template,
    qwen_player1_chat_template_contract,
    qwen_player1_chat_template_kwargs,
    qwen_player1_prepare_messages,
    qwen_player1_request_chat_template_kwargs,
)

__all__ = [
    "QWEN35_CHAT_TEMPLATE_ID",
    "QWEN35_PLAYER1_CHAT_TEMPLATE_PATH",
    "QWEN35_OFFICIAL_CHAT_TEMPLATE_PATH",
    "load_qwen35_player1_chat_template",
    "load_qwen35_official_chat_template",
    "qwen35_player1_chat_template_contract",
    "qwen35_player1_chat_template_kwargs",
    "QWEN38_CHAT_TEMPLATE_ID",
    "is_qwen38_chat_template",
    "qwen_player1_chat_template_contract",
    "qwen_player1_chat_template_kwargs",
    "qwen_player1_prepare_messages",
    "qwen_player1_request_chat_template_kwargs",
]

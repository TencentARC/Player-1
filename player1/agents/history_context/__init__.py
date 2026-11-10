"""Public history-context selection and replay contract."""

from .policy import (
    COLLAPSED_HISTORY_CONTEXT_MODES,
    OMITTED_IMAGE_PLACEHOLDER,
    OMITTED_THINKING_PLACEHOLDER,
    HISTORY_CONTEXT_MESSAGE_METADATA_KEY,
    HISTORY_CONTEXT_MODE_A,
    HISTORY_CONTEXT_MODE_T,
    HISTORY_CONTEXT_MODE_T_A,
    HISTORY_CONTEXT_MODE_V_A,
    HISTORY_CONTEXT_MODE_V_T_A,
    HISTORY_CONTEXT_REPLAY_SOURCES,
    SUPPORTED_HISTORY_CONTEXT_MODES,
    build_history_context_metadata,
    canonicalize_think_action_output,
    render_canonical_think_action,
    require_history_context_mode,
    select_history_context_messages,
)

__all__ = [
    "COLLAPSED_HISTORY_CONTEXT_MODES",
    "OMITTED_IMAGE_PLACEHOLDER",
    "OMITTED_THINKING_PLACEHOLDER",
    "HISTORY_CONTEXT_MESSAGE_METADATA_KEY",
    "HISTORY_CONTEXT_MODE_A",
    "HISTORY_CONTEXT_MODE_T",
    "HISTORY_CONTEXT_MODE_T_A",
    "HISTORY_CONTEXT_MODE_V_A",
    "HISTORY_CONTEXT_MODE_V_T_A",
    "HISTORY_CONTEXT_REPLAY_SOURCES",
    "SUPPORTED_HISTORY_CONTEXT_MODES",
    "build_history_context_metadata",
    "canonicalize_think_action_output",
    "render_canonical_think_action",
    "require_history_context_mode",
    "select_history_context_messages",
]

"""Runtime utilities for GameWorld."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

import colorlog

from agents.mm_agents import BaseClient, build_config, create_client, load_model
from runtime.runtime_config import RuntimeConfig

LOGGER = logging.getLogger(__name__)

MODEL_LOG_LEVEL = 25
GAME_LOG_LEVEL = 26
TASK_LOG_LEVEL = 27
ENV_LOG_LEVEL = 28

_CUSTOM_LOG_LEVELS = {
    "model": MODEL_LOG_LEVEL,
    "game": GAME_LOG_LEVEL,
    "task": TASK_LOG_LEVEL,
    "env": ENV_LOG_LEVEL,
}

_LOG_COLORS = {
    "DEBUG": "cyan",
    "INFO": "white",
    "WARNING": "yellow",
    "ERROR": "red,bg_white",
    "CRITICAL": "red,bg_white",
    "MODEL": "blue",
    "GAME": "red",
    "TASK": "green",
    "ENV": "purple",
}


def _build_level_logger(level: int):
    def _log(self, message, *args, **kwargs):
        if self.isEnabledFor(level):
            self._log(level, message, args, **kwargs)

    return _log


def _install_custom_logger_methods() -> None:
    for method_name, level in _CUSTOM_LOG_LEVELS.items():
        logging.addLevelName(level, method_name.upper())
        if not hasattr(logging.Logger, method_name):
            setattr(logging.Logger, method_name, _build_level_logger(level))


def _build_stream_handler() -> logging.Handler:
    handler = logging.StreamHandler()
    handler.setFormatter(
        colorlog.ColoredFormatter(
            "%(log_color)s[%(asctime)s] %(levelname)s: %(message)s",
            log_colors=_LOG_COLORS,
        )
    )
    return handler


def setup_logging(level: int = logging.INFO) -> None:
    """Configure colorful logging with custom levels (MODEL, GAME, TASK, ENV)."""
    root_logger = logging.getLogger()
    if root_logger.handlers:
        root_logger.handlers.clear()
    root_logger.addHandler(_build_stream_handler())
    root_logger.setLevel(level)
    logging.getLogger("client").setLevel(logging.DEBUG)


def _validate_runtime_fields(
    runtime_config: RuntimeConfig,
    agent_ids: Sequence[str],
) -> None:
    expected = runtime_config.agent_count
    actual_counts = {
        "agent_ids": len(agent_ids),
        "model_ids": len(runtime_config.model_ids),
        "system_prompts": len(runtime_config.system_prompts),
        "enable_memory": len(runtime_config.enable_memory),
        "role_controls_maps": len(runtime_config.role_controls_maps),
        "semantic_controls_maps": len(runtime_config.semantic_controls_maps),
        "semantic_controls_specs": len(runtime_config.semantic_controls_specs),
    }
    mismatches = [
        f"{field}={count}"
        for field, count in actual_counts.items()
        if count != expected
    ]
    if mismatches:
        raise ValueError(
            f"RuntimeConfig.agent_count={expected} is inconsistent with runtime fields: "
            + ", ".join(mismatches)
        )


def _build_runtime_overrides(
    runtime_config: RuntimeConfig,
    idx: int,
) -> dict[str, Any]:
    overrides: dict[str, Any] = {
        "system_prompt": runtime_config.system_prompts[idx],
        "enable_memory": runtime_config.enable_memory[idx],
        "memory_rounds": runtime_config.memory_rounds,
        "memory_format": runtime_config.memory_format,
        "log_session_id": runtime_config.log_session_id,
    }
    if runtime_config.log_root:
        overrides["log_root"] = runtime_config.log_root
    return overrides


def _prepare_client_config(
    runtime_config: RuntimeConfig,
    idx: int,
    model_id: str,
    model_endpoint_override: str | None = None,
):
    model_profile = load_model(model_id)
    model_config = build_config(model_profile)
    if model_endpoint_override:
        model_config.endpoint = model_endpoint_override

    client_config = model_config.with_overrides(
        **_build_runtime_overrides(runtime_config, idx)
    )
    return model_profile, client_config


def build_agent_clients(
    runtime_config: RuntimeConfig,
    agent_ids: list[str],
    *,
    model_endpoint_override: str | None = None,
) -> list[BaseClient]:
    """Build clients for game agents (supports mixed model ids)."""
    _validate_runtime_fields(runtime_config, agent_ids)

    clients: list[BaseClient] = []

    for idx, model_id in enumerate(runtime_config.model_ids):
        model_profile, client_config = _prepare_client_config(
            runtime_config,
            idx,
            model_id,
            model_endpoint_override,
        )
        clients.append(
            create_client(
                model_profile,
                client_config,
                semantic_controls_specs=runtime_config.semantic_controls_specs[idx],
            )
        )

    return clients


_install_custom_logger_methods()

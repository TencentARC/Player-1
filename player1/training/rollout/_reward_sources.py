"""Stable episode reward source catalog shared by rollout configuration and scoring."""

from __future__ import annotations


EPISODE_REWARD_SOURCES: tuple[str, ...] = (
    "success",
    "dense",
    "task_metric",
    "normalized_task_metric",
    "primary",
    "normalized_primary",
    "env_episode",
    "normalized_env_episode",
    "game",
    "normalized_game",
    "best",
    "normalized_best",
)

import asyncio
import logging
import math
import os
import time
from collections.abc import Mapping
from typing import Any
from uuid import uuid4

import torch
from PIL import Image
from pydantic import ConfigDict
from verl.experimental.agent_loop.agent_loop import AgentLoopBase, AgentLoopMetrics, AgentLoopOutput
from verl.utils.profiler import simple_timer
from verl.utils.tokenizer.chat_template import initialize_system_prompt
from verl.workers.rollout.replica import TokenOutput

from player1.agents.actions import (
    ACTION_SPACE_MODE,
    inspect_unified_action_output,
    is_control_action_space_mode,
    require_action_space_mode,
)
from player1.agents.actions.parser import PlayerOneActionParser, require_action_format
from player1.agents.chat_template import qwen_player1_chat_template_kwargs
from player1.agents.episode_policy import PlayerOneEpisodePolicy
from player1.agents.history_context import (
    require_history_context_mode,
)
from player1.agents.prompting import render_action_prompt
from player1.agents.vision import prepare_agent_image
from player1.catalog import build_runtime_config
from player1.catalog.visual_perturbation import PERTURBATION_PROFILE_OPTIONS
from player1.environments.browser.game_env import GameEnv
from player1.runtime.contracts import ActionOutcome, classify_action_outcome
from player1.environments.browser.contracts import RuntimeHealthError
from player1.runtime.episode import (
    EpisodeController,
    EpisodeRequest,
    EpisodeTurn,
    GenerationEnvelope,
    thaw_episode_value,
)
from player1.runtime.evaluator import Evaluator
from player1.runtime.types import Agent

from ..metrics.rollout import (
    add_rollout_timing_metrics,
    annotate_rollout_retry_output,
    build_rollout_summary_and_reward_extra_info,
    build_rollout_timing_summary,
    rollout_timeout_phase_code,
)
from .config import PlayerOneAgentLoopConfig
from .history_sampling import episode_history_capacities
from .loss_masking import (
    RESPONSE_MASK_ACTION,
    RESPONSE_MASK_THINK_AND_ACTION,
    THINK_BLOCK_PATTERN,
    build_response_loss_mask,
    find_think_block_spans,
)
from .reward import (
    PlayerOneRewardComputer,
    aggregate_reward_component_totals,
    safe_float,
)


logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("VERL_LOGGING_LEVEL", "WARN"))


class PlayerOneRolloutTimeout(TimeoutError):
    def __init__(self, phase: str):
        self.phase = phase
        super().__init__(f"Player-1 rollout timed out while running {phase}")


class PlayerOneAgentLoopMetrics(AgentLoopMetrics):
    """verl timing metrics plus Player-1 rollout phase timings."""

    model_config = ConfigDict(extra="allow")


class PlayerOneAgentLoopOutput(AgentLoopOutput):
    metrics: PlayerOneAgentLoopMetrics

    def as_dict(self) -> dict[str, Any]:
        """Pack this exact-context turn's training target at its final trainable token."""

        output = super().as_dict()
        step_reward = self.extra_fields.get("step_reward")
        response_mask = output["response_mask"]
        if step_reward is not None and response_mask.numel() > 0:
            trainable_positions = torch.nonzero(response_mask, as_tuple=False).flatten()
            if trainable_positions.numel() > 0:
                rm_scores = torch.zeros_like(response_mask, dtype=torch.float32)
                rm_scores[int(trainable_positions[-1].item())] = float(step_reward)
                output["rm_scores"] = rm_scores
        return output


__all__ = [
    "RESPONSE_MASK_ACTION",
    "RESPONSE_MASK_THINK_AND_ACTION",
    "THINK_BLOCK_PATTERN",
    "PlayerOneActionParser",
    "PlayerOneAgentLoop",
]


class PlayerOneAgentLoop(AgentLoopBase):
    """Minimal browser-game loop for catalog-driven Player-1 rollouts."""


    def _initialize_player1_settings(self, settings: PlayerOneAgentLoopConfig) -> None:
        """Apply the complete validated Player-1-owned runtime configuration."""

        self.fallback_action_id = settings.fallback_action_id
        self.action_prompt_text = settings.action_prompt_text
        self.observe_remaining_turns = settings.observe_remaining_turns
        self.max_environment_steps = settings.max_environment_steps
        self.max_turn_tokens = settings.max_turn_tokens
        self.response_mask_mode = settings.response_mask_mode
        self.think_max_tokens = settings.think_max_tokens
        self.think_length_penalty = settings.think_length_penalty
        self.think_length_penalty_max = settings.think_length_penalty_max
        self._reward_computer = PlayerOneRewardComputer(settings.reward)
        self.format_retry_max = settings.format_retry_max
        self.valid_rollout_retry_max = settings.valid_rollout_retry_max
        self.rollout_timeout_s = (
            None
            if settings.rollout_timeout_s is None or float(settings.rollout_timeout_s) <= 0
            else float(settings.rollout_timeout_s)
        )
        self.rollout_close_timeout_s = float(settings.rollout_close_timeout_s)
        self.history_context_turns = settings.history_context_turns
        self.history_context_old_turns = settings.history_context_old_turns
        self.history_context_old_mode = settings.history_context_old_mode
        self.history_context_sampling = settings.history_context_sampling
        self.history_context_sampling_seed = settings.history_context_sampling_seed
        self.headless = settings.headless
        self.screenshot_max_height = settings.screenshot_max_height

    def __init__(
        self,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        processing_class = self.processor if self.processor is not None else self.tokenizer
        original_system_prompt = list(self.system_prompt)
        self.apply_chat_template_kwargs, self.qwen35_chat_template_contract = qwen_player1_chat_template_kwargs(
            processing_class,
            self.apply_chat_template_kwargs,
        )
        patched_system_prompt = initialize_system_prompt(processing_class, **self.apply_chat_template_kwargs)
        if patched_system_prompt != original_system_prompt:
            raise RuntimeError("Player-1 Qwen3.5 template changed the user-only system prompt contract")
        self.system_prompt = patched_system_prompt
        settings = PlayerOneAgentLoopConfig.from_trainer_config(self.config)
        self._initialize_player1_settings(settings)
        self._validate_native_multi_output_advantage_config()

    @staticmethod
    def _require_environment_metadata(extra_info: dict[str, Any]) -> tuple[str, str, str]:
        values: list[str] = []
        for field in ("environment_id", "joint_training_id", "preset_spec"):
            value = str(extra_info.get(field) or "").strip()
            if not value:
                raise ValueError(
                    f"Player-1 rollout row is missing extra_info.{field}; "
                    "all single- and multi-environment datasets must use JointTrainingConfig"
                )
            values.append(value)
        return values[0], values[1], values[2]

    @staticmethod
    def _resolve_history_context_mode(config: Any, extra_info: dict[str, Any]) -> str:
        """Resolve the profile-owned mode and reject stale dataset metadata."""

        profile_mode = require_history_context_mode(str(getattr(config, "history_context_mode", "") or ""))
        raw_row_mode = str(extra_info.get("history_context_mode") or "").strip()
        if not raw_row_mode:
            raise ValueError("Player-1 rollout row is missing extra_info.history_context_mode")
        row_mode = require_history_context_mode(raw_row_mode)
        if row_mode != profile_mode:
            raise ValueError(
                "Player-1 rollout row history-context metadata does not match its model profile: "
                f"extra_info.history_context_mode={row_mode!r}, "
                f"runtime_config.history_context_mode={profile_mode!r}"
            )
        return profile_mode

    @staticmethod
    def _resolve_action_contract(config: Any, extra_info: dict[str, Any]) -> tuple[str, str]:
        """Reject dataset rows generated for a different action contract."""

        profile_format = require_action_format(str(getattr(config, "action_format", "") or ""))
        profile_mode = require_action_space_mode(str(getattr(config, "action_space_mode", "") or ""))
        resolved: list[str] = []
        for field, profile_value, validator in (
            ("action_format", profile_format, require_action_format),
            ("action_space_mode", profile_mode, require_action_space_mode),
        ):
            raw_row_value = str(extra_info.get(field) or "").strip()
            if not raw_row_value:
                raise ValueError(
                    f"Player-1 rollout row is missing extra_info.{field}; "
                    "regenerate the dataset with the current model profile"
                )
            try:
                row_value = validator(raw_row_value)
            except ValueError as exc:
                raise ValueError(
                    f"Player-1 rollout row has invalid extra_info.{field}={raw_row_value!r}; "
                    "regenerate the dataset with the current model profile"
                ) from exc
            if row_value != profile_value:
                raise ValueError(
                    f"Player-1 rollout row {field} metadata does not match its model profile: "
                    f"extra_info.{field}={row_value!r}, runtime_config.{field}={profile_value!r}; "
                    "regenerate the dataset with the current model profile"
                )
            resolved.append(profile_value)
        return resolved[0], resolved[1]


    def _load_image(self, image_source: Any) -> Image.Image:
        return prepare_agent_image(image_source, max_height=self.screenshot_max_height)


    @staticmethod
    def _record_timing(
        timing: dict[str, float],
        phase: str,
        started_at: float,
        *,
        step_timing: dict[str, float] | None = None,
    ) -> float:
        elapsed = time.perf_counter() - started_at
        timing[phase] = timing.get(phase, 0.0) + elapsed
        if step_timing is not None:
            step_timing[phase] = step_timing.get(phase, 0.0) + elapsed
        return elapsed

    @staticmethod
    def _annotate_exception(exc: Exception, **fields: Any) -> None:
        for key, value in fields.items():
            if getattr(exc, key, None) is not None:
                continue
            try:
                setattr(exc, key, value)
            except Exception:  # noqa: BLE001
                return

    async def _await_rollout_phase(self, awaitable, *, phase: str, deadline_at: float | None):
        remaining_s = None if deadline_at is None else deadline_at - time.perf_counter()
        if deadline_at is None:
            try:
                result = await awaitable
            except Exception as exc:
                self._annotate_exception(exc, player1_rollout_phase=phase)
                raise
            return result

        if remaining_s <= 0:
            close = getattr(awaitable, "close", None)
            if callable(close):
                close()
            raise PlayerOneRolloutTimeout(phase)

        try:
            result = await asyncio.wait_for(awaitable, timeout=remaining_s)
        except TimeoutError as exc:
            raise PlayerOneRolloutTimeout(phase) from exc
        except Exception as exc:
            self._annotate_exception(exc, player1_rollout_phase=phase)
            raise
        return result

    async def _close_game_with_timeout(self, env: GameEnv, *, outcome: str) -> None:
        close_coro = env.close_game(outcome=outcome)
        try:
            if self.rollout_close_timeout_s <= 0:
                await close_coro
            else:
                await asyncio.wait_for(close_coro, timeout=self.rollout_close_timeout_s)
        except TimeoutError:
            logger.warning("Player-1 env close timed out after %.1fs", self.rollout_close_timeout_s)
        except Exception:
            logger.warning("Player-1 env close failed", exc_info=True)

    @staticmethod
    def _response_mask_has_loss(response_mask: list[int] | None) -> bool:
        return any(bool(value) for value in response_mask or [])

    def _uses_group_relative_advantage(self) -> bool:
        algorithm_config = self.config.get("algorithm", {})
        adv_estimator = algorithm_config.get("adv_estimator", "")
        return str(adv_estimator).strip().lower() == "grpo"

    def _uses_gae_advantage(self) -> bool:
        algorithm_config = self.config.get("algorithm", {})
        adv_estimator = algorithm_config.get("adv_estimator", "")
        return str(adv_estimator).strip().lower() == "gae"

    def _validate_native_multi_output_advantage_config(self) -> None:
        if not self._uses_gae_advantage():
            return

        algorithm_config = self.config.get("algorithm", {})
        gamma = float(algorithm_config.get("gamma", 1.0))
        lam = float(algorithm_config.get("lam", 1.0))
        if not math.isclose(gamma, 1.0) or not math.isclose(lam, 1.0):
            raise ValueError(
                "Player-1 exact-context multi-output PPO requires algorithm.gamma=1.0 and "
                "algorithm.lam=1.0 so per-turn return-to-go targets preserve full-trajectory GAE semantics."
            )
        if bool(algorithm_config.get("use_kl_in_reward", False)):
            raise ValueError(
                "Player-1 exact-context multi-output PPO does not support algorithm.use_kl_in_reward=True; "
                "use actor KL loss so future token-level KL rewards are not lost across output boundaries."
            )


    def _build_fallback_action(
        self,
        agent: Agent,
        *,
        action_space_mode: str = ACTION_SPACE_MODE,
    ) -> dict[str, Any]:
        fallback_id = self.fallback_action_id
        action_map = getattr(agent, "unified_action_space_map", None)
        action_space_mode = require_action_space_mode(action_space_mode)
        fallback_tools = [fallback_id]
        if fallback_id != "control":
            fallback_tools.append("control")
        for tool_name in fallback_tools:
            inspection = inspect_unified_action_output(
                {
                    "action_space_mode": action_space_mode,
                    "tool_calls": [{"tool_name": tool_name, "arguments": {}}],
                },
                action_map,
            )
            mapped_action = inspection.get("mapped_action")
            if inspection["is_valid"] and mapped_action:
                return mapped_action
        return {"type": "game_step_action", "id": fallback_id}

    def _build_malformed_action_response_mask(
        self,
        token_ids: list[int],
        *,
        action_mask_info: dict[str, Any] | None = None,
    ) -> tuple[list[int], dict[str, Any]]:
        """Train every generated token in a retained malformed response."""

        info = dict(action_mask_info or {})
        if not token_ids:
            info.update({"mode": "malformed_action_empty", "masked_tokens": 0, "malformed_action_tokens": 0})
            return [], info

        mask = [1] * len(token_ids)
        masked_tokens = len(token_ids)
        info.update(
            {
                "mode": "malformed_action_all_tokens",
                "masked_tokens": masked_tokens,
                "malformed_action_tokens": masked_tokens,
            }
        )
        return mask, info

    def _compute_think_length_penalty(self, thinking_tokens: float | None) -> float:
        """Penalty for one model response, capped per response instead of per rollout."""
        try:
            per_response_thinking_tokens = max(0, int(thinking_tokens or 0))
        except (TypeError, ValueError):
            per_response_thinking_tokens = 0
        think_overage = max(0, per_response_thinking_tokens - int(self.think_max_tokens or 0))
        if self.think_length_penalty <= 0.0 or think_overage <= 0:
            return 0.0
        return min(
            self.think_length_penalty_max,
            think_overage * self.think_length_penalty,
        )

    def _build_observation_message(
        self,
        *,
        image: Image.Image | None,
        remaining_action_turns: int,
    ) -> dict[str, Any]:
        if image is None:
            raise ValueError("PlayerOneAgentLoop requires a screenshot for every observation. No image was captured.")

        return {
            "role": "user",
            "content": [
                {"type": "image", "image": image},
                {
                    "type": "text",
                    "text": render_action_prompt(
                        self.action_prompt_text,
                        remaining_action_turns=remaining_action_turns if self.observe_remaining_turns else None,
                    ),
                },
            ],
        }


    @staticmethod
    def _reduce_history_context_capacities(
        *,
        primary_turns: int | None,
        old_turns: int | None,
        context_info: Mapping[str, Any],
    ) -> tuple[int | None, int] | None:
        """Drop the oldest collapsed slot first, then the oldest primary slot."""

        resolved_old_turns = old_turns
        if resolved_old_turns is None:
            resolved_old_turns = int(context_info.get("requested_old_history_context_turns", 0))
        if resolved_old_turns > 0:
            return primary_turns, resolved_old_turns - 1

        resolved_primary_turns = primary_turns
        if resolved_primary_turns is None:
            resolved_primary_turns = int(
                context_info.get(
                    "requested_primary_history_context_turns",
                    context_info["retained_history_context_turns"],
                )
            )
        if resolved_primary_turns > 0:
            return resolved_primary_turns - 1, 0
        return None

    async def _build_episode_generation_context(
        self,
        *,
        controller: EpisodeController,
        turn: EpisodeTurn,
        chat_template_tools: list[dict[str, Any]] | None,
    ) -> tuple[
        list[int],
        list[Image.Image],
        list[dict[str, Any]],
        dict[str, Any],
        EpisodeRequest,
    ]:
        """Render one controller-owned request, reducing only history on overflow."""

        current_history_context_turns = controller.history_context_turns
        current_history_context_old_turns = controller.history_context_old_turns
        while True:
            request = controller.build_request(
                turn,
                history_context_turns_override=current_history_context_turns,
                history_context_old_turns_override=current_history_context_old_turns,
            )
            history_context_messages = [thaw_episode_value(message) for message in request.messages]
            multi_modal_data = await self.process_vision_info(history_context_messages)
            history_context_images = list(multi_modal_data.get("images") or [])
            context_videos = list(multi_modal_data.get("videos") or [])
            if context_videos:
                raise NotImplementedError("PlayerOneAgentLoop currently supports image observations only.")
            try:
                history_context_prompt_ids = await self.apply_chat_template(
                    history_context_messages,
                    tools=chat_template_tools,
                    images=history_context_images,
                    videos=None,
                    mm_processor_kwargs=dict(getattr(self, "mm_processor_kwargs", {}) or {}),
                )
            except ValueError as exc:
                if "rollout.prompt_length" not in str(exc):
                    raise
                reduced_capacities = self._reduce_history_context_capacities(
                    primary_turns=current_history_context_turns,
                    old_turns=current_history_context_old_turns,
                    context_info=request.context_info,
                )
                if reduced_capacities is None:
                    raise
                current_history_context_turns, current_history_context_old_turns = reduced_capacities
                continue
            history_context_info = {
                **request.context_info,
                "chat_template_id": self.qwen35_chat_template_contract["id"],
                "history_context_prompt_tokens": len(history_context_prompt_ids),
                "history_context_image_count": len(history_context_images),
            }
            return (
                history_context_prompt_ids,
                history_context_images,
                history_context_messages,
                history_context_info,
                request,
            )

    def _build_training_turn_output(
        self,
        *,
        prompt_ids: list[int],
        response_ids: list[int],
        response_mask: list[int],
        response_logprobs: list[float] | None,
        routed_experts: Any,
        images: list[Image.Image],
        step_reward: float,
        metrics: dict[str, Any],
        extra_fields: dict[str, Any],
    ) -> PlayerOneAgentLoopOutput:
        """Build one on-policy sample from the exact context used for generation."""

        if len(response_ids) != len(response_mask):
            raise ValueError(
                f"response_ids and response_mask must align, got {len(response_ids)} and {len(response_mask)}"
            )
        if response_logprobs is not None and len(response_logprobs) != len(response_ids):
            raise ValueError(
                f"response_logprobs and response_ids must align, got {len(response_logprobs)} and {len(response_ids)}"
            )

        turn_extra_fields = dict(extra_fields)
        turn_extra_fields["step_reward"] = float(step_reward)
        turn_extra_fields["turn_scores"] = [float(step_reward)]
        return PlayerOneAgentLoopOutput(
            prompt_ids=list(prompt_ids),
            response_ids=list(response_ids),
            response_mask=list(response_mask),
            response_logprobs=list(response_logprobs) if response_logprobs is not None else None,
            routed_experts=routed_experts,
            multi_modal_data={"images": list(images)} if images else {},
            mm_processor_kwargs=dict(getattr(self, "mm_processor_kwargs", {}) or {}),
            reward_score=float(step_reward),
            num_turns=1,
            metrics=PlayerOneAgentLoopMetrics(**metrics),
            extra_fields=turn_extra_fields,
        )

    @staticmethod
    def _compute_turn_training_targets(
        *,
        dense_turn_scores: list[float],
        episode_reward_mode: bool,
        group_relative_advantage: bool,
        gae_advantage: bool,
        episode_reward_score: float,
    ) -> list[float]:
        """Map environment rewards to native multi-output trainer targets."""

        if not dense_turn_scores:
            return []
        if group_relative_advantage:
            targets = [0.0] * len(dense_turn_scores)
            targets[-1] = float(episode_reward_score)
            return targets
        if gae_advantage:
            if episode_reward_mode:
                return [float(episode_reward_score)] * len(dense_turn_scores)
            targets = [0.0] * len(dense_turn_scores)
            return_to_go = 0.0
            for index in range(len(dense_turn_scores) - 1, -1, -1):
                return_to_go += float(dense_turn_scores[index])
                targets[index] = return_to_go
            return targets
        if episode_reward_mode:
            targets = [0.0] * len(dense_turn_scores)
            targets[-1] = float(episode_reward_score)
            return targets
        return [float(score) for score in dense_turn_scores]

    @staticmethod
    def _select_trainable_turns(
        *,
        turn_outputs: list[PlayerOneAgentLoopOutput],
        immediate_turn_scores: list[float],
        training_turn_targets: list[float],
        terminal_reward_target: float | None,
    ) -> tuple[list[PlayerOneAgentLoopOutput], list[float], list[float]]:
        """Filter zero-loss rows without recomputing trajectory-level reward targets."""

        if len(immediate_turn_scores) != len(turn_outputs) or len(training_turn_targets) != len(turn_outputs):
            raise RuntimeError(
                "Player-1 per-turn outputs, immediate rewards, and training targets diverged before filtering: "
                f"{len(turn_outputs)} outputs vs {len(immediate_turn_scores)} rewards vs "
                f"{len(training_turn_targets)} targets"
            )

        trainable_indices = [
            index
            for index, turn_output in enumerate(turn_outputs)
            if PlayerOneAgentLoop._response_mask_has_loss(turn_output.response_mask)
        ]
        trainable_outputs = [turn_outputs[index] for index in trainable_indices]
        trainable_immediate_scores = [immediate_turn_scores[index] for index in trainable_indices]
        trainable_targets = [training_turn_targets[index] for index in trainable_indices]
        if terminal_reward_target is not None and trainable_targets:
            trainable_targets[-1] = float(terminal_reward_target)
        return trainable_outputs, trainable_immediate_scores, trainable_targets

    @staticmethod
    def _finalize_training_turn_outputs(
        *,
        turn_outputs: list[PlayerOneAgentLoopOutput],
        immediate_turn_scores: list[float],
        training_turn_targets: list[float],
        episode_reward_score: float,
        final_metrics: dict[str, Any],
        final_extra_fields: dict[str, Any],
        retained_environment_turn_count: int | None = None,
    ) -> list[PlayerOneAgentLoopOutput]:
        if not turn_outputs:
            return []
        if len(immediate_turn_scores) != len(turn_outputs) or len(training_turn_targets) != len(turn_outputs):
            raise RuntimeError(
                "Player-1 per-turn outputs, immediate rewards, and training targets diverged: "
                f"{len(turn_outputs)} outputs vs {len(immediate_turn_scores)} rewards vs "
                f"{len(training_turn_targets)} targets"
            )

        trajectory_trainable_tokens = sum(
            sum(bool(token) for token in turn_output.response_mask) for turn_output in turn_outputs
        )
        if trajectory_trainable_tokens <= 0:
            raise RuntimeError("Player-1 finalized a trajectory without trainable response tokens")

        for turn_output, immediate_reward, training_target in zip(
            turn_outputs, immediate_turn_scores, training_turn_targets, strict=True,
        ):
            turn_output.reward_score = training_target
            turn_output.extra_fields["immediate_step_reward"] = immediate_reward
            turn_output.extra_fields["step_reward"] = training_target
            turn_output.extra_fields["turn_scores"] = [immediate_reward]

        final_output = turn_outputs[-1]
        final_output.num_turns = (
            len(turn_outputs) if retained_environment_turn_count is None else int(retained_environment_turn_count)
        )
        final_immediate_reward = immediate_turn_scores[-1]
        final_training_target = training_turn_targets[-1]
        final_output.reward_score = float(episode_reward_score)
        final_output.metrics = PlayerOneAgentLoopMetrics(**final_metrics)
        final_output.extra_fields.update(final_extra_fields)
        final_output.extra_fields["training_turn_indices"] = [
            int(turn_output.extra_fields.get("step_index", index)) for index, turn_output in enumerate(turn_outputs)
        ]
        final_output.extra_fields["training_turn_targets"] = [float(target) for target in training_turn_targets]
        final_output.extra_fields["training_turn_masked_tokens"] = [
            sum(bool(token) for token in turn_output.response_mask) for turn_output in turn_outputs
        ]
        final_output.extra_fields["immediate_step_reward"] = final_immediate_reward
        final_output.extra_fields["step_reward"] = final_training_target
        return turn_outputs

    async def _append_user_observation(
        self,
        *,
        env: GameEnv,
        messages: list[dict[str, Any]],
        step_index: int,
        max_steps: int,
        timing: dict[str, float] | None = None,
        step_timing: dict[str, float] | None = None,
        deadline_at: float | None = None,
    ) -> Image.Image:
        if self.processor is None:
            raise ValueError(
                "PlayerOneAgentLoop requires a vision-language model with a processor. "
                "Use a checkpoint such as Qwen3.5-9B, or Qwen3-VL-2B-Instruct."
            )
        phase_started_at = time.perf_counter()
        screenshot_bytes = await self._await_rollout_phase(
            env.capture_screenshot(),
            phase="capture_screenshot",
            deadline_at=deadline_at,
        )
        if timing is not None:
            self._record_timing(
                timing,
                "capture_screenshot_s",
                phase_started_at,
                step_timing=step_timing,
            )
        screenshot = self._load_image(screenshot_bytes)
        messages.append(self._build_observation_message(
            image=screenshot,
            remaining_action_turns=max_steps - step_index,
        ))
        return screenshot

    async def run(self, sampling_params: dict[str, Any], **kwargs) -> list[AgentLoopOutput]:
        return await self._run_with_retries(sampling_params, **kwargs)


    async def _run_with_retries(self, sampling_params: dict[str, Any], **kwargs) -> list[AgentLoopOutput]:
        retry_max = self.valid_rollout_retry_max
        max_attempts = retry_max + 1
        invalid_attempt_count = 0

        for rollout_attempt_index in range(max_attempts):
            try:
                output = await self._run_single_rollout_attempt(
                    sampling_params,
                    rollout_attempt_index=rollout_attempt_index,
                    **kwargs,
                )
            except RuntimeHealthError as exc:
                if (
                    rollout_attempt_index >= retry_max
                    or getattr(exc, "player1_rollout_phase", None) != "env_start"
                ):
                    raise
                logger.warning(
                    "Player-1 startup health check failed; retrying with a fresh browser context (%d/%d)",
                    rollout_attempt_index + 1,
                    retry_max,
                )
                continue
            if output:
                annotate_rollout_retry_output(
                    output[-1],
                    rollout_attempt_index=rollout_attempt_index,
                    rollout_attempt_count=rollout_attempt_index + 1,
                    invalid_rollout_attempt_count=invalid_attempt_count,
                )
                return output
            invalid_attempt_count += 1

        raise RuntimeError(
            "Player-1 failed to produce a valid rollout with any trainable action tokens "
            f"after {max_attempts} attempt(s)."
        )

    async def _run_single_rollout_attempt(
        self,
        sampling_params: dict[str, Any],
        *,
        rollout_attempt_index: int = 0,
        **kwargs,
    ) -> list[AgentLoopOutput]:
        rollout_started_at = time.perf_counter()
        deadline_at = None if self.rollout_timeout_s is None else rollout_started_at + float(self.rollout_timeout_s)
        timeout_phase: str | None = None
        rollout_timing: dict[str, float] = {}
        messages = list(kwargs["raw_prompt"])
        extra_info = dict(kwargs.get("extra_info") or {})
        environment_id, joint_training_id, preset_spec = self._require_environment_metadata(extra_info)
        rollout_phase = "train"

        metrics: dict[str, Any] = {}
        generated_assistant_turns = 0
        reset_count = 0
        format_retry_count = 0
        no_valid_action_count = 0
        rollout_invalid_reason: str | None = None
        step_records: list[dict[str, Any]] = []
        turn_outputs: list[PlayerOneAgentLoopOutput] = []
        extra_fields: dict[str, Any] = {
            "turn_scores": [],
            "tool_rewards": [],
            "environment_id": environment_id,
            "joint_training_id": joint_training_id,
        }
        request_id = uuid4().hex
        task_succeeded = False

        config = build_runtime_config(
            preset_spec, in_context_example_variant=extra_info.get("in_context_example_variant", "original")
        )
        action_format, action_space_mode = self._resolve_action_contract(config, extra_info)
        history_context_mode = self._resolve_history_context_mode(config, extra_info)
        action_parser = PlayerOneActionParser(
            action_format,
            action_space_mode=action_space_mode,
            runtime_tool_specs=config.unified_action_space_specs,
        )
        chat_template_tools = action_parser.chat_template_tools()
        extra_fields["action_format"] = action_format
        extra_fields["action_space_mode"] = action_space_mode
        extra_fields["history_context_mode"] = history_context_mode
        random_seed = extra_info.get("random_seed")
        if random_seed is not None:
            config.random_seed = int(random_seed)
        visual_perturbation_mode = extra_info.get("visual_perturbation_mode")
        if visual_perturbation_mode:
            extra_fields["visual_perturbation_id"] = str(extra_info["visual_perturbation_id"])
            extra_fields["visual_perturbation_mode"] = str(visual_perturbation_mode)
        for profile_field in PERTURBATION_PROFILE_OPTIONS.values():
            profile = extra_info.get(profile_field)
            if profile is None or str(profile).strip() == "":
                continue
            normalized_profile = str(profile).strip().lower()
            if normalized_profile != "perturbed":
                raise ValueError(
                    f"Unsupported rollout {profile_field}={profile!r}; expected 'perturbed' or null"
                )
            config.game_api_options[profile_field] = normalized_profile
            extra_fields[profile_field] = normalized_profile

        agent = Agent(
            agent_id="player",
            controls=config.role_controls,
            unified_action_space_map=config.unified_action_space_map,
        )
        episode_policy = PlayerOneEpisodePolicy(
            history_context_mode=history_context_mode,
            history_context_old_mode=self.history_context_old_mode,
            action_parser=action_parser,
            unified_action_space_map=agent.unified_action_space_map,
            fallback_action=self._build_fallback_action(
                agent,
                action_space_mode=action_space_mode,
            ),
            observation_builder=lambda observation: observation,
        )
        episode_history_turns, episode_history_old_turns = episode_history_capacities(
            mode=self.history_context_sampling,
            recent=self.history_context_turns,
            old=self.history_context_old_turns,
            seed=self.history_context_sampling_seed,
            episode=kwargs,
        )
        if self.history_context_sampling != "fixed" and rollout_phase == "train":
            logger.info(
                "[game-gym-history] uid=%s session=%s global_step=%s recent=%s old=%s sampling=%s",
                kwargs.get("uid"), kwargs.get("session_id"), kwargs.get("global_steps"),
                episode_history_turns, episode_history_old_turns, self.history_context_sampling,
            )
        episode_controller = EpisodeController(
            episode_policy,
            history_context_turns=episode_history_turns,
            history_context_old_turns=episode_history_old_turns,
        )
        episode_controller.reset(messages)
        evaluator = Evaluator(config)
        env = GameEnv(config=config, headless=self.headless)

        max_steps = self.max_environment_steps or config.max_steps or 1
        current_state: dict[str, Any] | None = None
        current_state_summary = "(no game state)"
        env_paused = False
        lease_outcome = "ok"
        action_outcome: ActionOutcome | None = None

        try:
            phase_started_at = time.perf_counter()
            await self._await_rollout_phase(env.start(), phase="env_start", deadline_at=deadline_at)
            self._record_timing(rollout_timing, "env_start_s", phase_started_at)
            phase_started_at = time.perf_counter()
            captured_state = await self._await_rollout_phase(
                env.capture_state(),
                phase="state_capture",
                deadline_at=deadline_at,
            )
            self._record_timing(rollout_timing, "state_capture_s", phase_started_at)
            if captured_state is not None:
                current_state = captured_state
                current_state_summary = env.summarize_state(current_state)

            for step_index in range(max_steps):
                action_outcome = None
                step_timing: dict[str, float] = {}
                observation_summary = current_state_summary
                if env.pause_during_inference and not env_paused:
                    await self._await_rollout_phase(env.pause_game(), phase="pause_game", deadline_at=deadline_at)
                    env_paused = True

                observation_buffer: list[dict[str, Any]] = []
                observation_image = await self._append_user_observation(
                    env=env,
                    messages=observation_buffer,
                    step_index=step_index,
                    max_steps=max_steps,
                    timing=rollout_timing,
                    step_timing=step_timing,
                    deadline_at=deadline_at,
                )
                if len(observation_buffer) != 1:
                    raise RuntimeError("Player-1 observation capture did not produce exactly one user message")
                episode_turn = episode_controller.open_turn(observation_buffer[0])

                step_sampling_params = dict(sampling_params)
                if self.max_turn_tokens is not None:
                    current_max_tokens = step_sampling_params.get("max_tokens")
                    current_max_new_tokens = step_sampling_params.get("max_new_tokens")
                    if current_max_tokens is not None:
                        step_sampling_params["max_tokens"] = min(int(current_max_tokens), self.max_turn_tokens)
                    elif current_max_new_tokens is not None:
                        step_sampling_params["max_new_tokens"] = min(int(current_max_new_tokens), self.max_turn_tokens)
                    else:
                        step_sampling_params["max_tokens"] = self.max_turn_tokens
                if int(step_sampling_params.get("max_tokens", step_sampling_params.get("max_new_tokens", 2)) or 0) > 0:
                    step_sampling_params["min_tokens"] = max(2, int(step_sampling_params.get("min_tokens", 0) or 0))
                generation_token_limit = int(
                    step_sampling_params.get("max_tokens", step_sampling_params.get("max_new_tokens", 0)) or 0
                )

                phase_started_at = time.perf_counter()
                (
                    history_context_prompt_ids,
                    history_context_images,
                    history_context_messages,
                    history_context_info,
                    episode_request,
                ) = await self._await_rollout_phase(
                    self._build_episode_generation_context(
                        controller=episode_controller,
                        turn=episode_turn,
                        chat_template_tools=chat_template_tools,
                    ),
                    phase="build_generation_context",
                    deadline_at=deadline_at,
                )
                self._record_timing(
                    rollout_timing,
                    "build_generation_context_s",
                    phase_started_at,
                    step_timing=step_timing,
                )
                history_context_tracking = {
                    field: int(history_context_info[field])
                    for field in (
                        "requested_history_context_turns",
                        "retained_history_context_turns",
                        "dropped_history_context_turns",
                    )
                }
                for field in (
                    "requested_primary_history_context_turns",
                    "retained_primary_history_context_turns",
                    "dropped_primary_history_context_turns",
                    "requested_old_history_context_turns",
                    "retained_old_history_context_turns",
                    "dropped_old_history_context_turns",
                ):
                    if field in history_context_info:
                        history_context_tracking[field] = int(history_context_info[field])

                format_retry_attempts_for_step = 0
                step_malformed_action_penalty = 0.0
                max_format_attempts = self.format_retry_max + 1

                for format_attempt_index in range(max_format_attempts):
                    phase_started_at = time.perf_counter()
                    with simple_timer("generate_sequences", metrics):
                        output: TokenOutput = await self._await_rollout_phase(
                            self.server_manager.generate(
                                request_id=request_id,
                                prompt_ids=history_context_prompt_ids,
                                sampling_params=step_sampling_params,
                                image_data=history_context_images,
                                video_data=None,
                                mm_processor_kwargs=dict(getattr(self, "mm_processor_kwargs", {}) or {}),
                            ),
                            phase="llm_generate",
                            deadline_at=deadline_at,
                        )
                    generated_assistant_turns += 1
                    self._record_timing(
                        rollout_timing,
                        "llm_generate_s",
                        phase_started_at,
                        step_timing=step_timing,
                    )

                    if metrics.get("num_preempted") is None:
                        metrics["num_preempted"] = output.num_preempted if output.num_preempted is not None else -1
                    else:
                        metrics["num_preempted"] += output.num_preempted if output.num_preempted is not None else 0

                    token_ids = output.token_ids
                    decoded_output = await self.loop.run_in_executor(
                        None,
                        lambda token_ids=token_ids: self.tokenizer.decode(token_ids, skip_special_tokens=True),
                    )

                    action_response_mask, action_mask_info = build_response_loss_mask(
                        tokenizer=self.tokenizer,
                        token_ids=token_ids,
                        text=decoded_output,
                        action_span=action_parser.find_selected_action_span(decoded_output),
                        action_block_pattern=action_parser.action_block_pattern,
                        response_mask_mode=self.response_mask_mode,
                    )
                    action_mask_info["reached_generation_limit"] = (
                        generation_token_limit > 0 and len(token_ids) >= generation_token_limit
                    )
                    action_mask_info["format_retry_attempt_index"] = format_attempt_index
                    action_mask_info["format_retry_attempts_before_valid"] = format_retry_attempts_for_step

                    episode_proposal = episode_controller.propose(
                        episode_request,
                        GenerationEnvelope(
                            text=decoded_output,
                            finish_reason=("length" if action_mask_info["reached_generation_limit"] else None),
                            metadata={
                                "reached_generation_limit": action_mask_info["reached_generation_limit"],
                            },
                        ),
                    )
                    proposal_draft = episode_proposal.draft
                    parsed_payload = (
                        None
                        if proposal_draft.parsed_payload is None
                        else thaw_episode_value(proposal_draft.parsed_payload)
                    )
                    missing_action = parsed_payload is None
                    action_block_count = int(proposal_draft.evidence["action_block_count"])
                    action_mask_info["multiple_control_block_count"] = 0.0
                    action_mask_info["action_call_count"] = float(action_block_count)
                    action_mask_info["dual_channel_frame_count"] = (
                        1.0
                        if (
                            is_control_action_space_mode(action_space_mode)
                            and isinstance(parsed_payload, dict)
                            and len(parsed_payload.get("tool_calls") or []) == 2
                        )
                        else 0.0
                    )

                    action_truncated = bool(proposal_draft.evidence["reached_generation_limit"] and missing_action)
                    thinking_tokens = int(action_mask_info.get("thinking_tokens", 0) or 0)
                    think_length_penalty = self._compute_think_length_penalty(thinking_tokens)
                    think_block_count = len(find_think_block_spans(decoded_output))

                    if not proposal_draft.model_action_valid:
                        if missing_action and action_block_count == 0:
                            no_valid_action_count += 1


                        if format_attempt_index + 1 < max_format_attempts:
                            format_retry_count += 1
                            format_retry_attempts_for_step += 1
                            continue

                        action_response_mask, action_mask_info = self._build_malformed_action_response_mask(
                            token_ids,
                            action_mask_info=action_mask_info,
                        )

                        step_malformed_action_penalty = self._reward_computer.config.malformed_action_penalty

                    if output.extra_fields:
                        extra_fields.update(output.extra_fields)
                    break

                chosen_action = thaw_episode_value(proposal_draft.requested_action)
                previous_state = current_state
                virtual_time_action = False
                if not isinstance(previous_state, dict):
                    raise TypeError("Player-1 cannot step without a structured source state")
                if not isinstance(chosen_action, dict):
                    raise TypeError("Player-1 cannot step without a structured action")
                if env_paused:
                    virtual_time_action = await self._await_rollout_phase(
                        env.action_uses_virtual_time(chosen_action),
                        phase="action_uses_virtual_time",
                        deadline_at=deadline_at,
                    )
                if env_paused and not virtual_time_action:
                    await self._await_rollout_phase(env.resume_game(), phase="resume_game", deadline_at=deadline_at)
                    env_paused = False

                phase_started_at = time.perf_counter()
                try:
                    runtime_step_payload: dict[str, Any] = await self._await_rollout_phase(
                        env.execute_runtime_step(
                            chosen_action,
                            pause_around_virtual_time=env_paused and virtual_time_action,
                            observation_size=observation_image.size,
                        ),
                        phase="runtime_step",
                        deadline_at=deadline_at,
                    )
                except Exception as exc:
                    rejected_outcome = classify_action_outcome(
                        parse_valid=proposal_draft.model_action_valid,
                        parse_reason=proposal_draft.invalid_reason,
                        fallback_used=proposal_draft.fallback_used,
                        fallback_reason=proposal_draft.invalid_reason,
                        model_action=parsed_payload,
                        requested_action=chosen_action,
                        runtime_step_result=None,
                        runtime_error=exc,
                        before_state=previous_state,
                        after_state=None,
                    ).to_dict()
                    self._annotate_exception(exc, player1_action_outcome=rejected_outcome)
                    raise
                self._record_timing(
                    rollout_timing,
                    "runtime_step_s",
                    phase_started_at,
                    step_timing=step_timing,
                )
                current_state = env.get_step_state(runtime_step_payload)
                current_state_summary = env.summarize_state(current_state)
                action_outcome = classify_action_outcome(
                    parse_valid=proposal_draft.model_action_valid,
                    parse_reason=proposal_draft.invalid_reason,
                    fallback_used=proposal_draft.fallback_used,
                    fallback_reason=proposal_draft.invalid_reason,
                    model_action=parsed_payload,
                    requested_action=chosen_action,
                    runtime_step_result=runtime_step_payload,
                    runtime_error=None,
                    before_state=previous_state,
                    after_state=current_state,
                )
                if env.pause_during_inference and not env_paused:
                    await self._await_rollout_phase(env.pause_game(), phase="pause_game", deadline_at=deadline_at)
                    env_paused = True

                agent.step_index += 1
                phase_started_at = time.perf_counter()
                eval_result = await self._await_rollout_phase(
                    evaluator.evaluate(agent, current_state),
                    phase="evaluate_task",
                    deadline_at=deadline_at,
                )
                if eval_result and eval_result.should_stop and not eval_result.should_reset:
                    eval_result = await self._await_rollout_phase(
                        evaluator.summarize(agent, current_state),
                        phase="summarize_task",
                        deadline_at=deadline_at,
                    )
                self._record_timing(
                    rollout_timing,
                    "evaluate_task_s",
                    phase_started_at,
                    step_timing=step_timing,
                )

                task_metric_best = safe_float(agent.eval_metrics.get("score_best"))
                game_score_best = self._reward_computer.extract_episode_game_score(current_state, config=config)
                terminal_failed = self._reward_computer.did_fail_terminal(
                    eval_result=eval_result,
                    state=current_state,
                )
                step_reward, step_reward_components = self._reward_computer.compute_step_reward(
                    config=config,
                    prev_state=previous_state,
                    state=current_state,
                    terminal_failed=terminal_failed,
                    think_length_penalty=think_length_penalty,
                    malformed_action_penalty=step_malformed_action_penalty,
                )
                step_reward_components.update(
                    {
                        "thinking_tokens": float(thinking_tokens),
                        "think_block_tokens": float(action_mask_info.get("think_block_tokens", 0) or 0),
                        "think_block_count": float(think_block_count),
                        "action_tokens": float(action_mask_info.get("masked_action_tokens", 0) or 0),
                        "output_tokens": float(action_mask_info.get("output_tokens", len(token_ids)) or 0),
                        "action_truncated": 1.0 if action_truncated else 0.0,
                        "format_retry_attempts": float(format_retry_attempts_for_step),
                        "malformed_action": 1.0 if (not proposal_draft.model_action_valid) else 0.0,
                        "malformed_action_tokens": float(action_mask_info.get("malformed_action_tokens", 0) or 0),
                    }
                )
                action_outcome_payload = action_outcome.to_dict()
                episode_controller.commit_execution(episode_proposal, action_outcome)
                messages = list(episode_controller.ledger_messages)
                extra_fields["turn_scores"].append(step_reward)
                step_records.append(
                    {
                        "step": agent.step_index,
                        "action_format": action_format,
                        "action_space_mode": action_space_mode,
                        "model_output": decoded_output,
                        "parsed_action": parsed_payload,
                        "chosen_action": chosen_action,
                        "virtual_time_action": virtual_time_action,
                        "invalid_reason": proposal_draft.invalid_reason,
                        "has_valid_action": proposal_draft.model_action_valid,
                        "retained_malformed_action": (not proposal_draft.model_action_valid),
                        "executed_fallback_action": action_outcome.provenance.source == "fallback",
                        "fallback_action_id": proposal_draft.fallback_tool_name,
                        "action_outcome": action_outcome_payload,
                        "task_status": eval_result.status if eval_result else None,
                        "stop_reason": eval_result.stop_reason if eval_result else None,
                        "task_metric_best": task_metric_best,
                        "game_score_best": game_score_best,
                        "step_reward": step_reward,
                        "reward_components": step_reward_components,
                        "action_mask_mode": action_mask_info["mode"],
                        "response_mask_mode": self.response_mask_mode,
                        "masked_tokens": action_mask_info["masked_tokens"],
                        "masked_action_tokens": action_mask_info["masked_action_tokens"],
                        "masked_thinking_tokens": action_mask_info["masked_thinking_tokens"],
                        "thinking_tokens": thinking_tokens,
                        "think_block_tokens": action_mask_info["think_block_tokens"],
                        "output_tokens": action_mask_info["output_tokens"],
                        "multiple_control_block_count": action_mask_info["multiple_control_block_count"],
                        "action_call_count": action_mask_info["action_call_count"],
                        "dual_channel_frame_count": action_mask_info["dual_channel_frame_count"],
                        "think_length_penalty": think_length_penalty,
                        "think_block_count": think_block_count,
                        "malformed_action_penalty": step_malformed_action_penalty,
                        "action_truncated": action_truncated,
                        "format_retry_attempts": format_retry_attempts_for_step,
                        "reached_generation_limit": action_mask_info["reached_generation_limit"],
                        "history_context_prompt_tokens": history_context_info["history_context_prompt_tokens"],
                        "history_context_image_count": history_context_info["history_context_image_count"],
                        "chat_template_id": history_context_info["chat_template_id"],
                        "history_context_mode": history_context_info["history_context_mode"],
                        "history_context_old_mode": history_context_info.get("history_context_old_mode"),
                        "retained_history_context_turns": history_context_info["retained_history_context_turns"],
                        "dropped_history_context_turns": history_context_info["dropped_history_context_turns"],
                        **history_context_tracking,
                        "observation_summary": observation_summary,
                        "reset_count": reset_count,
                        "timing": dict(sorted(step_timing.items())),
                    }
                )
                turn_outputs.append(
                    self._build_training_turn_output(
                        prompt_ids=history_context_prompt_ids,
                        response_ids=token_ids,
                        response_mask=action_response_mask,
                        response_logprobs=list(output.log_probs) if output.log_probs is not None else None,
                        routed_experts=output.routed_experts,
                        images=history_context_images,
                        step_reward=step_reward,
                        metrics={
                            "generate_sequences": float(step_timing.get("llm_generate_s", 0.0) or 0.0),
                            "tool_calls": float(step_timing.get("runtime_step_s", 0.0) or 0.0),
                            "num_preempted": output.num_preempted if output.num_preempted is not None else -1,
                            "rollout_total": float(sum(step_timing.values())),
                        },
                        extra_fields={
                            **output.extra_fields,
                            "environment_id": environment_id,
                            "joint_training_id": joint_training_id,
                            "action_format": action_format,
                            "action_space_mode": action_space_mode,
                            "history_context_mode": history_context_mode,
                            **history_context_tracking,
                            "step_index": step_index,
                            "reward_components": dict(step_reward_components),
                            "action_outcome": action_outcome_payload,
                        },
                    )
                )
                step_records[-1]["timing"] = dict(sorted(step_timing.items()))

                if not eval_result:
                    continue

                if eval_result.should_reset:
                    phase_started_at = time.perf_counter()
                    reset_ok = await self._await_rollout_phase(
                        env.reset_game(),
                        phase="reset_game",
                        deadline_at=deadline_at,
                    )
                    env_paused = False
                    self._record_timing(
                        rollout_timing,
                        "reset_game_s",
                        phase_started_at,
                        step_timing=step_timing,
                    )
                    if not reset_ok:
                        break
                    agent.eval_metrics = evaluator.reset_metrics(agent.eval_metrics)
                    reset_count += 1
                    if env.pause_during_inference:
                        await self._await_rollout_phase(
                            env.pause_game(),
                            phase="pause_game",
                            deadline_at=deadline_at,
                        )
                        env_paused = True
                    phase_started_at = time.perf_counter()
                    captured_state = await self._await_rollout_phase(
                        env.capture_state(),
                        phase="state_capture",
                        deadline_at=deadline_at,
                    )
                    self._record_timing(
                        rollout_timing,
                        "state_capture_s",
                        phase_started_at,
                        step_timing=step_timing,
                    )
                    current_state = captured_state
                    current_state_summary = env.summarize_state(current_state)
                    step_records[-1]["timing"] = dict(sorted(step_timing.items()))
                    continue

                if eval_result.should_stop:
                    task_succeeded = eval_result.status == "success"
                    break
        except PlayerOneRolloutTimeout as exc:
            lease_outcome = "timeout"
            timeout_phase = exc.phase
            rollout_invalid_reason = f"timeout:{timeout_phase}"
            timeout_elapsed_s = time.perf_counter() - rollout_started_at
            self._annotate_exception(
                exc,
                player1_rollout_phase=timeout_phase,
                player1_rollout_step_count=len(step_records),
                player1_generated_assistant_turns=generated_assistant_turns,
                rollout_request_id=request_id,
                history_context_mode=history_context_mode,
                player1_action_outcome=(
                    action_outcome.to_dict() if action_outcome is not None else None
                ),
            )
            metrics["rollout_timeout"] = 1.0
            metrics["rollout_timeout_phase_code"] = rollout_timeout_phase_code(timeout_phase)
            logger.warning(
                "Player-1 rollout timed out after %.1fs at phase=%s preset=%s attempt=%s",
                timeout_elapsed_s,
                timeout_phase,
                preset_spec,
                rollout_attempt_index,
            )
            raise
        except Exception as exc:
            lease_outcome = "error"
            self._annotate_exception(
                exc,
                player1_rollout_step_count=len(step_records),
                player1_generated_assistant_turns=generated_assistant_turns,
                rollout_request_id=request_id,
                history_context_mode=history_context_mode,
                player1_action_outcome=(
                    action_outcome.to_dict() if action_outcome is not None else None
                ),
            )
            raise
        finally:
            phase_started_at = time.perf_counter()
            await self._close_game_with_timeout(env, outcome=lease_outcome)
            self._record_timing(rollout_timing, "env_close_s", phase_started_at)

        reward_component_totals = aggregate_reward_component_totals(step_records)
        dense_turn_scores = list(extra_fields["turn_scores"])
        reward_score, reward_components = self._reward_computer.compute_reward_score(
            config=config,
            task_succeeded=task_succeeded,
            eval_metrics=agent.eval_metrics,
            state=current_state,
            turn_scores=dense_turn_scores,
            reward_component_totals=reward_component_totals,
        )
        reward_config = self._reward_computer.config
        episode_reward_mode = reward_config.reward_mode == "episode"
        if episode_reward_mode:
            extra_fields["dense_turn_scores"] = dense_turn_scores
            extra_fields["turn_scores"] = []
        rollout_summary, reward_extra_info = build_rollout_summary_and_reward_extra_info(
            step_records=step_records,
            reward_score=reward_score,
            reward_components=reward_components,
            dense_turn_scores=dense_turn_scores,
            format_retry_count=format_retry_count,
            no_valid_action_count=no_valid_action_count,
            timeout_phase=timeout_phase,
        )
        metrics.setdefault("rollout_timeout", rollout_summary["rollout_timeout"])
        metrics.setdefault("rollout_timeout_phase_code", rollout_summary["rollout_timeout_phase_code"])
        rollout_total_elapsed_s = time.perf_counter() - rollout_started_at
        rollout_timing_summary = build_rollout_timing_summary(
            timing=rollout_timing,
            step_records=step_records,
            total_elapsed_s=rollout_total_elapsed_s,
            generated_turns=generated_assistant_turns,
        )
        add_rollout_timing_metrics(
            metrics,
            timing=rollout_timing,
            timing_summary=rollout_timing_summary,
        )
        extra_fields.update(
            {
                "reward_extra_info": reward_extra_info,
                "step_records": step_records,
                "rollout_timing": rollout_timing_summary,
                "rollout_summary": rollout_summary,
                "rollout_invalid_reason": rollout_invalid_reason,
                "rollout_timeout_phase": timeout_phase,
                "final_eval_metrics": dict(agent.eval_metrics),
                "final_state_summary": current_state_summary,
                "history_context_turns": episode_history_turns,
                "history_context_mode": history_context_mode,
                "history_context_old_turns": episode_history_old_turns,
                "history_context_old_mode": self.history_context_old_mode,
                "action_format": action_format,
                "action_space_mode": action_space_mode,
                "response_mask_mode": self.response_mask_mode,
                "think_max_tokens": self.think_max_tokens,
                "think_length_penalty": self.think_length_penalty,
                "think_length_penalty_max": self.think_length_penalty_max,
                "malformed_action_penalty": reward_config.malformed_action_penalty,
                "fallback_action_id": self.fallback_action_id,
                "rescale_reward": reward_config.rescale_reward,
                "reward_mode": reward_config.reward_mode,
                "episode_reward_source": reward_config.episode_reward_source,
                "episode_reward_target": reward_config.episode_reward_target,
                "episode_reward_clip": reward_config.episode_reward_clip,
            }
        )

        retained_environment_turn_count = len(turn_outputs)
        aligned_dense_scores = dense_turn_scores
        if len(aligned_dense_scores) != len(turn_outputs):
            raise RuntimeError(
                "Player-1 per-turn outputs and dense rewards diverged before filtering: "
                f"{len(turn_outputs)} outputs vs {len(aligned_dense_scores)} rewards"
            )
        group_relative_advantage = self._uses_group_relative_advantage()
        gae_advantage = self._uses_gae_advantage()
        training_targets = self._compute_turn_training_targets(
            dense_turn_scores=aligned_dense_scores,
            episode_reward_mode=episode_reward_mode,
            group_relative_advantage=group_relative_advantage,
            gae_advantage=gae_advantage,
            episode_reward_score=reward_score,
        )
        terminal_reward_target = (
            reward_score
            if group_relative_advantage or (episode_reward_mode and not gae_advantage)
            else None
        )
        turn_outputs, trainable_immediate_scores, trainable_targets = self._select_trainable_turns(
            turn_outputs=turn_outputs,
            immediate_turn_scores=aligned_dense_scores,
            training_turn_targets=training_targets,
            terminal_reward_target=terminal_reward_target,
        )
        if not turn_outputs:
            return []

        return self._finalize_training_turn_outputs(
            turn_outputs=turn_outputs,
            immediate_turn_scores=trainable_immediate_scores,
            training_turn_targets=trainable_targets,
            episode_reward_score=reward_score,
            final_metrics=metrics,
            final_extra_fields=extra_fields,
            retained_environment_turn_count=retained_environment_turn_count,
        )

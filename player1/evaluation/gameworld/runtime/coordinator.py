"""Coordinator loop for agents, browser environment, and evaluation."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from agents.harness.semantic_controls import (
    inspect_semantic_controls_output,
)
from tools.runs import RuntimeLogger

from .env import GameEnv
from .evaluator import Evaluator
from .game_agent import ActionPayload, Agent

LOGGER = logging.getLogger(__name__)


class Coordinator:
    """Coordinates agents, environment, and evaluation in the main loop."""

    def __init__(
        self,
        env: GameEnv,
        agents: list[Agent],
        evaluator: Evaluator | None = None,
    ):
        if not agents:
            raise ValueError("Coordinator requires at least one agent.")

        self.env = env
        self.agents = agents
        self.evaluator = evaluator
        self._stop_event = asyncio.Event()
        self.agent_loggers: dict[str, RuntimeLogger] = {}
        self._evaluation_agent_id = self.agents[0].agent_id
        self._control_frame_index = 0
        self._controlled_real_time_ms = 0.0
        self._controlled_gameplay_time_ms = 0.0
        self._init_agent_loggers()

    @staticmethod
    def _build_runtime_logger(agent: Agent, env: GameEnv) -> RuntimeLogger:
        client = agent.client
        return RuntimeLogger(
            log_dir=client.config.log_dir,
            session_id=client.config.log_session_id,
            game_name=env.config.game_id,
            model_name=client.config.model,
            agent_id=agent.agent_id,
            session_root=getattr(client.config, "log_root", None),
            memory_screenshot_mode=getattr(
                client.config, "memory_screenshot_mode", "path"
            ),
        )

    def _init_agent_loggers(self) -> None:
        for agent in self.agents:
            self.agent_loggers[agent.agent_id] = self._build_runtime_logger(
                agent, self.env
            )

    def _log_model_interaction(
        self,
        agent: Agent,
        agent_logger: RuntimeLogger | None,
    ) -> dict[str, Any] | None:
        trace = agent.client.pop_logged_interaction()
        if agent_logger:
            agent_logger.log_interaction_from_trace(trace)
        return trace

    @staticmethod
    def _count_proposed_actions(action: ActionPayload) -> int:
        return len(Coordinator._collect_proposed_actions(action))

    @staticmethod
    def _collect_proposed_actions(action: ActionPayload) -> list[Any]:
        if isinstance(action, list):
            return list(action) or [None]

        if isinstance(action, dict):
            return [action]

        return [action]

    def _build_action_validity_record(
        self,
        agent: Agent,
        raw_action: ActionPayload,
        resolved_action: ActionPayload,
        trace: dict[str, Any] | None,
        semantic_inspection: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        trace = trace or {}
        executor = self.env._get_executor(agent)

        if agent.agent_type == "general":
            proposed_tool_call = trace.get("tool_call")
            semantic = semantic_inspection or inspect_semantic_controls_output(
                proposed_tool_call, agent.semantic_controls_map
            )
            low_level = executor.inspect_action(
                resolved_action if isinstance(resolved_action, dict) else None
            )
            is_valid = bool(semantic.get("is_valid")) and bool(
                low_level.get("is_valid")
            )
            invalid_kind = None
            reason = "valid"
            if not semantic.get("is_valid"):
                invalid_kind = semantic.get("invalid_kind")
                reason = str(semantic.get("reason") or "invalid_semantic_action")
            elif not low_level.get("is_valid"):
                invalid_kind = low_level.get("invalid_kind")
                reason = str(low_level.get("reason") or "invalid_low_level_action")

            return {
                "agent_type": agent.agent_type,
                "is_valid": is_valid,
                "reason": reason,
                "invalid_kind": invalid_kind,
                "proposed_action_count": 1,
                "valid_action_count": 1 if is_valid else 0,
                "raw_action": raw_action,
                "raw_tool_call": proposed_tool_call,
                "resolved_action": resolved_action,
                "normalized_action": low_level.get("normalized_action"),
                "semantic_control_id": semantic.get("control_id"),
            }

        proposed_count = self._count_proposed_actions(raw_action)
        if trace.get("error"):
            return {
                "agent_type": agent.agent_type,
                "is_valid": False,
                "reason": "client_parse_error",
                "invalid_kind": "no_function_call",
                "proposed_action_count": proposed_count,
                "valid_action_count": 0,
                "raw_action": raw_action,
                "resolved_action": resolved_action,
                "normalized_action": None,
            }

        if proposed_count != 1:
            return {
                "agent_type": agent.agent_type,
                "is_valid": False,
                "reason": "action_batch_not_allowed",
                "invalid_kind": "out_of_space",
                "proposed_action_count": proposed_count,
                "valid_action_count": 0,
                "raw_action": raw_action,
                "resolved_action": resolved_action,
                "normalized_action": None,
            }

        proposed_actions = self._collect_proposed_actions(raw_action)
        inspections = [executor.inspect_action(item) for item in proposed_actions]
        valid_count = sum(1 for item in inspections if item.get("is_valid"))
        first_invalid = next(
            (item for item in inspections if not item.get("is_valid")), None
        )
        is_valid = valid_count == proposed_count
        return {
            "agent_type": agent.agent_type,
            "is_valid": is_valid,
            "reason": (
                "valid"
                if is_valid
                else str((first_invalid or {}).get("reason") or "invalid_action")
            ),
            "invalid_kind": None
            if is_valid
            else (first_invalid or {}).get("invalid_kind"),
            "proposed_action_count": proposed_count,
            "valid_action_count": valid_count,
            "raw_action": raw_action,
            "resolved_action": resolved_action,
            "normalized_action": (
                inspections[0].get("normalized_action") if inspections else None
            ),
        }

    async def _capture_state(self) -> tuple[dict[str, Any] | None, str]:
        snapshot = await self.env.capture_state()
        if not snapshot:
            return None, "(no game state)"
        return snapshot.state, snapshot.summary

    @staticmethod
    def _extract_completion_progress(state: dict[str, Any] | None) -> object:
        if not isinstance(state, dict):
            return None
        game_state = state.get("game_state")
        if not isinstance(game_state, dict):
            return None
        return game_state.get("completion_progress")

    @staticmethod
    def _extract_game_status(state: dict[str, Any] | None) -> object:
        if not isinstance(state, dict):
            return None
        return state.get("status")

    def _build_evaluation_payload(
        self,
        agent: Agent,
        result: Any,
        game_status: object,
        progress: object,
        game_completion_progress: object,
        frame_timing: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "interaction_id": agent.step_index,
            "step": agent.step_index,
            "max_steps": self.env.config.max_steps,
            "benchmark_release": self.env.config.benchmark_release,
            "task_status": result.status,
            "game_status": game_status,
            "summary": result.summary,
            "should_stop": result.should_stop,
            "should_reset": result.should_reset,
            "stop_reason": result.stop_reason,
            "finalized": result.finalized,
            "progress": progress,
            "game_completion_progress": game_completion_progress,
            "frame_timing": frame_timing,
            "metrics": dict(agent.eval_metrics),
        }

    @staticmethod
    def _clock_number(clock: dict[str, float | bool], field: str) -> float:
        value = clock.get(field)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise RuntimeError(f"Gameplay clock missing numeric {field}: {clock!r}")
        return float(value)

    def _build_frame_timing(
        self,
        *,
        agent: Agent,
        start_clock: dict[str, float | bool],
        end_clock: dict[str, float | bool],
        action_timing: dict[str, float | str] | None,
        pause_during_inference: bool,
    ) -> dict[str, Any]:
        frame_real_time_ms = max(
            0.0,
            self._clock_number(end_clock, "active_real_time_ms")
            - self._clock_number(start_clock, "active_real_time_ms"),
        )
        frame_gameplay_time_ms = max(
            0.0,
            self._clock_number(end_clock, "gameplay_time_ms")
            - self._clock_number(start_clock, "gameplay_time_ms"),
        )
        self._control_frame_index += 1
        self._controlled_real_time_ms += frame_real_time_ms
        self._controlled_gameplay_time_ms += frame_gameplay_time_ms

        requested_duration_ms = (
            float(action_timing["requested_duration_ms"])
            if action_timing is not None
            else None
        )
        action_wall_time_ms = (
            float(action_timing["action_wall_time_ms"])
            if action_timing is not None
            else None
        )
        return {
            "frame_index": self._control_frame_index,
            "agent_step": agent.step_index + 1,
            "pause_during_inference": pause_during_inference,
            "speed_multiplier": self._clock_number(
                end_clock,
                "speed_multiplier",
            ),
            "requested_action_duration_ms": requested_duration_ms,
            "action_wall_time_ms": action_wall_time_ms,
            "action_duration_overshoot_ms": (
                round(action_wall_time_ms - requested_duration_ms, 3)
                if action_wall_time_ms is not None
                and requested_duration_ms is not None
                else None
            ),
            "frame_active_real_time_ms": round(frame_real_time_ms, 3),
            "frame_gameplay_time_ms": round(frame_gameplay_time_ms, 3),
            "cumulative_controlled_real_time_ms": round(
                self._controlled_real_time_ms,
                3,
            ),
            "cumulative_controlled_gameplay_time_ms": round(
                self._controlled_gameplay_time_ms,
                3,
            ),
            "browser_active_real_time_ms": round(
                self._clock_number(end_clock, "active_real_time_ms"),
                3,
            ),
            "browser_gameplay_time_ms": round(
                self._clock_number(end_clock, "gameplay_time_ms"),
                3,
            ),
        }

    async def _evaluate_step(
        self,
        agent: Agent,
        state: dict[str, Any] | None,
        agent_logger: RuntimeLogger | None,
        frame_timing: dict[str, Any],
    ):
        if not self.evaluator:
            return None
        if agent.agent_id != self._evaluation_agent_id:
            return None

        result = await self.evaluator.evaluate(agent, state)
        if result.should_stop and not result.should_reset:
            result.finalized = True

        progress = result.metrics.get("progress")
        game_completion_progress = self._extract_completion_progress(state)
        game_status = self._extract_game_status(state)
        evaluation_payload = self._build_evaluation_payload(
            agent,
            result,
            game_status,
            progress,
            game_completion_progress,
            frame_timing,
        )
        if agent_logger:
            agent_logger.log_task_evaluation(evaluation_payload)

        LOGGER.task(
            "Task eval (%s): step=%s/%s task_status=%s game_status=%s "
            "stop=%s reset=%s finalized=%s reason=%s progress=%s "
            "game_completion_progress=%s metrics=%s",
            agent.agent_id,
            agent.step_index,
            self.env.config.max_steps,
            result.status,
            game_status,
            result.should_stop,
            result.should_reset,
            result.finalized,
            result.stop_reason,
            progress,
            game_completion_progress,
            evaluation_payload["metrics"],
        )
        return result

    async def _handle_eval_controls(self, agent: Agent, result) -> None:
        if result and result.should_reset:
            reset_ok = await self.env.reset_game()
            if reset_ok:
                agent.eval_metrics = self.evaluator.reset_metrics(agent.eval_metrics)
                LOGGER.task(
                    "Task eval: auto-reset after fail; continuing at step=%s",
                    agent.step_index,
                )
            else:
                raise RuntimeError(
                    "Runtime environment failed to reset after a terminal episode "
                    f"at step={agent.step_index}"
                )
        if result and result.should_stop and result.stop_reason != "max_steps_exhausted":
            self._stop_event.set()

    async def _get_raw_action(self, agent: Agent) -> ActionPayload:
        screenshot_path = await self.env.capture_screenshot(agent.agent_id)
        return await asyncio.to_thread(agent.client.get_action, screenshot_path)

    def _resolve_action(
        self, agent: Agent, raw_action: ActionPayload
    ) -> tuple[ActionPayload, dict[str, Any] | None]:
        if agent.agent_type == "general":
            semantic = inspect_semantic_controls_output(
                raw_action if isinstance(raw_action, dict) else None,
                agent.semantic_controls_map,
            )
            action = (
                semantic.get("mapped_action")
                if semantic.get("is_valid")
                else raw_action
            )
            LOGGER.model(
                "Agent %s raw action %s -> semantic_controls mapped action: %s",
                agent.agent_id,
                raw_action,
                action,
            )
            return action, semantic

        LOGGER.model("Agent %s raw action %s", agent.agent_id, raw_action)
        return raw_action, None

    async def _run_agent_step(
        self, agent: Agent, agent_logger: RuntimeLogger | None
    ) -> None:
        pause_during_step = self.env.config.pause_during_inference
        if pause_during_step:
            await self.env.pause_game()

        raw_action = await self._get_raw_action(agent)
        trace = self._log_model_interaction(agent, agent_logger)
        action, semantic_inspection = self._resolve_action(agent, raw_action)
        action_validity = self._build_action_validity_record(
            agent,
            raw_action,
            action,
            trace,
            semantic_inspection,
        )
        if agent_logger:
            agent_logger.log_action_validity(action_validity)
        normalized_action = action_validity.get("normalized_action")

        action_timing: dict[str, float | str] | None = None
        if pause_during_step:
            start_clock = await self.env.resume_game()
            try:
                action_timing = await self.env.execute_action(
                    agent, normalized_action, already_normalized=True
                )
            finally:
                end_clock = await self.env.pause_game()
        else:
            start_clock = await self.env.read_gameplay_clock()
            action_timing = await self.env.execute_action(
                agent, normalized_action, already_normalized=True
            )
            end_clock = await self.env.read_gameplay_clock()

        frame_timing = self._build_frame_timing(
            agent=agent,
            start_clock=start_clock,
            end_clock=end_clock,
            action_timing=action_timing,
            pause_during_inference=pause_during_step,
        )

        # State capture, evaluation, logging, and the inter-step gap stay frozen.
        if agent_logger:
            agent_logger.log_executed_action(normalized_action)
            agent_logger.log_frame_timing(frame_timing)

        state, state_summary = await self._capture_state()
        if agent_logger:
            agent_logger.log_game_state(state)
        LOGGER.game("Game state: %s", state_summary)

        agent.step_index += 1
        result = await self._evaluate_step(
            agent,
            state,
            agent_logger,
            frame_timing,
        )
        await self._handle_eval_controls(agent, result)
        if agent_logger:
            agent_logger.finalize_step()

    async def _agent_loop(self) -> None:
        while not self._stop_event.is_set():
            for agent in self.agents:
                if self._stop_event.is_set():
                    return
                agent_logger = self.agent_loggers.get(agent.agent_id)
                try:
                    await self._run_agent_step(agent, agent_logger)
                except Exception as exc:
                    if agent_logger:
                        agent_logger.finalize_step()
                    LOGGER.exception("Agent %s loop error: %s", agent.agent_id, exc)
                    self._stop_event.set()
                    raise

                if self._stop_event.is_set():
                    return
            if self.evaluator and self.agents[0].step_index >= self.env.config.max_steps:
                self._stop_event.set()

    async def run(self) -> None:
        try:
            await self.env.start()
            await self._agent_loop()
        finally:
            for agent_logger in self.agent_loggers.values():
                agent_logger.finalize_step()
            await self.env.close_game()


__all__ = ["Coordinator"]

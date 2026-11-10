"""JSON-lines GameGym environment controller for vendored GameWorld.

The process owns GameWorld's browser, evaluator, pause/reset semantics, and
game assets.  It deliberately has no imports from the outer GameGym package.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import traceback
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping

from catalog.games._base import RoleControls
from env.game_launcher import GameLauncher
from env.runtime_pool import GameWorldBrowserPool
from runtime.env import GameEnv
from runtime.evaluator import Evaluator
from runtime.game_agent import Agent
from runtime.runtime_config import BENCHMARK_RELEASE, RuntimeConfig

from game_gym_control import GameGymControlExecutor


def _controls(payload: Mapping[str, Any]) -> RoleControls:
    return RoleControls(
        allowed_keys={str(key) for key in payload.get("allowed_keys", [])},
        hold_duration=float(payload.get("hold_duration", 0.1)),
        key_durations={str(key): float(value) for key, value in payload.get("key_durations", {}).items()},
        allow_clicks=bool(payload.get("allow_clicks", True)),
    )


class GameGymSession:
    def __init__(self, browser_pool: GameWorldBrowserPool) -> None:
        self.browser_pool = browser_pool
        self.env: GameEnv | None = None
        self.evaluator: Evaluator | None = None
        self.agents: list[Agent] = []
        self.executors: list[GameGymControlExecutor] = []
        self.role_cursor = 0
        self.decision_count = 0
        self.trial: dict[str, Any] = {}
        self.frame_index = 0
        self.controlled_real_time_ms = 0.0
        self.controlled_gameplay_time_ms = 0.0
        self.frame_timing: dict[str, Any] = {}

    def _require_env(self) -> GameEnv:
        if self.env is None:
            raise RuntimeError("GameWorld session is not started")
        return self.env

    async def _observation(self, *, evaluation: dict[str, Any] | None = None) -> dict[str, Any]:
        env = self._require_env()
        agent = self.agents[self.role_cursor]
        image_path = await env.capture_screenshot(agent.agent_id)
        return {
            "image_path": str(Path(image_path).resolve()),
            "role_index": self.role_cursor,
            "role_name": self.trial["roles"][self.role_cursor]["name"],
            "reward": float(bool(evaluation and evaluation.get("status") == "success")),
            "terminated": bool(evaluation and evaluation.get("should_stop")),
            "truncated": bool(evaluation and evaluation.get("stop_reason") == "max_steps_exhausted"),
            "evaluation": evaluation or {},
            "decision_count": self.decision_count,
            "runtime_reused": env.runtime_reused,
            "benchmark_release": str(self.trial["benchmark_release"]),
            "frame_timing": dict(self.frame_timing),
        }

    @staticmethod
    def _clock_value(clock: Mapping[str, Any], field: str) -> float:
        value = clock.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise RuntimeError(f"GameWorld gameplay clock is missing {field}: {clock!r}")
        return float(value)

    def _build_frame_timing(
        self,
        *,
        start_clock: Mapping[str, Any],
        end_clock: Mapping[str, Any],
        action_timing: Mapping[str, Any],
    ) -> dict[str, Any]:
        frame_real_time_ms = max(
            0.0,
            self._clock_value(end_clock, "active_real_time_ms")
            - self._clock_value(start_clock, "active_real_time_ms"),
        )
        frame_gameplay_time_ms = max(
            0.0,
            self._clock_value(end_clock, "gameplay_time_ms")
            - self._clock_value(start_clock, "gameplay_time_ms"),
        )
        self.frame_index += 1
        self.controlled_real_time_ms += frame_real_time_ms
        self.controlled_gameplay_time_ms += frame_gameplay_time_ms
        requested_duration_ms = float(action_timing["requested_duration_ms"])
        action_wall_time_ms = float(action_timing["action_wall_time_ms"])
        return {
            "frame_index": self.frame_index,
            "requested_action_duration_ms": requested_duration_ms,
            "action_wall_time_ms": action_wall_time_ms,
            "action_duration_overshoot_ms": round(
                action_wall_time_ms - requested_duration_ms,
                3,
            ),
            "frame_active_real_time_ms": round(frame_real_time_ms, 3),
            "frame_gameplay_time_ms": round(frame_gameplay_time_ms, 3),
            "cumulative_controlled_real_time_ms": round(self.controlled_real_time_ms, 3),
            "cumulative_controlled_gameplay_time_ms": round(
                self.controlled_gameplay_time_ms,
                3,
            ),
            "browser_active_real_time_ms": round(
                self._clock_value(end_clock, "active_real_time_ms"),
                3,
            ),
            "browser_gameplay_time_ms": round(
                self._clock_value(end_clock, "gameplay_time_ms"),
                3,
            ),
        }

    async def start(self, trial: Mapping[str, Any], *, port: int | None = None) -> dict[str, Any]:
        await self.close()
        self.trial = dict(trial)
        if self.trial.get("protocol") != "gameworld.game-gym.v1":
            raise ValueError("Unsupported GameWorld GameGym trial protocol")
        if self.trial.get("benchmark_release") != BENCHMARK_RELEASE:
            raise ValueError(
                "Unsupported GameWorld benchmark release: "
                f"{self.trial.get('benchmark_release')!r}"
            )
        roles = list(self.trial.get("roles") or [])
        if not roles:
            raise ValueError("GameWorld trial has no roles")
        role_controls = [_controls(role) for role in roles]
        games_root = str(os.environ.get("GAMEWORLD_GAMES_ROOT") or "").strip()
        if games_root:
            GameLauncher.FULL_LIBRARY_BASE_DIR = Path(games_root).expanduser().resolve()
        config = RuntimeConfig(
            url=self.trial.get("url"),
            speed_multiplier=float(self.trial.get("speed_multiplier", 1.0)),
            pause_during_inference=True,
            random_seed=int(self.trial.get("random_seed", 0)),
            width=int(self.trial.get("width", 1280)),
            height=int(self.trial.get("height", 720)),
            task_id=str(self.trial["task_id"]),
            game_id=str(self.trial["game_id"]),
            game_url_suffix=self.trial.get("game_url_suffix"),
            evaluator_config=dict(self.trial.get("evaluator_config") or {}),
            benchmark_release=BENCHMARK_RELEASE,
            max_steps=int(self.trial.get("max_steps", 400)),
            agent_count=len(roles),
            role_controls_maps=role_controls,
        )
        self.env = GameEnv(
            config,
            headless=True,
            port=port,
            browser_pool=self.browser_pool,
        )
        self.evaluator = Evaluator(config)
        self.agents = [
            Agent(
                agent_id=f"role_{index}_{role['name']}",
                agent_type="computer_use",
                client=None,  # type: ignore[arg-type]
                controls=role_controls[index],
            )
            for index, role in enumerate(roles)
        ]
        await self.env.start()
        await self.env.pause_game()
        manager = self.env.game_manager
        if manager is None or manager.page is None:
            raise RuntimeError("GameWorld browser page is unavailable after startup")
        self.executors = [GameGymControlExecutor(manager.page, controls) for controls in role_controls]
        await asyncio.gather(*(executor.validate_relative_pointer_contract() for executor in self.executors))
        self.role_cursor = 0
        self.decision_count = 0
        self.frame_index = 0
        self.controlled_real_time_ms = 0.0
        self.controlled_gameplay_time_ms = 0.0
        self.frame_timing = {}
        return await self._observation()

    async def step(self, action: Mapping[str, Any], *, role_index: int) -> dict[str, Any]:
        env = self._require_env()
        if role_index != self.role_cursor:
            raise ValueError(f"Expected GameWorld role_index={self.role_cursor}, got {role_index}")
        agent = self.agents[role_index]
        start_clock = await env.resume_game()
        try:
            action_timing = await self.executors[role_index].execute(action)
        finally:
            end_clock = await env.pause_game()
        self.frame_timing = self._build_frame_timing(
            start_clock=start_clock,
            end_clock=end_clock,
            action_timing=action_timing,
        )

        self.decision_count += 1
        evaluation_payload: dict[str, Any] = {}
        if role_index == 0:
            snapshot = await env.capture_state()
            agent.step_index += 1
            assert self.evaluator is not None
            result = await self.evaluator.evaluate(agent, snapshot.state if snapshot else None)
            if result.should_stop and not result.should_reset:
                result.finalized = True
            evaluation_payload = asdict(result)
            if result.should_reset:
                if not await env.reset_game():
                    raise RuntimeError("GameWorld game reset failed after terminal failure")
                agent.eval_metrics = self.evaluator.reset_metrics(agent.eval_metrics)

        if not evaluation_payload.get("should_stop"):
            self.role_cursor = (self.role_cursor + 1) % len(self.agents)
        return await self._observation(evaluation=evaluation_payload)

    async def close(self, *, reusable: bool = True) -> None:
        if self.env is not None:
            await self.env.close_game(reusable=reusable)
        self.env = None
        self.evaluator = None
        self.agents = []
        self.executors = []
        self.trial = {}
        self.frame_timing = {}


async def _run() -> None:
    browser_pool = GameWorldBrowserPool()
    session = GameGymSession(browser_pool)
    pool_closed = False
    try:
        for line in sys.stdin:
            shutdown_requested = False
            try:
                request = json.loads(line)
                op = request.get("op")
                if op == "start":
                    result = await session.start(request["trial"], port=request.get("port"))
                elif op == "step":
                    result = await session.step(request["action"], role_index=int(request["role_index"]))
                elif op == "close":
                    await session.close(reusable=bool(request.get("reusable", True)))
                    result = {}
                elif op == "shutdown":
                    await session.close()
                    await browser_pool.shutdown()
                    pool_closed = True
                    result = {}
                    shutdown_requested = True
                else:
                    raise ValueError(f"Unsupported GameWorld controller operation: {op!r}")
                response = {"ok": True, "result": result}
            except Exception as exc:  # noqa: BLE001
                try:
                    await session.close(reusable=False)
                except Exception as close_exc:  # noqa: BLE001
                    exc.add_note(f"GameWorld failed-session cleanup also failed: {close_exc}")
                response = {
                    "ok": False,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                }
            print(json.dumps(response, ensure_ascii=False, separators=(",", ":")), flush=True)
            if shutdown_requested:
                return
    finally:
        try:
            await session.close()
        finally:
            if not pool_closed:
                await browser_pool.shutdown()


if __name__ == "__main__":
    asyncio.run(_run())

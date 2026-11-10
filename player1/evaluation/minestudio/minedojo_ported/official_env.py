"""MineStudio execution boundary for the Programmatic MineDojo 1.16.5 port."""

from __future__ import annotations

import os
import random
import signal
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any, Callable, Self

import numpy as np
from PIL import Image

from player1.environments.minestudio.lifecycle import (
    DEFAULT_MINECRAFT_OPERATION_TIMEOUT_S,
    minecraft_operation_timeout,
    minecraft_reset_slot,
    require_minecraft_timeout,
    terminate_minecraft_instances,
)
from player1.environments.minestudio.readiness import RenderReadyTimeout
from player1.runtime.bootstrap import configure_runtime

from ..execution import (
    OfficialRuntimeConfig,
    acquire_worker_minecraft_simulator,
    configure_minerl_reset_gate,
    keep_minecraft_server_running_during_gui_actions,
    minecraft_simulator_was_reused,
    raise_for_minecraft_step_error,
    release_worker_minecraft_simulator,
)
from ..official_eval import OfficialActionAdapter, append_jsonl, pov_image, wait_for_official_render_ready
from .env_spec import MineDojoPortedEnvPlan, compile_env_plan, normalize_viewpoint
from .scorer import MineDojoPortedScore, MineDojoPortedScorer
from .trials import MineDojoPortedTrial

MINEDOJO_PORTED_OBS_SIZE = (224, 224)
MINEDOJO_PORTED_RENDER_SIZE = (640, 360)


def _set_instance_process_group_suspended(instance: Any, *, suspended: bool) -> None:
    pid = int(instance.minecraft_process.pid)
    process_group = os.getpgid(pid)
    if process_group != pid:
        raise RuntimeError(f"Minecraft launcher {pid} is not its process-group leader")
    os.killpg(process_group, signal.SIGSTOP if suspended else signal.SIGCONT)


@dataclass(frozen=True)
class MineDojoPortedStep:
    image: Image.Image
    reward: float
    terminated: bool
    truncated: bool
    info: dict[str, Any]
    evaluation: MineDojoPortedScore


class _MineDojoPortedSimulator:
    """Small callback-compatible facade around a task-specific MineRL EnvSpec."""

    def __init__(
        self,
        plan: MineDojoPortedEnvPlan,
        *,
        obs_size: tuple[int, int],
        render_size: tuple[int, int],
        viewpoint: str,
        operation_timeout_s: float,
        reset_slot_count: int | None = None,
        startup_event: Callable[[str], None] | None = None,
    ):
        from .env_spec import make_low_level_env

        self.plan = plan
        self.obs_size = tuple(obs_size)
        self.render_size = tuple(render_size)
        self.viewpoint = normalize_viewpoint(viewpoint)
        self.operation_timeout_s = require_minecraft_timeout(operation_timeout_s)
        self.reset_slot_count = reset_slot_count
        self.env = make_low_level_env(plan, resolution=self.render_size, viewpoint=self.viewpoint)
        self.callbacks: list[Any] = []
        self.obs: dict[str, Any] = {}
        self.info: dict[str, Any] = {}
        self._startup_event = startup_event

    def _operation(self, name: str, operation: Callable[[], Any]) -> Any:
        timeout_s = float(
            getattr(self, "operation_timeout_s", DEFAULT_MINECRAFT_OPERATION_TIMEOUT_S)
        )
        with minecraft_operation_timeout(timeout_s, operation=name):
            return operation()

    def _wrap_obs_info(self, obs: Any, info: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        """Expose the raw-observation hook used by shared readiness probing."""

        raw_obs = dict(obs or {})
        merged = dict(info or {})
        merged.update(raw_obs)
        frame = raw_obs.get("pov")
        if not isinstance(frame, np.ndarray):
            raise RuntimeError("MineDojo-ported MineRL EnvSpec did not return pov")
        resized = Image.fromarray(frame).resize(self.obs_size, resample=Image.Resampling.BILINEAR)
        wrapped = {"image": np.asarray(resized)}
        self.obs = wrapped
        self.info.update(merged)
        return wrapped, dict(self.info)

    def set_startup_event(self, startup_event: Callable[[str], None] | None) -> None:
        self._startup_event = startup_event

    def _resume_parked_instances(self) -> None:
        for instance in getattr(self.env, "instances", ()):
            if getattr(instance, "_player1_suspended", False):
                _set_instance_process_group_suspended(instance, suspended=False)
                instance._player1_suspended = False

    def reset(self) -> tuple[dict[str, Any], dict[str, Any]]:
        self.info = {}
        self._resume_parked_instances()
        if self._startup_event is not None:
            self._startup_event("low_level_reset_begin")
        with minecraft_reset_slot(getattr(self, "reset_slot_count", None)):
            obs = self._operation("MineDojo-ported reset", self.env.reset)
        if self._startup_event is not None:
            self._startup_event("low_level_reset_end")
        # Match the maintained MineStudio initialization boundary: let chunks
        # and entities load, then execute deterministic mob setup, then capture
        # the scorer baseline from the following observation.
        info: dict[str, Any] = {}
        for _ in range(20):
            obs, _reward, done, info = self._operation(
                "MineDojo-ported initial no-op step",
                lambda: self.env.step(self.env.action_space.no_op()),
            )
            if done:
                raise RuntimeError("MineDojo-ported environment ended during initial empty frames")
        for command in self.plan.initial_mob_commands():
            obs, _reward, done, info = self._operation(
                "MineDojo-ported initial command",
                lambda command=command: self.env.execute_cmd(command),
            )
            if done:
                raise RuntimeError("MineDojo-ported environment ended during initial mob setup")
            obs, _reward, done, info = self._operation(
                "MineDojo-ported command settle step",
                lambda: self.env.step(self.env.action_space.no_op()),
            )
            if done:
                raise RuntimeError("MineDojo-ported environment ended while settling initial mob setup")
        for _ in range(10):
            obs, _reward, done, info = self._operation(
                "MineDojo-ported post-setup settle step",
                lambda: self.env.step(self.env.action_space.no_op()),
            )
            if done:
                raise RuntimeError("MineDojo-ported environment ended during post-setup settle frames")
        if self._startup_event is not None:
            self._startup_event("settle_end")
        return self._wrap_obs_info(obs, info)

    def step(self, action: Mapping[str, Any]) -> tuple[dict[str, Any], float, bool, bool, dict[str, Any]]:
        obs, reward, done, info = self._operation(
            "MineDojo-ported policy step",
            lambda: self.env.step(dict(action)),
        )
        wrapped, merged = self._wrap_obs_info(obs, info)
        return wrapped, float(reward or 0.0), bool(done), bool(done), merged

    def noop_action(self) -> dict[str, Any]:
        return self.env.action_space.no_op()

    def park(self) -> None:
        """End the active mission while retaining its Minecraft JVM."""

        instances = tuple(self.env.instances)
        for instance in reversed(instances):
            self._operation(
                "MineDojo-ported mission park",
                lambda instance=instance: self.env._TO_MOVE_quit_current_episode(instance),  # noqa: SLF001
            )
        suspended = []
        try:
            for instance in instances:
                _set_instance_process_group_suspended(instance, suspended=True)
                instance._player1_suspended = True
                suspended.append(instance)
        except Exception:
            for instance in suspended:
                _set_instance_process_group_suspended(instance, suspended=False)
                instance._player1_suspended = False
            raise

    def close(self) -> None:
        self._resume_parked_instances()
        self.env.close()

    def force_close(self) -> None:
        """Kill only the Minecraft process groups owned by this simulator."""

        instances = tuple(getattr(self.env, "instances", ()))
        terminate_minecraft_instances(instances)
        self.env.instances = []
        self.callbacks = []


class MineDojoPortedEnvironment:
    """One synchronous MineDojo-ported rollout using the Player-1 KBM bridge."""

    def __init__(
        self,
        trial: MineDojoPortedTrial,
        *,
        runtime_config: OfficialRuntimeConfig,
        obs_size: tuple[int, int] = MINEDOJO_PORTED_OBS_SIZE,
        render_size: tuple[int, int] = MINEDOJO_PORTED_RENDER_SIZE,
        agent_image_short_edge: int | None = None,
        viewpoint: str = "first",
        action_adapter: OfficialActionAdapter | None = None,
        startup_log: Path | None = None,
    ):
        self.trial = trial
        self.runtime_config = runtime_config
        self.obs_size = tuple(obs_size)
        self.render_size = tuple(render_size)
        if agent_image_short_edge is not None and (
            isinstance(agent_image_short_edge, bool)
            or not isinstance(agent_image_short_edge, int)
            or agent_image_short_edge <= 0
        ):
            raise ValueError("agent_image_short_edge must be a positive integer or None")
        self.agent_image_short_edge = agent_image_short_edge
        self.viewpoint = normalize_viewpoint(viewpoint)
        self._action_adapter = action_adapter or OfficialActionAdapter(visible_game_size=self.render_size)
        plan_task = {
            **trial.task,
            "world_seed": trial.world_seed,
            "task_rng_seed": trial.task_rng_seed,
            "max_decisions": trial.max_decisions,
        }
        self.plan = compile_env_plan(plan_task)
        if self.plan.max_decisions != trial.max_decisions:
            raise RuntimeError("MineDojo-ported EnvSpec plan horizon disagrees with the trial ledger")
        self.scorer = MineDojoPortedScorer(trial.task)
        self._env: Any | None = None
        self._obs: dict[str, Any] = {}
        self._info: dict[str, Any] = {}
        self._evaluation: MineDojoPortedScore | None = None
        self._render_readiness: dict[str, Any] | None = None
        self._reusable = True
        self._runtime_reused = False
        self._startup_log = startup_log.expanduser().resolve() if startup_log is not None else None
        self._startup_started_at = time.perf_counter()
        self._startup_last_stage: str | None = None
        self._simulator_key = ("minedojo_ported", self.obs_size, self.render_size, self.viewpoint)
        self.decisions = 0

    def _startup_event(self, stage: str, **details: Any) -> None:
        self._startup_last_stage = stage
        if self._startup_log is None:
            return
        group_index = os.environ.get("MINESTUDIO_CONTROL_GROUP_INDEX")
        payload = {
            "schema_version": 1,
            "stage": stage,
            "rollout_id": self.trial.rollout_id,
            "task_id": self.trial.task_id,
            "pid": os.getpid(),
            "worker_slot": os.environ.get("MINESTUDIO_WORKER_SLOT"),
            "control_group_index": int(group_index) if group_index is not None else None,
            "minecraft_display_mode": "shared_control_group_xvfb",
            "display": os.environ.get("DISPLAY"),
            "elapsed_s": time.perf_counter() - self._startup_started_at,
            "wall_time_ns": time.time_ns(),
            **details,
        }
        append_jsonl(self._startup_log, payload)
        if stage in {
            "environment_start_begin",
            "low_level_reset_end",
            "settle_end",
            "publish_end",
            "start_complete",
            "failure",
        }:
            print(
                "[minestudio-startup] "
                f"rollout={self.trial.rollout_id} group={group_index or 'none'} "
                f"stage={stage} elapsed_s={payload['elapsed_s']:.3f}",
                flush=True,
            )

    def _record(self, obs: Any, info: Any) -> None:
        self._obs = dict(obs or {})
        self._info = dict(info or {})
        self._info.update(self._obs)

    def _step_result(self, *, simulator_reward: Any, terminated: Any, truncated: Any) -> MineDojoPortedStep:
        assert self._evaluation is not None
        raw_reward = float(simulator_reward or 0.0)
        info = dict(self._info)
        info["render_ready"] = self._render_readiness
        info["minedojo_ported"] = {
            "default_viewpoint": self.viewpoint,
            "evaluation": self._evaluation.to_dict(),
            # HumanSurvival currently declares no MineRL rewardables. Keep its
            # raw value as diagnostics while exposing the faithful ported
            # shaping reward through the standard step reward lane.
            "simulator_reward": raw_reward,
        }
        input_evidence = self._action_adapter.last_input_evidence
        if input_evidence is not None:
            info["gamegym_input"] = input_evidence
        image = pov_image(
            self._obs,
            self._info,
            source="MineDojo-ported",
            prefer_render_pov=True,
        )
        if self.agent_image_short_edge is not None and min(image.size) > self.agent_image_short_edge:
            scale = self.agent_image_short_edge / min(image.size)
            image = image.resize(
                tuple(max(1, round(value * scale)) for value in image.size),
                resample=Image.Resampling.LANCZOS,
            )
        return MineDojoPortedStep(
            image=self._action_adapter.bind_observation(image, self._info),
            reward=self._evaluation.shaping_reward,
            terminated=bool(terminated),
            truncated=bool(truncated),
            info=info,
            evaluation=self._evaluation,
        )

    @property
    def render_ready(self) -> bool:
        return bool(self._render_readiness and self._render_readiness.get("ready"))

    @property
    def render_readiness(self) -> dict[str, Any] | None:
        return dict(self._render_readiness) if self._render_readiness is not None else None

    def start(self) -> MineDojoPortedStep:
        if self._env is not None:
            raise RuntimeError("MineDojo-ported environment is already started")
        self._startup_event("environment_start_begin")
        configure_runtime()
        from player1.environments.minestudio.runtime import configure_runtime_environment

        configure_runtime_environment(self.runtime_config)
        self._action_adapter.reset()
        self._action_adapter.verify_runtime()
        # This backend constructs a task-specific low-level MineRL EnvSpec and
        # never instantiates MineStudio's high-level ``MinecraftSim``.  Install
        # the maintained package shim before the first simulator import so the
        # minimal controller runtime does not eagerly pull model/training-only
        # dependencies such as torch and einops.
        from player1.environments.minestudio.runtime import install_minerl_only_simulator_package

        install_minerl_only_simulator_package()
        configure_minerl_reset_gate(self.runtime_config.minecraft_max_resetting_envs)
        random.seed(self.trial.task_rng_seed)
        np.random.seed(self.trial.task_rng_seed)
        try:
            self._env = acquire_worker_minecraft_simulator(
                self._simulator_key,
                lambda: self._action_adapter.prepare_simulator(
                    _MineDojoPortedSimulator(
                        self.plan,
                        obs_size=self.obs_size,
                        render_size=self.render_size,
                        viewpoint=self.viewpoint,
                        operation_timeout_s=self.runtime_config.minecraft_operation_timeout_s,
                        reset_slot_count=self.runtime_config.minecraft_max_resetting_envs,
                    )
                ),
                max_rollouts_per_jvm=self.runtime_config.minecraft_max_rollouts_per_jvm,
            )
            self._runtime_reused = minecraft_simulator_was_reused(self._env)
            set_startup_event = getattr(self._env, "set_startup_event", None)
            if callable(set_startup_event):
                set_startup_event(self._startup_event)
            obs, info = self._env.reset()
            self._startup_event("publish_begin")
            keep_minecraft_server_running_during_gui_actions(self._env)
            self._startup_event("publish_end")
            self._record(obs, info)
            if self.runtime_config.render_ready.enabled:
                try:
                    readiness = wait_for_official_render_ready(
                        self._env,
                        record=self._record,
                        config=self.runtime_config.render_ready,
                        source="MineDojo-ported",
                    )
                except RenderReadyTimeout as exc:
                    self._render_readiness = exc.report.to_dict()
                    raise
                self._render_readiness = readiness.to_dict()
            self._evaluation = self.scorer.reset(self._info)
            self._startup_event("scorer_ready")
            self._startup_event("start_complete")
            return self._step_result(simulator_reward=0.0, terminated=False, truncated=False)
        except Exception as exc:
            self._startup_event("failure", error_type=type(exc).__name__, error=str(exc))
            self._reusable = False
            try:
                self.close()
            except Exception as close_exc:
                exc.add_note(f"MineDojo-ported failed-start cleanup also failed: {close_exc}")
            raise

    def step(self, action: Mapping[str, Any]) -> MineDojoPortedStep:
        if self._env is None:
            raise RuntimeError("MineDojo-ported environment is not started")
        try:
            env_action = self._action_adapter.to_env_action(action)
            obs, reward, terminated, truncated, info = self._env.step(env_action)
            raise_for_minecraft_step_error(info, source="MineDojo-ported")
            self._record(obs, info)
            self._evaluation = self.scorer.step(self._info)
            self.decisions += 1
            return self._step_result(
                simulator_reward=reward,
                terminated=terminated,
                truncated=truncated,
            )
        except Exception:
            self._reusable = False
            raise

    def park_for_reuse(self) -> None:
        """Stop world time before returning the current JVM to the reuse pool."""

        if self._env is None:
            return
        try:
            self._env.park()
        except Exception:
            self._reusable = False
            raise

    @property
    def runtime_reused(self) -> bool:
        return self._runtime_reused

    def close(self) -> None:
        if self._env is None:
            return
        try:
            if self._reusable:
                self.park_for_reuse()
        finally:
            env, self._env = self._env, None
            release_worker_minecraft_simulator(self._simulator_key, env, reusable=self._reusable)

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        self.close()


__all__ = [
    "MINEDOJO_PORTED_OBS_SIZE",
    "MINEDOJO_PORTED_RENDER_SIZE",
    "MineDojoPortedEnvironment",
    "MineDojoPortedStep",
]

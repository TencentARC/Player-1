"""Execution and worker-runtime isolation for official MineStudio evaluation."""

from __future__ import annotations

import atexit
import concurrent.futures
import multiprocessing
import os
import shutil
import sys
import tempfile
from collections import OrderedDict
from collections.abc import Callable, Hashable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import Enum
from multiprocessing.util import Finalize
from pathlib import Path
from typing import Any, TypeVar

from player1.environments.minestudio.readiness import RenderReadyConfig

from player1.environments.minestudio.lifecycle import (
    DEFAULT_MINECRAFT_OPERATION_TIMEOUT_S,
    MinecraftValidationInfrastructureError,
    minecraft_operation_timeout,
    require_minecraft_timeout,
)
from .xvfb_runtime import configure_control_group_xvfb

TrialT = TypeVar("TrialT")
ConfigT = TypeVar("ConfigT")

# Safe direct-Python defaults. Supported launchers pass an explicit total worker
# count derived from their own per-GPU capacity policy.
DEFAULT_MINECRAFT_EVALUATION_WORKERS = 8
DEFAULT_MINECRAFT_RESETTING_ENVS_PER_GPU = 4


@dataclass(frozen=True)
class MinecraftControlGroupConfig:
    """Process-pool topology for isolated groups of MineStudio workers.

    The executor remains one global dynamically scheduled pool.  Its spawned
    processes claim a stable slot before importing MineStudio, then select one
    of these writable roots and non-overlapping Malmo port ranges. MineStudio's
    diskcache-backed reset gate is consequently shared only by workers in the
    same group. Each group owns one persistent Xvfb display shared by its
    workers, so rapid JVM replacement does not race display teardown/startup.
    """

    root: Path
    group_count: int
    workers_per_group: int
    malmo_base_port: int = 9000
    malmo_port_stride: int = 5000

    def __post_init__(self) -> None:
        root = self.root.expanduser()
        if not root.is_absolute():
            raise ValueError("Minecraft control-group root must be absolute")
        if self.group_count <= 0:
            raise ValueError("Minecraft control-group count must be positive")
        if self.workers_per_group <= 0:
            raise ValueError("Minecraft workers per control group must be positive")
        if self.malmo_base_port <= 0 or self.malmo_port_stride < 5000:
            raise ValueError("Minecraft control-group Malmo ports require a positive base and stride >= 5000")
        highest_exclusive = self.malmo_base_port + self.group_count * self.malmo_port_stride
        if highest_exclusive > 65536:
            raise ValueError("Minecraft control-group Malmo port ranges exceed TCP port space")
        object.__setattr__(self, "root", root.resolve())

    @property
    def worker_capacity(self) -> int:
        return self.group_count * self.workers_per_group

    def group_root(self, group_index: int) -> Path:
        if not 0 <= group_index < self.group_count:
            raise ValueError("Minecraft control-group index is out of range")
        return self.root / f"group-{group_index:02d}"

    def identity(self, *, resetting_envs_per_group: int) -> dict[str, Any]:
        return {
            "protocol": "spawn_slot_round_robin_control_groups",
            "group_count": self.group_count,
            "workers_per_group": self.workers_per_group,
            "resetting_envs_per_group": resetting_envs_per_group,
            "isolated_minecraft_dir": True,
            "minecraft_display_mode": "shared_control_group_xvfb",
            "malmo_base_port": self.malmo_base_port,
            "malmo_port_stride": self.malmo_port_stride,
        }


@dataclass(frozen=True)
class MinecraftWorkerControlGroup:
    worker_slot: int
    worker_index_in_group: int
    group_index: int
    group_root: Path
    minecraft_dir: Path
    malmo_base_port: int


def resolve_minecraft_worker_control_group(
    config: MinecraftControlGroupConfig,
    *,
    worker_slot: int,
) -> MinecraftWorkerControlGroup:
    """Resolve a unique spawn slot without coupling task scheduling to groups."""

    if worker_slot < 0 or worker_slot >= config.worker_capacity:
        raise ValueError("Minecraft worker slot exceeds control-group capacity")
    # Round robin keeps partially populated pools balanced across control groups while
    # still assigning exactly workers_per_group slots to every full group.
    group_index = worker_slot % config.group_count
    worker_index_in_group = worker_slot // config.group_count
    group_root = config.group_root(group_index)
    return MinecraftWorkerControlGroup(
        worker_slot=worker_slot,
        worker_index_in_group=worker_index_in_group,
        group_index=group_index,
        group_root=group_root,
        minecraft_dir=group_root / "minecraft",
        malmo_base_port=config.malmo_base_port + group_index * config.malmo_port_stride,
    )


def _initialize_minecraft_worker_control_group(
    slot_counter: Any,
    config: MinecraftControlGroupConfig,
) -> None:
    """Claim one worker slot and isolate MineStudio before its first import."""

    with slot_counter.get_lock():
        worker_slot = int(slot_counter.value)
        slot_counter.value += 1
    assignment = resolve_minecraft_worker_control_group(config, worker_slot=worker_slot)
    imported = sorted(name for name in sys.modules if name == "minestudio" or name.startswith("minestudio."))
    if imported:
        raise RuntimeError(
            "MineStudio was imported before worker control-group initialization: "
            + ", ".join(imported[:5])
        )
    if not assignment.minecraft_dir.is_dir():
        raise RuntimeError(
            f"Minecraft control-group root was not bootstrapped: {assignment.minecraft_dir}"
        )
    os.environ["MINESTUDIO_DIR"] = str(assignment.minecraft_dir)
    os.environ["MINESTUDIO_CONTROL_GROUP_INDEX"] = str(assignment.group_index)
    os.environ["MINESTUDIO_CONTROL_GROUP_WORKER_INDEX"] = str(assignment.worker_index_in_group)
    os.environ["MINESTUDIO_WORKER_SLOT"] = str(assignment.worker_slot)
    os.environ["MINESTUDIO_MALMO_BASE_PORT"] = str(assignment.malmo_base_port)
    configure_control_group_xvfb(assignment.group_root)


@dataclass(frozen=True)
class OfficialRuntimeConfig:
    extra_env: dict[str, str] = field(default_factory=dict)
    render_devices: str | None = None
    minecraft_output_logdir: str | None = None
    java_tool_options: str | None = None
    minecraft_max_resetting_envs: int = DEFAULT_MINECRAFT_RESETTING_ENVS_PER_GPU
    minecraft_max_rollouts_per_jvm: int = 8
    minecraft_start_retries: int = 1
    minecraft_operation_timeout_s: float = DEFAULT_MINECRAFT_OPERATION_TIMEOUT_S
    render_ready: RenderReadyConfig = field(default_factory=RenderReadyConfig)
    minecraft_control_groups: MinecraftControlGroupConfig | None = None

    def __post_init__(self) -> None:
        if self.minecraft_max_resetting_envs <= 0:
            raise ValueError("Minecraft concurrent reset limit must be positive")
        if self.minecraft_max_rollouts_per_jvm <= 0:
            raise ValueError("Minecraft rollouts per JVM must be positive")
        if self.minecraft_start_retries < 0:
            raise ValueError("Minecraft start retries cannot be negative")
        require_minecraft_timeout(self.minecraft_operation_timeout_s)


_REGISTERED_JAVA_RUNTIME_ROOTS: set[Path] = set()
_MINECRAFT_CLEANUP_PID: int | None = None
_MINECRAFT_CLEANUP_FINALIZER: Finalize | None = None
_PUBLISHED_SERVER_MARKER = "_player1_integrated_server_published"
_RUNTIME_REUSED_MARKER = "_player1_runtime_reused"


class MinecraftJvmState(str, Enum):
    IDLE = "idle"
    LEASED = "leased"
    UNHEALTHY = "unhealthy"
    CLOSED = "closed"


@dataclass
class _MinecraftSimulatorSlot:
    simulator: Any
    state: MinecraftJvmState = MinecraftJvmState.IDLE
    completed_rollouts: int = 0


class MinecraftJvmPool:
    """Worker-local capacity-bounded pool for retained Minecraft JVMs."""

    def __init__(self, *, capacity: int = 1) -> None:
        if capacity <= 0:
            raise ValueError("Minecraft JVM pool capacity must be positive")
        self.capacity = int(capacity)
        self._slots: OrderedDict[Hashable, _MinecraftSimulatorSlot] = OrderedDict()

    def reset_after_fork(self) -> None:
        self._slots.clear()

    def acquire(
        self,
        key: Hashable,
        factory: Callable[[], Any],
        *,
        max_rollouts_per_jvm: int,
    ) -> Any:
        if max_rollouts_per_jvm <= 0:
            raise ValueError("Minecraft rollouts per JVM must be positive")
        slot = self._slots.pop(key, None)
        if slot is not None and slot.state == MinecraftJvmState.LEASED:
            self._slots[key] = slot
            raise RuntimeError(f"Minecraft simulator {key!r} is already in use")
        if slot is not None and slot.completed_rollouts >= max_rollouts_per_jvm:
            self._close_slot(slot)
            slot = None

        if slot is None:
            self._evict_for_capacity()

        try:
            candidate = factory()
        except Exception:
            if slot is not None:
                self._slots[key] = slot
            raise
        reused = slot is not None
        if slot is not None:
            try:
                _transfer_minecraft_instances(slot.simulator, candidate)
            except Exception:
                try:
                    _close_simulator(candidate, finalize_callbacks=True)
                except Exception:
                    pass
                self._slots[key] = slot
                raise

        setattr(candidate, _RUNTIME_REUSED_MARKER, reused)
        active = _MinecraftSimulatorSlot(
            simulator=candidate,
            state=MinecraftJvmState.LEASED,
            completed_rollouts=(slot.completed_rollouts if slot is not None else 0),
        )
        self._slots[key] = active
        return candidate

    def release(self, key: Hashable, simulator: Any, *, reusable: bool) -> None:
        slot = self._slots.get(key)
        if (
            slot is None
            or slot.simulator is not simulator
            or slot.state != MinecraftJvmState.LEASED
        ):
            raise RuntimeError(f"Minecraft simulator {key!r} is not leased here")

        callback_error: BaseException | None = None
        try:
            _finalize_simulator_callbacks(simulator)
        except BaseException as exc:
            callback_error = exc
            reusable = False
        slot.completed_rollouts += 1
        if reusable:
            slot.state = MinecraftJvmState.IDLE
            self._slots.move_to_end(key)
        else:
            slot.state = MinecraftJvmState.UNHEALTHY
            self._slots.pop(key, None)
            try:
                self._close_slot(slot)
            except BaseException:
                if callback_error is None:
                    raise
        if callback_error is not None:
            raise callback_error

    def close_all(self) -> None:
        slots = tuple(self._slots.values())
        self._slots.clear()
        for slot in slots:
            try:
                self._close_slot(slot, finalize_callbacks=slot.state == MinecraftJvmState.LEASED)
            except Exception:
                pass

    def _evict_for_capacity(self) -> None:
        while len(self._slots) >= self.capacity:
            key, slot = next(iter(self._slots.items()))
            if slot.state == MinecraftJvmState.LEASED:
                raise RuntimeError("Minecraft JVM pool capacity is fully leased")
            self._slots.pop(key)
            self._close_slot(slot)

    @staticmethod
    def _close_slot(slot: _MinecraftSimulatorSlot, *, finalize_callbacks: bool = False) -> None:
        try:
            _close_simulator(slot.simulator, finalize_callbacks=finalize_callbacks)
        finally:
            slot.state = MinecraftJvmState.CLOSED


_MINECRAFT_JVM_POOL = MinecraftJvmPool(capacity=1)


def configure_minerl_reset_gate(max_resetting_envs: int) -> None:
    """Override MineRL's process-wide concurrent reset limit."""

    if max_resetting_envs <= 0:
        raise ValueError("Minecraft concurrent reset limit must be positive")
    from minestudio.simulator.minerl.env import _multiagent
    from minestudio.simulator.minerl.env.malmo import InstanceManager

    _multiagent.MAX_RESETTING_ENV_COUNT = max_resetting_envs
    configured_base_port = os.environ.get("MINESTUDIO_MALMO_BASE_PORT")
    if configured_base_port is not None:
        if not configured_base_port.isdigit() or not 0 < int(configured_base_port) < 65536:
            raise ValueError("MINESTUDIO_MALMO_BASE_PORT must be a valid positive TCP port")
        InstanceManager.configure_malmo_base_port(int(configured_base_port))


def _java_system_property(name: str, value: Path) -> str:
    escaped = str(value).replace('"', '\\"')
    return f'-D{name}="{escaped}"'


def isolated_minecraft_runtime(
    runtime: OfficialRuntimeConfig,
) -> OfficialRuntimeConfig:
    """Give each evaluator worker its own JVM native extraction directory."""

    root = Path(tempfile.gettempdir()) / "game-gym-official-minestudio" / str(os.getpid())
    java_tmp = root / "tmp"
    lwjgl_natives = root / "lwjgl-natives"
    jna_tmp = root / "jna"
    for path in (java_tmp, lwjgl_natives, jna_tmp):
        path.mkdir(parents=True, exist_ok=True)
    if root not in _REGISTERED_JAVA_RUNTIME_ROOTS:
        atexit.register(shutil.rmtree, root, ignore_errors=True)
        _REGISTERED_JAVA_RUNTIME_ROOTS.add(root)

    options = [
        runtime.java_tool_options or "",
        _java_system_property("java.io.tmpdir", java_tmp),
        _java_system_property(
            "org.lwjgl.system.SharedLibraryExtractPath",
            lwjgl_natives,
        ),
        _java_system_property("jna.tmpdir", jna_tmp),
        "-Dio.netty.eventLoopThreads=4",
    ]
    extra_env = dict(runtime.extra_env)
    extra_env["TMPDIR"] = str(java_tmp)
    return replace(
        runtime,
        extra_env=extra_env,
        java_tool_options=" ".join(option for option in options if option).strip(),
    )


def _finalize_simulator_callbacks(simulator: Any) -> None:
    callbacks = tuple(getattr(simulator, "callbacks", ()))
    first_error: Exception | None = None
    try:
        for method_name in ("before_close", "after_close"):
            for callback in callbacks:
                try:
                    timeout_s = float(
                        getattr(simulator, "operation_timeout_s", DEFAULT_MINECRAFT_OPERATION_TIMEOUT_S)
                    )
                    with minecraft_operation_timeout(
                        timeout_s,
                        operation=f"simulator callback {type(callback).__name__}.{method_name}",
                    ):
                        getattr(callback, method_name)(simulator)
                except Exception as exc:
                    if first_error is None:
                        first_error = exc
    finally:
        simulator.callbacks = []
    if first_error is not None:
        raise first_error


def _close_simulator(simulator: Any, *, finalize_callbacks: bool) -> None:
    callback_error: Exception | None = None
    if finalize_callbacks:
        try:
            _finalize_simulator_callbacks(simulator)
        except Exception as exc:
            callback_error = exc
    try:
        timeout_s = float(getattr(simulator, "operation_timeout_s", DEFAULT_MINECRAFT_OPERATION_TIMEOUT_S))
        with minecraft_operation_timeout(
            timeout_s,
            operation=f"simulator {type(simulator).__name__}.close",
        ):
            simulator.close()
    except Exception:
        force_close = getattr(simulator, "force_close", None)
        if callable(force_close):
            try:
                force_close()
            except Exception:
                pass
        if callback_error is None:
            raise
    if callback_error is not None:
        raise callback_error


def close_worker_minecraft_simulators() -> None:
    """Close every JVM owned by the current evaluator worker."""

    _MINECRAFT_JVM_POOL.close_all()


def _register_minecraft_cleanup() -> None:
    global _MINECRAFT_CLEANUP_FINALIZER, _MINECRAFT_CLEANUP_PID

    pid = os.getpid()
    if _MINECRAFT_CLEANUP_PID == pid:
        return
    if _MINECRAFT_CLEANUP_PID is not None:
        _MINECRAFT_JVM_POOL.reset_after_fork()
    _MINECRAFT_CLEANUP_PID = pid
    atexit.register(close_worker_minecraft_simulators)
    _MINECRAFT_CLEANUP_FINALIZER = Finalize(
        None,
        close_worker_minecraft_simulators,
        exitpriority=10,
    )


def _transfer_minecraft_instances(previous: Any, candidate: Any) -> None:
    previous_env = getattr(previous, "env", None)
    candidate_env = getattr(candidate, "env", None)
    previous_instances = getattr(previous_env, "instances", None)
    candidate_instances = getattr(candidate_env, "instances", None)
    if not isinstance(previous_instances, list) or not isinstance(
        candidate_instances,
        list,
    ):
        raise RuntimeError("MineStudio MinecraftSim does not expose transferable instance lists")
    if candidate_instances:
        raise RuntimeError("A new MineStudio simulator unexpectedly owns instances")

    previous_env.instances = []
    try:
        candidate_env.instances = previous_instances
    except Exception:
        previous_env.instances = previous_instances
        raise


def acquire_worker_minecraft_simulator(
    key: Hashable,
    factory: Callable[[], Any],
    *,
    max_rollouts_per_jvm: int,
) -> Any:
    """Create a fresh facade and reuse each worker-local JVM for a bounded batch."""

    _register_minecraft_cleanup()
    return _MINECRAFT_JVM_POOL.acquire(
        key,
        factory,
        max_rollouts_per_jvm=max_rollouts_per_jvm,
    )


def release_worker_minecraft_simulator(
    key: Hashable,
    simulator: Any,
    *,
    reusable: bool,
) -> None:
    """Finish one rollout and retain or discard its underlying JVM."""

    _MINECRAFT_JVM_POOL.release(key, simulator, reusable=reusable)


def minecraft_simulator_was_reused(simulator: Any) -> bool:
    return bool(getattr(simulator, _RUNTIME_REUSED_MARKER, False))


def run_trial_batch(
    trials: Sequence[TrialT],
    config: ConfigT,
    *,
    worker: Callable[[tuple[TrialT, ConfigT]], dict[str, Any]],
    workers: int,
    minecraft_control_groups: MinecraftControlGroupConfig | None = None,
    on_result: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    """Run directly or in persistent spawned workers with dynamic scheduling."""

    if workers <= 0:
        raise ValueError("Official evaluation worker count must be positive")
    if minecraft_control_groups is not None and workers != minecraft_control_groups.worker_capacity:
        raise ValueError(
            "Official evaluation workers must exactly fill the configured "
            "Minecraft control-group capacity"
        )
    payloads = tuple((trial, config) for trial in trials)
    if workers == 1 and minecraft_control_groups is None:
        try:
            results = []
            for payload in payloads:
                result = worker(payload)
                results.append(result)
                if on_result is not None:
                    on_result(result)
            return results
        finally:
            close_worker_minecraft_simulators()
    spawn_context = multiprocessing.get_context("spawn")
    executor_kwargs: dict[str, Any] = {
        "max_workers": workers,
        "mp_context": spawn_context,
    }
    if minecraft_control_groups is not None:
        executor_kwargs.update(
            initializer=_initialize_minecraft_worker_control_group,
            initargs=(spawn_context.Value("i", 0, lock=True), minecraft_control_groups),
        )
    with concurrent.futures.ProcessPoolExecutor(**executor_kwargs) as executor:
        from player1.runtime.evaluation import map_evaluation

        return map_evaluation(executor, worker, payloads, capacity=workers, on_result=on_result)


def raise_for_minecraft_step_error(
    info: Any,
    *,
    source: str,
) -> None:
    """Reject MineRL's random-observation fallback after a socket failure."""

    if isinstance(info, Mapping) and "error" in info:
        raise MinecraftValidationInfrastructureError(
            f"{source} MineStudio step failed: {info['error']}"
        )


def keep_minecraft_server_running_during_gui_actions(simulator: Any) -> bool:
    """Publish one retained JVM once so pause-screen GUIs cannot stop its ticks."""

    environment = getattr(simulator, "env", None)
    instances = getattr(environment, "instances", None)
    if not isinstance(instances, list) or len(instances) != 1:
        raise RuntimeError("MineStudio must own exactly one Minecraft instance after reset")
    instance = instances[0]
    if getattr(instance, _PUBLISHED_SERVER_MARKER, False):
        return False
    execute_cmd = getattr(environment, "execute_cmd", None)
    if not callable(execute_cmd):
        raise RuntimeError("MineStudio environment does not expose execute_cmd")
    timeout_s = float(getattr(simulator, "operation_timeout_s", DEFAULT_MINECRAFT_OPERATION_TIMEOUT_S))
    with minecraft_operation_timeout(timeout_s, operation="MineStudio /publish"):
        result = execute_cmd("/publish")
    if not isinstance(result, tuple) or len(result) != 4:
        raise RuntimeError("MineStudio /publish returned an unexpected result")
    _observation, _reward, done, info = result
    raise_for_minecraft_step_error(info, source="MineStudio /publish")
    if done:
        raise RuntimeError("MineStudio ended while publishing its integrated server")
    setattr(instance, _PUBLISHED_SERVER_MARKER, True)
    return True


__all__ = [
    "DEFAULT_MINECRAFT_OPERATION_TIMEOUT_S",
    "DEFAULT_MINECRAFT_EVALUATION_WORKERS",
    "DEFAULT_MINECRAFT_RESETTING_ENVS_PER_GPU",
    "MinecraftControlGroupConfig",
    "MinecraftJvmPool",
    "MinecraftJvmState",
    "MinecraftWorkerControlGroup",
    "OfficialRuntimeConfig",
    "acquire_worker_minecraft_simulator",
    "close_worker_minecraft_simulators",
    "configure_minerl_reset_gate",
    "isolated_minecraft_runtime",
    "keep_minecraft_server_running_during_gui_actions",
    "minecraft_simulator_was_reused",
    "raise_for_minecraft_step_error",
    "release_worker_minecraft_simulator",
    "resolve_minecraft_worker_control_group",
    "run_trial_batch",
]

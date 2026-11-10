"""Bound and recover synchronous Minecraft/JVM lifecycle operations.

This module is deliberately independent from the evaluator, training loop, and
MineDojo task implementation.  Those callers only need three small contracts:
bound one blocking operation, classify infrastructure failures, and terminate
the process groups owned by a broken simulator.
"""

from __future__ import annotations

import fcntl
import math
import os
import signal
import threading
import time
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

DEFAULT_MINECRAFT_OPERATION_TIMEOUT_S = 300.0
MINECRAFT_CONTROLLER_RESPONSE_GRACE_S = 15.0
MINECRAFT_PROCESS_TERMINATION_GRACE_S = 5.0


class MinecraftOperationTimeout(TimeoutError):
    """A synchronous MineRL/Minecraft operation exceeded its deadline."""


class MinecraftValidationInfrastructureError(RuntimeError):
    """A validation trial may be retried after replacing its JVM/controller."""


@contextmanager
def minecraft_reset_slot(max_resetting_envs: int | None) -> Iterator[None]:
    """Queue a worker outside the timed MineRL reset operation.

    MineRL already limits concurrent resets, but waiting inside that gate is
    part of ``env.reset()`` and therefore consumes the operation timeout. A
    large worker pool can then time out healthy queued starts before they ever
    receive a reset slot. Control-group workers use stable slot files so only
    the configured number enter MineRL at once; the per-reset timeout starts
    after this wait.
    """

    if max_resetting_envs is None:
        yield
        return
    if isinstance(max_resetting_envs, bool) or not isinstance(max_resetting_envs, int):
        raise TypeError("Minecraft concurrent reset limit must be an integer")
    if max_resetting_envs <= 0:
        raise ValueError("Minecraft concurrent reset limit must be positive")

    worker_index = os.environ.get("MINESTUDIO_CONTROL_GROUP_WORKER_INDEX")
    minecraft_dir = os.environ.get("MINESTUDIO_DIR")
    if worker_index is None:
        yield
        return
    if minecraft_dir is None:
        raise RuntimeError("MINESTUDIO_DIR is required for a control-group reset slot")
    if not worker_index.isdigit():
        raise RuntimeError("MINESTUDIO_CONTROL_GROUP_WORKER_INDEX must be non-negative")

    slot_root = Path(minecraft_dir).expanduser().resolve() / ".player1_reset_slots"
    slot_root.mkdir(parents=True, exist_ok=True)
    slot_index = int(worker_index) % max_resetting_envs
    lock_path = slot_root / f"slot-{slot_index:03d}.lock"
    with lock_path.open("a+b") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def require_minecraft_timeout(timeout_s: float, *, name: str = "Minecraft operation timeout") -> float:
    if (
        isinstance(timeout_s, bool)
        or not isinstance(timeout_s, (int, float))
        or not math.isfinite(float(timeout_s))
        or float(timeout_s) <= 0
    ):
        raise ValueError(f"{name} must be a positive finite number")
    return float(timeout_s)


@contextmanager
def minecraft_operation_timeout(timeout_s: float, *, operation: str) -> Iterator[None]:
    """Interrupt one blocking synchronous operation on its worker main thread.

    MineStudio evaluator workers and the isolated training controller invoke
    MineRL on their main thread.  Failing closed elsewhere avoids silently
    pretending that a watchdog is active when Python cannot install SIGALRM.
    """

    timeout = require_minecraft_timeout(timeout_s)
    if not hasattr(signal, "SIGALRM") or not hasattr(signal, "setitimer"):
        raise RuntimeError("Minecraft operation timeouts require POSIX SIGALRM")
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("Minecraft operations must run on the controller main thread")

    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)
    started_at = time.monotonic()

    def expire(_signum: int, _frame: object) -> None:
        raise MinecraftOperationTimeout(
            f"Minecraft operation timed out after {timeout:g}s: {operation}"
        )

    signal.signal(signal.SIGALRM, expire)
    signal.setitimer(signal.ITIMER_REAL, timeout)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        previous_delay, previous_interval = previous_timer
        if previous_delay > 0 or previous_interval > 0:
            elapsed = time.monotonic() - started_at
            signal.setitimer(
                signal.ITIMER_REAL,
                max(0.000001, previous_delay - elapsed),
                previous_interval,
            )


def _process_is_alive(process: Any) -> bool:
    poll = getattr(process, "poll", None)
    if callable(poll):
        return poll() is None
    pid = int(process.pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _wait_process(process: Any, timeout_s: float) -> None:
    wait = getattr(process, "wait", None)
    if not callable(wait):
        return
    try:
        wait(timeout=max(0.0, timeout_s))
    except Exception:  # noqa: BLE001 - best-effort reap after force termination
        pass


def terminate_minecraft_instances(
    instances: Iterable[Any],
    *,
    grace_s: float = MINECRAFT_PROCESS_TERMINATION_GRACE_S,
) -> None:
    """Resume, terminate, then kill all Minecraft process groups if needed."""

    grace = require_minecraft_timeout(grace_s, name="Minecraft termination grace")
    processes: dict[int, Any] = {}
    for instance in tuple(instances):
        process = getattr(instance, "minecraft_process", None)
        if process is None:
            continue
        pid = int(process.pid)
        processes[pid] = process

    for pid in processes:
        try:
            process_group = os.getpgid(pid)
        except ProcessLookupError:
            continue
        try:
            os.killpg(process_group, signal.SIGCONT)
        except ProcessLookupError:
            continue
        try:
            os.killpg(process_group, signal.SIGTERM)
        except ProcessLookupError:
            pass

    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        if not any(_process_is_alive(process) for process in processes.values()):
            break
        time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))

    for pid, process in processes.items():
        if not _process_is_alive(process):
            _wait_process(process, 0.0)
            continue
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
        _wait_process(process, 1.0)


def _linux_descendant_pids(root_pid: int) -> set[int]:
    """Snapshot descendants without adding psutil to the controller runtime."""

    proc_root = Path("/proc")
    if not proc_root.is_dir():
        return set()
    children: dict[int, set[int]] = {}
    for stat_path in proc_root.glob("[0-9]*/stat"):
        try:
            payload = stat_path.read_text(encoding="utf-8")
            pid = int(stat_path.parent.name)
            fields = payload.rsplit(")", 1)[1].split()
            parent_pid = int(fields[1])
        except (OSError, ValueError, IndexError):
            continue
        children.setdefault(parent_pid, set()).add(pid)
    descendants: set[int] = set()
    pending = list(children.get(root_pid, ()))
    while pending:
        pid = pending.pop()
        if pid in descendants:
            continue
        descendants.add(pid)
        pending.extend(children.get(pid, ()))
    return descendants


def terminate_minecraft_descendants(
    controller_pid: int,
    *,
    grace_s: float = MINECRAFT_PROCESS_TERMINATION_GRACE_S,
) -> None:
    """Kill descendant process groups before replacing a wedged controller."""

    grace = require_minecraft_timeout(grace_s, name="Minecraft termination grace")
    descendants = _linux_descendant_pids(int(controller_pid))
    if not descendants:
        return
    try:
        controller_group = os.getpgid(int(controller_pid))
    except ProcessLookupError:
        controller_group = None
    own_group = os.getpgrp()
    process_groups: set[int] = set()
    for pid in descendants:
        try:
            process_group = os.getpgid(pid)
        except ProcessLookupError:
            continue
        if process_group not in {controller_group, own_group}:
            process_groups.add(process_group)

    for process_group in process_groups:
        try:
            os.killpg(process_group, signal.SIGCONT)
            os.killpg(process_group, signal.SIGTERM)
        except ProcessLookupError:
            pass

    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        if not any(Path(f"/proc/{pid}").exists() for pid in descendants):
            return
        time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
    for process_group in process_groups:
        try:
            os.killpg(process_group, signal.SIGKILL)
        except ProcessLookupError:
            pass


__all__ = [
    "DEFAULT_MINECRAFT_OPERATION_TIMEOUT_S",
    "MINECRAFT_CONTROLLER_RESPONSE_GRACE_S",
    "MINECRAFT_PROCESS_TERMINATION_GRACE_S",
    "MinecraftOperationTimeout",
    "MinecraftValidationInfrastructureError",
    "minecraft_operation_timeout",
    "require_minecraft_timeout",
    "terminate_minecraft_descendants",
    "terminate_minecraft_instances",
]

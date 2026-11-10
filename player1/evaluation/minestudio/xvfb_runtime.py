"""Shared Xvfb display assignment for MineStudio control groups."""

from __future__ import annotations

import os
import signal
import time
from pathlib import Path

XVFB_DISPLAY_STATE_RELATIVE_PATH = Path("state/xvfb.display")


def configure_control_group_xvfb(group_root: Path) -> str:
    """Publish the persistent Xvfb display bootstrapped for one control group."""

    display_path = group_root.expanduser().resolve() / XVFB_DISPLAY_STATE_RELATIVE_PATH
    try:
        display = display_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError(f"MineStudio control-group Xvfb display is unavailable: {display_path}") from exc
    if not display.startswith(":") or not display[1:].isdigit():
        raise RuntimeError(f"MineStudio control-group Xvfb display is invalid: {display!r}")
    os.environ["DISPLAY"] = display
    return display


def stop_control_group_xvfb(group_root: Path) -> None:
    """Release only the display whose PID and argv match this control group."""
    pid_path = group_root / "state/xvfb.pid"
    display_path = group_root / XVFB_DISPLAY_STATE_RELATIVE_PATH
    if not pid_path.is_file() or not display_path.is_file():
        return
    pid = int(pid_path.read_text().strip())
    display = display_path.read_text().strip()
    if pid <= 1 or not display.startswith(":") or not display[1:].isdigit():
        raise ValueError("Invalid control-group Xvfb ownership state")
    command = Path(f"/proc/{pid}/cmdline")
    try:
        argv = command.read_bytes().split(b"\0")
    except (FileNotFoundError, ProcessLookupError):
        return
    if os.path.basename(os.fsdecode(argv[0])) != "Xvfb" or argv[1:2] != [display.encode()]:
        raise RuntimeError("Control-group Xvfb PID belongs to another process")
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    deadline = time.monotonic() + 5
    while True:
        try:
            if not command.read_bytes():
                break  # Exited, including an unreaped zombie.
        except (FileNotFoundError, ProcessLookupError):
            break
        if time.monotonic() >= deadline:
            raise TimeoutError("Owned control-group Xvfb did not exit")
        time.sleep(0.05)
    pid_path.unlink(missing_ok=True)
    display_path.unlink(missing_ok=True)


__all__ = [
    "XVFB_DISPLAY_STATE_RELATIVE_PATH",
    "configure_control_group_xvfb",
    "stop_control_group_xvfb",
]

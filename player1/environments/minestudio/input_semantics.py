"""Shared keyboard semantics for Player-1's MineStudio input bridge."""

from __future__ import annotations

import math
import zipfile
from collections.abc import Callable, Collection, Mapping, MutableSequence
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any

MLLM_GAME_AGENT_MINESTUDIO_INPUT_PROTOCOL = "mllm_game_agent_minestudio_input_v3"
MINESTUDIO_INPUT_BRIDGE_MARKER = "META-INF/gamegym-minestudio-input-v3"
MINESTUDIO_INPUT_BRIDGE_MARKER_CONTENT = MLLM_GAME_AGENT_MINESTUDIO_INPUT_PROTOCOL + "\n"
MINESTUDIO_KEYBOARD_INPUT_PROTOCOL = "minestudio_keyboard_input_v1"
MINESTUDIO_INPUT_HELD_VALUE = 1
MINESTUDIO_INPUT_IMPULSE_VALUE = 2

MINESTUDIO_ACTION_KEYS = (
    "attack",
    "back",
    "forward",
    "jump",
    "left",
    "right",
    "sneak",
    "sprint",
    "use",
    "hotbar.1",
    "hotbar.2",
    "hotbar.3",
    "hotbar.4",
    "hotbar.5",
    "hotbar.6",
    "hotbar.7",
    "hotbar.8",
    "hotbar.9",
    "inventory",
    "drop",
    "swapHands",
    "ESC",
    "togglePerspective",
)

MINESTUDIO_KEYBOARD_IMPULSE_ACTIONS = frozenset(
    {f"hotbar.{index}" for index in range(1, 10)}
    | {"inventory", "drop", "swapHands", "ESC", "togglePerspective"}
)
MINESTUDIO_KEYBOARD_HELD_ACTIONS = frozenset({"back", "forward", "jump", "left", "right", "sneak", "sprint"})

MINESTUDIO_CONTROL_KEY_TO_ACTION = MappingProxyType(
    {
        "w": "forward",
        "arrowup": "forward",
        "s": "back",
        "arrowdown": "back",
        "a": "left",
        "arrowleft": "left",
        "d": "right",
        "arrowright": "right",
        "space": "jump",
        "shift": "sneak",
        "control": "sprint",
        "e": "inventory",
        "q": "drop",
        "f": "swapHands",
        "escape": "ESC",
        **{str(index): f"hotbar.{index}" for index in range(1, 10)},
    }
)

_RAW_KEY_ALIASES = MappingProxyType(
    {
        " ": "space",
        "leftshift": "shift",
        "ctrl": "control",
        "leftctrl": "control",
        "leftcontrol": "control",
        "esc": "escape",
    }
)

# MineStudio's HumanSurvival omits these commands from its actionables even
# though the pinned Java bridge understands them.
_OPTIONAL_ACTION_KEY_CODES = (
    ("drop", "16"),
    ("swapHands", "33"),
    ("ESC", "1"),
    ("togglePerspective", "63"),
)


def mine_studio_action_for_key(key: Any, *, allow_aliases: bool = False) -> str | None:
    raw = str(key or "").lower()
    normalized = raw if raw == " " else raw.strip()
    if allow_aliases:
        normalized = _RAW_KEY_ALIASES.get(normalized, normalized)
    return MINESTUDIO_CONTROL_KEY_TO_ACTION.get(normalized)


def resolve_mine_studio_key_actions(keys: Any, *, field: str) -> tuple[str, ...]:
    """Strictly resolve and stably deduplicate one canonical key lane."""

    if not isinstance(keys, list) or not keys:
        raise TypeError(f"{field} must be a non-empty canonical list")
    if any(not isinstance(key, str) for key in keys):
        invalid = next(key for key in keys if not isinstance(key, str))
        raise ValueError(f"Unsupported MineStudio key in {field}: {invalid!r}")
    if len(keys) != len(set(keys)):
        raise ValueError(f"{field} must not contain duplicates")

    action_names: list[str] = []
    seen_actions: set[str] = set()
    for key in keys:
        action_name = mine_studio_action_for_key(key)
        if action_name is None:
            raise ValueError(f"Unsupported MineStudio key in {field}: {key!r}")
        if action_name in seen_actions:
            continue
        seen_actions.add(action_name)
        action_names.append(action_name)
    return tuple(action_names)


def mine_studio_action_admission_error(
    tool_call: Mapping[str, Any] | None,
    *,
    allowed_keys: Collection[str],
    mouse_click_buttons: Collection[str],
    mouse_hold_buttons: Collection[str],
) -> str | None:
    """Reject canonical controls that the configured Minecraft game cannot execute."""

    if not isinstance(tool_call, Mapping):
        return None
    raw_calls = tool_call.get("tool_calls")
    calls = raw_calls if isinstance(raw_calls, list) else [tool_call]
    for call in calls:
        if not isinstance(call, Mapping):
            continue
        arguments = call.get("arguments")
        if not isinstance(arguments, Mapping):
            continue
        for field_name in ("keys", "key_hold", "key_tap"):
            keys = arguments.get(field_name)
            if isinstance(keys, list):
                unsupported = sorted(str(key) for key in keys if str(key) not in allowed_keys)
                if unsupported:
                    return f"unreachable_keys:{','.join(unsupported)}"
        key_hold, key_tap = arguments.get("key_hold"), arguments.get("key_tap")
        if isinstance(key_hold, list) and isinstance(key_tap, list):
            held = set(resolve_mine_studio_key_actions(key_hold, field="key_hold"))
            tapped = set(resolve_mine_studio_key_actions(key_tap, field="key_tap"))
            conflicts = sorted(held & tapped)
            if conflicts:
                return f"conflicting_mapped_keys:{','.join(conflicts)}"
        mouse_capabilities = (
            ("mouse_click", mouse_click_buttons),
            ("mouse_hold", mouse_hold_buttons),
        )
        for field_name, allowed_buttons in mouse_capabilities:
            button = arguments.get(field_name)
            if isinstance(button, str) and button not in allowed_buttons:
                return f"unreachable_{field_name}:{button}"
    return None


@lru_cache(maxsize=8)
def _verify_mine_studio_input_bridge_cached(path_text: str, size: int, modified_ns: int) -> None:
    del size, modified_ns
    path = Path(path_text)
    try:
        with zipfile.ZipFile(path) as archive:
            marker = archive.read(MINESTUDIO_INPUT_BRIDGE_MARKER).decode("utf-8")
    except (KeyError, OSError, UnicodeDecodeError, zipfile.BadZipFile) as exc:
        raise RuntimeError(
            f"MineStudio engine does not provide {MLLM_GAME_AGENT_MINESTUDIO_INPUT_PROTOCOL}: {path}"
        ) from exc
    if marker != MINESTUDIO_INPUT_BRIDGE_MARKER_CONTENT:
        raise RuntimeError(f"MineStudio input bridge marker mismatch in {path}")


def verify_mine_studio_input_bridge(engine_path: str | Path) -> Path:
    """Require the versioned held/impulse bridge without pinning a JAR hash."""

    resolved = Path(engine_path).expanduser().resolve()
    stat = resolved.stat()
    _verify_mine_studio_input_bridge_cached(str(resolved), stat.st_size, stat.st_mtime_ns)
    return resolved


def _append_missing_actionables(
    actionables: MutableSequence[Any],
    action_factory: Callable[[str, str], Any],
    mouse_wheel_factory: Callable[[], Any],
) -> tuple[str, ...]:
    existing = {str(action.to_string()) for action in actionables}
    added: list[str] = []
    for command, key_code in _OPTIONAL_ACTION_KEY_CODES:
        if command in existing:
            continue
        actionables.append(action_factory(command, key_code))
        existing.add(command)
        added.append(command)
    if "dwheel" not in existing:
        actionables.append(mouse_wheel_factory())
        added.append("dwheel")
    return tuple(added)


def install_player1_input_actionables(simulator: Any) -> tuple[str, ...]:
    """Expose optional keyboard commands on one constructed MineStudio simulator."""

    minerl_env = getattr(simulator, "env", simulator)
    task = getattr(minerl_env, "task", None)
    if task is None:
        raise RuntimeError("MineStudio simulator does not expose its MineRL task")
    seen: set[int] = set()
    while getattr(task, "env_to_wrap", None) is not None:
        if id(task) in seen:
            raise RuntimeError("MineStudio task wrappers contain a cycle")
        seen.add(id(task))
        task = task.env_to_wrap

    actionables = getattr(task, "actionables", None)
    if not isinstance(actionables, MutableSequence):
        raise RuntimeError("MineStudio task does not expose mutable actionables")

    from minestudio.simulator.minerl.herobraine.hero import handlers as mine_studio_handlers

    return _append_missing_actionables(
        actionables,
        lambda command, key_code: mine_studio_handlers.KeybasedCommandAction(command, key_code),
        mine_studio_handlers.MouseWheelAction,
    )


def mine_studio_mouse_wheel_value(scroll: Any) -> float:
    """Map one canonical vertical scroll impulse to MineStudio's wheel lane."""

    if not isinstance(scroll, Mapping) or set(scroll) != {"dx", "dy"}:
        raise TypeError("scroll must contain only dx and dy")
    dx, dy = scroll.get("dx"), scroll.get("dy")
    if isinstance(dx, bool) or not isinstance(dx, (int, float)) or not math.isfinite(float(dx)) or float(dx) != 0.0:
        raise ValueError("MineStudio scroll.dx must be zero")
    if isinstance(dy, bool) or not isinstance(dy, (int, float)) or not math.isfinite(float(dy)) or float(dy) == 0.0:
        raise ValueError("MineStudio scroll.dy must be non-zero")
    return 1.0 if float(dy) < 0.0 else -1.0


__all__ = [
    "MINESTUDIO_INPUT_BRIDGE_MARKER",
    "MINESTUDIO_INPUT_BRIDGE_MARKER_CONTENT",
    "MINESTUDIO_ACTION_KEYS",
    "MINESTUDIO_CONTROL_KEY_TO_ACTION",
    "MINESTUDIO_INPUT_HELD_VALUE",
    "MINESTUDIO_INPUT_IMPULSE_VALUE",
    "MINESTUDIO_KEYBOARD_HELD_ACTIONS",
    "MINESTUDIO_KEYBOARD_IMPULSE_ACTIONS",
    "MINESTUDIO_KEYBOARD_INPUT_PROTOCOL",
    "MLLM_GAME_AGENT_MINESTUDIO_INPUT_PROTOCOL",
    "install_player1_input_actionables",
    "mine_studio_action_admission_error",
    "mine_studio_action_for_key",
    "mine_studio_mouse_wheel_value",
    "resolve_mine_studio_key_actions",
    "verify_mine_studio_input_bridge",
]

"""Shared parser helpers for computer-use agents."""

from __future__ import annotations

KEY_ALIASES = {
    "arrowleft": "ArrowLeft",
    "left": "ArrowLeft",
    "arrowright": "ArrowRight",
    "right": "ArrowRight",
    "arrowup": "ArrowUp",
    "up": "ArrowUp",
    "arrowdown": "ArrowDown",
    "down": "ArrowDown",
    "space": "Space",
    "spacebar": "Space",
    "enter": "Enter",
    "return": "Enter",
    "esc": "Escape",
    "escape": "Escape",
    "tab": "Tab",
    "backspace": "Backspace",
    "delete": "Delete",
    "del": "Delete",
    "shift": "Shift",
    "shiftleft": "Shift",
    "shiftright": "ShiftRight",
    "control": "Control",
    "ctrl": "Control",
    "controlleft": "Control",
    "controlright": "ControlRight",
    "alt": "Alt",
    "altleft": "Alt",
    "altright": "AltRight",
    "slash": "/",
    "period": ".",
    "comma": ",",
    "quote": "'",
    "apostrophe": "'",
    "semicolon": ";",
    "backslash": "\\",
    "bracketleft": "[",
    "bracketright": "]",
    "minus": "-",
    "equal": "=",
}


def normalize_key(key: str) -> str:
    """Normalize a key name to Playwright-compatible format."""
    normalized = str(key or "").strip()
    if not normalized:
        return ""
    if len(normalized) == 1:
        return normalized.lower()
    return KEY_ALIASES.get(normalized.lower(), normalized)


def normalize_coordinate(v: int | float, image_dim: int) -> float:
    """Normalize a coordinate from model pixel space to absolute pixels."""
    del image_dim
    try:
        return float(v)
    except Exception:
        return 0.0


def text_keys_to_list(k: str) -> list[str]:
    """Parse a key string into a list of keys."""
    k = (k or "").strip().lower()
    if not k:
        return []
    if "+" in k:
        return [p.strip() for p in k.split("+") if p.strip()]
    if " " in k:
        return [p.strip() for p in k.split(" ") if p.strip()]
    return [k]


def clamp_0_1000(v: int | float) -> int:
    """Clamp a value to the 0-1000 range."""
    f = float(v)
    return int(max(0, min(1000, round(f))))

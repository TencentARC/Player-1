"""Parse OpenAI computer-use responses into runtime actions."""

from __future__ import annotations

from typing import Any, Dict

from ..base.parser_utils import normalize_key


def _get_value(payload: Any, *names: str) -> Any:
    for name in names:
        if isinstance(payload, dict) and name in payload:
            return payload.get(name)
        value = getattr(payload, name, None)
        if value is not None:
            return value
    return None


def _coerce_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_point(
    payload: Any, *field_pairs: tuple[str, str], containers: tuple[str, ...] = ()
) -> tuple[float, float] | None:
    for x_name, y_name in field_pairs:
        x = _coerce_float(_get_value(payload, x_name))
        y = _coerce_float(_get_value(payload, y_name))
        if x is not None and y is not None:
            return x, y

    for key in containers:
        point = _get_value(payload, key)
        if isinstance(point, (list, tuple)) and len(point) >= 2:
            x = _coerce_float(point[0])
            y = _coerce_float(point[1])
            if x is not None and y is not None:
                return x, y
        if isinstance(point, dict):
            x = _coerce_float(point.get("x"))
            y = _coerce_float(point.get("y"))
            if x is not None and y is not None:
                return x, y
    return None


def _extract_duration(payload: Any) -> float | None:
    return _coerce_float(
        _get_value(
            payload,
            "duration",
            "seconds",
            "hold_duration",
            "hold_seconds",
        )
    )


def _is_same_point(
    first: tuple[float, float] | None, second: tuple[float, float] | None
) -> bool:
    if first is None or second is None:
        return False
    return abs(first[0] - second[0]) <= 1.0 and abs(first[1] - second[1]) <= 1.0


def parse_openai_computer_action(
    action: Any, display_w: int = 1024, display_h: int = 768
) -> Dict[str, object] | None:
    """Parse a single OpenAI computer action into a standardized action dict.

    Args:
        action: The action object from OpenAI's response.
        display_w: Display width hint (used for coordinate normalization).
        display_h: Display height hint (used for coordinate normalization).

    Returns:
        Action dictionary or None if action type is unsupported.
        Coordinates are in absolute pixels.
    """
    a_type = _get_value(action, "type")

    if a_type == "click":
        point = _extract_point(
            action,
            ("x", "y"),
            ("client_x", "client_y"),
            containers=("coordinate", "position"),
        )
        if point is None:
            return None
        x, y = point
        button = _get_value(action, "button")
        # OpenAI returns absolute pixel coordinates based on display hints
        # Return as-is (already absolute)
        normalized_button = str(button).lower() if button is not None else "left"
        payload: Dict[str, object] = {"action": "click", "x": x, "y": y}
        if normalized_button in {"right", "middle"}:
            payload["button"] = normalized_button
        return payload

    if a_type == "double_click":
        point = _extract_point(
            action,
            ("x", "y"),
            ("client_x", "client_y"),
            containers=("coordinate", "position"),
        )
        if point is None:
            return None
        x, y = point
        # For browser games, treat double-click as single click
        return {"action": "click", "x": x, "y": y}

    if a_type == "move":
        point = _extract_point(
            action,
            ("x", "y"),
            ("client_x", "client_y"),
            containers=("coordinate", "position"),
        )
        if point is None:
            return None
        x, y = point
        return {
            "action": "mouse_move",
            "from_x": float(display_w) * 0.5,
            "from_y": float(display_h) * 0.5,
            "x": x,
            "y": y,
        }

    if a_type in {"drag", "drag_to"}:
        start = _extract_point(
            action,
            ("start_x", "start_y"),
            ("from_x", "from_y"),
            containers=("start", "from", "origin", "start_position"),
        )
        end = _extract_point(
            action,
            ("end_x", "end_y"),
            ("destination_x", "destination_y"),
            ("x", "y"),
            containers=("end", "to", "destination", "coordinate", "position"),
        )
        duration = _extract_duration(action)

        if start is None and end is not None and duration is not None:
            payload = {"action": "click_hold", "x": end[0], "y": end[1]}
            payload["duration"] = duration
            return payload

        if _is_same_point(start, end):
            payload = {"action": "click_hold", "x": start[0], "y": start[1]}
            if duration is not None:
                payload["duration"] = duration
            return payload

        if start is None or end is None:
            return None

        payload = {
            "action": "drag",
            "x1": start[0],
            "y1": start[1],
            "x2": end[0],
            "y2": end[1],
        }
        if duration is not None:
            payload["duration"] = duration
        return payload

    if a_type == "scroll":
        sx = _get_value(action, "scroll_x")
        sy = _get_value(action, "scroll_y")
        sx = int(sx) if sx is not None else 0
        sy = int(sy) if sy is not None else 0
        # Map scroll to arrow keys for browser games
        direction = (
            "down"
            if sy > 0
            else "up"
            if sy < 0
            else ("right" if sx > 0 else "left" if sx < 0 else "down")
        )
        key_map = {
            "down": "ArrowDown",
            "up": "ArrowUp",
            "left": "ArrowLeft",
            "right": "ArrowRight",
        }
        return {"action": "press_key", "key": key_map[direction]}

    if a_type == "keypress":
        keys = _get_value(action, "keys")
        if isinstance(keys, (list, tuple)) and keys:
            # Multiple keys: create press_keys action for combos
            if len(keys) > 1:
                normalized_keys = [normalize_key(str(k)) for k in keys]
                return {"action": "press_keys", "keys": normalized_keys}
            else:
                # Single key
                key = normalize_key(str(keys[0]))
                return {"action": "press_key", "key": key}
        if isinstance(keys, str):
            # Split by '+' and whitespace
            import re

            parts = [k.strip() for k in re.split(r"[\s+]+", keys) if k.strip()]
            if len(parts) > 1:
                normalized_keys = [normalize_key(k) for k in parts]
                return {"action": "press_keys", "keys": normalized_keys}
            elif parts:
                return {"action": "press_key", "key": normalize_key(parts[0])}

    if a_type == "type":
        text = _get_value(action, "text")
        if text:
            return {"action": "type", "text": str(text)}
        return {"action": "wait"}

    if a_type == "wait":
        duration = _get_value(action, "duration")
        if duration is not None:
            return {"action": "wait", "duration": duration}
        else:
            return {"action": "wait"}

    return None


def parse_openai_output_items(
    output_items: list[Any],
) -> tuple[list[Dict[str, object]], str | None]:
    """Parse OpenAI Responses API output items into actions and thought.

    Args:
        output_items: List of output items from OpenAI responses.create().

    Returns:
        Tuple of (actions list, thought text or None).
    """
    actions: list[Dict[str, object]] = []
    thought_chunks: list[str] = []

    for item in output_items or []:
        t = getattr(item, "type", None) or (
            item.get("type") if isinstance(item, dict) else None
        )

        if t == "reasoning":
            summary = getattr(item, "summary", None) or (
                item.get("summary") if isinstance(item, dict) else None
            )
            if isinstance(summary, list):
                for s in summary:
                    text = getattr(s, "text", None) or (
                        s.get("text") if isinstance(s, dict) else None
                    )
                    if text:
                        thought_chunks.append(str(text))

        if t == "computer_call":
            action = getattr(item, "action", None) or (
                item.get("action") if isinstance(item, dict) else None
            )
            parsed = parse_openai_computer_action(action)
            if parsed is not None:
                actions.append(parsed)

    thought = "\n".join(thought_chunks) if thought_chunks else None
    return actions, thought


__all__ = ["parse_openai_computer_action", "parse_openai_output_items"]

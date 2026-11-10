"""Parse Claude computer-use tool blocks into runtime actions."""

from typing import Any, Dict

from ..base.parser_utils import normalize_coordinate, normalize_key, text_keys_to_list


def _scale_coordinate(value: Any, image_dim: int, coordinate_scale: float) -> float:
    scaled = normalize_coordinate(value, image_dim)
    inv_scale = 1.0 / max(float(coordinate_scale or 1.0), 1e-6)
    return float(scaled * inv_scale)


def _extract_coordinate(
    payload: dict,
    *keys: str,
) -> list[float] | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, (list, tuple)) and len(value) >= 2:
            return [value[0], value[1]]
    return None


def _coerce_duration(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_same_point(start: tuple[float, float], end: tuple[float, float]) -> bool:
    return abs(start[0] - end[0]) <= 1.0 and abs(start[1] - end[1]) <= 1.0


def parse_claude_tool_use_block(
    block: Any,
    image_w: int,
    image_h: int,
    coordinate_scale: float = 1.0,
) -> list[Dict[str, object]]:
    """Parse a Claude tool_use block into action dictionaries.

    Args:
        block: A tool_use block from Claude's response.
        image_w: Screenshot width in pixels.
        image_h: Screenshot height in pixels.
        coordinate_scale: API-side image scale factor. Coordinates are scaled back by 1/scale.

    Returns:
        List of action dictionaries.
    """
    actions: list[Dict[str, object]] = []

    name = getattr(block, "name", None) or getattr(block, "tool_name", None) or ""
    if str(name) != "computer":
        return actions

    data = getattr(block, "input", None) or {}
    if not isinstance(data, dict):  # pragma: no cover - defensive
        try:
            data = dict(data)
        except Exception:
            return actions

    action = str(data.get("action", "")).lower()

    if action in (
        "left_click",
        "right_click",
        "double_click",
        "triple_click",
        "middle_click",
    ):
        coord = _extract_coordinate(data, "coordinate", "coordinates")
        if coord is None:
            return actions
        x = _scale_coordinate(coord[0], image_w, coordinate_scale)
        y = _scale_coordinate(coord[1], image_h, coordinate_scale)

        payload: Dict[str, object] = {"action": "click", "x": x, "y": y}
        if action == "right_click":
            payload["button"] = "right"
        elif action == "middle_click":
            payload["button"] = "middle"
        actions.append(payload)

    elif action == "mouse_move":
        coord = _extract_coordinate(data, "coordinate", "coordinates")
        if coord is None:
            return actions
        x = _scale_coordinate(coord[0], image_w, coordinate_scale)
        y = _scale_coordinate(coord[1], image_h, coordinate_scale)
        actions.append(
            {
                "action": "mouse_move",
                "from_x": float(image_w) * 0.5,
                "from_y": float(image_h) * 0.5,
                "x": x,
                "y": y,
            }
        )

    elif action in ("left_mouse_down", "mouse_down"):
        coord = _extract_coordinate(data, "coordinate", "coordinates")
        if coord is None:
            return actions
        x = _scale_coordinate(coord[0], image_w, coordinate_scale)
        y = _scale_coordinate(coord[1], image_h, coordinate_scale)
        payload: Dict[str, object] = {"action": "click_hold", "x": x, "y": y}
        duration = _coerce_duration(data.get("seconds", data.get("duration")))
        if duration is not None and duration > 0:
            payload["duration"] = duration
        actions.append(payload)

    elif action in ("left_click_drag", "drag"):
        start = _extract_coordinate(data, "start_coordinate", "from")
        end = _extract_coordinate(
            data, "coordinate", "coordinate2", "end_coordinate", "to"
        )
        if start is None or end is None:
            return actions

        x1 = _scale_coordinate(start[0], image_w, coordinate_scale)
        y1 = _scale_coordinate(start[1], image_h, coordinate_scale)
        x2 = _scale_coordinate(end[0], image_w, coordinate_scale)
        y2 = _scale_coordinate(end[1], image_h, coordinate_scale)
        if _is_same_point((x1, y1), (x2, y2)):
            payload: Dict[str, object] = {"action": "click_hold", "x": x1, "y": y1}
            duration = _coerce_duration(data.get("seconds", data.get("duration")))
            if duration is not None and duration > 0:
                payload["duration"] = duration
            actions.append(payload)
        else:
            actions.append({"action": "drag", "x1": x1, "y1": y1, "x2": x2, "y2": y2})

    elif action == "scroll":
        # Map scroll to arrow keys
        dir_ = str(data.get("scroll_direction", "down")).lower()
        key_map = {
            "down": "ArrowDown",
            "up": "ArrowUp",
            "left": "ArrowLeft",
            "right": "ArrowRight",
        }
        key = key_map.get(dir_, "ArrowDown")
        actions.append({"action": "press_key", "key": key})

    elif action == "type":
        text = data.get("text")
        if text is None:
            return actions
        actions.append({"action": "type", "text": str(text)})

    elif action in ("key", "hold_key"):
        # Anthropic computer-use may emit key payloads in `key`, `text`, or `keys`.
        key_value: Any = data.get("key")
        if key_value in (None, ""):
            key_value = data.get("text")
        if key_value in (None, ""):
            key_value = data.get("keys")

        keys: list[str] = []
        if isinstance(key_value, str):
            keys = text_keys_to_list(key_value)
        elif isinstance(key_value, (list, tuple)):
            for item in key_value:
                if not isinstance(item, str):
                    continue
                keys.extend(text_keys_to_list(item))

        duration = None
        if action == "hold_key":
            try:
                raw_duration = data.get("seconds", data.get("duration"))
                duration = float(raw_duration or 0)
            except Exception:
                duration = None
            if duration is not None and duration <= 0:
                duration = None

        if len(keys) > 1:
            # Multiple keys: create press_keys action for combos
            normalized_keys = [normalize_key(k) for k in keys]
            payload: Dict[str, object] = {
                "action": "press_keys",
                "keys": normalized_keys,
            }
            if duration is not None:
                payload["duration"] = duration
            actions.append(payload)
        elif keys:
            # Single key
            payload = {"action": "press_key", "key": normalize_key(keys[0])}
            if duration is not None:
                payload["duration"] = duration
            actions.append(payload)

    elif action == "wait":
        seconds = data.get("seconds", data.get("duration"))
        actions.append({"action": "wait", "duration": seconds})

    # 'screenshot' and 'zoom' produce no action
    return actions


__all__ = ["parse_claude_tool_use_block"]

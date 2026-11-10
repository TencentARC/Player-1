"""Parse UI-TARS-style text outputs into runtime actions."""

from __future__ import annotations

import ast
import re

from ..base.parser_utils import normalize_key

CLICK_ACTION_BUTTONS = {
    "click": None,
    "left_single": None,
    "left_click": None,
    "left_double": None,
    "double_click": None,
    "right_single": "right",
    "right_click": "right",
}
CLICK_HOLD_ACTIONS = {"click_hold", "left_click_hold", "left_hold", "mouse_down"}
KEY_ACTIONS = {"hotkey", "press_key", "press_keys", "press", "keydown", "game_action"}
DRAG_ACTIONS = {"drag", "drag_drop", "drag_and_drop"}
WAIT_ACTIONS = {"wait", "finished"}


def parse_ui_tars_action(
    raw_text: str,
    width: int,
    height: int,
    *,
    normalized_coordinates: bool = False,
) -> dict[str, object]:
    """Parse a UI-TARS style response into one action dictionary."""
    text = raw_text.strip()
    if "Action:" in text:
        action_segment = text.split("Action:", 1)[1].strip()
    else:
        action_segment = text

    if action_segment.startswith("{"):
        import json

        try:
            obj = json.loads(action_segment)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Failed to parse JSON action: {action_segment!r}"
            ) from exc

        action_type = obj.get("action")
        action_type_normalized = (
            action_type.strip().lower() if isinstance(action_type, str) else ""
        )
        if action_type_normalized in CLICK_ACTION_BUTTONS:
            return _parse_click_action(
                obj,
                width,
                height,
                normalized_coordinates=normalized_coordinates,
                button=CLICK_ACTION_BUTTONS[action_type_normalized],
            )
        if action_type_normalized == "mouse_move":
            x = float(obj["x"])
            y = float(obj["y"])
            return {
                "action": "mouse_move",
                "from_x": float(width) * 0.5,
                "from_y": float(height) * 0.5,
                "x": x,
                "y": y,
            }
        if action_type_normalized in CLICK_HOLD_ACTIONS:
            x, y = _extract_action_point(
                obj,
                width,
                height,
                normalized_coordinates=normalized_coordinates,
            )
            payload: dict[str, object] = {"action": "click_hold", "x": x, "y": y}
            button = str(obj.get("button", "")).strip().lower()
            if button in {"right", "middle"}:
                payload["button"] = button
            duration = _parse_duration(obj.get("duration"))
            if duration is not None:
                payload["duration"] = duration
            return payload
        if action_type_normalized in DRAG_ACTIONS:
            payload = _parse_drag_action(
                obj,
                width,
                height,
                normalized_coordinates=normalized_coordinates,
            )
            duration = obj.get("duration")
            if duration is not None:
                payload["duration"] = duration
            return payload
        if action_type_normalized in KEY_ACTIONS:
            raw_keys = obj.get("keys", obj.get("key", ""))
            payload = _parse_key_action(raw_keys)
            duration = obj.get("duration")
            if duration is not None:
                payload["duration"] = duration
            return payload
        if action_type_normalized == "type":
            text = obj.get("text", obj.get("content", ""))
            if not isinstance(text, str) or not text:
                raise RuntimeError(
                    f"Empty or invalid text in JSON type action: {obj!r}"
                )
            return {"action": "type", "text": text}
        if action_type_normalized == "scroll":
            return _parse_scroll_action(
                obj,
                width,
                height,
                normalized_coordinates=normalized_coordinates,
            )
        if action_type_normalized in WAIT_ACTIONS:
            duration = obj.get("duration")
            if duration is not None:
                return {"action": "wait", "duration": duration}
            return {"action": "wait"}
        raise RuntimeError(f"Unsupported JSON action type: {action_type!r}")

    action_line = (
        action_segment.strip().split("\n")[0]
        if "\n" in action_segment
        else action_segment.strip()
    )
    try:
        func_name, kwargs = _parse_function_call(action_line)
    except Exception as exc:
        raise RuntimeError(f"Failed to parse UI-TARS action: {action_line!r}") from exc

    func_name = func_name.lower()

    if func_name in CLICK_ACTION_BUTTONS:
        return _parse_click_action(
            kwargs,
            width,
            height,
            normalized_coordinates=normalized_coordinates,
            button=CLICK_ACTION_BUTTONS[func_name],
        )

    if func_name == "mouse_move":
        point_str = (
            kwargs.get("point") or kwargs.get("target") or kwargs.get("coordinate")
        )
        x, y = _parse_point(
            point_str, width, height, normalized_coordinates=normalized_coordinates
        )
        return {
            "action": "mouse_move",
            "from_x": float(width) * 0.5,
            "from_y": float(height) * 0.5,
            "x": x,
            "y": y,
        }

    if func_name in CLICK_HOLD_ACTIONS:
        x, y = _extract_action_point(
            kwargs,
            width,
            height,
            normalized_coordinates=normalized_coordinates,
        )
        payload: dict[str, object] = {"action": "click_hold", "x": x, "y": y}
        button = str(kwargs.get("button", "")).strip().lower()
        if button in {"right", "middle"}:
            payload["button"] = button
        duration = _parse_duration(kwargs.get("duration"))
        if duration is not None:
            payload["duration"] = duration
        return payload

    if func_name in DRAG_ACTIONS:
        return _parse_drag_action(
            kwargs,
            width,
            height,
            normalized_coordinates=normalized_coordinates,
        )

    if func_name in KEY_ACTIONS:
        raw_keys = kwargs.get("keys") or kwargs.get("key") or ""
        return _parse_key_action(raw_keys)

    if func_name == "scroll":
        return _parse_scroll_action(
            kwargs,
            width,
            height,
            normalized_coordinates=normalized_coordinates,
        )

    if func_name == "type":
        text = kwargs.get("content") or kwargs.get("text") or ""
        if not isinstance(text, str) or not text:
            raise RuntimeError(f"Empty or invalid text in type action: {kwargs}")
        return {"action": "type", "text": text}

    if func_name in WAIT_ACTIONS:
        duration = kwargs.get("duration")
        if duration is not None:
            return {"action": "wait", "duration": duration}
        return {"action": "wait"}

    raise RuntimeError(f"Unsupported UI-TARS action_type: {func_name!r}")


def _parse_function_call(action_str: str) -> tuple[str, dict[str, str]]:
    if not action_str.rstrip().endswith(")"):
        action_str = action_str + ")"

    node = ast.parse(action_str, mode="eval")
    if not isinstance(node, ast.Expression) or not isinstance(node.body, ast.Call):
        raise ValueError(f"Not a call expression: {action_str}")

    call = node.body
    if isinstance(call.func, ast.Name):
        func_name = call.func.id
    elif isinstance(call.func, ast.Attribute):
        func_name = call.func.attr
    else:
        raise ValueError(f"Unsupported function form in: {action_str}")

    kwargs: dict[str, str] = {}
    for kw in call.keywords:
        key = kw.arg
        if key is None:
            continue
        val_node = kw.value
        if isinstance(val_node, ast.Constant):
            kwargs[key] = str(val_node.value)
        elif isinstance(val_node, ast.Str):
            kwargs[key] = val_node.s
        else:
            kwargs[key] = action_str[val_node.col_offset : val_node.end_col_offset]
    return func_name, kwargs


def _denormalize(
    raw_x: float, raw_y: float, width: int, height: int
) -> tuple[float, float]:
    x = max(0.0, min(1000.0, raw_x)) / 1000.0 * width
    y = max(0.0, min(1000.0, raw_y)) / 1000.0 * height
    return x, y


def _parse_key_action(raw_keys: object) -> dict[str, object]:
    if isinstance(raw_keys, (list, tuple)):
        parts = [str(part).strip() for part in raw_keys if str(part).strip()]
    elif isinstance(raw_keys, str):
        parts = [part for part in re.split(r"[,+\s]+", raw_keys.strip()) if part]
    else:
        raise RuntimeError(f"Invalid key field: {raw_keys!r}")
    if not parts:
        raise RuntimeError("Empty key string from UI-TARS")
    normalized_keys = [normalize_key(part) for part in parts]
    return (
        {"action": "press_key", "key": normalized_keys[0]}
        if len(normalized_keys) == 1
        else {"action": "press_keys", "keys": normalized_keys}
    )


def _extract_action_point(
    payload: dict[str, object],
    width: int,
    height: int,
    *,
    normalized_coordinates: bool,
) -> tuple[float, float]:
    if "x" in payload and "y" in payload:
        return float(payload["x"]), float(payload["y"])
    point_str = payload.get("point") or payload.get("start_box")
    return _parse_point(
        point_str,
        width,
        height,
        normalized_coordinates=normalized_coordinates,
    )


def _parse_click_action(
    payload: dict[str, object],
    width: int,
    height: int,
    *,
    normalized_coordinates: bool,
    button: str | None = None,
) -> dict[str, object]:
    x, y = _extract_click_point(
        payload,
        width,
        height,
        normalized_coordinates=normalized_coordinates,
    )
    action: dict[str, object] = {"action": "click", "x": x, "y": y}
    resolved_button = str(button or payload.get("button", "")).strip().lower()
    if resolved_button in {"right", "middle"}:
        action["button"] = resolved_button
    return action


def _extract_click_point(
    payload: dict[str, object],
    width: int,
    height: int,
    *,
    normalized_coordinates: bool,
) -> tuple[float, float]:
    has_point = (
        ("x" in payload or "y" in payload)
        or bool(payload.get("point"))
        or bool(payload.get("start_box"))
    )
    if not has_point and set(payload).issubset({"action"}):
        return float(width) * 0.5, float(height) * 0.5
    return _extract_action_point(
        payload,
        width,
        height,
        normalized_coordinates=normalized_coordinates,
    )


def _parse_drag_action(
    payload: dict[str, object],
    width: int,
    height: int,
    *,
    normalized_coordinates: bool,
) -> dict[str, object]:
    if all(key in payload for key in ("x1", "y1", "x2", "y2")):
        return {
            "action": "drag",
            "x1": float(payload["x1"]),
            "y1": float(payload["y1"]),
            "x2": float(payload["x2"]),
            "y2": float(payload["y2"]),
        }

    start_str = (
        payload.get("start_point")
        or payload.get("start")
        or payload.get("start_box")
        or payload.get("point")
    )
    end_str = (
        payload.get("end_point")
        or payload.get("end")
        or payload.get("end_box")
        or payload.get("target")
    )
    if not start_str or not end_str:
        raise RuntimeError(f"Drag action missing points: {payload}")
    x1, y1 = _parse_point(
        start_str,
        width,
        height,
        normalized_coordinates=normalized_coordinates,
    )
    x2, y2 = _parse_point(
        end_str,
        width,
        height,
        normalized_coordinates=normalized_coordinates,
    )
    return {"action": "drag", "x1": x1, "y1": y1, "x2": x2, "y2": y2}


def _parse_scroll_action(
    payload: dict[str, object],
    width: int,
    height: int,
    *,
    normalized_coordinates: bool,
) -> dict[str, object]:
    if "delta_x" in payload or "delta_y" in payload:
        return {
            "action": "scroll",
            "delta_x": float(payload.get("delta_x", 0) or 0),
            "delta_y": float(payload.get("delta_y", 0) or 0),
        }

    direction = str(payload.get("direction", "")).strip().lower()
    direction_deltas = {
        "down": (0.0, 500.0),
        "up": (0.0, -500.0),
        "right": (500.0, 0.0),
        "left": (-500.0, 0.0),
    }
    if direction not in direction_deltas:
        raise RuntimeError(f"Unsupported scroll direction: {direction!r}")

    delta_x, delta_y = direction_deltas[direction]
    action: dict[str, object] = {
        "action": "scroll",
        "delta_x": delta_x,
        "delta_y": delta_y,
    }
    point_str = payload.get("point") or payload.get("start_box")
    if point_str:
        x, y = _parse_point(
            point_str,
            width,
            height,
            normalized_coordinates=normalized_coordinates,
        )
        action["x"] = x
        action["y"] = y
    return action


def _parse_point(
    point_str: object,
    width: int,
    height: int,
    *,
    normalized_coordinates: bool,
) -> tuple[float, float]:
    if not isinstance(point_str, str) or not point_str.strip():
        raise ValueError(f"Unrecognized point format: {point_str}")

    point_match = re.search(
        r"<point>\s*(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s*</point>",
        point_str,
    )
    if point_match:
        x = float(point_match.group(1))
        y = float(point_match.group(2))
        return _denormalize(x, y, width, height) if normalized_coordinates else (x, y)

    if point_str.startswith("(") and point_str.endswith(")"):
        inside = point_str[1:-1]
        parts = [p.strip() for p in inside.split(",")]
        if len(parts) == 2:
            x = float(parts[0])
            y = float(parts[1])
            return (
                _denormalize(x, y, width, height) if normalized_coordinates else (x, y)
            )

    parts = re.split(r"[\s,]+", re.sub(r"[()\[\]]", " ", point_str).strip())
    if len(parts) >= 2:
        x = float(parts[0])
        y = float(parts[1])
        return _denormalize(x, y, width, height) if normalized_coordinates else (x, y)

    raise ValueError(f"Unrecognized point format: {point_str}")


def _parse_duration(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


__all__ = ["parse_ui_tars_action"]

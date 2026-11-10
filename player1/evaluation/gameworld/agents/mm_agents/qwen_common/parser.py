"""Parse Qwen-VL tool calls into runtime actions."""

import json
import re


_TOOL_CALL_PATTERN = re.compile(
    r"<tool(?:\s+|_)call>\s*([\s\S]*?)\s*</tool(?:\s+|_)call>",
    flags=re.IGNORECASE,
)
_FUNCTION_PATTERN = re.compile(
    r"<function\s*=\s*([^>\s]+)\s*>([\s\S]*?)</function\s*>",
    flags=re.IGNORECASE,
)
_PARAMETER_PATTERN = re.compile(
    r"<parameter\s*=\s*([^>\s]+)\s*>([\s\S]*?)</parameter\s*>",
    flags=re.IGNORECASE,
)


def _parse_argument_value(raw_value: str) -> object:
    value = raw_value.strip()
    if not value:
        return ""
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def parse_qwen_function_tool_calls(raw_text: str) -> list[dict[str, object]]:
    """Parse Qwen3.5/3.6 ``function``/``parameter`` XML tool calls."""
    tool_calls: list[dict[str, object]] = []
    for tool_match in _TOOL_CALL_PATTERN.finditer(raw_text):
        function_match = _FUNCTION_PATTERN.fullmatch(tool_match.group(1).strip())
        if function_match is None:
            continue

        function_name = function_match.group(1).strip()
        if not function_name:
            continue

        arguments: dict[str, object] = {}
        for parameter_match in _PARAMETER_PATTERN.finditer(function_match.group(2)):
            argument_name = parameter_match.group(1).strip()
            if argument_name:
                arguments[argument_name] = _parse_argument_value(
                    parameter_match.group(2)
                )

        tool_calls.append({"name": function_name, "arguments": arguments})
    return tool_calls


def _parse_qwen_json_tool_calls(raw_text: str) -> list[dict[str, object]]:
    tool_calls: list[dict[str, object]] = []
    for tool_match in _TOOL_CALL_PATTERN.finditer(raw_text):
        try:
            payload = json.loads(tool_match.group(1).strip())
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            tool_calls.append(payload)
    return tool_calls


def _denormalize(
    raw_x: float, raw_y: float, image_w: int, image_h: int
) -> tuple[float, float]:
    """Denormalize 0-1000 coordinates to absolute viewport pixels.

    Qwen VL models output coordinates in a normalized 0-1000 range regardless
    of the stated screen resolution in the prompt.
    """
    x = max(0.0, min(1000.0, raw_x)) / 1000.0 * image_w
    y = max(0.0, min(1000.0, raw_y)) / 1000.0 * image_h
    return x, y


def _coerce_duration(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_qwen_actions(
    tool_calls: list[dict[str, object]], image_w: int, image_h: int
) -> list[dict[str, object]]:
    """Convert normalized Qwen tool-call payloads into runtime actions."""
    actions: list[dict[str, object]] = []
    deprecated_actions = {
        "left_click",
        "right_click",
        "left_click_hold",
        "left_click_and_hold",
        "left_click_drag",
        "keypress",
        "key_press",
        "press",
        "key_combination",
        "input_text",
        "type_text",
        "terminate",
        "finished",
    }

    def _parse_coordinate(coord: object) -> tuple[float, float] | None:
        """Parse raw coordinate and denormalize from 0-1000 to viewport pixels."""
        raw: tuple[float, float] | None = None
        if isinstance(coord, (list, tuple)) and len(coord) >= 2:
            try:
                raw = (float(coord[0]), float(coord[1]))
            except (TypeError, ValueError):
                return None
        elif isinstance(coord, dict):
            x = coord.get("x")
            y = coord.get("y")
            if isinstance(x, (int, float)) and isinstance(y, (int, float)):
                raw = (float(x), float(y))
        elif isinstance(coord, str):
            nums = re.findall(r"-?\d+(?:\.\d+)?", coord)
            if len(nums) >= 2:
                try:
                    raw = (float(nums[0]), float(nums[1]))
                except (TypeError, ValueError):
                    return None
        if raw is None:
            return None
        return _denormalize(raw[0], raw[1], image_w, image_h)

    def _split_keys(keys_value: object) -> list[str]:
        if isinstance(keys_value, str):
            parts = [k for k in re.split(r"[\s+]+", keys_value.strip()) if k]
            return parts
        if isinstance(keys_value, (list, tuple)):
            parts: list[str] = []
            for item in keys_value:
                if isinstance(item, str):
                    parts.append(item)
            return parts
        return []

    for obj in tool_calls:
        args = obj.get("arguments", {}) or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        if not isinstance(args, dict):
            args = {}

        tool_name = str(obj.get("name", "")).strip().lower()
        action = str(args.get("action", "")).strip().lower()
        if not action and tool_name and tool_name != "computer_use":
            action = tool_name
        if action in deprecated_actions:
            raise RuntimeError(f"Deprecated Qwen action verb: {action}")

        if action == "click":
            coord = args.get("coordinate")
            parsed = _parse_coordinate(coord)
            if not parsed:
                continue
            x, y = parsed
            payload: dict[str, object] = {"action": "click", "x": x, "y": y}
            button = str(args.get("button", "")).strip().lower()
            if button in {"right", "middle"}:
                payload["button"] = button
            actions.append(payload)

        elif action == "click_hold":
            coord = args.get("coordinate")
            parsed = _parse_coordinate(coord)
            if not parsed:
                continue
            x, y = parsed
            payload: dict[str, object] = {"action": "click_hold", "x": x, "y": y}
            button = str(args.get("button", "")).strip().lower()
            if button in {"right", "middle"}:
                payload["button"] = button
            duration = _coerce_duration(args.get("duration"))
            if duration is not None:
                payload["duration"] = duration
            actions.append(payload)

        elif action == "drag":
            start = _parse_coordinate(args.get("start_coordinate") or args.get("start"))
            end = _parse_coordinate(
                args.get("coordinate") or args.get("end_coordinate") or args.get("end")
            )
            if not start or not end:
                continue
            actions.append(
                {
                    "action": "drag",
                    "x1": start[0],
                    "y1": start[1],
                    "x2": end[0],
                    "y2": end[1],
                }
            )

        elif action == "press_key":
            key = args.get("key") or args.get("keys")
            keys = _split_keys(key)
            if not keys:
                continue
            duration = args.get("duration")
            if len(keys) == 1:
                payload = {"action": "press_key", "key": keys[0]}
            else:
                payload = {"action": "press_keys", "keys": keys}
            if isinstance(duration, (int, float)):
                payload["duration"] = float(duration)
            actions.append(payload)

        elif action == "press_keys":
            keys = _split_keys(args.get("keys") or args.get("key"))
            if not keys:
                continue
            duration = args.get("duration")
            payload: dict[str, object]
            if len(keys) == 1:
                payload = {"action": "press_key", "key": keys[0]}
            else:
                payload = {"action": "press_keys", "keys": keys}
            if isinstance(duration, (int, float)):
                payload["duration"] = float(duration)
            actions.append(payload)

        elif action == "type":
            text = args.get("text")
            if text is None:
                text = args.get("value")
            if text is not None:
                actions.append({"action": "type", "text": str(text)})

        elif action == "wait":
            duration = args.get("duration")
            actions.append({"action": "wait", "duration": duration})

        elif action == "mouse_move":
            coord = args.get("coordinate")
            parsed = _parse_coordinate(coord)
            if not parsed:
                continue
            x, y = parsed
            actions.append(
                {
                    "action": "mouse_move",
                    "from_x": float(image_w) * 0.5,
                    "from_y": float(image_h) * 0.5,
                    "x": x,
                    "y": y,
                }
            )

    return actions


def parse_qwen_tool_calls(
    raw_text: str, image_w: int, image_h: int
) -> list[dict[str, object]]:
    """Parse Qwen3-VL JSON-in-XML tool calls into runtime actions."""
    return _parse_qwen_actions(
        _parse_qwen_json_tool_calls(raw_text), image_w=image_w, image_h=image_h
    )


__all__ = [
    "parse_qwen_function_tool_calls",
    "parse_qwen_tool_calls",
]

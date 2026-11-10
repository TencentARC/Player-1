"""Parse Gemini computer-use function calls into runtime actions."""

from __future__ import annotations

from typing import Any, Dict

from ..base.parser_utils import clamp_0_1000, normalize_key


def _denormalize(
    args: dict[str, Any],
    x_key: str = "x",
    y_key: str = "y",
    *,
    image_w: int,
    image_h: int,
) -> tuple[float, float]:
    nx = clamp_0_1000(args.get(x_key, 0))
    ny = clamp_0_1000(args.get(y_key, 0))
    return float(nx) / 1000.0 * image_w, float(ny) / 1000.0 * image_h


def _same_point(x1: float, y1: float, x2: float, y2: float) -> bool:
    return abs(x1 - x2) <= 1.0 and abs(y1 - y2) <= 1.0


def _coerce_duration(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_gemini_function_calls(
    parts: list[Any], image_w: int, image_h: int
) -> list[Dict[str, object]]:
    """Parse Gemini function_call parts into action dictionaries."""
    actions: list[Dict[str, object]] = []

    for p in parts or []:
        fc = getattr(p, "function_call", None)
        if not fc:
            continue

        name = getattr(fc, "name", "") or ""
        args = getattr(fc, "args", {}) or {}
        if not isinstance(args, dict):
            try:
                args = dict(args)
            except Exception:
                args = {}
        n = name.lower()

        if n == "click_at":
            x, y = _denormalize(args, image_w=image_w, image_h=image_h)
            button = str(args.get("button", "left")).lower()
            payload: Dict[str, object] = {"action": "click", "x": x, "y": y}
            if button in {"right", "middle"}:
                payload["button"] = button
            actions.append(payload)

        elif n == "hover_at":
            x, y = _denormalize(args, image_w=image_w, image_h=image_h)
            actions.append(
                {
                    "action": "mouse_move",
                    "from_x": float(image_w) * 0.5,
                    "from_y": float(image_h) * 0.5,
                    "x": x,
                    "y": y,
                }
            )

        elif n == "right_click_at":
            x, y = _denormalize(args, image_w=image_w, image_h=image_h)
            actions.append({"action": "click", "x": x, "y": y, "button": "right"})

        elif n == "type_text_at":
            x, y = _denormalize(args, image_w=image_w, image_h=image_h)
            text = str(args.get("text", ""))
            press_enter = bool(args.get("press_enter", False))
            type_action: Dict[str, object] = {"action": "type", "text": text}
            if press_enter:
                type_action["press_enter"] = True
            type_action["x"] = x
            type_action["y"] = y
            actions.append(type_action)

        elif n == "scroll_at":
            direction = str(args.get("direction", "down")).lower()
            key_map = {
                "down": "ArrowDown",
                "up": "ArrowUp",
                "left": "ArrowLeft",
                "right": "ArrowRight",
            }
            actions.append(
                {"action": "press_key", "key": key_map.get(direction, "ArrowDown")}
            )

        elif n == "drag_and_drop":
            x1, y1 = _denormalize(args, image_w=image_w, image_h=image_h)
            x2, y2 = _denormalize(
                args,
                x_key="destination_x",
                y_key="destination_y",
                image_w=image_w,
                image_h=image_h,
            )
            hold_duration = _coerce_duration(
                args.get("duration", args.get("hold_duration"))
            )
            if _same_point(x1, y1, x2, y2):
                payload: Dict[str, object] = {"action": "click_hold", "x": x1, "y": y1}
                if hold_duration is not None:
                    payload["duration"] = hold_duration
                actions.append(payload)
            else:
                actions.append(
                    {
                        "action": "drag",
                        "x1": x1,
                        "y1": y1,
                        "x2": x2,
                        "y2": y2,
                        "steps": 20,
                        "duration": hold_duration if hold_duration is not None else 0.5,
                    }
                )

        elif n == "key_combination":
            keys = args.get("keys")
            if isinstance(keys, str):
                import re

                parts_keys = [k.strip() for k in re.split(r"[\s+]+", keys) if k.strip()]
                if len(parts_keys) > 1:
                    actions.append(
                        {
                            "action": "press_keys",
                            "keys": [normalize_key(k) for k in parts_keys],
                        }
                    )
                elif parts_keys:
                    actions.append(
                        {"action": "press_key", "key": normalize_key(parts_keys[0])}
                    )
            elif isinstance(keys, (list, tuple)):
                if len(keys) > 1:
                    actions.append(
                        {
                            "action": "press_keys",
                            "keys": [normalize_key(str(k)) for k in keys],
                        }
                    )
                elif keys:
                    actions.append(
                        {"action": "press_key", "key": normalize_key(str(keys[0]))}
                    )

        elif n == "game_action":
            action_type = args.get("action", "").lower()
            if action_type == "press_key":
                key = args.get("key")
                if key:
                    actions.append(
                        {"action": "press_key", "key": normalize_key(str(key))}
                    )
            elif action_type == "click":
                x = args.get("x")
                y = args.get("y")
                if x is not None and y is not None:
                    actions.append({"action": "click", "x": float(x), "y": float(y)})
            elif action_type == "wait":
                actions.append({"action": "wait", "duration": args.get("duration")})

        elif n == "wait_5_seconds":
            actions.append({"action": "wait", "duration": 5.0})

        elif name:
            actions.append({"tool_name": name, "arguments": args})

    return actions


__all__ = ["parse_gemini_function_calls"]

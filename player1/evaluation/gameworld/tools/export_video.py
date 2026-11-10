"""Explicit MP4 exporter for logged interaction screenshots."""

from __future__ import annotations

import argparse
import json
import logging
import math
import re
import shutil
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path
import sys
from typing import Any

from PIL import Image, ImageDraw, ImageFont

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.runs.artifacts import build_interaction_payload

LOGGER = logging.getLogger(__name__)

RENDER_MODE_WITH_UI_OVERLAY = "with_ui_overlay"
RENDER_MODE_RAW_SCREENSHOTS = "raw_screenshots"
RENDER_MODES = (RENDER_MODE_WITH_UI_OVERLAY, RENDER_MODE_RAW_SCREENSHOTS)
_OVERLAY_DIR = Path(__file__).with_name("video_overlay")
_OVERLAY_LAYOUT_PATH = _OVERLAY_DIR / "wasd-minimal.json"
_OVERLAY_SPRITE_PATH = _OVERLAY_DIR / "wasd.png"
_KEY_OVERLAY_CACHE: dict[str, Any] | None = None
_MOUSE_OVERLAY_LAYOUT_PATH = _OVERLAY_DIR / "mouse-no-movement.json"
_MOUSE_OVERLAY_SPRITE_PATH = _OVERLAY_DIR / "mouse.png"
_MOUSE_OVERLAY_CACHE: dict[str, Any] | None = None

_GLASS_ACCENT = (112, 196, 255, 224)
_HUD_PANEL_BORDER = (6, 16, 30, 160)
_HUD_PANEL_TOP_FILL = (1, 16, 44, 128)
_HUD_PANEL_BOTTOM_FILL = (6, 33, 75, 116)

_OVERLAY_ID_PRIORITY = [
    "q",
    "w",
    "e",
    "shift",
    "a",
    "s",
    "d",
    "ctrl",
    "space",
]
_OVERLAY_ID_BY_KEY = {
    "ArrowUp": "w",
    "ArrowLeft": "a",
    "ArrowDown": "s",
    "ArrowRight": "d",
    "w": "w",
    "a": "a",
    "s": "s",
    "d": "d",
    "Space": "space",
    "Enter": "e",
}


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_render_mode(value: Any) -> str:
    normalized = str(value or RENDER_MODE_WITH_UI_OVERLAY).strip().lower()
    if normalized not in RENDER_MODES:
        supported = ", ".join(sorted(RENDER_MODES))
        raise SystemExit(
            f"Unsupported render mode: {value!r}. Supported values: {supported}"
        )
    return normalized


def _log_progress(message: str) -> None:
    """Log export progress."""
    LOGGER.info(message)


def _get_session_dir(log_dir: Path, session: str) -> Path:
    session_dir = log_dir / session
    if not session_dir.is_dir():
        raise SystemExit(f"Session '{session}' not found in {log_dir}")
    return session_dir


def _action_name(action: dict[str, Any]) -> str:
    if not isinstance(action, dict):
        return ""
    raw = action.get("action")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    tool_name = action.get("tool_name")
    if isinstance(tool_name, str) and tool_name.strip():
        return "tool_call"
    return ""


def _mouse_button(action: dict[str, Any]) -> str:
    if not isinstance(action, dict):
        return "left"
    raw = action.get("button")
    if isinstance(raw, str):
        button = raw.strip().lower()
        if button in {"left", "right", "middle"}:
            return button
    return "left"


def _normalize_key_name(value: str) -> str:
    item = str(value).strip()
    if not item:
        return ""

    lowered = item.lower()
    if lowered == "space" or lowered == "spacebar":
        return "Space"
    if lowered in {"enter", "return"}:
        return "Enter"
    if lowered in {"arrowleft", "left"}:
        return "ArrowLeft"
    if lowered in {"arrowright", "right"}:
        return "ArrowRight"
    if lowered in {"arrowup", "up"}:
        return "ArrowUp"
    if lowered in {"arrowdown", "down"}:
        return "ArrowDown"
    if lowered in {"w", "a", "s", "d"}:
        return lowered
    return item


def _dedupe_in_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def _extract_tool_call_keys(action: dict[str, Any]) -> list[str]:
    tool_name = action.get("tool_name")
    if not isinstance(tool_name, str):
        return []

    lowered = tool_name.strip().lower()
    if not lowered:
        return []

    tokens = [tok for tok in re.split(r"[^a-z0-9]+", lowered) if tok]
    token_set = set(tokens)
    keys: list[str] = []

    token_to_key = {
        "left": "ArrowLeft",
        "right": "ArrowRight",
        "up": "ArrowUp",
        "down": "ArrowDown",
        "w": "w",
        "a": "a",
        "s": "s",
        "d": "d",
        "enter": "Enter",
        "start": "Enter",
        "confirm": "Enter",
    }
    for token, key in token_to_key.items():
        if token in token_set:
            keys.append(key)

    if token_set.intersection(
        {"jump", "flap", "fire", "shoot", "thrust", "boost", "dash", "space"}
    ):
        keys.append("Space")

    # Catch patterns like "move_left" even when tokenization is unexpected.
    if "left" in lowered:
        keys.append("ArrowLeft")
    if "right" in lowered:
        keys.append("ArrowRight")
    if re.search(r"(^|_)up($|_)", lowered):
        keys.append("ArrowUp")
    if re.search(r"(^|_)down($|_)", lowered):
        keys.append("ArrowDown")

    return _dedupe_in_order([_normalize_key_name(key) for key in keys])


def _extract_pressed_keys(action: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    key = action.get("key")
    if isinstance(key, str) and key.strip():
        keys.append(key.strip())

    raw_keys = action.get("keys")
    if isinstance(raw_keys, (list, tuple)):
        for item in raw_keys:
            if isinstance(item, str) and item.strip():
                keys.append(item.strip())

    args = action.get("arguments")
    if isinstance(args, dict):
        arg_key = args.get("key")
        if isinstance(arg_key, str) and arg_key.strip():
            keys.append(arg_key.strip())
        arg_keys = args.get("keys")
        if isinstance(arg_keys, (list, tuple)):
            for item in arg_keys:
                if isinstance(item, str) and item.strip():
                    keys.append(item.strip())

    normalized = [_normalize_key_name(item) for item in keys]
    normalized = _dedupe_in_order([item for item in normalized if item])
    if normalized:
        return normalized

    if _action_name(action) == "tool_call":
        return _extract_tool_call_keys(action)
    return []


def _effective_action(interaction: dict[str, Any]) -> dict[str, Any]:
    executed = interaction.get("executed_action")
    if isinstance(executed, dict) and executed:
        return executed

    parsed = interaction.get("parsed_action")
    if isinstance(parsed, dict):
        return parsed
    return {}


def _tile_has_visible_pixels(tile: Image.Image, alpha_threshold: int = 24) -> bool:
    alpha = tile.getchannel("A")
    extrema = alpha.getextrema()
    if not extrema:
        return False
    return int(extrema[1]) > alpha_threshold


def _detect_pressed_row_offset(
    sprite: Image.Image,
    x: int,
    y: int,
    w: int,
    h: int,
    max_extra: int = 28,
) -> int:
    # Atlas rows are stacked: normal row then pressed row a fixed distance below.
    search_start = y + h
    search_end = min(sprite.height - h, y + h + max(1, max_extra))
    for row_y in range(search_start, search_end + 1):
        row = sprite.crop((x, row_y, x + w, row_y + 1))
        if _tile_has_visible_pixels(row):
            offset = row_y - y
            if offset > 0:
                return offset
    return h


def _load_overlay_layout() -> dict[str, Any]:
    global _KEY_OVERLAY_CACHE
    if _KEY_OVERLAY_CACHE is not None:
        return _KEY_OVERLAY_CACHE

    layout = json.loads(_OVERLAY_LAYOUT_PATH.read_text(encoding="utf-8"))
    with Image.open(_OVERLAY_SPRITE_PATH) as source:
        sprite = source.convert("RGBA")

    elements_by_id: dict[str, dict[str, Any]] = {}
    for element in layout["elements"]:
        key_id = str(element["id"]).strip().lower()
        mx, my, mw, mh = map(int, element["mapping"])
        px, py = map(int, element["pos"])
        normal = sprite.crop((mx, my, mx + mw, my + mh))
        pressed_offset = _detect_pressed_row_offset(sprite, mx, my, mw, mh)
        pressed_y = my + pressed_offset
        pressed = sprite.crop((mx, pressed_y, mx + mw, pressed_y + mh))
        elements_by_id[key_id] = {
            "id": key_id,
            "pos": (px, py),
            "size": (mw, mh),
            "normal": normal,
            "pressed": pressed,
        }

    ordered_ids = [key for key in _OVERLAY_ID_PRIORITY if key in elements_by_id]
    for key in sorted(elements_by_id):
        if key not in ordered_ids:
            ordered_ids.append(key)

    overlay = {
        "width": int(layout["overlay_width"]),
        "height": int(layout["overlay_height"]),
        "elements": elements_by_id,
        "ordered_ids": ordered_ids,
    }
    _KEY_OVERLAY_CACHE = overlay
    return overlay


def _active_overlay_ids(active_keys: set[str]) -> set[str]:
    active_ids: set[str] = set()
    for key in active_keys:
        mapped = _OVERLAY_ID_BY_KEY.get(key)
        if mapped:
            active_ids.add(mapped)
            continue
        lowered = key.lower()
        if lowered in _OVERLAY_ID_PRIORITY:
            active_ids.add(lowered)
    return active_ids


def _load_mouse_overlay_layout() -> dict[str, Any]:
    global _MOUSE_OVERLAY_CACHE
    if _MOUSE_OVERLAY_CACHE is not None:
        return _MOUSE_OVERLAY_CACHE

    layout = json.loads(_MOUSE_OVERLAY_LAYOUT_PATH.read_text(encoding="utf-8"))
    with Image.open(_MOUSE_OVERLAY_SPRITE_PATH) as source:
        sprite = source.convert("RGBA")

    elements: dict[str, dict[str, Any]] = {}
    for element in layout["elements"]:
        elem_id = str(element["id"]).strip().lower()
        mx, my, mw, mh = map(int, element["mapping"])
        px, py = map(int, element["pos"])
        normal = sprite.crop((mx, my, mx + mw, my + mh))
        pressed = normal
        if int(element.get("type", 0)) == 3:
            offset = _detect_pressed_row_offset(
                sprite,
                mx,
                my,
                mw,
                mh,
                max_extra=max(220, mh + 40),
            )
            pressed_y = my + offset
            pressed = sprite.crop((mx, pressed_y, mx + mw, pressed_y + mh))
        elements[elem_id] = {
            "id": elem_id,
            "pos": (px, py),
            "size": (mw, mh),
            "normal": normal,
            "pressed": pressed,
            "code": int(element.get("code", 0)),
            "z_level": int(element.get("z_level", 0)),
        }

    ordered_ids = sorted(
        elements.keys(),
        key=lambda key: (elements[key]["z_level"], key),
    )
    mouse_overlay = {
        "width": int(layout["overlay_width"]),
        "height": int(layout["overlay_height"]),
        "elements": elements,
        "ordered_ids": ordered_ids,
    }
    _MOUSE_OVERLAY_CACHE = mouse_overlay
    return mouse_overlay


def _frame_repeat_for_action(action: dict[str, Any], fps: int) -> int:
    action_name = _action_name(action)
    duration = _coerce_float(action.get("duration"), default=0.0)
    if action_name in {"wait", "click_hold"}:
        duration = duration or 1.0
        return min(30, max(1, int(round(duration * fps))))
    if action_name == "drag":
        duration = duration or 0.8
        return min(30, max(1, int(round(duration * fps))))
    if action_name in {"press_key", "press_keys"} and duration > 0:
        return min(30, max(1, int(round(duration * fps))))
    return 1


def _coord_to_pixel(value: Any, span: int) -> tuple[float, bool]:
    """Convert 0-1000 relative coordinates into pixel coordinates."""
    v = _coerce_float(value, -1)
    if v < 0:
        return -1.0, False
    if 0.0 <= v <= 1000.0:
        max_span = max(1, int(span) - 1)
        return (v / 1000.0) * float(max_span), True
    return v, False


def _resolve_click_point(
    action: dict[str, Any],
    frame_size: tuple[int, int] | None,
) -> tuple[float, float, bool]:
    x = _coerce_float(action.get("x"), -1)
    y = _coerce_float(action.get("y"), -1)
    if not frame_size:
        return x, y, False

    width, height = frame_size
    px, conv_x = _coord_to_pixel(x, width)
    py, conv_y = _coord_to_pixel(y, height)
    return px, py, (conv_x or conv_y)


def _resolve_drag_points(
    action: dict[str, Any],
    frame_size: tuple[int, int] | None,
) -> tuple[float, float, float, float, bool]:
    x1 = _coerce_float(action.get("x1"), -1)
    y1 = _coerce_float(action.get("y1"), -1)
    x2 = _coerce_float(action.get("x2"), -1)
    y2 = _coerce_float(action.get("y2"), -1)
    if not frame_size:
        return x1, y1, x2, y2, False

    width, height = frame_size
    px1, conv_x1 = _coord_to_pixel(x1, width)
    py1, conv_y1 = _coord_to_pixel(y1, height)
    px2, conv_x2 = _coord_to_pixel(x2, width)
    py2, conv_y2 = _coord_to_pixel(y2, height)
    converted = conv_x1 or conv_y1 or conv_x2 or conv_y2
    return px1, py1, px2, py2, converted


def _fmt_coord(value: float) -> int:
    if value < 0:
        return -1
    return int(round(value))


def _action_summary(
    action: dict[str, Any],
    *,
    frame_size: tuple[int, int] | None = None,
) -> str:
    action_name = _action_name(action)
    if action_name == "click":
        x, y, _ = _resolve_click_point(action, frame_size)
        button = _mouse_button(action)
        prefix = "click" if button == "left" else f"click[{button}]"
        return f"{prefix} ({_fmt_coord(x)}, {_fmt_coord(y)})"
    if action_name == "click_hold":
        x, y, _ = _resolve_click_point(action, frame_size)
        button = _mouse_button(action)
        prefix = "click_hold" if button == "left" else f"click_hold[{button}]"
        return f"{prefix} ({_fmt_coord(x)}, {_fmt_coord(y)})"
    if action_name == "drag":
        x1, y1, x2, y2, _ = _resolve_drag_points(action, frame_size)
        button = _mouse_button(action)
        prefix = "drag" if button == "left" else f"drag[{button}]"
        return (
            f"{prefix} ({_fmt_coord(x1)}, {_fmt_coord(y1)})"
            f" -> ({_fmt_coord(x2)}, {_fmt_coord(y2)})"
        )
    if action_name == "press_key":
        return f"{action_name} {action.get('key')}"
    if action_name == "press_keys":
        return f"press_keys {action.get('keys')}"
    if action_name == "wait":
        return f"wait {action.get('duration', 'unknown')}s"
    if action_name == "tool_call":
        tool_name = action.get("tool_name") or "unknown_tool"
        return f"tool_call {tool_name}"
    if action_name:
        return action_name
    return "unknown"


def _load_font(size: int) -> ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/SFNS.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Supplemental/HelveticaNeue.ttc",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Helvetica.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "DejaVuSans.ttf",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except Exception:  # noqa: BLE001
            continue
    return ImageFont.load_default()


def _scaled_font_size(base_size: int, scale: float, minimum: int) -> int:
    return max(minimum, int(round(base_size * scale)))


def _load_hud_fonts(
    frame_size: tuple[int, int] | None = None,
) -> dict[str, ImageFont.ImageFont]:
    # Keep text proportionate across different screenshot resolutions.
    if frame_size:
        _, frame_h = frame_size
        ui_scale = max(0.62, min(1.0, frame_h / 1080.0))
    else:
        ui_scale = 1.0

    return {
        "header": _load_font(_scaled_font_size(34, ui_scale, 22)),
        "meta": _load_font(_scaled_font_size(23, ui_scale, 15)),
        "hud": _load_font(_scaled_font_size(25, ui_scale, 16)),
    }


def _resize_overlay_preserve_color(
    image: Image.Image,
    size: tuple[int, int],
) -> Image.Image:
    """Resize overlay assets with premultiplied alpha to avoid darkened fringes."""
    return (
        image.convert("RGBa")
        .resize(size, resample=Image.Resampling.LANCZOS)
        .convert("RGBA")
    )


def _composite_tile(
    canvas: Image.Image, tile: Image.Image, pos: tuple[int, int]
) -> None:
    """Composite a tile without applying alpha twice."""
    canvas.alpha_composite(tile, dest=pos)


def _draw_text(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    text: str,
    fill: tuple[int, int, int, int],
    font: ImageFont.ImageFont,
    stroke_width: int = 0,
    stroke_fill: tuple[int, int, int, int] | None = None,
) -> None:
    draw.text(
        (x, y),
        text,
        fill=fill,
        font=font,
        stroke_width=stroke_width,
        stroke_fill=stroke_fill,
    )


def _draw_arrow(
    draw: ImageDraw.ImageDraw,
    start: tuple[float, float],
    end: tuple[float, float],
    color: tuple[int, int, int, int],
    width: int = 5,
) -> None:
    draw.line([start, end], fill=color, width=width)
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    head_len = 18
    spread = math.pi / 7
    left = (
        end[0] - head_len * math.cos(angle - spread),
        end[1] - head_len * math.sin(angle - spread),
    )
    right = (
        end[0] - head_len * math.cos(angle + spread),
        end[1] - head_len * math.sin(angle + spread),
    )
    draw.polygon([end, left, right], fill=color)


def _draw_action_marker(
    draw: ImageDraw.ImageDraw,
    action: dict[str, Any],
    progress: float,
    frame_size: tuple[int, int],
) -> None:
    action_name = _action_name(action)
    if action_name in {"click", "click_hold"}:
        x, y, _ = _resolve_click_point(action, frame_size)
        if x < 0 or y < 0:
            return
        base_radius = 16
        radius = int(base_radius + 6 * math.sin(progress * math.pi))
        draw.ellipse(
            [(x - radius, y - radius), (x + radius, y + radius)],
            outline=_GLASS_ACCENT,
            width=4,
        )
        draw.ellipse([(x - 3, y - 3), (x + 3, y + 3)], fill=_GLASS_ACCENT)
        return

    if action_name == "drag":
        x1, y1, x2, y2, _ = _resolve_drag_points(action, frame_size)
        if min(x1, y1, x2, y2) < 0:
            return
        alpha = int(170 + 85 * progress)
        _draw_arrow(
            draw,
            (x1, y1),
            (x2, y2),
            color=(140, 221, 255, alpha),
            width=5,
        )


def _draw_keyboard_panel(
    frame: Image.Image,
    frame_size: tuple[int, int],
    active_keys: set[str],
) -> None:
    width, height = frame_size
    overlay = _load_overlay_layout()
    active_ids = _active_overlay_ids(active_keys)
    canvas_w = int(overlay["width"])
    canvas_h = int(overlay["height"])
    overlay_canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))

    for key_id in overlay["ordered_ids"]:
        config = overlay["elements"][key_id]
        tile = config["pressed"] if key_id in active_ids else config["normal"]
        _composite_tile(overlay_canvas, tile, config["pos"])

    target_w = max(320, int(width * 0.24))
    target_h = max(188, int(canvas_h * target_w / canvas_w))
    max_h = int(height * 0.33)
    if target_h > max_h:
        target_h = max_h
        target_w = max(220, int(canvas_w * target_h / canvas_h))

    overlay_canvas = _resize_overlay_preserve_color(
        overlay_canvas,
        (target_w, target_h),
    )
    frame.alpha_composite(overlay_canvas, (18, height - target_h - 18))


def _draw_mouse_panel(
    frame: Image.Image,
    frame_size: tuple[int, int],
    action: dict[str, Any],
    *,
    hud_font: ImageFont.ImageFont,
) -> None:
    width, height = frame_size
    action_name = _action_name(action)
    button = _mouse_button(action)
    left_pressed = action_name in {"click", "click_hold", "drag"} and button == "left"
    right_pressed = action_name in {"click", "click_hold", "drag"} and button == "right"
    if action_name == "tool_call":
        tool_name = str(action.get("tool_name") or "").lower()
        if any(token in tool_name for token in ("mouse_right", "rmb")):
            right_pressed = True
        elif any(
            token in tool_name for token in ("click", "mouse_left", "lmb", "drag")
        ):
            left_pressed = True

    overlay = _load_mouse_overlay_layout()
    pressed_ids: set[str] = set()
    if left_pressed:
        pressed_ids.add("lmb")
    if right_pressed:
        pressed_ids.add("rmb")

    canvas_w = int(overlay["width"])
    canvas_h = int(overlay["height"])
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    for element_id in overlay["ordered_ids"]:
        config = overlay["elements"][element_id]
        tile = config["pressed"] if element_id in pressed_ids else config["normal"]
        _composite_tile(canvas, tile, config["pos"])

    target_h = min(max(210, int(height * 0.285)), int(height * 0.41))
    target_w = max(140, int(canvas_w * target_h / canvas_h))
    max_w = int(width * 0.20)
    if target_w > max_w:
        target_w = max_w
        target_h = max(120, int(canvas_h * target_w / canvas_w))

    canvas = _resize_overlay_preserve_color(canvas, (target_w, target_h))
    frame.alpha_composite(canvas, (width - target_w - 18, height - target_h - 18))

    coords_text = ""
    if action_name == "click":
        x, y, converted = _resolve_click_point(action, frame_size)
        if converted:
            coords_text = (
                f"Click: rel({_coerce_int(action.get('x'))}, {_coerce_int(action.get('y'))})"
                f" -> px({_fmt_coord(x)}, {_fmt_coord(y)})"
            )
        else:
            coords_text = f"Click: ({_fmt_coord(x)}, {_fmt_coord(y)})"
    elif action_name == "drag":
        x1, y1, x2, y2, converted = _resolve_drag_points(action, frame_size)
        if converted:
            coords_text = (
                f"Drag: rel({_coerce_int(action.get('x1'))}, {_coerce_int(action.get('y1'))})"
                f" -> rel({_coerce_int(action.get('x2'))}, {_coerce_int(action.get('y2'))})"
                f" -> px({_fmt_coord(x1)}, {_fmt_coord(y1)}) to ({_fmt_coord(x2)}, {_fmt_coord(y2)})"
            )
        else:
            coords_text = (
                f"Drag: ({_fmt_coord(x1)}, {_fmt_coord(y1)})"
                f" -> ({_fmt_coord(x2)}, {_fmt_coord(y2)})"
            )
    elif action_name:
        coords_text = f"Action: {_action_summary(action, frame_size=frame_size)}"

    if coords_text:
        text_w = min(340, int(width * 0.30))
        text_h = 36
        text_x1 = 18
        text_x2 = text_x1 + text_w
        text_y2 = height - 14
        text_y1 = text_y2 - text_h
        text_layer = Image.new("RGBA", frame_size, (0, 0, 0, 0))
        text_draw = ImageDraw.Draw(text_layer, "RGBA")
        text_draw.rounded_rectangle(
            [(text_x1, text_y1), (text_x2, text_y2)],
            radius=10,
            fill=_HUD_PANEL_BOTTOM_FILL,
            outline=_HUD_PANEL_BORDER,
            width=2,
        )
        _draw_text(
            text_draw,
            text_x1 + 10,
            text_y1 + 5,
            coords_text,
            (247, 250, 255, 244),
            hud_font,
        )
        frame.alpha_composite(text_layer)


def _draw_header(
    frame: Image.Image,
    frame_size: tuple[int, int],
    *,
    session: str,
    interaction_index: int,
    interaction_total: int,
    interaction: dict[str, Any],
    action: dict[str, Any],
    header_font: ImageFont.ImageFont,
    meta_font: ImageFont.ImageFont,
) -> None:
    width, _ = frame_size
    header_layer = Image.new("RGBA", frame_size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(header_layer, "RGBA")
    panel_x1 = 16
    panel_y1 = 12
    panel_x2 = width - 16
    # Compact the lower half to save vertical space while keeping readability.
    panel_y2 = 96

    # Two-tone deep-blue header (top darker, bottom slightly lighter), no shadow.
    outer_radius = 18
    inner_radius = 15
    border_color = _HUD_PANEL_BORDER
    top_fill = _HUD_PANEL_TOP_FILL
    bottom_fill = _HUD_PANEL_BOTTOM_FILL

    draw.rounded_rectangle(
        [(panel_x1, panel_y1), (panel_x2, panel_y2)],
        radius=outer_radius,
        fill=bottom_fill,
        outline=border_color,
        width=3,
    )

    inner_x1 = panel_x1 + 3
    inner_y1 = panel_y1 + 3
    inner_x2 = panel_x2 - 3
    top_band_h = 34

    draw.rounded_rectangle(
        [(inner_x1, inner_y1), (inner_x2, inner_y1 + top_band_h)],
        radius=inner_radius,
        fill=top_fill,
    )
    # Flatten the lower edge of the top band so it visually separates from the lower section.
    draw.rectangle(
        [(inner_x1, inner_y1 + top_band_h - 10), (inner_x2, inner_y1 + top_band_h)],
        fill=top_fill,
    )

    timestamp = _format_timestamp(interaction["timestamp"])
    agent_id = interaction["agent_id"]
    summary = _action_summary(action, frame_size=frame_size)

    line_1 = (
        f"Session: {session}   |   Step: {interaction_index}/{interaction_total}   "
        f"|   Agent: {agent_id}   |   Timestamp: {timestamp}"
    )
    line_2 = f"Action: {summary}"
    action_line_y = panel_y1 + 42
    _draw_text(
        draw,
        panel_x1 + 18,
        panel_y1 + 12,
        line_1,
        (245, 251, 255, 252),
        meta_font,
        stroke_width=1,
        stroke_fill=(2, 8, 18, 210),
    )
    _draw_text(
        draw,
        panel_x1 + 18,
        action_line_y,
        line_2,
        (247, 252, 255, 252),
        header_font,
        stroke_width=1,
        stroke_fill=(2, 8, 18, 210),
    )
    frame.alpha_composite(header_layer)


def _load_base_frame(image_path: Path | None) -> Image.Image:
    if image_path is None:
        raise ValueError("Interaction does not reference a screenshot")
    if not image_path.is_file():
        raise FileNotFoundError(f"Screenshot not found: {image_path}")
    with Image.open(image_path) as source:
        return source.convert("RGBA")


def _format_timestamp(value: str) -> str:
    text = value.strip()
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    dt = datetime.fromisoformat(normalized)
    hundredths = dt.microsecond // 10000
    return f"{dt:%Y-%m-%d %H:%M:%S}.{hundredths:02d}"


def _default_video_output_path(session_dir: Path, render_mode: str) -> Path:
    render_mode = _normalize_render_mode(render_mode)
    if render_mode == RENDER_MODE_RAW_SCREENSHOTS:
        return session_dir / "video_raw_screenshots.mp4"
    return session_dir / "video.mp4"


def _render_frame(
    *,
    base_image: Image.Image,
    session: str,
    interaction_index: int,
    interaction_total: int,
    interaction: dict[str, Any],
    action: dict[str, Any],
    progress: float,
    fonts: dict[str, ImageFont.ImageFont],
    render_mode: str,
) -> Image.Image:
    frame = base_image.copy()
    if render_mode == RENDER_MODE_RAW_SCREENSHOTS:
        return frame

    draw = ImageDraw.Draw(frame, "RGBA")
    active_keys = set(_extract_pressed_keys(action))

    _draw_action_marker(draw, action, progress=progress, frame_size=frame.size)
    _draw_header(
        frame,
        frame.size,
        session=session,
        interaction_index=interaction_index,
        interaction_total=interaction_total,
        interaction=interaction,
        action=action,
        header_font=fonts["header"],
        meta_font=fonts["meta"],
    )
    _draw_keyboard_panel(
        frame,
        frame.size,
        active_keys,
    )
    _draw_mouse_panel(
        frame,
        frame.size,
        action,
        hud_font=fonts["hud"],
    )
    return frame


def _encode_video_from_frames(frame_dir: Path, fps: int, output: Path) -> None:
    ffmpeg_cmd = [
        "ffmpeg",
        "-y",
        "-framerate",
        str(fps),
        "-i",
        str(frame_dir / "frame_%06d.png"),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(output),
    ]
    proc = subprocess.run(
        ffmpeg_cmd,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        details = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"ffmpeg failed ({proc.returncode}): {details[-1200:]}")


def export_video(
    *,
    session: str,
    logs_dir: Path,
    output: Path | None = None,
    fps: int = 6,
    keep_frames: bool = False,
    max_interactions: int | None = None,
    render_mode: str = RENDER_MODE_WITH_UI_OVERLAY,
) -> dict[str, Any]:
    """Render an MP4 in either raw-screenshot or UI-overlay mode."""
    logs_dir = Path(logs_dir)
    if not logs_dir.exists():
        raise SystemExit(f"Log directory does not exist: {logs_dir}")
    render_mode = _normalize_render_mode(render_mode)

    session_dir = _get_session_dir(logs_dir, session)
    payload = build_interaction_payload(session_dir, logs_dir)
    interactions = list(payload["interactions"])
    if not interactions:
        raise SystemExit(f"No interactions found in {session_dir}")
    if max_interactions is not None and max_interactions > 0:
        interactions = interactions[:max_interactions]
    output_path = output or _default_video_output_path(session_dir, render_mode)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if fps <= 0:
        raise ValueError(f"FPS must be positive, got {fps}")

    planned_frames = 0
    for interaction in interactions:
        action = _effective_action(interaction)
        planned_frames += _frame_repeat_for_action(action, fps=fps)
    _log_progress(
        (
            f"[video] start session={session_dir.name} interactions={len(interactions)} "
            f"planned_frames={planned_frames} fps={fps} mode={render_mode} output={output_path}"
        ),
    )

    frame_dir = Path(
        tempfile.mkdtemp(
            prefix=f"video_export_{session_dir.name}_",
            dir=str(output_path.parent),
        )
    )
    fonts: dict[str, ImageFont.ImageFont] = {}

    frame_count = 0
    last_progress_frames = 0
    last_progress_time = time.monotonic()
    progress_step_frames = max(1, planned_frames // 20)  # ~5% increments

    try:
        interaction_total = len(interactions)
        for idx, interaction in enumerate(interactions, start=1):
            action = _effective_action(interaction)

            screenshot_rel = interaction.get("screenshot")
            screenshot_path = logs_dir / screenshot_rel if screenshot_rel else None

            base_image = _load_base_frame(screenshot_path)
            if render_mode != RENDER_MODE_RAW_SCREENSHOTS and not fonts:
                fonts = _load_hud_fonts(frame_size=base_image.size)

            repeat = _frame_repeat_for_action(action, fps=fps)
            for rep_idx in range(repeat):
                progress = 1.0 if repeat <= 1 else rep_idx / (repeat - 1)
                frame = _render_frame(
                    base_image=base_image,
                    session=session_dir.name,
                    interaction_index=idx,
                    interaction_total=interaction_total,
                    interaction=interaction,
                    action=action,
                    progress=progress,
                    fonts=fonts,
                    render_mode=render_mode,
                )
                frame_count += 1
                frame_path = frame_dir / f"frame_{frame_count:06d}.png"
                frame.convert("RGB").save(frame_path)

                now = time.monotonic()
                reached_step = (
                    frame_count - last_progress_frames
                ) >= progress_step_frames
                reached_tail = frame_count == planned_frames
                reached_timer = (now - last_progress_time) >= 1.5
                if reached_step or reached_tail or reached_timer:
                    pct = (frame_count / planned_frames) * 100.0
                    _log_progress(
                        (
                            f"[video] frame_progress {frame_count}/{planned_frames} "
                            f"({pct:.1f}%) interaction={idx}/{interaction_total}"
                        ),
                    )
                    last_progress_frames = frame_count
                    last_progress_time = now

        _log_progress("[video] encoding mp4 with ffmpeg...")
        _encode_video_from_frames(frame_dir=frame_dir, fps=fps, output=output_path)
        _log_progress(f"[video] done output: {output_path} frames: {frame_count}")
    except Exception as exc:
        _log_progress(f"[video] failed error={exc}")
        raise
    finally:
        if not keep_frames:
            shutil.rmtree(frame_dir, ignore_errors=True)
            _log_progress("[video] cleaned temporary frame directory")
        else:
            _log_progress(f"[video] kept frame directory at {frame_dir}")

    return {
        "session": session_dir.name,
        "video": output_path,
        "frame_count": frame_count,
        "fps": fps,
        "interaction_count": len(interactions),
        "frame_dir": frame_dir if keep_frames else None,
        "render_mode": render_mode,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export logged interaction screenshots as an MP4."
    )
    parser.add_argument(
        "--logs-dir", default="results", help="Directory containing runtime logs."
    )
    parser.add_argument(
        "--session", required=True, help="Exact session folder name under --logs-dir."
    )
    parser.add_argument("--output", help="Optional output .mp4 path.")
    parser.add_argument("--fps", type=int, default=6, help="Video FPS (default: 6).")
    parser.add_argument(
        "--render-mode",
        choices=RENDER_MODES,
        default=RENDER_MODE_WITH_UI_OVERLAY,
        help=(
            "Video rendering mode. "
            "'with_ui_overlay' adds HUD overlays; "
            "'raw_screenshots' keeps only the logged screenshots."
        ),
    )
    parser.add_argument(
        "--keep-frames",
        action="store_true",
        help="Keep temporary rendered frames for debugging.",
    )
    parser.add_argument(
        "--max-interactions",
        type=int,
        default=None,
        help="Render only the first N interactions (for quick tests).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = export_video(
        session=args.session,
        logs_dir=Path(args.logs_dir),
        output=Path(args.output) if args.output else None,
        fps=args.fps,
        keep_frames=args.keep_frames,
        max_interactions=args.max_interactions,
        render_mode=args.render_mode,
    )
    print(f"Video written to: {result['video']}")
    print(f"Session: {result['session']}")
    print(f"Interactions rendered: {result['interaction_count']}")
    print(f"Frames rendered: {result['frame_count']} at {result['fps']} FPS")
    print(f"Render mode: {result['render_mode']}")
    if result.get("frame_dir"):
        print(f"Frame directory: {result['frame_dir']}")


if __name__ == "__main__":
    main()

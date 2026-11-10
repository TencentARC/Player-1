"""Source/session calibration into the paper's normalized screen coordinates."""

from __future__ import annotations

import math


def rounded(value: float) -> int:
    if not math.isfinite(value):
        raise ValueError("Coordinates must be finite")
    return math.floor(value + 0.5) if value >= 0 else math.ceil(value - 0.5)


def _positive(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be positive and finite")
    return float(value)


def fit_axis(pairs):
    """Huber IRLS fit through the origin for native input / observed pointer pairs."""
    if len(pairs) < 3:
        raise ValueError("Calibration requires at least three motion pairs per axis")
    xs, ys = zip(*pairs, strict=True)
    if any(not math.isfinite(float(x)) or not math.isfinite(float(y)) for x, y in pairs):
        raise ValueError("Calibration pairs must be finite")
    if sum(x * x for x in xs) <= 0:
        raise ValueError("Calibration has no native motion")
    gain = sum(x * y for x, y in pairs) / sum(x * x for x in xs)
    for _ in range(20):
        residuals = [abs(y - gain * x) for x, y in pairs]
        median = sorted(residuals)[len(residuals) // 2]
        delta = max(1.0, 1.345 * 1.4826 * median)
        weights = [min(1.0, delta / max(r, 1e-12)) for r in residuals]
        new = sum(w * x * y for w, x, y in zip(weights, xs, ys, strict=True)) / sum(
            w * x * x for w, x in zip(weights, xs, strict=True)
        )
        if abs(new - gain) < 1e-10:
            gain = new
            break
        gain = new
    return _positive(gain, "calibration gain")


def relative_mapping(source: str, session_id: str, geometry: dict, settings: dict | None) -> dict:
    """Resolve explicit session fit, metadata profile, then declared display scale."""
    config = dict(settings or {})
    if config.get("session_id", session_id) != session_id:
        raise ValueError("Calibration belongs to another source session")
    size = config.get("logical_size", [geometry["width_px"], geometry["height_px"]])
    if len(size) != 2:
        raise ValueError("logical_size must contain width and height")
    width, height = (_positive(v, "logical size") for v in size)
    blocks = config.get("gui_blocks")
    if blocks is not None:
        if len(blocks) < 2:
            raise ValueError("Session GUI fit requires two non-overlapping two-second blocks")
        previous_end = -1
        for block in sorted(blocks, key=lambda b: b["start_ms"]):
            if block["start_ms"] < previous_end or block["end_ms"] - block["start_ms"] < 2000:
                raise ValueError("Calibration GUI blocks overlap or are shorter than two seconds")
            previous_end = block["end_ms"]
        kx = fit_axis([pair for block in blocks for pair in block["x_pairs"]])
        ky = fit_axis([pair for block in blocks for pair in block["y_pairs"]])
        tier = "same_session_gui_fit"
    elif "gains" in config:
        kx, ky = config["gains"]
        tier = "metadata_profile"
    elif "display_scale" in config and source == "pixel2play":
        kx, ky = config["display_scale"]
        tier = "display_scale"
    elif source == "vpt":
        kx = ky = 2
        width, height, tier = 1280.0, 720.0, "vpt_logical_1280x720"
    elif source == "d2e":
        kx = ky = 0.66
        tier = "d2e_source_estimate"
    else:
        raise ValueError(f"{source} relative motion requires explicit calibration; no mapping was inferred")
    return {
        "k_x": _positive(kx, "k_x"),
        "k_y": _positive(ky, "k_y"),
        "width": width,
        "height": height,
        "tier": tier,
        "session_id": session_id,
    }


def relative(dx, dy, mapping):
    x = rounded(1000 * dx * mapping["k_x"] / mapping["width"])
    y = rounded(1000 * dy * mapping["k_y"] / mapping["height"])
    if not (-1000 <= x <= 1000 and -1000 <= y <= 1000):
        raise ValueError("Relative projection is outside [-1000,1000]; cannot clip recorded inputs")
    return {"mode": "relative", "dx": x, "dy": y} if x or y else None


def absolute(x, y, width, height):
    width, height = _positive(width, "width"), _positive(height, "height")
    px, py = rounded(1000 * x / width), rounded(1000 * y / height)
    if not (0 <= px <= 1000 and 0 <= py <= 1000):
        raise ValueError("Absolute projection is outside [0,1000]; cannot clip recorded inputs")
    return {"mode": "absolute", "x": px, "y": py}


def pixel_scroll_dy(dy: float, unit: str | None) -> float:
    # Windows wheel ticks (including MCAP's semantic mouse topic) are positive up.
    # Pixel2Play/VPT pixel deltas are already positive down. Gaming500 remains
    # unchanged until its source-specific convention has been calibrated.
    return -dy if unit in {"wheel_ticks", "mcap_scroll_delta"} else dy

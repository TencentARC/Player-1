"""Shared image-size rules for browser capture and agent observations."""

from __future__ import annotations

import math


def fit_size_to_max_height(width: int, height: int, max_height: int) -> tuple[int, int]:
    """Downscale to ``max_height`` while preserving aspect ratio.

    Width is rounded to the nearest even pixel so standard 16:9 heights map to
    conventional video dimensions such as 640x360 and 854x480.
    """

    for name, value in (("width", width), ("height", height), ("max_height", max_height)):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{name} must be a positive integer, got {value!r}")

    if height <= max_height:
        return width, height

    scaled_width = float(width) * float(max_height) / float(height)
    even_width = max(2, 2 * math.floor((scaled_width / 2.0) + 0.5))
    return min(width, even_width), max_height


__all__ = ["fit_size_to_max_height"]

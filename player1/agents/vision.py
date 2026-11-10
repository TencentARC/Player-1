"""Shared preparation for images sent to Player-1 agents."""

from __future__ import annotations

from io import BytesIO
from typing import Any

from PIL import Image

from player1.runtime.image_geometry import fit_size_to_max_height


DEFAULT_AGENT_IMAGE_MAX_HEIGHT = 480


def prepare_agent_image(image_source: Any, *, max_height: int) -> Image.Image:
    """Decode PNG bytes or an image source to RGB at the configured maximum height."""

    if isinstance(max_height, bool) or not isinstance(max_height, int) or max_height <= 0:
        raise ValueError(f"Agent image max_height must be a positive integer, got {max_height!r}")

    cached_image = getattr(image_source, "image", None)
    if isinstance(image_source, Image.Image):
        converted = image_source.copy().convert("RGB")
    elif isinstance(cached_image, Image.Image):
        converted = cached_image.copy().convert("RGB")
    else:
        if isinstance(image_source, bytes):
            data = image_source
        else:
            read_bytes = getattr(image_source, "read_bytes", None)
            if not callable(read_bytes):
                raise TypeError(f"Unsupported agent image input: {type(image_source)!r}")
            data = read_bytes()
        with Image.open(BytesIO(data)) as image:
            converted = image.convert("RGB")

    resized = fit_size_to_max_height(converted.width, converted.height, max_height)
    if converted.size == resized:
        return converted
    return converted.resize(resized, resample=Image.Resampling.BILINEAR)


__all__ = ["DEFAULT_AGENT_IMAGE_MAX_HEIGHT", "prepare_agent_image"]

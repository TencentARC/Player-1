"""Model camera gain in observation pixels, independent of hidden render geometry."""

import math
from collections.abc import Sequence


CAMERA_RADIANS_PER_OBSERVATION_PIXEL = 0.00196
CAMERA_DEGREES_PER_OBSERVATION_PIXEL = math.degrees(CAMERA_RADIANS_PER_OBSERVATION_PIXEL)


def normalize_observation_size(value: Sequence[int]) -> tuple[int, int]:
    """Require the actual current image dimensions before model-processor patching."""

    if (
        isinstance(value, (str, bytes))
        or not isinstance(value, Sequence)
        or len(value) != 2
        or any(isinstance(axis, bool) or not isinstance(axis, int) or axis <= 0 for axis in value)
    ):
        raise ValueError("observation_size must contain positive integer width and height")
    return value[0], value[1]

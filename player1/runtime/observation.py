"""A screenshot and the receipt of an environment transition."""

from dataclasses import dataclass, field
from typing import Any

from PIL import Image


@dataclass
class Observation:
    image: Image.Image
    reward: float = 0.0
    terminated: bool = False
    truncated: bool = False
    info: dict[str, Any] = field(default_factory=dict)

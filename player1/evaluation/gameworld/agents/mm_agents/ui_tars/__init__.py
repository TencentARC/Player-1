"""UI-TARS computer-use adapter."""

from .agent import UITars15Agent as Client
from .agent import UITars15Config as Config
from .prompt import OUTPUT_FORMAT, PROMPT_TEMPLATE

__all__ = ["Client", "Config", "OUTPUT_FORMAT", "PROMPT_TEMPLATE"]

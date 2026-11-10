"""Seed computer-use adapter."""

from .agent import Seed18CUAAgent as Client
from .agent import Seed18CUAConfig as Config
from .prompt import OUTPUT_FORMAT, PROMPT_TEMPLATE

__all__ = ["Client", "Config", "OUTPUT_FORMAT", "PROMPT_TEMPLATE"]

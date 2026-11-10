"""Kimi semantic-action adapter."""

from .agent import KimiK25Agent as Client
from .agent import KimiK25Config as Config
from .prompt import OUTPUT_FORMAT, PROMPT_TEMPLATE

__all__ = ["Client", "Config", "OUTPUT_FORMAT", "PROMPT_TEMPLATE"]

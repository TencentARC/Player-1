"""Grok semantic-action adapter."""

from .agent import Grok41FastReasoningAgent as Client
from .agent import Grok41FastReasoningConfig as Config
from .prompt import OUTPUT_FORMAT, PROMPT_TEMPLATE

__all__ = ["Client", "Config", "OUTPUT_FORMAT", "PROMPT_TEMPLATE"]

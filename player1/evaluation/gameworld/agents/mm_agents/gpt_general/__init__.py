"""GPT semantic-action adapter."""

from .agent import GPT52Agent as Client
from .agent import GPT52Config as Config
from .prompt import OUTPUT_FORMAT, PROMPT_TEMPLATE

__all__ = ["Client", "Config", "OUTPUT_FORMAT", "PROMPT_TEMPLATE"]

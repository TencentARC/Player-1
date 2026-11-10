"""Claude computer-use adapter."""

from .agent import ClaudeSonnet46CUAAgent as Client
from .agent import ClaudeSonnet46CUAConfig as Config
from .prompt import OUTPUT_FORMAT, PROMPT_TEMPLATE

__all__ = ["Client", "Config", "OUTPUT_FORMAT", "PROMPT_TEMPLATE"]

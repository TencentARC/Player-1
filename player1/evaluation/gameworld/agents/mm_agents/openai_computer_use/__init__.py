"""OpenAI computer-use adapter."""

from .agent import ComputerUsePreviewAgent as Client
from .agent import ComputerUsePreviewConfig as Config
from .prompt import OUTPUT_FORMAT, PROMPT_TEMPLATE

__all__ = ["Client", "Config", "OUTPUT_FORMAT", "PROMPT_TEMPLATE"]

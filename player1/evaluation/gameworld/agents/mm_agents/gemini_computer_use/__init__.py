"""Gemini computer-use adapter."""

from .agent import Gemini25ComputerUsePreviewAgent as Client
from .agent import Gemini25ComputerUsePreviewConfig as Config
from .prompt import OUTPUT_FORMAT, PROMPT_TEMPLATE

__all__ = ["Client", "Config", "OUTPUT_FORMAT", "PROMPT_TEMPLATE"]

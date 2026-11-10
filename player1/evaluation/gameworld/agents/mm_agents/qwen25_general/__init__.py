"""Qwen 2.5 local semantic-action adapter."""

from ..qwen_common.local import QwenLocalAgent as Client
from ..qwen_common.local import QwenLocalConfig as Config
from .prompt import OUTPUT_FORMAT, PROMPT_TEMPLATE

__all__ = ["Client", "Config", "OUTPUT_FORMAT", "PROMPT_TEMPLATE"]

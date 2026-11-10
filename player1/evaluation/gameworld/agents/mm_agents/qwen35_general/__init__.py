"""Qwen3.5/3.6 local semantic-action adapter."""

from ..qwen_common.local import QwenFunctionLocalAgent as Client
from ..qwen_common.local import QwenLocalConfig as Config
from .prompt import OUTPUT_FORMAT, PROMPT_TEMPLATE

__all__ = ["Client", "Config", "OUTPUT_FORMAT", "PROMPT_TEMPLATE"]

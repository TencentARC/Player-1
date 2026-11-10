"""Qwen3-VL local computer-use adapter."""

from ..qwen_common.local_cua import QwenLocalCUAAgent as Client
from ..qwen_common.local_cua import QwenLocalCUAConfig as Config
from .prompt import OUTPUT_FORMAT, PROMPT_TEMPLATE

__all__ = ["Client", "Config", "OUTPUT_FORMAT", "PROMPT_TEMPLATE"]

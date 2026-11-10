"""Prompt contract for Qwen3-VL Plus computer use."""

PROMPT_TEMPLATE = "computer_use_agent.j2"
OUTPUT_FORMAT = """\
- Use the `computer_use` tool call and return exactly one action or key combination per step.
- Do not output free-form text outside <tool_call> blocks."""

__all__ = ["OUTPUT_FORMAT", "PROMPT_TEMPLATE"]

"""Prompt contract for OpenAI computer use."""

PROMPT_TEMPLATE = "computer_use_agent.j2"
OUTPUT_FORMAT = """\
- Use the computer-use tool to return exactly one action or key combination per step.
- Do not output free-form text outside tool calls.
- Do not take screenshots on your own."""

__all__ = ["OUTPUT_FORMAT", "PROMPT_TEMPLATE"]

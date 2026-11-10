"""Prompt contract for Gemini computer use."""

PROMPT_TEMPLATE = "computer_use_agent.j2"
OUTPUT_FORMAT = """\
- Use the built-in computer-use tool to return one action or key combination per step.
- Do not output free-form text outside tool calls."""

__all__ = ["OUTPUT_FORMAT", "PROMPT_TEMPLATE"]

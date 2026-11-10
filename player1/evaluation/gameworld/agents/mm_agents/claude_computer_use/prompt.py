"""Prompt contract for Claude computer use."""

PROMPT_TEMPLATE = "computer_use_agent.j2"
OUTPUT_FORMAT = """\
- Use the Claude computer-use tool to return exactly one action or key combination per step.
- You are not allowed to take screenshots on your own.
- Do not output free-form text outside tool calls."""

__all__ = ["OUTPUT_FORMAT", "PROMPT_TEMPLATE"]

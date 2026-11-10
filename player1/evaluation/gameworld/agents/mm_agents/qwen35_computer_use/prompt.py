"""Prompt contract for Qwen3.5/3.6 local computer use."""

PROMPT_TEMPLATE = "computer_use_agent.j2"
OUTPUT_FORMAT = """\
Response format for every step:
A <think> ... </think> block of a very short sentence describing what to do.
A single <tool_call> ... </tool_call> block containing only the JSON: {"name": "<function-name>", "arguments": <args-json-object>}

Use the `computer_use` tool call and return exactly one action per step.
Use only the <think> and the <tool_call> block; do not add any other text."""

__all__ = ["OUTPUT_FORMAT", "PROMPT_TEMPLATE"]

"""Prompt contract for Qwen 2.5 local semantic actions."""

PROMPT_TEMPLATE = "game_agent.j2"
OUTPUT_FORMAT = """\
Response format for every step:
Thinking: a short sentence describing what to do.
A single <tool_call> ... </tool_call> block containing only the JSON: {"name": "<function-name>", "arguments": <args-json-object>}

For each function call, return a JSON object with function name and arguments within <tool_call></tool_call> XML tags:
<tool_call>
{"name": "<function-name>", "arguments": <args-json-object>}
</tool_call>

Use only the Thinking line and the single <tool_call> block; do not add any other text.
Include required action arguments."""

__all__ = ["OUTPUT_FORMAT", "PROMPT_TEMPLATE"]

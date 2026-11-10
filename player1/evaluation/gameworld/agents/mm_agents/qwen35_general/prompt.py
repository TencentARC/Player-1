"""Prompt contract for Qwen3.5/3.6 local semantic actions."""

PROMPT_TEMPLATE = "game_agent.j2"
OUTPUT_FORMAT = """\
Keep the reasoning to one very short sentence.
Return exactly one function call per step in this format with no suffix:
<tool_call>
<function=<function-name>>
<parameter=<argument-name>>
argument-value
</parameter>
</function>
</tool_call>

Use a registered semantic action as the function name. Repeat the <parameter> block for each required argument, or omit it when the action has no arguments."""

__all__ = ["OUTPUT_FORMAT", "PROMPT_TEMPLATE"]

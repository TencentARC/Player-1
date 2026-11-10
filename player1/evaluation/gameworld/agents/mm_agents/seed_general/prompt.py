"""Prompt contract for Seed semantic actions."""

PROMPT_TEMPLATE = "game_agent.j2"
OUTPUT_FORMAT = """\
- You must call exactly ONE tool per step.
- The tool name must be a registered action id.
- Include `reasoning` as a short rationale.
- Do not output free-form text."""

__all__ = ["OUTPUT_FORMAT", "PROMPT_TEMPLATE"]

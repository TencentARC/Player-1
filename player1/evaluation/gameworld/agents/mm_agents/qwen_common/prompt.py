"""Shared Qwen-VL computer-use prompt utilities."""

import json
from typing import Literal


ToolCallFormat = Literal["json", "function"]

_JSON_TOOL_CALL_INSTRUCTION = (
    "For each function call, return a json object with function name and arguments "
    "within <tool_call></tool_call> XML tags:\n"
    "<tool_call>\n"
    '{"name":"computer_use","arguments":{"action":"wait","duration":1}}\n'
    "</tool_call>"
)
_FUNCTION_TOOL_CALL_INSTRUCTION = (
    "For each function call, return the function and its arguments within "
    "<tool_call></tool_call> XML tags:\n"
    "<tool_call>\n"
    "<function=<function-name>>\n"
    "<parameter=<argument-name>>\n"
    "argument-value\n"
    "</parameter>\n"
    "</function>\n"
    "</tool_call>\n\n"
    "Repeat the <parameter> block for each argument. Omit parameter blocks when "
    "the function has no arguments."
)


def build_qwen_system_prompt(
    screen_width: int,
    screen_height: int,
    instruction: str | None = None,
    tool_call_format: ToolCallFormat = "json",
) -> str:
    """Return the Qwen CUA system prompt with the UI tool spec.

    Args:
        screen_width: Screenshot width in pixels.
        screen_height: Screenshot height in pixels.

    Returns:
        System prompt with tool definition.
    """
    tool = {
        "type": "function",
        "function": {
            "name": "computer_use",
            "description": (
                "Use a keyboard and mouse to interact with a computer.\n"
                f"* The screen's resolution is {screen_width}x{screen_height}.\n"
                "* Click buttons, links, icons, and similar targets with the cursor tip "
                "near the center of the element. Do not click box edges unless asked.\n"
                "* For games, prefer keyboard actions for movement/attacks and mouse clicks "
                "for UI menus.\n"
                "* Use press_key for single keys, press_keys for key combinations, and wait "
                "to pause briefly."
            ),
            "parameters": {
                "properties": {
                    "action": {
                        "description": (
                            "The action to perform. The available actions are:\n"
                            "* `click`: Click a mouse button with coordinate (x, y). "
                            "Use button='right' for right click.\n"
                            "* `click_hold`: Hold a mouse button at coordinate (x, y).\n"
                            "* `mouse_move`: Move the mouse to coordinate (x, y) to turn "
                            "the camera.\n"
                            "* `press_key`: Press a single keyboard key "
                            "(e.g., 'w', 'ArrowUp', 'Space').\n"
                            "* `press_keys`: Press multiple keys together (e.g., ['w', 'd']).\n"
                            "* `wait`: Wait/pause for a short duration.\n"
                        ),
                        "enum": [
                            "click",
                            "click_hold",
                            "mouse_move",
                            "press_key",
                            "press_keys",
                            "wait",
                        ],
                        "type": "string",
                    },
                    "coordinate": {
                        "description": (
                            "(x, y): The x/y pixels from the top-left corner. "
                            "Required by `action=mouse_move`, `action=click`, "
                            "and `action=click_hold`."
                        ),
                        "type": "array",
                    },
                    "button": {
                        "description": (
                            "Mouse button for `action=click` or `action=click_hold`; "
                            "one of left, right, middle."
                        ),
                        "type": "string",
                        "enum": ["left", "right", "middle"],
                    },
                    "key": {
                        "description": (
                            "Keyboard key for `action=press_key` "
                            "(e.g., 'w', 'ArrowUp', 'Space')."
                        ),
                        "type": "string",
                    },
                    "keys": {
                        "description": "Keyboard keys for `action=press_keys` (e.g., ['w', 'd']).",
                        "type": "array",
                    },
                    "duration": {
                        "description": (
                            "Optional duration in seconds for key holds, mouse holds, or waits."
                        ),
                        "type": "number",
                    },
                },
                "required": ["action"],
                "type": "object",
            },
        },
    }

    if tool_call_format == "json":
        tool_call_instruction = _JSON_TOOL_CALL_INSTRUCTION
    elif tool_call_format == "function":
        tool_call_instruction = _FUNCTION_TOOL_CALL_INSTRUCTION
    else:
        raise ValueError(f"Unsupported Qwen tool-call format: {tool_call_format}")

    header = (
        "# Tools\n\n"
        "You may call one or more functions to assist with the user query.\n\n"
        "You are provided with function signatures within <tools></tools> XML tags:\n"
        "<tools>\n"
        f"{json.dumps(tool)}\n"
        "</tools>\n\n"
        f"{tool_call_instruction}"
    )
    if instruction and str(instruction).strip():
        return f"{header}\n\n## User Instruction\n{instruction}"
    return header


def build_qwen_prompt(
    instruction: str,
    screen_width: int,
    screen_height: int,
    tool_call_format: ToolCallFormat = "json",
) -> str:
    system = build_qwen_system_prompt(
        screen_width=screen_width,
        screen_height=screen_height,
        tool_call_format=tool_call_format,
    )
    return f"{system}\n\nUser Task:\n{instruction}"


__all__ = ["ToolCallFormat", "build_qwen_system_prompt", "build_qwen_prompt"]

"""Player-1 agent contract narrowed to ViZDoom's executable controls."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from player1.agents.actions.parser import PlayerOneActionParser
from player1.agents.inference.agent import (
    DEFAULT_MODEL_PROFILE_ID,
    AgentConfig,
    GameAgent,
)

def _relative_horizontal_mouse_schema(source: Mapping[str, Any]) -> dict[str, Any]:
    branches = source.get("oneOf")
    if not isinstance(branches, list) or not branches or not isinstance(branches[0], Mapping):
        raise ValueError("Player-1 Control mouse schema does not expose its relative movement branch")
    relative = deepcopy(dict(branches[0]))
    properties = relative.get("properties")
    if not isinstance(properties, dict) or "dy" not in properties:
        raise ValueError("Player-1 Control relative mouse schema is missing dy")
    properties["dy"] = {
        "type": "integer",
        "const": 0,
        "description": "vertical movement is fixed because the ViZDoom suite only supports horizontal aiming.",
    }
    relative["description"] = "one relative horizontal camera movement; positive dx turns right."
    return relative


def _restrict_vizdoom_runtime_tool_specs(
    runtime_tool_specs: list[dict[str, Any]],
    *,
    allowed_keys: tuple[str, ...],
    allow_mouse_move: bool,
    mouse_click_buttons: tuple[str, ...],
    mouse_hold_buttons: tuple[str, ...],
) -> list[dict[str, Any]]:
    restricted = deepcopy(runtime_tool_specs)
    for spec in restricted:
        tool_name = str(spec.get("id") or "")
        for schema_name in ("argument_schema", "prompt_argument_schema"):
            schema = spec.get(schema_name)
            if not isinstance(schema, dict):
                raise ValueError(f"Player-1 Control tool {tool_name!r} is missing {schema_name}")
            properties = schema.get("properties")
            if not isinstance(properties, dict):
                raise ValueError(f"Player-1 Control tool {tool_name!r} has no properties")
            if tool_name == "mouse_control":
                mouse_move = properties.get("mouse_move")
                if allow_mouse_move and not isinstance(mouse_move, Mapping):
                    raise ValueError("Player-1 Control mouse tool is missing mouse_move")
                if allow_mouse_move:
                    properties["mouse_move"] = _relative_horizontal_mouse_schema(mouse_move)
                else:
                    properties.pop("mouse_move", None)
                if mouse_click_buttons:
                    properties["mouse_click"] = {
                        "type": "string",
                        "enum": list(mouse_click_buttons),
                        "description": "click a supported mouse button once.",
                    }
                else:
                    properties.pop("mouse_click", None)
                if mouse_hold_buttons:
                    properties["mouse_hold"] = {
                        "type": "string",
                        "enum": list(mouse_hold_buttons),
                        "description": "hold a supported mouse button for this frame.",
                    }
                else:
                    properties.pop("mouse_hold", None)
                properties.pop("mouse_scroll", None)
            elif tool_name == "key_control":
                for field_name in ("key_hold", "key_tap"):
                    field = properties.get(field_name)
                    if not isinstance(field, dict):
                        raise ValueError(f"Player-1 Control key tool is missing {field_name}")
                    items = field.get("items")
                    if not isinstance(items, dict):
                        raise ValueError(f"Player-1 Control {field_name} has no item schema")
                    items["enum"] = list(allowed_keys)
    return [
        spec
        for spec in restricted
        if spec.get("id") != "mouse_control" or bool(spec.get("argument_schema", {}).get("properties"))
    ]


class VizDoomGameAgent(GameAgent):
    """Expose the Player-1 controls declared by the selected map."""

    def __init__(
        self,
        *,
        game_id: str,
        model_profile_id: str = DEFAULT_MODEL_PROFILE_ID,
    ):
        super().__init__(
            AgentConfig(
                game_id=game_id,
                model_profile_id=model_profile_id,
            )
        )
        controls = self.game.role_control.game_controls
        allowed_keys = tuple(controls.keys)
        self.runtime_tool_specs = _restrict_vizdoom_runtime_tool_specs(
            self.runtime_tool_specs,
            allowed_keys=allowed_keys,
            allow_mouse_move=controls.mouse_move,
            mouse_click_buttons=tuple(controls.mouse_click),
            mouse_hold_buttons=tuple(controls.mouse_hold),
        )
        runtime_schemas = {str(spec["id"]): deepcopy(spec["argument_schema"]) for spec in self.runtime_tool_specs}
        self.unified_action_space_map = {
            name: {
                **deepcopy(binding),
                "argument_schema": deepcopy(runtime_schemas[name]),
            }
            for name, binding in self.unified_action_space_map.items()
            if name in runtime_schemas
        }
        self.action_parser = PlayerOneActionParser(
            self.model_profile.action_format,
            action_space_mode=self.model_profile.action_space_mode,
            runtime_tool_specs=self.runtime_tool_specs,
        )
        self.model_tools = self.action_parser.chat_template_tools()


__all__ = ["VizDoomGameAgent"]

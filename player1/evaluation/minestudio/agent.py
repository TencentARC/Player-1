"""Minecraft admission rules for the shared Player-1 inference agent."""
from collections.abc import Mapping
from typing import Any

from player1.agents.inference.agent import GameAgent
from player1.environments.minestudio.input_semantics import mine_studio_action_admission_error


class MineStudioGameAgent(GameAgent):
    def action_admission_error(self, tool_call: Mapping[str, Any] | None) -> str | None:
        controls = self.game.role_control.game_controls
        return mine_studio_action_admission_error(
            tool_call, allowed_keys=controls.allowed_keys,
            mouse_click_buttons=controls.mouse_click, mouse_hold_buttons=controls.mouse_hold,
        )

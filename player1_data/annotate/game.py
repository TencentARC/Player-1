"""A reusable profile for one explicitly named game and version."""

import json
from pathlib import Path

from player1.datasets.player1_control import player1_control_model_tools
from player1.datasets.release_contract import _canonical_action
from player1_data.annotate.client import require_text, text
from player1_data.files import fingerprint, read_json


def observed_controls(trajectories):
    controls = set()
    for trajectory in trajectories:
        for turn in trajectory["turns"]:
            action = turn["action"]
            controls.update(action.get("key_hold", []) + action.get("key_tap", []))
            controls.update("mouse." + action[key] for key in ("mouse_click", "mouse_hold") if key in action)
            if "mouse_move" in action:
                controls.add("mouse." + action["mouse_move"]["mode"])
            if "mouse_scroll" in action:
                controls.add("mouse.scroll")
    return sorted(controls)


def annotate_game(game: dict, trajectories: list, client, cache_root: Path):
    controls = observed_controls(trajectories)
    cache = cache_root / (fingerprint(game)[:24] + ".json")

    def validate(value):
        if (
            not isinstance(value, dict)
            or set(value) != {"game", "rules", "controls", "example"}
            or value["game"] != game
        ):
            raise ValueError("Game profile must match the explicit game/version")
        require_text(value["rules"], "game rules")
        if not isinstance(value["controls"], dict) or not set(controls) <= value["controls"].keys():
            raise ValueError("Game profile does not cover recorded controls; review this game before continuing")
        for description in value["controls"].values():
            require_text(description, "control description")
        example = value["example"]
        if not isinstance(example, dict) or set(example) != {"reasoning", "action"}:
            raise ValueError("Game profile needs one reasoning/action example")
        require_text(example["reasoning"], "example reasoning")
        _canonical_action(example["action"], sample_id="game-profile-example")

    if cache.exists():
        saved = read_json(cache)
        if saved["provider"] != client.identity():
            raise ValueError("Game profile belongs to another provider/model")
        value = json.loads(saved["response"]["choices"][0]["message"]["content"])
        validate(value)
        return value
    prompt = (
        "Create a game profile for the explicit identity below; keep different versions separate. "
        "Return {game: the unchanged identity, rules: string, controls: {input: meaning}, "
        "example: {reasoning: string, action: valid Player-1 XML}}. Cover every recorded input. "
        "The example may use <tool_call>\\n<function=wait>\\n</function>\\n</tool_call>.\n"
        + json.dumps(
            {"game": game, "recorded_inputs": controls, "tools": player1_control_model_tools()}, ensure_ascii=False
        )
    )
    return client.ask("game", [text(prompt)], cache, validate)

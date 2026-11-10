"""Infer a trajectory goal from its complete storyboard and fixed action timeline."""

import json
from pathlib import Path

from player1_data.annotate.client import require_text, text


def annotate_task(trajectory, profile, root: Path, client, images):
    content = [
        text(
            "Return {task: string}: the concrete goal supported by the entire storyboard and action timeline. "
            "Do not invent achievements or alter recorded controls.\n" + json.dumps(profile, ensure_ascii=False)
        )
    ]
    for turn in trajectory["turns"]:
        content += [text(f"Turn {turn['index']}: {turn['canonical_action']}"), images[turn["image"]]]

    def validate(value):
        if not isinstance(value, dict) or set(value) != {"task"}:
            raise ValueError("Task response must contain exactly task")
        require_text(value["task"], "task")

    return client.ask("task", content, root / "task.json", validate)["task"]

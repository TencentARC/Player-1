"""Causal per-turn reasoning; the demonstrated action is never model-generated."""

import json
from pathlib import Path

from player1_data.annotate.client import require_text, text


def annotate_reasoning(trajectory, profile, task: str, root: Path, client, images):
    result = []
    for index, turn in enumerate(trajectory["turns"]):
        context = {
            "game": trajectory["game"],
            "profile": profile,
            "task": task,
            "fixed_action": turn["canonical_action"],
            "past_actions": [t["canonical_action"] for t in trajectory["turns"][max(0, index - 4) : index]],
        }
        content = [
            text(
                "Return {reasoning: string}: explain the fixed recorded action using only the visible "
                "current and past observations. Do not claim an unseen outcome or rationalize a different action.\n"
                + json.dumps(context, ensure_ascii=False)
            )
        ]
        for past in trajectory["turns"][max(0, index - 2) : index + 1]:
            content += [text(f"Observation at turn {past['index']}"), images[past["image"]]]

        def validate(value):
            if not isinstance(value, dict) or set(value) != {"reasoning"}:
                raise ValueError("Turn response must contain exactly reasoning")
            require_text(value["reasoning"], "reasoning")

        label = client.ask("reasoning", content, root / "labels" / f"{index:04d}.json", validate)
        result.append(label["reasoning"].strip())
    return result

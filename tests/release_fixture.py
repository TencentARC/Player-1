"""Build the single public dataset format for shared reader tests."""

import tempfile
from pathlib import Path

from PIL import Image

from player1_data.files import file_digest, fingerprint
from player1_data.write import write_dataset


def build_release(root, trajectories=2):
    root = Path(root)
    with tempfile.TemporaryDirectory(dir=root.parent) as work:
        prepared = Path(work)
        image = prepared / "frame.jpg"
        Image.new("RGB", (64, 36), "blue").save(image)
        action = "<tool_call>\n<function=wait>\n</function>\n</tool_call>"
        image_sha = file_digest(image)["sha256"]
        items = []
        for index in range(trajectories):
            identity = {
                "adapter_id": "fixture",
                "dataset_id": "fixture",
                "source_revision": "fixture",
                "session_id": f"session-{index}",
                "trajectory_id": f"trajectory-{index}",
            }
            turns = [
                {"index": turn, "image": image.name, "image_sha256": image_sha, "canonical_action": action}
                for turn in range(50)
            ]
            items.append(
                {
                    "root": prepared,
                    "trajectory": {
                        "identity": identity,
                        "binding": fingerprint(identity),
                        "turns": turns,
                        "kind": "gameplay",
                        "game": {"name": "Fixture", "version": "test"},
                    },
                    "profile": {
                        "rules": "Wait in the scene.",
                        "controls": {"wait": "Wait."},
                        "example": {"reasoning": "Observe the scene.", "action": action},
                    },
                    "task": "Wait for the scene.",
                    "reasoning": ["Observe the scene."] * 50,
                    "provider": {"backend": "local_fixture", "model": "fixture"},
                }
            )
        return write_dataset(items, root)

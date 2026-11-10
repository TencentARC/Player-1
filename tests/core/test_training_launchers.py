"""Check launcher configuration and the completed SFT-to-RL handoff."""

import json

import pytest

from player1.training.sft.checkpoint_export import export_identity, exported_model


def test_rl_requires_export_of_latest_completed_sft_step(tmp_path):
    checkpoint = tmp_path / "global_step_1"
    checkpoint.mkdir()
    (checkpoint / "player1.json").write_text('{"dataset":"release-a"}')
    (checkpoint / "model_world_size_1_rank_0.pt").write_bytes(b"native weights")
    (tmp_path / "latest_checkpointed_iteration.txt").write_text("1")
    model = checkpoint / "exported-model"
    model.mkdir()
    (model / "player1-export.json").write_text(json.dumps(export_identity(checkpoint)))
    (model / "config.json").write_text("{}")
    (model / "model.safetensors").touch()
    assert exported_model(tmp_path) == model
    (checkpoint / "player1.json").write_text('{"dataset":"release-b"}')
    with pytest.raises(ValueError, match="identity mismatch"):
        exported_model(tmp_path)
    (tmp_path / "latest_checkpointed_iteration.txt").write_text("2")
    with pytest.raises(ValueError, match="completed"):
        exported_model(tmp_path)

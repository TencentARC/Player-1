"""Viewer contracts for resumed, sampled and still-running evaluations."""

import json

import pytest
from PIL import Image

from player1.evaluation.common import write_json
from player1.evaluation.viewer import _within, episode_index, load_episode


@pytest.fixture
def recording(tmp_path):
    job = {"benchmark": "minedojo", "task_id": "task", "trial": 0, "seed": 42,
           "max_steps": 3, "episode_id": "minedojo/task/trial-0000"}
    parent = tmp_path / job["episode_id"]
    attempt = parent / "attempt-0000"
    attempt.mkdir(parents=True)
    return tmp_path, job, parent, attempt


def test_legacy_sampled_trace_and_partial_write(recording):
    root, job, parent, attempt = recording
    rows = [{"decision": index + 1, "action": {"id": "wait"}, "reward": 0} for index in range(3)]
    (attempt / "trace.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows) + '{"decision":')
    Image.new("RGB", (32, 18)).save(attempt / "step-0000.png")
    data = load_episode(root, job, run_id=0)
    assert len(data["steps"]) == 3
    assert data["steps"][0]["image_url"].startswith("/image?run=0")
    assert data["steps"][1]["image_url"] is None
    assert data["final_image_url"] is None
    assert episode_index(root, [job])[0]["status"] == "in progress"
    write_json(parent / "result.json", {"complete": True, "score": 1})
    assert episode_index(root, [job])[0]["status"] == "complete"


def test_retry_keeps_failed_attempt_and_selects_success(recording):
    root, job, parent, first = recording
    write_json(first / "failure.json", {"error": "Disconnected"})
    assert episode_index(root, [job])[0]["status"] == "failed"
    second = parent / "attempt-0001"
    second.mkdir()
    Image.new("RGB", (32, 18)).save(second / "final.png")
    write_json(parent / "result.json", {"complete": True, "score": 1,
                                        "attempt": second.name, "final_image": "final.png"})
    data = load_episode(root, job, run_id=0)
    assert data["attempt"] == second.name
    assert data["final_image_url"]
    data = load_episode(root, job, run_id=0, attempt=first.name)
    assert data["failure"]["error"] == "Disconnected"
    assert data["final_image_url"] is None
    with pytest.raises(ValueError, match="Unknown attempt"):
        load_episode(root, job, run_id=0, attempt="../outside")


def test_paths_cannot_escape_output_or_follow_external_symlink(tmp_path):
    root = tmp_path / "run"
    root.mkdir()
    (root / "link").symlink_to(tmp_path)
    for name in ("../outside", str(tmp_path / "outside"), "link/outside"):
        with pytest.raises(ValueError, match="outside"):
            _within(root, name)


def test_gym_ledger_uses_stable_collection_seed_offsets():
    from player1.evaluation.gym import build_episodes
    from player1.gym import list_games

    games = list_games()
    rows = build_episodes(trials=2)
    assert len(rows) == len(games) * 2 == 32
    selected = build_episodes(tasks=[games[-1]], trials=2)
    assert selected == rows[-2:]
    assert selected[0]["seed"] == 10000 + (len(games) - 1) * 100000
    assert all(row["max_steps"] > 0 for row in rows)
    with pytest.raises(ValueError, match="Unknown Gym"):
        build_episodes(tasks=["unknown"])

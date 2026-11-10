"""Frozen ViZDoom episode seeds and reporting scales."""

from types import SimpleNamespace

import pytest

from player1.environments.vizdoom.suite import suite_spec
from player1.evaluation.vizdoom.evaluate import _Episode, build_episodes


def test_vizdoom_frozen_ledger_and_seed_slots():
    suite = suite_spec("vizdoom-10-maps")
    expected = {"basic": 0, "deadly_corridor": 1, "deathmatch": 2, "defend_center": 3,
                "defend_line": 4, "health_gathering": 5, "health_gathering_supreme": 6,
                "my_way_home": 7, "battle1": 10, "battle2": 11}
    assert {spec.map_id: suite.seed_index(spec.map_id) for spec in suite.maps} == expected
    jobs = build_episodes()
    assert len(jobs) == 500
    assert [(job["task_id"], job["trial"], job["seed"]) for job in jobs] == [
        (name, trial, 10000 + slot * 100000 + trial)
        for name, slot in expected.items()
        for trial in range(50)
    ]
    limits = {name: 1050 for name in expected}
    limits.update(basic=150, deathmatch=2100)
    assert all(job["max_steps"] == limits[job["task_id"]] for job in jobs)
    assert all(job["benchmark"] == "vizdoom" for job in jobs)
    assert [job["episode_id"] for job in jobs] == [
        f"vizdoom/{name}/trial-{trial:04d}" for name in expected for trial in range(50)
    ]
    for name, slot in expected.items():
        assert build_episodes(tasks=[name], trials=1)[0]["seed"] == 10000 + slot * 100000


@pytest.mark.parametrize("task,reward,score", [
    ("basic", -50, -0.5), ("health_gathering", 2100, 1),
    ("battle1", 20, 2), ("my_way_home", 0, 0),
])
def test_vizdoom_fixed_scores_preserve_negative_and_unbounded_values(task, reward, score):
    episode = object.__new__(_Episode)
    episode.spec = next(spec for spec in suite_spec("vizdoom-10-maps").maps if spec.map_id == task)
    assert episode.score(SimpleNamespace(info={"total_reward": reward})) == score

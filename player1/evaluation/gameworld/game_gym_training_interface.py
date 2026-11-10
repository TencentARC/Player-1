"""Emit GameWorld trials as JSON for the outer training data builder."""

from __future__ import annotations

import argparse
import json

from game_gym_catalog import GAMEWORLD_SUITES, materialize_suite, select_suite_tasks


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", choices=GAMEWORLD_SUITES, required=True)
    parser.add_argument("--trials-per-task", type=int, required=True)
    parser.add_argument("--max-steps", type=int)
    parser.add_argument("--task-id", action="append", default=[])
    parser.add_argument("--print-trial-count", action="store_true")
    args = parser.parse_args()
    if args.trials_per_task <= 0:
        parser.error("--trials-per-task must be positive")
    task_pairs = select_suite_tasks(args.suite, args.task_id)
    if args.print_trial_count:
        print(len(task_pairs) * args.trials_per_task)
        return
    print(
        json.dumps(
            materialize_suite(
                args.suite,
                trials_per_task=args.trials_per_task,
                max_steps=args.max_steps,
                task_pairs=task_pairs,
            ),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

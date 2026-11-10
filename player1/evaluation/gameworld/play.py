#!/usr/bin/env python3
"""Play or validate gameAPI integrations via live browser sessions."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import shutil
import sys
from pathlib import Path

from env.game_launcher import append_url_suffix
from catalog.games import resolve_game_id
from utils import setup_logging

setup_logging()
LOGGER = logging.getLogger(__name__)

DEFAULT_PORT = 8101
DEFAULT_COMMAND = "stream-state"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Play or validate gameAPI integrations through live browser sessions. "
            "When the command is omitted, play.py defaults to 'stream-state'."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    stream_parser = subparsers.add_parser(
        "stream-state",
        help="Launch a game and continuously print gameAPI state snapshots.",
    )
    stream_parser.add_argument(
        "--game",
        required=True,
        help="Exact catalog game id.",
    )
    stream_parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"HTTP server port (default: {DEFAULT_PORT}).",
    )
    stream_parser.add_argument(
        "--suffix",
        default=None,
        help="Optional URL suffix override.",
    )
    stream_parser.add_argument(
        "--headless",
        action="store_true",
        help="Run browser in headless mode.",
    )

    capture_parser = subparsers.add_parser(
        "capture-task",
        help="Launch a catalog game/task and capture screenshots plus a manifest.",
    )
    capture_parser.add_argument(
        "--game",
        required=True,
        help="Exact catalog game id.",
    )
    capture_parser.add_argument(
        "--task",
        required=True,
        help="Exact task id.",
    )
    capture_parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"HTTP server port (default: {DEFAULT_PORT}).",
    )
    capture_parser.add_argument(
        "--suffix",
        default=None,
        help="Optional URL suffix override. Defaults to task.game_url_suffix.",
    )
    capture_parser.add_argument(
        "--headless",
        action="store_true",
        help="Run browser in headless mode.",
    )

    return parser


def _normalize_argv(argv: list[str] | None = None) -> list[str] | None:
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        return argv
    first = str(argv[0]).strip()
    if first in {"-h", "--help", "help", DEFAULT_COMMAND, "capture-task"}:
        return argv
    return [DEFAULT_COMMAND, *argv]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    return _build_parser().parse_args(_normalize_argv(argv))


def _serialize_task_evaluation(result) -> dict[str, object] | None:
    if result is None:
        return None
    return {
        "task_status": result.status,
        "summary": result.summary,
        "should_stop": result.should_stop,
        "should_reset": result.should_reset,
        "metrics": dict(result.metrics or {}),
    }


async def _stream_state(args: argparse.Namespace) -> int:
    from env.browser_manager import BrowserConfig, BrowserGameManager
    from env.game_launcher import GameLauncher
    from env.game_state_tracker import build_game_state_tracker
    from catalog.games import load_game

    game_id = resolve_game_id(args.game)
    game = load_game(game_id)

    launcher = GameLauncher(
        game_name=game.game_id,
        port=args.port,
    )
    tracker = build_game_state_tracker()

    game_url = launcher.start()
    try:
        game_url = append_url_suffix(game_url, args.suffix)
        manager = BrowserGameManager(
            BrowserConfig(
                game_url=game_url,
                width=game.width,
                height=game.height,
                headless=bool(args.headless),
                speed_multiplier=game.speed_multiplier,
            )
        )

        async with manager:
            while True:
                snapshot = await tracker.snapshot(manager.page)
                print(snapshot.summary)
                await asyncio.sleep(1.0)
    finally:
        launcher.stop()


async def _capture_task(args: argparse.Namespace) -> int:
    from env import build_task_evaluator, reset_task_evaluator_episode_metrics
    from env.browser_manager import BrowserConfig, BrowserGameManager
    from env.game_launcher import GameLauncher
    from env.game_state_tracker import build_game_state_tracker
    from catalog.games import load_game
    from catalog.tasks import load_task

    game_id = resolve_game_id(args.game)
    task_id = str(args.task).strip()
    game = load_game(game_id)
    task = load_task(game_id, task_id)
    suffix = args.suffix if args.suffix is not None else task.game_url_suffix

    output_dir = (Path("results") / "play" / game_id / task_id).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    launcher = GameLauncher(
        game_name=game.game_id,
        port=args.port,
    )
    tracker = build_game_state_tracker()
    evaluator = build_task_evaluator(
        evaluator_config=task.evaluator_config,
    )

    game_url = launcher.start()
    try:
        game_url = append_url_suffix(game_url, suffix)
        manager = BrowserGameManager(
            BrowserConfig(
                game_url=game_url,
                width=game.width,
                height=game.height,
                headless=bool(args.headless),
                speed_multiplier=game.speed_multiplier,
            )
        )

        async with manager:
            ready = await manager.wait_until_actionable(
                stage="capture-task",
            )
            snapshot = await tracker.snapshot(manager.page)
            eval_metrics: dict[str, object] = {}
            evaluation_result = await evaluator(
                state=snapshot.state,
                step_index=1,
                metrics=eval_metrics,
            )
            if evaluation_result.metrics:
                eval_metrics = dict(evaluation_result.metrics)
            task_evaluation: dict[str, object] = {
                "before_reset": _serialize_task_evaluation(evaluation_result),
                "reset_invoked": False,
                "reset_ok": None,
                "ready_after_reset": None,
                "after_reset": None,
            }
            if evaluation_result.should_reset:
                task_evaluation["reset_invoked"] = True
                reset_ok = await manager.reset_game()
                task_evaluation["reset_ok"] = bool(reset_ok)
                if reset_ok:
                    eval_metrics = reset_task_evaluator_episode_metrics(eval_metrics)
                    ready = await manager.wait_until_actionable(
                        stage="capture-task-reset",
                    )
                    task_evaluation["ready_after_reset"] = ready
                    snapshot = await tracker.snapshot(manager.page)
                    evaluation_result = await evaluator(
                        state=snapshot.state,
                        step_index=2,
                        metrics=eval_metrics,
                    )
                    if evaluation_result.metrics:
                        eval_metrics = dict(evaluation_result.metrics)
                    task_evaluation["after_reset"] = _serialize_task_evaluation(
                        evaluation_result
                    )
            screenshot_path = await manager.capture_screenshot("capture.png")

            destination = output_dir / "capture.png"
            if screenshot_path != destination:
                shutil.copy2(screenshot_path, destination)

            manifest = {
                "game_id": game_id,
                "task_id": task_id,
                "task_prompt": task.task_prompt,
                "game_url": game_url,
                "ready": ready,
                "screenshot": str(destination),
                "state_summary": snapshot.summary,
                "state": snapshot.state,
                "task_evaluation": task_evaluation,
            }
            manifest_path = output_dir / "manifest.json"
            manifest_path.write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            LOGGER.info("Wrote validation capture to %s", output_dir)
    finally:
        launcher.stop()
    return 0


async def _run_async(args: argparse.Namespace) -> int:
    if args.command == "stream-state":
        return await _stream_state(args)
    if args.command == "capture-task":
        return await _capture_task(args)
    raise ValueError(f"Unsupported command: {args.command}")


def main() -> int:
    args = _parse_args()
    return asyncio.run(_run_async(args))


if __name__ == "__main__":
    raise SystemExit(main())

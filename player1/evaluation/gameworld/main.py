"""Prototype entry-point that ties together the multi-agent VLM framework."""

from __future__ import annotations

import argparse
import asyncio
import logging

from catalog import build_runtime_config
from runtime import Agent, Coordinator, Evaluator, GameEnv
from tools.runs import finalize_run_metadata, prepare_run_artifacts
from utils import (
    build_agent_clients,
    setup_logging,
)

LOGGER = logging.getLogger(__name__)


async def main(
    config_preset: str,
    headless: bool | None = None,
    port: int | None = None,
    log_root: str | None = None,
    model_endpoint: str | None = None,
):
    """Main entry point for the game worlds.

    Args:
        config_preset: Catalog preset spec (game_id+task_id+model1,model2,...).
    """
    runtime_config = build_runtime_config(config_preset)
    prepare_run_artifacts(
        runtime_config,
        config_preset=config_preset,
        port=port,
        log_root=log_root,
    )
    LOGGER.info(
        "Loading preset config: %s.\nAgent models: %s",
        config_preset,
        ", ".join(f"agent_{i}={mt}" for i, mt in enumerate(runtime_config.model_ids)),
    )

    agent_ids = [f"agent_{i}" for i in range(runtime_config.agent_count)]
    clients = build_agent_clients(
        runtime_config,
        agent_ids,
        model_endpoint_override=model_endpoint,
    )
    agents = [
        Agent(
            agent_id=agent_id,
            agent_type=clients[idx].config.model_type,
            client=clients[idx],
            controls=runtime_config.role_controls_maps[idx],
            semantic_controls_map=runtime_config.semantic_controls_maps[idx],
        )
        for idx, agent_id in enumerate(agent_ids)
    ]

    env = GameEnv(runtime_config, headless=headless, port=port)
    evaluator = Evaluator(runtime_config)
    coordinator = Coordinator(
        env=env,
        agents=agents,
        evaluator=evaluator,
    )

    final_return_code = 1
    final_status = "error"

    try:
        await coordinator.run()  # main loop
        final_return_code = 0
        final_status = "completed"

    except asyncio.CancelledError:
        LOGGER.info("Main loop cancelled")
        final_return_code = 130
        final_status = "error"
        raise
    except KeyboardInterrupt:
        LOGGER.info("Main loop interrupted")
        final_return_code = 130
        final_status = "error"
        raise
    finally:
        finalize_run_metadata(
            runtime_config,
            status=final_status,
            return_code=final_return_code,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run VLM agents to play browser games",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
    Examples:
    # Catalog format: game_id+task_id+model1,model2
    python main.py --config 01_2048+01_01+gpt-5.2
    python main.py --config 10_doodle-jump+10_05+qwen3-vl-235b-a22b-cua
    """,
    )
    parser.add_argument(
        "--config",
        type=str,
        required=True,
        metavar="PRESET",
        help="Catalog preset spec: game_id+task_id+model1,model2 (required)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Local game server port (default: internal default).",
    )
    parser.add_argument(
        "--log-root",
        default=None,
        help="Exact output directory for this run.",
    )
    parser.add_argument(
        "--model-endpoint",
        default=None,
        help="Override the catalog endpoint for all agents in this run.",
    )
    headless_group = parser.add_mutually_exclusive_group()
    headless_group.add_argument(
        "--headless",
        action="store_true",
        help="Run the browser in headless mode (default when no display is detected).",
    )
    headless_group.add_argument(
        "--headed",
        dest="headless",
        action="store_false",
        help="Force headed mode (requires an X server or Wayland display).",
    )
    parser.set_defaults(headless=None)
    args = parser.parse_args()
    setup_logging()

    try:
        asyncio.run(
            main(
                config_preset=args.config,
                headless=args.headless,
                port=args.port,
                log_root=args.log_root,
                model_endpoint=args.model_endpoint,
            )
        )
    except KeyboardInterrupt:
        LOGGER.info("Shutting down due to keyboard interrupt")
        raise SystemExit(130)

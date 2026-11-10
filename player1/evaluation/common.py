"""Shared episode execution and model-policy settings."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import mean

from player1.agents.inference import AgentConfig, GameAgent, ModelConfig, PlayerOnePolicy
from player1.agents.vision import prepare_agent_image


@dataclass
class EvaluationConfig:
    model: str
    model_revision: str
    output: Path = Path("outputs/evaluation")
    endpoint: str = "http://127.0.0.1:8000/v1"
    api_key_env: str | None = None
    history_turns: int = 2
    old_history_turns: int = 2
    frame_interval: int = 1

    def __post_init__(self):
        if not self.model.strip() or not self.model_revision.strip():
            raise ValueError("Model and model revision must be specified")
        if min(self.history_turns, self.old_history_turns, self.frame_interval) < 0:
            raise ValueError("History and frame intervals cannot be negative")
        self.output = Path(self.output).expanduser()


def policy_for(args, game_id, *, agent_factory=None):
    return PlayerOnePolicy(
        ModelConfig(model=args.model, endpoint=args.endpoint, max_tokens=512,
                    temperature=1.0, top_p=0.95, top_k=20, enable_thinking=True,
                    tool_choice="auto", api_key_env=args.api_key_env, max_retries=0),
        agent_factory=agent_factory or (lambda: GameAgent(AgentConfig(
            game_id=game_id, model_profile_id="qwen3.5-player1-control-v-a-baserl",
        ))), action_format_retry_max=0, observe_remaining_turns=True,
    )


def reset_policy(policy, args, job, instruction):
    policy.reset(instruction, job["seed"], {
        "max_decisions": job["max_steps"], "history_context_turns": args.history_turns,
        "history_context_old_turns": args.old_history_turns,
        "history_context_old_mode": "a" if args.old_history_turns else None,
    })


def identity(args, jobs):
    config = {key: getattr(args, key) for key in (
        "model", "model_revision", "history_turns", "old_history_turns",
    )}
    config["benchmark"] = jobs[0]["benchmark"] if jobs else None
    config["jobs"] = jobs
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def summarize(jobs, results):
    completed = [result for result in results if result.get("complete") is True]
    grouped = defaultdict(list)
    for result in completed:
        grouped[result["task_id"]].append(result["score"])
    return {
        "expected_episodes": len(jobs), "completed_episodes": len(completed),
        "infrastructure_failures": len(results) - len(completed),
        "complete": len(completed) == len(jobs),
        "mean_task_score": mean(mean(values) for values in grouped.values()) if grouped else None,
        "by_task": {task: {"mean_score": mean(values), "episodes": len(values)} for task, values in grouped.items()},
    }


def prepare_evaluation(args: EvaluationConfig, jobs):
    signature = identity(args, jobs)
    args.output.mkdir(parents=True, exist_ok=True)
    plan_path = args.output / "plan.json"
    if plan_path.exists() and json.loads(plan_path.read_text())["signature"] != signature:
        raise ValueError("Existing output belongs to a different model revision or evaluation protocol")
    write_json(plan_path, {"signature": signature, "jobs": jobs,
                           "model": args.model, "model_revision": args.model_revision})
    return signature


async def run_episode(args: EvaluationConfig, job, create_episode, signature):
    parent = args.output / job["episode_id"]
    final_path = parent / "result.json"
    if final_path.exists():
        result = json.loads(final_path.read_text())
        if result.get("signature") != signature or result.get("job") != job or result.get("complete") is not True:
            raise ValueError(f"Invalid completed evaluation receipt: {final_path}")
        return result
    parent.mkdir(parents=True, exist_ok=True)
    attempt = parent / f"attempt-{len(list(parent.glob('attempt-*'))):04d}"
    attempt.mkdir()
    episode = None
    try:
        episode = create_episode(args, job)
        current = await episode.start()
        with (attempt / "trace.jsonl").open("w") as trace:
            for index in range(job["max_steps"]):
                image = prepare_agent_image(current.image, max_height=480)
                image_name = None
                if args.frame_interval > 0 and index % args.frame_interval == 0:
                    image_name = f"step-{index:04d}.png"
                    image.save(attempt / image_name)
                step = await asyncio.to_thread(episode.policy.act, image)
                current = await episode.step(step.control_action)
                episode.policy.commit_after_successful_step(step, current)
                trace.write(json.dumps({"decision": index + 1, "valid": step.valid,
                                        "action": step.control_action, "reward": current.reward,
                                        "observation_image": image_name,
                                        "invalid_reason": step.invalid_reason,
                                        "terminated": current.terminated, "truncated": current.truncated,
                                        "generation": step.generation.to_dict()}, allow_nan=False) + "\n")
                trace.flush()
                if hasattr(episode, "after_commit"):
                    episode.after_commit()
                if current.terminated or current.truncated:
                    break
        final_image = None
        if args.frame_interval > 0:
            final_image = "final.png"
            prepare_agent_image(current.image, max_height=480).save(attempt / final_image)
        result = {"task_id": job["task_id"], "job": job, "signature": signature,
                  "score": episode.score(current), "complete": True, "decisions": index + 1,
                  "attempt": attempt.name, "final_image": final_image,
                  "terminated": current.terminated, "truncated": current.truncated}
        await episode.close()
        episode = None
        write_json(final_path, result)
    except Exception as error:
        result = {"task_id": job["task_id"], "job": job, "signature": signature,
                  "complete": False, "error": f"{type(error).__name__}: {error}"}
        write_json(attempt / "failure.json", result)
    finally:
        if episode:
            try:
                await episode.close()
            except Exception as error:
                write_json(attempt / "cleanup-failure.json", {"error": f"{type(error).__name__}: {error}"})
    print(f"{job['episode_id']}: {'complete' if result['complete'] else 'infrastructure failure'}", flush=True)
    return result


async def run_episodes(args: EvaluationConfig, jobs, create_episode):
    signature = prepare_evaluation(args, jobs)
    results = []
    for job in jobs:
        results.append(await run_episode(args, job, create_episode, signature))
        write_json(args.output / "summary.json", summarize(jobs, results))
    summary = summarize(jobs, results)
    write_json(args.output / "summary.json", summary)
    return summary

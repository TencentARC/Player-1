"""CLI facade for benchmark experiment runs."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from tools.runs.process import (
    build_run_overrides,
    build_experiment_context,
    run_wave,
    start_experiment,
    update_live_experiment_manifest,
)
from tools.runs.reports import write_experiment_outputs
from tools.runs.spec import load_experiment, resolve_experiment_path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a benchmark experiment.")
    parser.add_argument(
        "--experiment", required=True, help="Benchmark experiment YAML path."
    )
    parser.add_argument("--results-dir", default="results", help="Results root.")
    parser.add_argument("--port", type=int, default=8101, help="Base game server port.")
    parser.add_argument(
        "--max-parallel", default=5, type=int, help="Max concurrent runs."
    )
    parser.add_argument(
        "--model-endpoint",
        action="append",
        default=[],
        help=(
            "Model endpoint assigned to benchmark runs. Repeat the flag to define an "
            "endpoint pool selected round-robin by run index."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    root = Path(__file__).resolve().parent
    experiment_path = resolve_experiment_path(args.experiment)
    results_dir = Path(args.results_dir)

    experiment = load_experiment(experiment_path)
    run_overrides = build_run_overrides(experiment.config)

    max_parallel = max(
        1,
        min(args.max_parallel or len(experiment.runs), len(experiment.runs)),
    )
    effective_parallel = min(
        max_parallel, max(len(wave) for wave in experiment.repeat_waves)
    )
    model_endpoints = tuple(
        dict.fromkeys(
            endpoint.strip() for endpoint in args.model_endpoint if endpoint.strip()
        )
    )
    output_dir = (
        results_dir / f"{experiment.name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )

    print(
        f"Benchmark: {experiment.name}\n"
        f"Expanded runs: {len(experiment.runs)}\n"
        f"Repeat waves: {len(experiment.repeat_waves)}\n"
        f"Parallel workers: {effective_parallel}\n"
        f"Run overrides: {json.dumps(run_overrides, ensure_ascii=False, sort_keys=True)}\n"
        f"Model endpoints: {json.dumps(model_endpoints, ensure_ascii=False)}\n"
        f"Base port: {args.port}\n"
        f"Results dir: {output_dir}"
    )

    context = build_experiment_context(
        root=root,
        output_dir=output_dir,
        experiment=experiment,
        run_overrides=run_overrides,
        base_port=args.port,
        max_parallel=effective_parallel,
        model_endpoints=model_endpoints,
    )

    start_experiment(context)
    started_at = datetime.now().isoformat()
    rows = []
    for wave_idx, wave_runs in enumerate(experiment.repeat_waves, start=1):
        rows.extend(
            run_wave(
                wave_runs,
                context=context,
                wave_idx=wave_idx,
                completed_rows=rows,
            )
        )

    rows.sort(key=lambda row: int(row["run_index"]))
    write_experiment_outputs(
        output_dir,
        experiment.name,
        experiment.path,
        started_at,
        rows,
    )
    manifest = update_live_experiment_manifest(
        context,
        rows=rows,
        active_run_ids=[],
        final=True,
    )

    print(
        (
            "\nBenchmark completed."
            if manifest["status"] == "completed"
            else "\nBenchmark completed with errors."
        ),
        f"Summary JSON: {output_dir / 'summary.json'}",
        f"Runs CSV: {output_dir / 'runs.csv'}",
        f"Aggregate by model CSV: {output_dir / 'aggregate_by_model.csv'}",
    )
    return 0 if manifest["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

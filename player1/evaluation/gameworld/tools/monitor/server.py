"""Small HTTP dashboard over the canonical run artifacts."""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import time
import urllib.parse
import webbrowser
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from tools.runs.artifacts import (
    build_interaction_payload,
    default_results_dir,
    list_all_run_dirs,
    list_experiment_dirs,
    list_experiment_run_dirs,
    list_interaction_paths,
    load_evaluation,
    read_experiment_manifest,
    read_json_object,
    read_last_jsonl_object,
    read_run_meta,
    resolve_experiment_dir,
    resolve_run_dir,
)

LOGGER = logging.getLogger(__name__)
TEMPLATE_PATH = Path(__file__).with_name("dashboard_template.html")
ACTIVE_RUN_STATUSES = {"starting", "running"}
DEFAULT_RUN_LIMIT = 50
ALLOWED_ARTIFACT_SUFFIXES = {
    ".gif",
    ".jpeg",
    ".jpg",
    ".log",
    ".png",
    ".webp",
}


def _parse_timestamp(value: Any) -> datetime:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    return datetime.min


def _latest_interaction(
    run_dir: Path,
    *,
    allow_incomplete_tail: bool,
) -> tuple[Path, dict[str, Any]] | None:
    latest: tuple[Path, dict[str, Any]] | None = None
    latest_key: tuple[datetime, int, str] | None = None
    for path in list_interaction_paths(run_dir):
        payload = read_last_jsonl_object(
            path,
            allow_incomplete_tail=allow_incomplete_tail,
        )
        if payload is None:
            continue
        key = (
            _parse_timestamp(payload.get("timestamp")),
            int(payload.get("interaction_id") or 0),
            str(payload.get("agent_id") or path.parent.name),
        )
        if latest_key is None or key >= latest_key:
            latest = (path, payload)
            latest_key = key
    return latest


def _artifact_link(results_dir: Path, target: Path | None) -> str | None:
    if target is None or not target.is_file():
        return None
    resolved = target.resolve()
    if not resolved.is_relative_to(results_dir):
        return None
    if not _is_canonical_artifact(results_dir, resolved):
        return None
    return resolved.relative_to(results_dir).as_posix()


def _run_outcome(meta: dict[str, Any], evaluation: dict[str, Any]) -> str:
    status = str(meta.get("status") or "").strip().lower()
    if status in ACTIVE_RUN_STATUSES:
        return "active"
    if status in {"error", "incomplete"}:
        return status
    if evaluation.get("finalized") is True:
        task_status = str(evaluation.get("task_status") or "").strip().lower()
        if task_status in {"success", "fail"}:
            return task_status
    if status == "completed":
        return "incomplete"
    return status or "unknown"


def build_run_overview(
    run_dir: str | Path,
    results_dir: str | Path,
    *,
    meta: dict[str, Any] | None = None,
    evaluation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the compact run projection used by overview and experiment pages."""
    run_dir = Path(run_dir)
    results_dir = Path(results_dir).resolve()
    meta = meta or read_run_meta(run_dir)
    evaluation = evaluation if evaluation is not None else load_evaluation(run_dir)
    evaluation = evaluation or {}
    metrics = evaluation.get("metrics")
    metrics = metrics if isinstance(metrics, dict) else {}
    status = str(meta.get("status") or "unknown").strip().lower()
    latest = _latest_interaction(
        run_dir,
        allow_incomplete_tail=status in ACTIVE_RUN_STATUSES,
    )
    latest_timestamp = None
    latest_screenshot = None
    if latest is not None:
        interaction_path, interaction = latest
        latest_timestamp = interaction.get("timestamp")
        input_payload = interaction.get("input")
        if isinstance(input_payload, dict) and input_payload.get("screenshot"):
            latest_screenshot = _artifact_link(
                results_dir,
                interaction_path.parent / str(input_payload["screenshot"]),
            )

    updated_at = meta.get("updated_at")
    if _parse_timestamp(latest_timestamp) > _parse_timestamp(updated_at):
        updated_at = latest_timestamp
    return {
        "run_id": meta["run_id"],
        "experiment_id": meta.get("experiment_id"),
        "game_id": meta.get("game_id"),
        "task_id": meta.get("task_id"),
        "model_spec": meta.get("model_spec"),
        "status": status,
        "outcome": _run_outcome(meta, evaluation),
        "updated_at": updated_at,
        "step": evaluation.get("step"),
        "max_steps": evaluation.get("max_steps"),
        "game_status": evaluation.get("game_status"),
        "score": metrics.get("score"),
        "progress": evaluation.get("progress"),
        "latest_screenshot": latest_screenshot,
    }


def _sorted_run_overviews(
    entries: list[tuple[Path, dict[str, Any], dict[str, Any]]],
    results_dir: Path,
) -> list[dict[str, Any]]:
    indexed_runs = [
        (
            build_run_overview(
                run_dir,
                results_dir,
                meta=meta,
                evaluation=evaluation,
            ),
            int(meta.get("run_index") or 0),
        )
        for run_dir, meta, evaluation in entries
    ]
    indexed_runs.sort(
        key=lambda item: (
            _parse_timestamp(item[0].get("updated_at")),
            item[1],
            str(item[0]["run_id"]),
        ),
        reverse=True,
    )
    return [run for run, _index in indexed_runs]


def _experiment_summary(
    experiment_dir: Path,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    overall: dict[str, Any] = {}
    summary_path = experiment_dir / "summary.json"
    if summary_path.is_file() and not summary_path.is_symlink():
        summary = read_json_object(summary_path)
        if isinstance(summary.get("overall"), dict):
            overall = summary["overall"]

    return {
        key: manifest.get(key)
        for key in (
            "experiment_id",
            "experiment_name",
            "status",
            "total_runs",
            "completed_runs",
            "started_at",
            "updated_at",
        )
    } | {
        "task_avg_success_rate": overall.get("task_avg_success_rate"),
        "task_avg_progress": overall.get("task_avg_progress"),
    }


def build_overview_payload(
    results_dir: str | Path,
    *,
    run_limit: int = DEFAULT_RUN_LIMIT,
) -> dict[str, Any]:
    """Return all active runs plus enough recent runs to fill ``run_limit``."""
    started_at = time.perf_counter()
    results_dir = Path(results_dir).resolve()
    run_limit = max(1, int(run_limit))

    manifests = [
        (path, read_experiment_manifest(path))
        for path in list_experiment_dirs(results_dir)
    ]
    entries: list[tuple[Path, dict[str, Any], dict[str, Any]]] = []
    stats = {
        "known_runs": 0,
        "active_runs": 0,
        "success_runs": 0,
        "fail_runs": 0,
        "error_runs": 0,
        "incomplete_runs": 0,
        "known_experiments": len(manifests),
    }
    for run_dir in list_all_run_dirs(results_dir):
        meta = read_run_meta(run_dir)
        evaluation = load_evaluation(run_dir) or {}
        entries.append((run_dir, meta, evaluation))
        stats["known_runs"] += 1
        status = str(meta.get("status") or "").strip().lower()
        outcome = _run_outcome(meta, evaluation)
        if status in ACTIVE_RUN_STATUSES:
            stats["active_runs"] += 1
        if outcome in {"success", "fail", "error", "incomplete"}:
            stats[f"{outcome}_runs"] += 1

    entries.sort(
        key=lambda item: (
            _parse_timestamp(item[1].get("updated_at")),
            int(item[1].get("run_index") or 0),
            str(item[1].get("run_id") or ""),
        ),
        reverse=True,
    )
    active = [
        entry
        for entry in entries
        if str(entry[1].get("status") or "").strip().lower() in ACTIVE_RUN_STATUSES
    ]
    selected_paths = {entry[0].resolve() for entry in active}
    selected = list(active)
    for entry in entries:
        if len(selected) >= max(run_limit, len(active)):
            break
        if entry[0].resolve() not in selected_paths:
            selected.append(entry)
            selected_paths.add(entry[0].resolve())

    runs = _sorted_run_overviews(selected, results_dir)
    experiments = sorted(
        (
            _experiment_summary(experiment_dir, manifest)
            for experiment_dir, manifest in manifests
        ),
        key=lambda item: _parse_timestamp(item.get("updated_at")),
        reverse=True,
    )
    duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
    LOGGER.info(
        "Overview built. results_dir=%s known_runs=%d returned_runs=%d duration_ms=%.2f",
        results_dir,
        stats["known_runs"],
        len(runs),
        duration_ms,
    )
    return {
        "generated_at": datetime.now().isoformat(),
        "stats": stats,
        "runs": runs,
        "experiments": experiments,
        "overview_duration_ms": duration_ms,
    }


def build_experiment_payload(
    results_dir: str | Path,
    experiment_id: str,
) -> dict[str, Any]:
    results_dir = Path(results_dir).resolve()
    experiment_dir = resolve_experiment_dir(results_dir, experiment_id)
    manifest = read_experiment_manifest(experiment_dir)
    entries = [
        (run_dir, read_run_meta(run_dir), load_evaluation(run_dir) or {})
        for run_dir in list_experiment_run_dirs(experiment_dir)
    ]
    runs = _sorted_run_overviews(entries, results_dir)
    run_order = manifest.get("run_order")
    if isinstance(run_order, list):
        order = {str(run_id): index for index, run_id in enumerate(run_order)}
        runs.sort(
            key=lambda item: (order.get(item["run_id"], len(order)), item["run_id"])
        )
    return {
        "experiment": _experiment_summary(experiment_dir, manifest),
        "runs": runs,
    }


def build_run_payload(
    results_dir: str | Path,
    run_id: str,
    *,
    experiment_id: str | None = None,
) -> dict[str, Any]:
    """Return one complete interaction snapshot; empty streams are valid."""
    results_dir = Path(results_dir).resolve()
    run_dir = resolve_run_dir(results_dir, run_id, experiment_id=experiment_id)
    meta = read_run_meta(run_dir)
    evaluation = load_evaluation(run_dir) or {}
    is_active = str(meta.get("status") or "").strip().lower() in ACTIVE_RUN_STATUSES
    interactions = build_interaction_payload(
        run_dir,
        results_dir,
        allow_incomplete_tail=is_active,
    )
    overview = build_run_overview(
        run_dir,
        results_dir,
        meta=meta,
        evaluation=evaluation,
    )
    stderr_path = (
        run_dir / "stderr.log" if meta.get("stderr_log") == "stderr.log" else None
    )
    return {
        "run": overview,
        "agents": interactions["agents"],
        "interactions": interactions["interactions"],
        "artifacts": {
            "stderr_log": _artifact_link(results_dir, stderr_path),
        },
    }


def _json_response(
    handler: BaseHTTPRequestHandler,
    payload: dict[str, Any],
    status: int = HTTPStatus.OK,
) -> None:
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(raw)))
    handler.end_headers()
    handler.wfile.write(raw)


def _text_response(
    handler: BaseHTTPRequestHandler,
    payload: str,
    *,
    content_type: str,
    status: int = HTTPStatus.OK,
) -> None:
    raw = payload.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Cache-Control", "no-store")
    handler.send_header(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self'; "
        "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'",
    )
    handler.send_header("Content-Length", str(len(raw)))
    handler.end_headers()
    handler.wfile.write(raw)


def _empty_response(
    handler: BaseHTTPRequestHandler,
    status: int = HTTPStatus.NO_CONTENT,
) -> None:
    handler.send_response(status)
    handler.send_header("Content-Length", "0")
    handler.end_headers()


def _artifact_path(results_dir: Path, rel_path: str) -> Path:
    candidate = (results_dir / rel_path.lstrip("/")).resolve()
    if not candidate.is_relative_to(results_dir):
        raise ValueError(f"Artifact path escapes results directory: {rel_path}")
    return candidate


def _is_canonical_artifact(results_dir: Path, target: Path) -> bool:
    try:
        parts = target.relative_to(results_dir).parts
    except ValueError:
        return False

    try:
        if len(parts) >= 4 and parts[1] == "runs":
            run_dir = resolve_run_dir(
                results_dir,
                parts[2],
                experiment_id=parts[0],
            )
        elif len(parts) >= 2:
            run_dir = resolve_run_dir(results_dir, parts[0])
        else:
            return False
    except (FileNotFoundError, ValueError):
        return False

    relative = target.relative_to(run_dir).parts
    if relative == ("stderr.log",):
        return True
    return (
        len(relative) >= 4
        and relative[0].startswith("agent_")
        and relative[1] == "artifacts"
        and relative[2] in {"memory", "screenshots"}
        and target.suffix.lower() in ALLOWED_ARTIFACT_SUFFIXES - {".log"}
    )


def _artifact_response(
    handler: BaseHTTPRequestHandler,
    results_dir: Path,
    rel_path: str,
) -> int:
    target = _artifact_path(results_dir, rel_path)
    if not target.is_file() or not _is_canonical_artifact(results_dir, target):
        _json_response(
            handler,
            {"error": "artifact_not_found"},
            status=HTTPStatus.NOT_FOUND,
        )
        return HTTPStatus.NOT_FOUND

    content_type = {
        ".gif": "image/gif",
        ".jpeg": "image/jpeg",
        ".jpg": "image/jpeg",
        ".log": "text/plain; charset=utf-8",
        ".png": "image/png",
        ".webp": "image/webp",
    }[target.suffix.lower()]
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", content_type)
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("Content-Length", str(target.stat().st_size))
    handler.end_headers()
    with target.open("rb") as source:
        shutil.copyfileobj(source, handler.wfile)
    return HTTPStatus.OK


def _make_handler(results_dir: Path):
    results_dir = results_dir.resolve()

    class DashboardHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            request_started = time.perf_counter()
            parsed = urllib.parse.urlparse(self.path)
            parts = [
                urllib.parse.unquote(part) for part in parsed.path.split("/") if part
            ]
            status = HTTPStatus.OK
            try:
                match parts:
                    case []:
                        _text_response(
                            self,
                            TEMPLATE_PATH.read_text(encoding="utf-8"),
                            content_type="text/html; charset=utf-8",
                        )
                    case ["favicon.ico"]:
                        status = HTTPStatus.NO_CONTENT
                        _empty_response(self, status)
                    case ["api", "overview"]:
                        _json_response(self, build_overview_payload(results_dir))
                    case ["api", "experiments", experiment_id]:
                        _json_response(
                            self,
                            build_experiment_payload(results_dir, experiment_id),
                        )
                    case ["api", "runs", run_id]:
                        _json_response(self, build_run_payload(results_dir, run_id))
                    case ["api", "experiments", experiment_id, "runs", run_id]:
                        _json_response(
                            self,
                            build_run_payload(
                                results_dir,
                                run_id,
                                experiment_id=experiment_id,
                            ),
                        )
                    case ["artifacts", *artifact_parts] if artifact_parts:
                        status = _artifact_response(
                            self,
                            results_dir,
                            "/".join(artifact_parts),
                        )
                    case _:
                        status = HTTPStatus.NOT_FOUND
                        _json_response(self, {"error": "not_found"}, status=status)
            except FileNotFoundError:
                status = HTTPStatus.NOT_FOUND
                _json_response(self, {"error": "not_found"}, status=status)
            except ValueError as exc:
                status = HTTPStatus.BAD_REQUEST
                _json_response(
                    self,
                    {"error": "bad_request", "detail": str(exc)},
                    status=status,
                )
            except Exception:  # noqa: BLE001
                status = HTTPStatus.INTERNAL_SERVER_ERROR
                LOGGER.exception("Dashboard request failed for %s", parsed.path)
                _json_response(self, {"error": "internal_error"}, status=status)
            finally:
                duration_ms = (time.perf_counter() - request_started) * 1000
                if status >= HTTPStatus.BAD_REQUEST or duration_ms >= 500:
                    LOGGER.warning(
                        "GET %s status=%d duration_ms=%.2f",
                        parsed.path,
                        int(status),
                        duration_ms,
                    )

        def log_message(self, _format: str, *_args: Any) -> None:  # noqa: A003
            return

    return DashboardHandler


def run_dashboard_server(results_dir: str | Path, host: str, port: int) -> None:
    resolved_results = Path(results_dir).resolve()
    server = ThreadingHTTPServer((host, int(port)), _make_handler(resolved_results))
    LOGGER.info("Dashboard serving %s at http://%s:%s", resolved_results, host, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        LOGGER.info("Dashboard interrupted, shutting down.")
    finally:
        server.server_close()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve the run dashboard.")
    parser.add_argument(
        "--results-dir",
        default=str(default_results_dir()),
        help="Results root to monitor.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bind host.")
    parser.add_argument("--port", type=int, default=8787, help="Bind port.")
    parser.add_argument("--open-browser", action="store_true")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper()),
        format="[%(levelname)s] %(message)s",
    )
    url = f"http://{args.host}:{args.port}"
    print(url, flush=True)
    if args.open_browser:
        webbrowser.open(url)
    run_dashboard_server(args.results_dir, args.host, args.port)


if __name__ == "__main__":
    main()

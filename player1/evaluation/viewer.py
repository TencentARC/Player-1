"""Serve recorded evaluation trajectories without starting a model or simulator."""

from __future__ import annotations

import argparse
import json
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit


def _json(path):
    return json.loads(path.read_text()) if path.is_file() else None


def _within(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Path is outside the evaluation directory")
    return path


def _attempts(parent):
    return sorted(path.name for path in parent.glob("attempt-*") if path.is_dir())


def episode_index(root, jobs):
    rows = []
    for index, job in enumerate(jobs):
        parent = _within(root, job["episode_id"])
        result = _json(parent / "result.json")
        attempts = _attempts(parent)
        status = "pending"
        if result and result.get("complete") is True:
            status = "complete"
        elif attempts:
            status = "failed" if (parent / attempts[-1] / "failure.json").exists() else "in progress"
        rows.append({"id": index, "job": job, "status": status,
                     "score": result.get("score") if result else None})
    return rows


def load_episode(root, job, *, run_id, attempt=None):
    parent = _within(root, job["episode_id"])
    attempts = _attempts(parent)
    result = _json(parent / "result.json")
    selected = attempt or (result or {}).get("attempt") or (attempts[-1] if attempts else None)
    if selected is not None and selected not in attempts:
        raise ValueError("Unknown attempt")
    steps = []
    failure = None
    final_image = None
    if selected is not None:
        directory = _within(root, str((parent / selected).relative_to(root)))

        def image_url(name):
            if not name:
                return None
            path = _within(directory, name)
            if path.suffix != ".png" or not path.is_file():
                return None
            return "/image?" + urlencode({"run": run_id, "path": str(path.relative_to(root))})

        failure = _json(directory / "failure.json")
        trace = directory / "trace.jsonl"
        lines = trace.read_text().splitlines(keepends=True) if trace.is_file() else []
        for index, line in enumerate(lines):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                if index == len(lines) - 1 and not line.endswith("\n"):
                    break  # A running evaluation may still be writing its last row.
                raise
            # Existing traces use the zero-based screenshot filename without a reference field.
            name = row.get("observation_image", f"step-{row['decision'] - 1:04d}.png")
            row["image_url"] = image_url(name)
            steps.append(row)
        if result and result.get("attempt") == selected:
            final_image = image_url(result.get("final_image"))
    return {"job": job, "result": result, "attempts": attempts, "attempt": selected,
            "failure": failure, "steps": steps, "final_image_url": final_image}


class _Handler(BaseHTTPRequestHandler):
    def __init__(self, *args, runs, **kwargs):
        self.runs = runs
        super().__init__(*args, **kwargs)

    def log_message(self, *_args):
        pass

    def _send(self, body, content_type, status=200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        request = urlsplit(self.path)
        query = parse_qs(request.query)
        try:
            if request.path == "/":
                return self._send(Path(__file__).with_suffix(".html").read_bytes(), "text/html; charset=utf-8")
            if request.path == "/api/runs":
                payload = [{"id": index, "name": root.name, "model": plan.get("model"),
                            "model_revision": plan.get("model_revision"), "episodes": len(plan["jobs"]),
                            "summary": _json(root / "summary.json")}
                           for index, (root, plan) in enumerate(self.runs)]
            else:
                run_id = int(query["run"][0])
                if not 0 <= run_id < len(self.runs):
                    raise ValueError("Unknown run")
                root, plan = self.runs[run_id]
                if request.path == "/api/episodes":
                    payload = episode_index(root, plan["jobs"])
                elif request.path == "/api/episode":
                    index = int(query["episode"][0])
                    if not 0 <= index < len(plan["jobs"]):
                        raise ValueError("Unknown episode")
                    payload = load_episode(root, plan["jobs"][index], run_id=run_id,
                                           attempt=query.get("attempt", [None])[0])
                elif request.path == "/image":
                    path = _within(root, query["path"][0])
                    if path.suffix != ".png" or not path.is_file():
                        raise ValueError("Unknown screenshot")
                    return self._send(path.read_bytes(), "image/png")
                else:
                    raise ValueError("Unknown endpoint")
            self._send(json.dumps(payload, allow_nan=False).encode(), "application/json")
        except (ValueError, KeyError, TypeError, OSError) as error:
            self._send(json.dumps({"error": str(error)}).encode(), "application/json", status=400)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("outputs", type=Path, nargs="+", help="Evaluation directories containing plan.json")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    runs = []
    for output in args.outputs:
        root = output.expanduser().resolve()
        plan = _json(root / "plan.json")
        if not isinstance(plan, dict) or not isinstance(plan.get("jobs"), list):
            parser.error(f"{root} does not contain an evaluation plan.json")
        runs.append((root, plan))
    with ThreadingHTTPServer(("127.0.0.1", args.port), partial(_Handler, runs=runs)) as server:
        print(f"Trajectory viewer: http://127.0.0.1:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()

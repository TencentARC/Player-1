"""Two public commands: produce a dataset and view a dataset."""

import argparse
import json
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m player1_data", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Prepare, annotate and write a new dataset snapshot.")
    run.add_argument("--config", type=Path, required=True)
    run.add_argument("--work", type=Path, required=True, help="Reusable preparation and accepted annotation results.")
    run.add_argument("--output", type=Path, required=True, help="New immutable dataset directory.")
    view = commands.add_parser("view", help="Read a final dataset through a local Viewer.")
    view.add_argument("dataset", type=Path)
    view.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    if args.command == "run":
        from player1_data.pipeline import load_config, run

        manifest = run(load_config(args.config), work=args.work, output=args.output)
        print(json.dumps({"trajectories": len(manifest["trajectories"]), "rows": sum(t["rows"] for t in manifest["trajectories"])}))
    else:
        from player1_data.viewer import serve

        serve(args.dataset, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

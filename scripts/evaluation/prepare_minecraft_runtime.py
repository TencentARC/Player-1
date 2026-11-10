"""Extract the low-level simulator from a local MineStudio checkout."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

SOURCE = Path("downloads/MineStudio")
OUTPUT = Path("downloads/minestudio-runtime")


def prepare(source: Path, output: Path):
    source = source.expanduser().resolve(strict=True)
    output = output.expanduser().resolve()
    if output.exists() or output.is_relative_to(source):
        raise ValueError("Choose a new output directory outside the upstream checkout")
    simulator = source / "minestudio/simulator/minerl"
    if not simulator.is_dir():
        raise FileNotFoundError(f"Missing upstream low-level simulator: {simulator}")
    output.mkdir(parents=True)
    ignored = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store")
    shutil.copytree(simulator, output / "minestudio/simulator/minerl", ignore=ignored)
    malmo = output / "minestudio/simulator/minerl/Malmo"
    for path in malmo.iterdir():
        if path.name not in {"Schemas", "LICENSE.txt"}:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
    utils = output / "minestudio/utils"
    utils.mkdir()
    for name in ("temp.py", "register.py"):
        shutil.copy2(source / "minestudio/utils" / name, utils / name)
    for name in ("minestudio/__init__.py", "minestudio/simulator/__init__.py"):
        (output / name).write_text('"""MineStudio low-level simulator runtime."""\n')
    (utils / "__init__.py").write_text("from .temp import get_mine_studio_dir\nfrom .register import Register, Registers\n")
    shutil.copy2(source / "LICENSE", output / "LICENSE")
    (output / "README.md").write_text(
        "# MineStudio low-level runtime\n\n"
        "Extracted from https://github.com/CraftJarvis/MineStudio.\n"
        "Includes the upstream MineRL simulator, schemas and notices.\n",
    )
    (output / "source.json").write_text(json.dumps({
        "repository": "https://github.com/CraftJarvis/MineStudio",
    }, indent=2) + "\n")


if __name__ == "__main__":
    prepare(SOURCE, OUTPUT)
    print(OUTPUT.resolve())

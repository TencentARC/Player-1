"""Linux runtime environment setup for the Minecraft adapter."""

from __future__ import annotations

import os
import sys
import types
from pathlib import Path
from typing import Any


def configure_runtime_environment(config: Any) -> None:
    """Apply the Minecraft process environment on the supported Linux runtime."""
    if sys.platform != "linux":
        raise RuntimeError("MineDojo evaluation requires Linux")
    for key, value in getattr(config, "extra_env", {}).items():
        if value is not None:
            os.environ[str(key)] = str(value)

    render_devices = getattr(config, "render_devices", None)
    if render_devices:
        os.environ["RENDER_DEVICES"] = str(render_devices)

    minecraft_output_logdir = getattr(config, "minecraft_output_logdir", None)
    if minecraft_output_logdir:
        os.environ["MALMO_MINECRAFT_OUTPUT_LOGDIR"] = str(Path(minecraft_output_logdir).expanduser())

    java_tool_options = getattr(config, "java_tool_options", None)
    if java_tool_options:
        option = str(java_tool_options)
        existing = os.environ.get("JAVA_TOOL_OPTIONS", "")
        if option not in existing:
            os.environ["JAVA_TOOL_OPTIONS"] = " ".join([existing, option]).strip()


def install_minerl_only_simulator_package() -> None:
    """Bypass MineStudio's high-level simulator package import.

    MineStudio's ``minestudio.simulator.__init__`` eagerly imports
    ``MinecraftSim``, which pulls in model/action-transformer dependencies such
    as torch and einops. For Player-1 we only need the vendored MineRL/Malmo
    runtime, so install a package shim that exposes the simulator subdirectory
    without executing that high-level ``__init__``.
    """
    if "minestudio.simulator" in sys.modules:
        return

    import minestudio

    simulator_dir = Path(minestudio.__file__).resolve().parent / "simulator"
    module = types.ModuleType("minestudio.simulator")
    module.__path__ = [str(simulator_dir)]  # type: ignore[attr-defined]
    module.__package__ = "minestudio"
    module._player1_minerl_only = True  # type: ignore[attr-defined]
    sys.modules["minestudio.simulator"] = module
    minestudio.simulator = module

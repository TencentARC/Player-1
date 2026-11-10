"""Canonical logical tick duration for the native MineStudio simulator.

MineStudio's mission template and ``mc.py`` both define a 50 ms simulator
step.  Its separate ``MINERL_FPS=25`` constant only paces the optional human
play UI; it is not the synchronous Minecraft environment cadence.
"""

MINESTUDIO_STEP_DURATION_MS = 50

__all__ = ["MINESTUDIO_STEP_DURATION_MS"]

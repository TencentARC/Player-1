"""ViZDoom suite and per-map control definitions."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from player1.runtime.camera import CAMERA_DEGREES_PER_OBSERVATION_PIXEL

SUITE_ID = "vizdoom-10-maps"
SUITE_PROTOCOL = "vizdoom_10_v1"
VIZDOOM_VERSION = "1.3.0"
DEFAULT_FRAME_SKIP_TICS = 2
DEFAULT_EPISODE_TIMEOUT_TICS = 2100
DEFAULT_EPISODES_PER_MAP = 50
TURN_DELTA_DEGREES = 10.0
MOUSE_SENSITIVITY_DEGREES_PER_PIXEL = CAMERA_DEGREES_PER_OBSERVATION_PIXEL
RENDER_RESOLUTION_NAME = "RES_640X480"
RENDER_RESOLUTION = (640, 480)

ASSET_ROOT = Path(__file__).with_name("assets")

ASSET_FILES = (
    "battle.wad",
    "battle2.wad",
    "battle_continuous_turning.cfg",
    "battle2_continuous_turning.cfg",
    "defend_the_center.wad",
    "defend_the_center.cfg",
    "defend_the_line.wad",
    "defend_the_line.cfg",
)

ActionMode = Literal[
    "battle",
    "corridor",
    "deathmatch",
    "defense",
    "lateral",
    "maze",
    "navigation",
]
ConfigSource = Literal["vendored", "vizdoom"]
MouseTurnMode = Literal["none", "buttons", "delta"]
ActionField = Literal[
    "move_forward",
    "move_backward",
    "strafe_left",
    "strafe_right",
    "speed",
    "turn_left",
    "turn_right",
]


@dataclass(frozen=True)
class MapSpec:
    """One scenario and the exact Player-1 controls executable in it."""

    map_id: str
    game_id: str
    display_name: str
    config_file: str
    action_mode: ActionMode
    instruction: str
    key_actions: tuple[tuple[str, ActionField], ...]
    mouse_turn: MouseTurnMode = "none"
    fire: bool = False
    weapon_slots: bool = False
    config_source: ConfigSource = "vendored"
    episode_timeout_tics: int = DEFAULT_EPISODE_TIMEOUT_TICS

    @property
    def allowed_keys(self) -> tuple[str, ...]:
        keys = tuple(key for key, _ in self.key_actions)
        if self.weapon_slots:
            return keys + tuple(str(slot) for slot in range(1, 7))
        return keys

    @property
    def default_max_decisions(self) -> int:
        return max_decisions_for_timeout(self.episode_timeout_tics)

    def resolve_config_path(self, vizdoom: Any) -> Path:
        if self.config_source == "vendored":
            return ASSET_ROOT / self.config_file
        return Path(vizdoom.scenarios_path) / self.config_file


@dataclass(frozen=True)
class SuiteSpec:
    suite_id: str
    protocol: str
    maps: tuple[MapSpec, ...]
    default_episodes_per_map: int
    seed_indices: tuple[int, ...]

    def seed_index(self, map_id: str) -> int:
        return self.seed_indices[tuple(spec.map_id for spec in self.maps).index(map_id)]


def max_decisions_for_timeout(
    episode_timeout_tics: int,
    frame_skip_tics: int = DEFAULT_FRAME_SKIP_TICS,
) -> int:
    """Return enough policy decisions to reach the native scenario timeout."""

    if episode_timeout_tics <= 0 or frame_skip_tics <= 0:
        raise ValueError("ViZDoom timeout and frame skip must be positive")
    return math.ceil(episode_timeout_tics / frame_skip_tics)


_BATTLE_KEYS: tuple[tuple[str, ActionField], ...] = (
    ("w", "move_forward"),
    ("a", "strafe_left"),
    ("s", "move_backward"),
    ("d", "strafe_right"),
    ("shift", "speed"),
)
_WASD_KEYS = _BATTLE_KEYS[:-1]
_LATERAL_KEYS: tuple[tuple[str, ActionField], ...] = (
    ("a", "strafe_left"),
    ("d", "strafe_right"),
)
_TURN_KEYS: tuple[tuple[str, ActionField], ...] = (
    ("a", "turn_left"),
    ("d", "turn_right"),
)

BATTLE1_SPEC = MapSpec(
    map_id="battle1",
    game_id="vizdoom_battle1",
    display_name="Battle 1",
    config_file="battle_continuous_turning.cfg",
    action_mode="battle",
    instruction=(
        "Fight the monsters and maximize the total episode reward. Move through the arena, "
        "keep enemies in view, and fire accurately while staying alive."
    ),
    key_actions=_BATTLE_KEYS,
    mouse_turn="delta",
    fire=True,
)
BATTLE2_SPEC = MapSpec(
    map_id="battle2",
    game_id="vizdoom_battle2",
    display_name="Battle 2",
    config_file="battle2_continuous_turning.cfg",
    action_mode="battle",
    instruction=(
        "Fight the monsters and maximize the total episode reward. Move through the arena, "
        "keep enemies in view, and fire accurately while staying alive."
    ),
    key_actions=_BATTLE_KEYS,
    mouse_turn="delta",
    fire=True,
)
DEFEND_CENTER_SPEC = MapSpec(
    map_id="defend_center",
    game_id="vizdoom_defend_center",
    display_name="Defend the Center",
    config_file="defend_the_center.cfg",
    action_mode="defense",
    instruction=(
        "Defend the center and maximize the total episode reward. You cannot move; turn toward "
        "approaching monsters and fire before they reach you."
    ),
    key_actions=_TURN_KEYS,
    mouse_turn="buttons",
    fire=True,
)
DEFEND_LINE_SPEC = MapSpec(
    map_id="defend_line",
    game_id="vizdoom_defend_line",
    display_name="Defend the Line",
    config_file="defend_the_line.cfg",
    action_mode="defense",
    instruction=(
        "Defend the line and maximize the total episode reward. You cannot move; turn toward "
        "approaching monsters and fire before they cross the line."
    ),
    key_actions=_TURN_KEYS,
    mouse_turn="buttons",
    fire=True,
)

_DEFAULT_SCENARIO_SPECS = (
    MapSpec(
        map_id="basic",
        game_id="vizdoom_basic",
        display_name="Basic",
        config_file="basic.cfg",
        config_source="vizdoom",
        action_mode="lateral",
        instruction="Move sideways, aim at the visible monster, and shoot it before time runs out.",
        key_actions=_LATERAL_KEYS,
        fire=True,
        episode_timeout_tics=300,
    ),
    MapSpec(
        map_id="deadly_corridor",
        game_id="vizdoom_deadly_corridor",
        display_name="Deadly Corridor",
        config_file="deadly_corridor.cfg",
        config_source="vizdoom",
        action_mode="corridor",
        instruction="Fight through the corridor and reach the green armor at the far end while staying alive.",
        key_actions=_WASD_KEYS,
        mouse_turn="buttons",
        fire=True,
    ),
    MapSpec(
        map_id="deathmatch",
        game_id="vizdoom_deathmatch",
        display_name="Deathmatch",
        config_file="deathmatch.cfg",
        config_source="vizdoom",
        action_mode="deathmatch",
        instruction="Explore the arena, collect resources, and defeat as many hostile monsters as possible.",
        key_actions=_BATTLE_KEYS,
        mouse_turn="delta",
        fire=True,
        weapon_slots=True,
        episode_timeout_tics=4200,
    ),
    DEFEND_CENTER_SPEC,
    DEFEND_LINE_SPEC,
    MapSpec(
        map_id="health_gathering",
        game_id="vizdoom_health_gathering",
        display_name="Health Gathering",
        config_file="health_gathering.cfg",
        config_source="vizdoom",
        action_mode="navigation",
        instruction="Survive on the damaging floor by moving continuously and collecting nearby medkits.",
        key_actions=(("w", "move_forward"),) + _TURN_KEYS,
        mouse_turn="buttons",
    ),
    MapSpec(
        map_id="health_gathering_supreme",
        game_id="vizdoom_health_gathering_supreme",
        display_name="Health Gathering Supreme",
        config_file="health_gathering_supreme.cfg",
        config_source="vizdoom",
        action_mode="navigation",
        instruction="Search the damaging maze for medical cases, avoid poison bottles, and survive as long as possible.",
        key_actions=(("w", "move_forward"),) + _TURN_KEYS,
        mouse_turn="buttons",
    ),
    MapSpec(
        map_id="my_way_home",
        game_id="vizdoom_my_way_home",
        display_name="My Way Home",
        config_file="my_way_home.cfg",
        config_source="vizdoom",
        action_mode="maze",
        instruction="Explore the maze and reach the green armor before time runs out.",
        key_actions=(("w", "move_forward"),) + _LATERAL_KEYS,
        mouse_turn="buttons",
    ),
)

MAP_SPECS = _DEFAULT_SCENARIO_SPECS + (BATTLE1_SPEC, BATTLE2_SPEC)

_SUITE = SuiteSpec(
    SUITE_ID, SUITE_PROTOCOL, MAP_SPECS, DEFAULT_EPISODES_PER_MAP,
    # Frozen protocol indices: slots 8 and 9 remain reserved.
    seed_indices=(0, 1, 2, 3, 4, 5, 6, 7, 10, 11),
)


def suite_spec(suite_id: str) -> SuiteSpec:
    if suite_id != SUITE_ID:
        raise KeyError(f"Unknown ViZDoom suite {suite_id!r}; expected {SUITE_ID}")
    return _SUITE


def require_assets() -> tuple[str, ...]:
    """Require the vendored scenarios used by ViZDoom-10."""

    missing = [name for name in ASSET_FILES if not (ASSET_ROOT / name).is_file()]
    if missing:
        raise FileNotFoundError(f"Missing ViZDoom assets: {', '.join(missing)}")
    return ASSET_FILES


__all__ = [
    "ASSET_ROOT",
    "ASSET_FILES",
    "ActionMode",
    "ConfigSource",
    "DEFAULT_EPISODE_TIMEOUT_TICS",
    "DEFAULT_EPISODES_PER_MAP",
    "DEFAULT_FRAME_SKIP_TICS",
    "MAP_SPECS",
    "MOUSE_SENSITIVITY_DEGREES_PER_PIXEL",
    "MapSpec",
    "MouseTurnMode",
    "RENDER_RESOLUTION",
    "RENDER_RESOLUTION_NAME",
    "SUITE_ID",
    "SUITE_PROTOCOL",
    "SuiteSpec",
    "TURN_DELTA_DEGREES",
    "VIZDOOM_VERSION",
    "max_decisions_for_timeout",
    "require_assets",
    "suite_spec",
]

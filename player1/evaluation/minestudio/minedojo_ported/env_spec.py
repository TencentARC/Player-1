"""MineStudio EnvSpec construction for the MineDojo-ported benchmark.

This module deliberately keeps task compilation independent from MineStudio
imports.  A worker can therefore materialize and hash all 1,581 plans before
launching Minecraft, then call :func:`build_env_spec` inside the simulator
process.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

from player1.environments.minestudio.timing import MINESTUDIO_STEP_DURATION_MS

from .mappings import MappingResult, map_biome, map_entity, map_inventory_slot, map_item
from .trials import MINEDOJO_PORTED_CATEGORY_MAX_DECISIONS, task_max_decisions

PORTED_ENV_PROTOCOL = "minedojo_ported_minestudio_1_16_5_env_v2"
PORTED_V1_ACTION_DURATION_MS = MINESTUDIO_STEP_DURATION_MS
PORTED_V1_SIM_TICKS_PER_DECISION = 1
MINECRAFT_TICKS_PER_DAY = 24_000

# HumanSurvival omits these keyboard commands. Declaring them only on a
# constructed MineRL task is insufficient because EnvSpec.reset() rebuilds
# actionables at every mission reset (including a transferred JVM).
PORTED_V1_OPTIONAL_ACTION_KEY_CODES = (
    ("drop", "16"),
    ("swapHands", "33"),
    ("ESC", "1"),
    ("togglePerspective", "63"),
)

MINEDOJO_VIEWPOINTS = ("first", "behind", "front")
_MINEDOJO_VIEWPOINT_VALUES = {name: value for value, name in enumerate(MINEDOJO_VIEWPOINTS)}


def normalize_viewpoint(viewpoint: str) -> str:
    normalized = str(viewpoint).strip().lower()
    if normalized not in _MINEDOJO_VIEWPOINT_VALUES:
        raise ValueError(f"viewpoint must be one of {', '.join(MINEDOJO_VIEWPOINTS)}")
    return normalized

@dataclass(frozen=True)
class PortedInventoryStack:
    slot: int
    item: str
    quantity: int
    source_item: str
    source_variant: int | None
    mapping_status: str

    def to_handler_value(self) -> dict[str, Any]:
        return {"type": self.item, "quantity": self.quantity}


@dataclass(frozen=True)
class MineDojoPortedEnvPlan:
    """Fully materialized, JSON-shaped plan for one MineDojo ported task."""

    task_id: str
    category: str
    world_seed: int
    task_rng_seed: int
    initial_inventory: tuple[PortedInventoryStack, ...]
    start_position: dict[str, float] | None
    start_health: float
    start_food: int
    start_time: int | None
    allow_time_passage: bool
    initial_weather: str | None
    allow_mob_spawn: bool
    break_speed_multiplier: float
    world_dimension: str
    specified_biome_id: int | None
    specified_biome_name: str | None
    drawing_str: str | None
    initial_mobs: tuple[str, ...]
    initial_mob_spawn_range_low: tuple[float, float, float] | None
    initial_mob_spawn_range_high: tuple[float, float, float] | None
    requested_max_decisions: int | None
    max_decisions: int
    episode_horizon_ticks: int
    horizon_reason: str
    source_voxel_bounds: dict[str, int] | None
    source_lidar_requested: bool
    mapping_evidence: tuple[dict[str, Any], ...]

    @property
    def inventory_handler(self) -> dict[int, dict[str, Any]]:
        return {stack.slot: stack.to_handler_value() for stack in self.initial_inventory}

    def initial_mob_commands(self) -> tuple[str, ...]:
        """Materialize deterministic 1.16 summon commands for post-reset setup.

        MineDojo samples continuous relative positions and truncates each axis
        before issuing ``/summon``.  The port uses an explicitly seeded NumPy
        generator; its distribution is stable but is not claimed to reproduce
        Gym's historical Box PRNG bit-for-bit.
        """

        if not self.initial_mobs:
            return ()
        assert self.initial_mob_spawn_range_low is not None
        assert self.initial_mob_spawn_range_high is not None
        rng = np.random.default_rng(self.task_rng_seed)
        positions = rng.uniform(
            low=np.asarray(self.initial_mob_spawn_range_low, dtype=float),
            high=np.asarray(self.initial_mob_spawn_range_high, dtype=float),
            size=(len(self.initial_mobs), 3),
        )
        commands = []
        for mob, position in zip(self.initial_mobs, positions, strict=True):
            x, y, z = (int(value) for value in position)
            commands.append(f"/summon minecraft:{mob} ~{x} ~{y} ~{z}")
        return tuple(commands)

    def protocol_identity(self) -> dict[str, Any]:
        return {
            "protocol": PORTED_ENV_PROTOCOL,
            "minecraft_source_version": "1.11.2",
            "minecraft_runtime_version": "1.16.5",
            "action_duration_ms": PORTED_V1_ACTION_DURATION_MS,
            "sim_ticks_per_decision": PORTED_V1_SIM_TICKS_PER_DECISION,
            "world_reset": "force_reset_each_trial",
            "worldgen": "minestudio_1_16_5",
            "world_dimension": self.world_dimension,
            "specified_biome": "legacy_raw_id_via_biome_generator",
            "initial_mob_sampling": "numpy_default_rng_uniform_then_truncate_v1",
            "keyboard_actionables": "human_survival_plus_drop_swap_hands_escape_toggle_perspective",
            "max_decisions": self.max_decisions,
            "episode_horizon_ticks": self.episode_horizon_ticks,
            "horizon_reason": self.horizon_reason,
            "source_observations": {
                "pov": True,
                "voxel": self.source_voxel_bounds,
                "lidar": self.source_lidar_requested,
            },
            "policy_observation": "rgb_only",
        }

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["protocol"] = PORTED_ENV_PROTOCOL
        payload["initial_mob_commands"] = list(self.initial_mob_commands())
        payload["protocol_identity"] = self.protocol_identity()
        return payload


def _task_payload(task: Mapping[str, Any]) -> dict[str, Any]:
    """Accept compiler output or a raw MineDojo task spec without coupling."""

    payload: dict[str, Any] = {}
    for key in ("source_spec", "task_spec", "env_spec", "spec"):
        nested = task.get(key)
        if isinstance(nested, Mapping):
            payload.update(nested)
    payload.update(task)
    return payload


def _category(payload: Mapping[str, Any]) -> str:
    value = payload.get("task_type", payload.get("category", payload.get("__cls__", payload.get("meta_task"))))
    category = str(value or "").strip().lower().replace("-", "_")
    category = {"tech_tree": "techtree", "tech": "techtree"}.get(category, category)
    if category not in MINEDOJO_PORTED_CATEGORY_MAX_DECISIONS:
        raise ValueError(f"Unsupported MineDojo ported task category: {value!r}")
    return category


def _stable_seed(value: Any, *, fallback: int) -> int:
    if value is None or value == "":
        return fallback
    if isinstance(value, bool):
        raise ValueError(f"Minecraft seed cannot be boolean: {value!r}")
    try:
        return int(value)
    except (TypeError, ValueError):
        digest = hashlib.sha256(str(value).encode("utf-8")).digest()
        return int.from_bytes(digest[:8], "big") & 0x7FFF_FFFF


def _finite_number(value: Any, *, field_name: str, default: float) -> float:
    if value is None:
        return default
    if isinstance(value, bool):
        raise ValueError(f"{field_name} cannot be boolean")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field_name} must be finite")
    return number


def _triplet(value: Any, *, field_name: str) -> tuple[float, float, float] | None:
    if value is None:
        return None
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != 3:
        raise ValueError(f"{field_name} must contain three coordinates")
    return tuple(
        _finite_number(item, field_name=f"{field_name}[{index}]", default=0.0) for index, item in enumerate(value)
    )


def _start_position(value: Any) -> dict[str, float] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("MineDojo start_position must be a mapping")
    result = {
        axis: _finite_number(value.get(axis), field_name=f"start_position.{axis}", default=default)
        for axis, default in (("x", 0.0), ("y", 0.0), ("z", 0.0), ("yaw", 0.0), ("pitch", 0.0))
    }
    return result


def _inventory_entries(value: Any) -> list[tuple[Any, Any]]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        if value and all(
            isinstance(quantity, (int, float)) and not isinstance(quantity, bool) for quantity in value.values()
        ):
            # Also accept the lightweight ``{item: quantity}`` shape.  It has
            # no equipment semantics, so items are placed sequentially.
            return [
                (index, {"name": item, "quantity": quantity}) for index, (item, quantity) in enumerate(value.items())
            ]
        return list(value.items())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        entries = []
        for index, stack in enumerate(value):
            if not isinstance(stack, Mapping):
                raise ValueError(f"MineDojo initial_inventory[{index}] must be a mapping")
            entries.append((stack.get("slot", index), stack))
        return entries
    raise ValueError("MineDojo initial_inventory must be a mapping or sequence")


def _compile_inventory(value: Any) -> tuple[tuple[PortedInventoryStack, ...], list[MappingResult]]:
    stacks: list[PortedInventoryStack] = []
    mappings: list[MappingResult] = []
    occupied: set[int] = set()
    for raw_slot, raw_stack in _inventory_entries(value):
        if isinstance(raw_stack, str):
            raw_stack = {"name": raw_stack}
        if not isinstance(raw_stack, Mapping):
            raise ValueError(f"MineDojo inventory slot {raw_slot!r} must contain a stack mapping")
        slot = map_inventory_slot(raw_stack.get("slot", raw_slot))
        if slot in occupied:
            raise ValueError(f"MineDojo initial inventory declares slot {slot} more than once")
        occupied.add(slot)
        compiled_source = raw_stack.get("source")
        if isinstance(compiled_source, Mapping):
            source_item = compiled_source.get("name", raw_stack.get("type"))
            variant_value = compiled_source.get("variant")
            source_slot = map_inventory_slot(compiled_source.get("slot", raw_slot))
            if source_slot != slot:
                raise ValueError(
                    f"Compiled MineDojo inventory slot disagrees with source slot: {source_slot} != {slot}"
                )
        else:
            source_item = raw_stack.get("name", raw_stack.get("type", raw_stack.get("item")))
            variant_value = raw_stack.get("variant", raw_stack.get("metadata"))
        variant = None if variant_value is None else int(variant_value)
        mapping = map_item(source_item, variant=variant)
        target = str(mapping.require_target())
        if isinstance(compiled_source, Mapping):
            compiled_target = str(raw_stack.get("type") or "").strip().lower().removeprefix("minecraft:")
            if target != compiled_target:
                raise ValueError(
                    f"Compiled MineDojo inventory target disagrees with runtime mapping: "
                    f"{source_item!r} -> {compiled_target!r}"
                )
        quantity = int(raw_stack.get("quantity", raw_stack.get("count", 1)))
        if quantity <= 0:
            raise ValueError(f"MineDojo initial inventory quantity must be positive, got {quantity}")
        stacks.append(
            PortedInventoryStack(
                slot=slot,
                item=target,
                quantity=quantity,
                source_item=str(source_item),
                source_variant=variant,
                mapping_status=mapping.status,
            )
        )
        mappings.append(mapping)
    return tuple(sorted(stacks, key=lambda stack: stack.slot)), mappings


def _initial_mobs(value: Any) -> tuple[tuple[str, ...], list[MappingResult]]:
    if value is None:
        return (), []
    values = [value] if isinstance(value, str) else list(value)
    mappings = [map_entity(item) for item in values]
    return tuple(str(mapping.require_target()) for mapping in mappings), mappings


def _compiled_initial_mobs(
    value: Any,
) -> tuple[
    tuple[str, ...],
    tuple[float, float, float] | None,
    tuple[float, float, float] | None,
    list[MappingResult],
]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError("Compiled MineDojo initialization.mobs must be a sequence")
    mobs: list[str] = []
    low: tuple[float, float, float] | None = None
    high: tuple[float, float, float] | None = None
    mappings: list[MappingResult] = []
    for index, entry in enumerate(value):
        if not isinstance(entry, Mapping):
            raise ValueError(f"Compiled MineDojo initialization.mobs[{index}] must be a mapping")
        source = entry.get("source_entity", entry.get("entity"))
        target = str(entry.get("entity") or "").strip().lower().removeprefix("minecraft:")
        if not target:
            raise ValueError(f"Compiled MineDojo initialization.mobs[{index}] is missing entity")
        mapping = map_entity(source)
        # The compiler owns the authoritative target mapping.  Still reject a
        # disagreement so two mapping tables cannot silently define one run.
        if str(mapping.require_target()) != target:
            raise ValueError(f"Compiled MineDojo mob target disagrees with runtime mapping: {source!r} -> {target!r}")
        quantity = int(entry.get("quantity", 1))
        if quantity <= 0:
            raise ValueError("Compiled MineDojo mob quantities must be positive")
        spawn_range = entry.get("spawn_range")
        if not isinstance(spawn_range, Mapping):
            raise ValueError(f"Compiled MineDojo initialization.mobs[{index}] is missing spawn_range")
        entry_low = _triplet(spawn_range.get("low"), field_name=f"initialization.mobs[{index}].spawn_range.low")
        entry_high = _triplet(spawn_range.get("high"), field_name=f"initialization.mobs[{index}].spawn_range.high")
        if entry_low is None or entry_high is None:
            raise ValueError("Compiled MineDojo mob spawn ranges cannot be null")
        if spawn_range.get("sampling") != "seeded_uniform_box_then_truncate_toward_zero":
            raise ValueError("Compiled MineDojo mob spawn sampling protocol is unsupported")
        if low is not None and (entry_low != low or entry_high != high):
            raise ValueError("Ported-v1 requires one shared initial-mob spawn range per task")
        low, high = entry_low, entry_high
        mobs.extend([target] * quantity)
        mappings.append(mapping)
    return tuple(mobs), low, high, mappings


def _survival_target_days(payload: Mapping[str, Any]) -> int | None:
    if _category(payload) != "survival":
        return None
    scorer = payload.get("scorer")
    source = scorer if isinstance(scorer, Mapping) else payload
    target_days = int(source.get("target_days", payload.get("target_days", 0)))
    if target_days <= 1:
        raise ValueError(f"MineDojo survival target_days must be greater than one, got {target_days}")
    return target_days


def compile_env_plan(task: Mapping[str, Any]) -> MineDojoPortedEnvPlan:
    """Compile one loose task mapping into an executable ported-v1 EnvSpec plan."""

    if not isinstance(task, Mapping):
        raise TypeError(f"MineDojo ported task must be a mapping, got {type(task)!r}")
    payload = _task_payload(task)
    category = _category(payload)
    task_id = str(payload.get("task_id", payload.get("id", ""))).strip()
    if not task_id:
        raise ValueError("MineDojo ported task requires task_id")

    world_seed = _stable_seed(
        payload.get("world_seed", payload.get("public_world_seed", payload.get("seed"))),
        fallback=0,
    )
    task_rng_seed = _stable_seed(
        payload.get("task_rng_seed", payload.get("generation_seed", payload.get("seed"))),
        fallback=world_seed,
    )
    initialization = payload.get("initialization")
    compiled_initialization = initialization if isinstance(initialization, Mapping) else None
    inventory_value = (
        compiled_initialization.get("inventory")
        if compiled_initialization is not None
        else payload.get("initial_inventory", payload.get("inventory"))
    )
    inventory, mapping_evidence = _compile_inventory(inventory_value)
    if compiled_initialization is not None:
        mobs, mob_low, mob_high, mob_mappings = _compiled_initial_mobs(compiled_initialization.get("mobs", ()))
    else:
        mobs, mob_mappings = _initial_mobs(payload.get("initial_mobs"))
        mob_low = _triplet(payload.get("initial_mob_spawn_range_low"), field_name="initial_mob_spawn_range_low")
        mob_high = _triplet(payload.get("initial_mob_spawn_range_high"), field_name="initial_mob_spawn_range_high")
    mapping_evidence.extend(mob_mappings)

    biome_id = None
    biome_name = None
    world_dimension = "overworld"
    compiled_world = compiled_initialization.get("world") if compiled_initialization is not None else None
    if compiled_world is not None and not isinstance(compiled_world, Mapping):
        raise ValueError("Compiled MineDojo initialization.world must be a mapping")
    compiled_generator = compiled_world.get("generator") if isinstance(compiled_world, Mapping) else None
    if compiled_generator is not None and not isinstance(compiled_generator, Mapping):
        raise ValueError("Compiled MineDojo initialization.world.generator must be a mapping")
    if isinstance(compiled_generator, Mapping):
        generator_kind = str(compiled_generator.get("kind") or "")
        world_dimension = str(compiled_generator.get("dimension") or "")
        if world_dimension != "overworld":
            raise ValueError(
                f"Ported-v1 supports only the source benchmark's overworld generators, got {world_dimension!r}"
            )
        if generator_kind == "constant_biome":
            biome_mapping = map_biome(compiled_generator.get("source_biome", compiled_generator.get("biome_id")))
            source_biome_id = int(compiled_generator["source_biome_id"])
            biome_id = int(compiled_generator["biome_id"])
            if int(biome_mapping.require_target()) != source_biome_id or source_biome_id != biome_id:
                raise ValueError("Compiled MineDojo biome target disagrees with runtime mapping")
            biome_name = str(compiled_generator.get("biome") or "").strip()
            if not biome_name:
                raise ValueError("Compiled MineDojo constant-biome generator is missing its target biome name")
            mapping_evidence.append(biome_mapping)
        elif generator_kind != "default":
            raise ValueError(f"Unsupported compiled MineDojo world generator: {generator_kind!r}")
    else:
        specified_biome = payload.get("specified_biome")
        if specified_biome is not None:
            biome_mapping = map_biome(specified_biome)
            biome_id = int(biome_mapping.require_target())
            biome_name = str(specified_biome)
            mapping_evidence.append(biome_mapping)

    if mobs and (mob_low is None or mob_high is None):
        raise ValueError("MineDojo initial mobs require low and high spawn ranges")
    if mobs and any(low > high for low, high in zip(mob_low or (), mob_high or (), strict=True)):
        raise ValueError("MineDojo initial mob spawn low coordinates cannot exceed high coordinates")

    compiled_time = compiled_world.get("time") if isinstance(compiled_world, Mapping) else None
    if compiled_time is not None and not isinstance(compiled_time, Mapping):
        raise ValueError("Compiled MineDojo initialization.world.time must be a mapping")
    if isinstance(compiled_time, Mapping):
        start_time_value = compiled_time.get("start_time")
        start_time = None if start_time_value is None else int(start_time_value)
        allow_time_passage = bool(compiled_time.get("allow_time_passage", True))
        start_at_night = bool(compiled_time.get("start_at_night", False))
        always_night = bool(compiled_time.get("always_night", False))
        if always_night:
            valid_time_contract = start_at_night and start_time == 18_000 and not allow_time_passage
        elif start_at_night:
            expected_start_time = 13_000 if category == "combat" else 18_000
            valid_time_contract = start_time == expected_start_time and allow_time_passage
        else:
            valid_time_contract = start_time is None and allow_time_passage
        if not valid_time_contract:
            raise ValueError("Compiled MineDojo night/time fields are internally inconsistent")
    else:
        explicit_start_time = payload.get("start_time")
        if explicit_start_time is not None:
            start_time = int(explicit_start_time)
        elif payload.get("always_night"):
            start_time = 18_000
        elif payload.get("start_at_night"):
            # This difference is present in the released MineDojo meta tasks.
            start_time = 13_000 if category == "combat" else 18_000
        else:
            start_time = None
        allow_time_passage = bool(payload.get("allow_time_passage", True))
        if payload.get("always_night"):
            allow_time_passage = False

    requested_max = payload.get("max_decisions")
    requested_max_decisions = None if requested_max is None else int(requested_max)
    if requested_max_decisions is not None and requested_max_decisions <= 0:
        raise ValueError("MineDojo ported max_decisions must be positive")
    max_decisions = requested_max_decisions or task_max_decisions(payload)
    horizon_reason = "explicit_task_horizon" if requested_max_decisions is not None else "category_default"

    target_days = _survival_target_days(payload)
    minimum_survival_ticks = 0 if target_days is None else target_days * MINECRAFT_TICKS_PER_DAY
    if target_days is not None and requested_max_decisions is None:
        horizon_reason = "survival_target_derived_horizon"
    if requested_max_decisions is None and minimum_survival_ticks > max_decisions:
        max_decisions = minimum_survival_ticks
        horizon_reason = "raised_to_survival_target_ticks"
    requested_tick_horizon = payload.get("episode_horizon_ticks", payload.get("max_sim_ticks"))
    episode_horizon_ticks = int(requested_tick_horizon) if requested_tick_horizon is not None else max_decisions
    if episode_horizon_ticks <= 0:
        raise ValueError("MineDojo ported episode_horizon_ticks must be positive")
    if requested_max_decisions is None and episode_horizon_ticks < minimum_survival_ticks:
        episode_horizon_ticks = minimum_survival_ticks
        horizon_reason = "raised_to_survival_target_ticks"
    executable_tick_horizon = max_decisions * PORTED_V1_SIM_TICKS_PER_DECISION
    if episode_horizon_ticks != executable_tick_horizon:
        raise ValueError(
            "MineDojo ported episode_horizon_ticks must equal the executable decision horizon "
            f"({executable_tick_horizon})"
        )

    compiled_observations = payload.get("observations")
    if compiled_observations is not None:
        if not isinstance(compiled_observations, Mapping):
            raise ValueError("Compiled MineDojo observations must be a mapping")
        if compiled_observations.get("pov") is not True:
            raise ValueError("MineDojo ported-v1 requires the source POV observation")
        voxel_value = compiled_observations.get("voxel")
        source_lidar_requested = bool(compiled_observations.get("lidar", False))
    else:
        voxel_value = payload.get("voxel_size") if payload.get("use_voxel") else None
        source_lidar_requested = bool(payload.get("use_lidar", False))
    if source_lidar_requested:
        raise ValueError("MineDojo ported-v1 does not support source lidar observations")
    source_voxel_bounds = None
    if voxel_value is not None:
        if not isinstance(voxel_value, Mapping):
            raise ValueError("MineDojo source voxel bounds must be a mapping")
        voxel_keys = ("xmin", "ymin", "zmin", "xmax", "ymax", "zmax")
        if set(voxel_value) != set(voxel_keys):
            raise ValueError(f"MineDojo source voxel bounds must contain exactly {voxel_keys!r}")
        source_voxel_bounds = {key: int(voxel_value[key]) for key in voxel_keys}
        for low_key, high_key in (("xmin", "xmax"), ("ymin", "ymax"), ("zmin", "zmax")):
            if source_voxel_bounds[low_key] > source_voxel_bounds[high_key]:
                raise ValueError("MineDojo source voxel lower bounds cannot exceed upper bounds")

    initial_weather_value = payload.get("initial_weather")
    initial_weather = None if initial_weather_value is None else str(initial_weather_value).strip().lower()
    if initial_weather not in {None, "normal", "clear", "rain", "thunder"}:
        raise ValueError(f"Unsupported MineDojo initial weather: {initial_weather!r}")

    drawing_value = payload.get("drawing_str")
    drawing_str = None if drawing_value is None else str(drawing_value)
    return MineDojoPortedEnvPlan(
        task_id=task_id,
        category=category,
        world_seed=world_seed,
        task_rng_seed=task_rng_seed,
        initial_inventory=inventory,
        start_position=_start_position(payload.get("start_position")),
        start_health=_finite_number(payload.get("start_health"), field_name="start_health", default=20.0),
        start_food=int(_finite_number(payload.get("start_food"), field_name="start_food", default=20.0)),
        start_time=start_time,
        allow_time_passage=allow_time_passage,
        initial_weather=initial_weather,
        allow_mob_spawn=(
            bool(compiled_world.get("allow_mob_spawn", True))
            if isinstance(compiled_world, Mapping)
            else bool(payload.get("allow_mob_spawn", True))
        ),
        break_speed_multiplier=_finite_number(
            payload.get("break_speed_multiplier"),
            field_name="break_speed_multiplier",
            default=1.0,
        ),
        world_dimension=world_dimension,
        specified_biome_id=biome_id,
        specified_biome_name=biome_name,
        drawing_str=drawing_str,
        initial_mobs=mobs,
        initial_mob_spawn_range_low=mob_low,
        initial_mob_spawn_range_high=mob_high,
        requested_max_decisions=requested_max_decisions,
        max_decisions=max_decisions,
        episode_horizon_ticks=episode_horizon_ticks,
        horizon_reason=horizon_reason,
        source_voxel_bounds=source_voxel_bounds,
        source_lidar_requested=source_lidar_requested,
        mapping_evidence=tuple(mapping.to_dict() for mapping in mapping_evidence),
    )


def _safe_env_name(task_id: str) -> str:
    digest = hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:12]
    return f"MineRLPlayer1MineDojoPorted-{digest}-v0"


def build_env_spec(
    task_or_plan: Mapping[str, Any] | MineDojoPortedEnvPlan,
    *,
    resolution: tuple[int, int] = (640, 360),
    viewpoint: str = "first",
    human_survival_cls: type[Any] | None = None,
    handlers_module: Any | None = None,
) -> Any:
    """Build a MineStudio ``HumanSurvival`` subclass for one compiled plan.

    ``human_survival_cls`` and ``handlers_module`` are dependency-injection
    seams used by unit tests.  Production calls import the installed
    MineStudio runtime lazily.
    """

    plan = task_or_plan if isinstance(task_or_plan, MineDojoPortedEnvPlan) else compile_env_plan(task_or_plan)
    viewpoint = normalize_viewpoint(viewpoint)
    if human_survival_cls is None:
        from minestudio.simulator.minerl.herobraine.env_specs.human_survival_specs import HumanSurvival

        human_survival_cls = HumanSurvival
    if handlers_module is None:
        from minestudio.simulator.minerl.herobraine.hero import handlers

        handlers_module = handlers
    handlers = handlers_module

    class _ViewpointPOVObservation(handlers.POVObservation):  # type: ignore[misc, valid-type]
        def __init__(self) -> None:
            super().__init__(resolution)
            self.viewpoint = _MINEDOJO_VIEWPOINT_VALUES[viewpoint]

        def xml_template(self) -> str:
            return """
                <VideoProducer
                    want_depth="{{ include_depth | string | lower }}"
                    viewpoint="{{ viewpoint }}">
                    <Width>{{ video_width }}</Width>
                    <Height>{{ video_height }}</Height>
                </VideoProducer>"""

    class _MineDojoPortedHumanSurvival(human_survival_cls):  # type: ignore[misc, valid-type]
        def __init__(self) -> None:
            self.ported_plan = plan
            super().__init__(
                name=_safe_env_name(plan.task_id),
                fov_range=[70, 70],
                gamma_range=[2, 2],
                guiscale_range=[1, 1],
                cursor_size_range=[16.0, 16.0],
                frameskip=1,
                resolution=resolution,
                max_episode_steps=plan.max_decisions,
                inventory=None,
                preferred_spawn_biome=None,
            )

        def create_actionables(self) -> list[Any]:
            result = list(super().create_actionables())
            existing = {str(action.to_string()) for action in result}
            for command, key_code in PORTED_V1_OPTIONAL_ACTION_KEY_CODES:
                if command not in existing:
                    result.append(handlers.KeybasedCommandAction(command, key_code))
                    existing.add(command)
            if "dwheel" not in existing:
                result.append(handlers.MouseWheelAction())
            return result

        def create_observables(self) -> list[Any]:
            result = list(super().create_observables())
            pov_indices = [index for index, observable in enumerate(result) if observable.to_string() == "pov"]
            if len(pov_indices) != 1:
                raise RuntimeError(f"MineDojo-ported expected one POV observable, found {len(pov_indices)}")
            result[pov_indices[0]] = _ViewpointPOVObservation()
            return result

        def create_agent_start(self) -> list[Any]:
            result = list(super().create_agent_start())
            result.append(handlers.DoneOnDeath())
            result.append(handlers.AgentStartBreakSpeedMultiplier(plan.break_speed_multiplier))
            result.append(handlers.StartingHealthAgentStart(health=plan.start_health))
            result.append(handlers.StartingFoodAgentStart(food=plan.start_food))
            if plan.initial_inventory:
                result.append(handlers.InventoryAgentStart(plan.inventory_handler))
            if plan.start_position is not None:
                result.append(handlers.AgentStartPlacement(**plan.start_position))
            return result

        def create_server_world_generators(self) -> list[Any]:
            if plan.specified_biome_id is None:
                result = [handlers.DefaultWorldGenerator(force_reset=True)]
            else:
                result = [handlers.BiomeGenerator(plan.specified_biome_id, force_reset=True)]
            if plan.drawing_str is not None:
                result.append(handlers.DrawingDecorator(plan.drawing_str))
            return result

        def create_server_initial_conditions(self) -> list[Any]:
            result = [
                handlers.TimeInitialCondition(
                    allow_passage_of_time=plan.allow_time_passage,
                    start_time=plan.start_time,
                ),
                handlers.SpawningInitialCondition(plan.allow_mob_spawn),
            ]
            if plan.initial_weather is not None:
                result.append(handlers.WeatherInitialCondition(plan.initial_weather))
            return result

    _MineDojoPortedHumanSurvival.__name__ = "MineDojoPortedHumanSurvival"
    _MineDojoPortedHumanSurvival.__qualname__ = "MineDojoPortedHumanSurvival"
    return _MineDojoPortedHumanSurvival()


def make_low_level_env(
    task_or_plan: Mapping[str, Any] | MineDojoPortedEnvPlan,
    *,
    resolution: tuple[int, int] = (640, 360),
    viewpoint: str = "first",
    human_survival_cls: type[Any] | None = None,
    handlers_module: Any | None = None,
) -> Any:
    """Construct and seed the low-level MineRL environment for a worker."""

    plan = task_or_plan if isinstance(task_or_plan, MineDojoPortedEnvPlan) else compile_env_plan(task_or_plan)
    spec = build_env_spec(
        plan,
        resolution=resolution,
        viewpoint=viewpoint,
        human_survival_cls=human_survival_cls,
        handlers_module=handlers_module,
    )
    environment = spec.make()
    environment.seed(plan.world_seed)
    return environment


__all__ = [
    "MINECRAFT_TICKS_PER_DAY",
    "MINEDOJO_VIEWPOINTS",
    "PORTED_ENV_PROTOCOL",
    "PORTED_V1_ACTION_DURATION_MS",
    "PORTED_V1_OPTIONAL_ACTION_KEY_CODES",
    "PORTED_V1_SIM_TICKS_PER_DECISION",
    "MineDojoPortedEnvPlan",
    "PortedInventoryStack",
    "build_env_spec",
    "compile_env_plan",
    "make_low_level_env",
    "normalize_viewpoint",
]

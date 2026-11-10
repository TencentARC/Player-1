"""Faithful Python success and shaping-reward semantics for MineDojo tasks.

MineDojo's environment reward is shaping, not a success signal.  The ported
runner must stop on :attr:`MineDojoPortedScore.success`; it may record reward
for diagnostics but must never substitute ``reward > 0`` for task completion.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from .env_spec import MINECRAFT_TICKS_PER_DAY
from .mappings import MappingResult, map_entity, map_item

SCORER_PROTOCOL = "minedojo_programmatic_success_1_11_2_on_minestudio_1_16_5_v1"

TECH_ITEMS: dict[str, tuple[str, ...]] = {
    "wooden": tuple(f"wooden_{tool}" for tool in ("axe", "hoe", "pickaxe", "shovel", "sword")),
    "leather": tuple(f"leather_{armor}" for armor in ("boots", "chestplate", "helmet", "leggings")),
    "chainmail": tuple(f"chainmail_{armor}" for armor in ("boots", "chestplate", "helmet", "leggings")),
    "golden": tuple(
        f"golden_{item}"
        for item in ("boots", "chestplate", "helmet", "leggings", "axe", "hoe", "pickaxe", "shovel", "sword")
    ),
    "stone": tuple(f"stone_{tool}" for tool in ("axe", "hoe", "pickaxe", "shovel", "sword")),
    "iron": tuple(
        f"iron_{item}"
        for item in ("boots", "chestplate", "helmet", "leggings", "axe", "hoe", "pickaxe", "shovel", "sword")
    ),
    "diamond": tuple(
        f"diamond_{item}"
        for item in ("boots", "chestplate", "helmet", "leggings", "axe", "hoe", "pickaxe", "shovel", "sword")
    ),
    "archery": ("bow",),
    "explosives": ("tnt",),
    "redstone": (
        "redstone_block",
        "clock",
        "compass",
        "dispenser",
        "dropper",
        "observer",
        "piston",
        "redstone_lamp",
        "redstone_torch",
        "repeater",
        "detector_rail",
        "comparator",
        "activator_rail",
    ),
}


class MineDojoScorerStateError(RuntimeError):
    """The MineStudio observation lacks state required for exact scoring."""


@dataclass(frozen=True)
class MineDojoPortedScore:
    task_id: str
    category: str
    success: bool
    newly_successful: bool
    shaping_reward: float
    elapsed_steps: int
    criteria: tuple[dict[str, Any], ...]
    progress: dict[str, float]
    protocol: str = SCORER_PROTOCOL

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["criteria"] = [dict(item) for item in self.criteria]
        return payload


@dataclass(frozen=True)
class _Target:
    source: str
    target: str
    quantity: int
    reward_weight: float
    mapping: MappingResult


@dataclass(frozen=True)
class _ScoreState:
    inventory: dict[str, float]
    kill_entity: dict[str, float]
    use_item: dict[str, float]
    time_since_death: float | None


_MISSING = object()


def _task_payload(task: Mapping[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key in ("source_spec", "task_spec", "env_spec", "spec"):
        nested = task.get(key)
        if isinstance(nested, Mapping):
            payload.update(nested)
    payload.update(task)
    scorer = task.get("scorer")
    if isinstance(scorer, Mapping):
        payload.update(scorer)
    return payload


def _category(payload: Mapping[str, Any]) -> str:
    raw = payload.get(
        "task_type",
        payload.get("kind", payload.get("category", payload.get("__cls__", payload.get("meta_task")))),
    )
    category = str(raw or "").strip().lower().replace("-", "_")
    category = {
        "tech_tree": "techtree",
        "tech": "techtree",
        "inventory": "harvest",
        "kill_entity": "combat",
        "use_item": "techtree",
        "time_since_death": "survival",
    }.get(category, category)
    if category not in {"harvest", "combat", "techtree", "survival"}:
        raise ValueError(f"Unsupported MineDojo scorer category: {raw!r}")
    return category


def _bare_identifier(value: Any) -> str:
    identifier = str(value or "").strip().lower()
    return identifier.split(":", 1)[-1]


def _finite(value: Any, *, context: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise MineDojoScorerStateError(f"MineStudio {context} is not numeric: {value!r}") from exc
    if not math.isfinite(number):
        raise MineDojoScorerStateError(f"MineStudio {context} is not finite: {value!r}")
    return number


def _nonnegative(value: Any, *, context: str) -> float:
    number = _finite(value, context=context)
    if number < 0:
        raise MineDojoScorerStateError(f"MineStudio {context} cannot be negative: {value!r}")
    return number


def _nested(data: Any, path: tuple[str, ...]) -> Any:
    current = data
    for key in path:
        if not isinstance(current, Mapping) or key not in current:
            return _MISSING
        current = current[key]
    return current


def _first(data: Mapping[str, Any], paths: Sequence[tuple[str, ...]]) -> Any:
    for path in paths:
        value = _nested(data, path)
        if value is not _MISSING:
            return value
    return _MISSING


def _inventory_counts(info: Mapping[str, Any]) -> dict[str, float]:
    value = _first(
        info,
        (
            ("inventory",),
            ("minecraft", "inventory"),
            ("minecraft", "info", "inventory"),
        ),
    )
    if value is _MISSING:
        raise MineDojoScorerStateError("MineStudio info is missing inventory state")
    counts: dict[str, float] = {}
    if isinstance(value, Mapping):
        if all(not isinstance(item, Mapping) for item in value.values()):
            for item, quantity in value.items():
                counts[_bare_identifier(item)] = _nonnegative(quantity, context=f"inventory[{item!r}]")
            return counts
        stacks = value.values()
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        stacks = value
    else:
        raise MineDojoScorerStateError(f"MineStudio inventory has unsupported shape: {type(value)!r}")

    for index, stack in enumerate(stacks):
        if not isinstance(stack, Mapping):
            continue
        item = stack.get("name", stack.get("type", stack.get("item")))
        identifier = _bare_identifier(item)
        if not identifier or identifier in {"air", "none"}:
            continue
        quantity = _nonnegative(
            stack.get("quantity", stack.get("count", 0)),
            context=f"inventory stack {index}",
        )
        counts[identifier] = counts.get(identifier, 0.0) + quantity
    return counts


def _event_counts(info: Mapping[str, Any], event: str) -> dict[str, float]:
    value = _first(
        info,
        (
            (event,),
            ("stat", event),
            ("stats", event),
            ("minecraft", "stats", event),
            ("minecraft", "info", event),
            ("minecraft", "info", "stat", event),
        ),
    )
    if value is _MISSING:
        raise MineDojoScorerStateError(f"MineStudio info is missing {event!r} statistics")
    if not isinstance(value, Mapping):
        raise MineDojoScorerStateError(f"MineStudio {event!r} statistics must be a mapping")
    namespace = value.get("minecraft")
    if isinstance(namespace, Mapping):
        value = namespace
    counts: dict[str, float] = {}
    for item, count in value.items():
        if isinstance(count, Mapping):
            continue
        counts[_bare_identifier(item)] = _nonnegative(count, context=f"{event}[{item!r}]")
    return counts


def _time_since_death(info: Mapping[str, Any]) -> float:
    value = _first(
        info,
        (
            ("stat", "time_since_death"),
            ("custom", "time_since_death"),
            ("stats", "custom", "time_since_death"),
            ("minecraft", "stats", "custom", "time_since_death"),
            ("minecraft", "info", "custom", "time_since_death"),
            ("minecraft", "info", "stat", "time_since_death"),
        ),
    )
    if value is _MISSING:
        raise MineDojoScorerStateError("MineStudio info is missing custom.time_since_death")
    return _nonnegative(value, context="custom.time_since_death")


def _as_names(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        result = []
        for item in value:
            if isinstance(item, Mapping):
                name = item.get("name", item.get("target", item.get("item")))
                result.append(str(name))
            else:
                result.append(str(item))
        return result
    if isinstance(value, Mapping):
        return [str(item) for item in value]
    raise ValueError(f"MineDojo targets must be a string, sequence, or mapping, got {type(value)!r}")


def _quantity_map(names: Sequence[str], value: Any, *, original_targets: Any) -> dict[str, int]:
    if value is None and isinstance(original_targets, Mapping):
        value = original_targets
    if value is None and isinstance(original_targets, Sequence) and not isinstance(original_targets, (str, bytes)):
        if all(isinstance(item, Mapping) and "quantity" in item for item in original_targets):
            value = [item["quantity"] for item in original_targets]
    if isinstance(value, Mapping):
        result = {name: int(value[name]) for name in names}
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        if len(value) != len(names):
            raise ValueError("MineDojo target quantity list must match target names")
        result = {name: int(quantity) for name, quantity in zip(names, value, strict=True)}
    else:
        quantity = 1 if value is None else int(value)
        result = {name: quantity for name in names}
    if any(quantity <= 0 for quantity in result.values()):
        raise ValueError("MineDojo target quantities must be positive")
    return result


def _weight_map(names: Sequence[str], value: Any, *, default: float) -> dict[str, float]:
    if isinstance(value, Mapping):
        result = {name: float(value[name]) for name in names}
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        if len(value) != len(names):
            raise ValueError("MineDojo reward weight list must match target names")
        result = {name: float(weight) for name, weight in zip(names, value, strict=True)}
    else:
        weight = default if value is None else float(value)
        result = {name: weight for name in names}
    if not all(math.isfinite(weight) for weight in result.values()):
        raise ValueError("MineDojo reward weights must be finite")
    return result


def _simple_targets(payload: Mapping[str, Any], *, category: str) -> tuple[_Target, ...]:
    raw_targets = payload.get("target_names", payload.get("targets"))
    names = _as_names(raw_targets)
    quantities = _quantity_map(names, payload.get("target_quantities"), original_targets=raw_targets)
    weights = _weight_map(names, payload.get("reward_weights"), default=1.0)
    results = []
    for name in names:
        mapping = map_item(name) if category == "harvest" else map_entity(name)
        results.append(
            _Target(
                source=name,
                target=str(mapping.require_target()),
                quantity=quantities[name],
                reward_weight=weights[name],
                mapping=mapping,
            )
        )
    return tuple(results)


def _tech_names(payload: Mapping[str, Any]) -> list[str]:
    explicit = payload.get("tech_items", payload.get("target_items"))
    if explicit is not None:
        return _as_names(explicit)
    tech_item = payload.get("tech_item")
    if tech_item is not None:
        return [str(tech_item)]
    tech = str(payload.get("tech") or "").strip().lower()
    try:
        return list(TECH_ITEMS[tech])
    except KeyError as exc:
        raise ValueError(f"MineDojo TechTree scorer requires known tech or explicit tech_items, got {tech!r}") from exc


class MineDojoPortedScorer:
    """Stateful MineDojo success/reward evaluator over MineStudio ``info``."""

    def __init__(self, task: Mapping[str, Any]):
        if not isinstance(task, Mapping):
            raise TypeError(f"MineDojo scorer task must be a mapping, got {type(task)!r}")
        self._payload = _task_payload(task)
        self.task_id = str(self._payload.get("task_id", self._payload.get("id", ""))).strip()
        if not self.task_id:
            raise ValueError("MineDojo scorer requires task_id")
        self.category = _category(self._payload)
        self._targets: tuple[_Target, ...] = ()
        self._tech_obtain_weights: dict[str, float] = {}
        self._tech_use_weights: dict[str, float] = {}
        self._survival_target_days: int | None = None
        self._survival_per_day_reward = 0.0
        self._survival_success_reward = 0.0
        compiled_target = self._payload.get("target")
        self._compiled_target = dict(compiled_target) if isinstance(compiled_target, Mapping) else None
        compiled_rewards = self._payload.get("reward")
        if compiled_rewards is None:
            self._compiled_rewards = ()
        elif isinstance(compiled_rewards, Sequence) and not isinstance(compiled_rewards, (str, bytes)):
            if not all(isinstance(item, Mapping) for item in compiled_rewards):
                raise ValueError("Compiled MineDojo reward entries must all be mappings")
            self._compiled_rewards = tuple(dict(item) for item in compiled_rewards)
        else:
            raise ValueError("Compiled MineDojo reward must be a sequence of mappings")

        if self._compiled_target is not None:
            self._validate_compiled_contract()
        elif self.category in {"harvest", "combat"}:
            self._targets = _simple_targets(self._payload, category=self.category)
        elif self.category == "techtree":
            source_names = _tech_names(self._payload)
            obtain_weights = _weight_map(
                source_names,
                self._payload.get("obtain_items_reward_weights"),
                default=1.0,
            )
            use_weights = _weight_map(
                source_names,
                self._payload.get("use_items_reward_weights"),
                default=10.0,
            )
            targets = []
            for source_name in source_names:
                mapping = map_item(source_name)
                target = str(mapping.require_target())
                targets.append(
                    _Target(
                        source=source_name,
                        target=target,
                        quantity=1,
                        reward_weight=use_weights[source_name],
                        mapping=mapping,
                    )
                )
                self._tech_obtain_weights[target] = obtain_weights[source_name]
                self._tech_use_weights[target] = use_weights[source_name]
            self._targets = tuple(targets)
        else:
            self._survival_target_days = int(self._payload.get("target_days", 0))
            if self._survival_target_days <= 1:
                raise ValueError("MineDojo survival scorer target_days must be greater than one")
            self._survival_per_day_reward = float(self._payload.get("per_day_reward", 1.0))
            configured_success = self._payload.get("success_reward")
            self._survival_success_reward = (
                self._survival_target_days * self._survival_per_day_reward
                if configured_success is None or float(configured_success) == 0.0
                else float(configured_success)
            )

        self._initial: _ScoreState | None = None
        self._previous: _ScoreState | None = None
        self._elapsed_steps = 0
        self._successful = False

    def protocol_identity(self) -> dict[str, Any]:
        return {
            "protocol": SCORER_PROTOCOL,
            "category": self.category,
            "success_is_separate_from_shaping_reward": True,
            "harvest_success": "any_target_inventory_delta_from_post_setup_baseline",
            "combat_success": "any_target_kill_entity_delta_from_post_setup_baseline",
            "tech_tree_success": "all_target_use_item_deltas_from_post_setup_baseline",
            "survival_success": "absolute_time_since_death_gte_target_days_x_24000",
            "target_mappings": [target.mapping.to_dict() for target in self._targets],
            "compiled_target": None if self._compiled_target is None else dict(self._compiled_target),
        }

    def _capture(self, info: Mapping[str, Any]) -> _ScoreState:
        inventory: dict[str, float] = {}
        kill_entity: dict[str, float] = {}
        use_item: dict[str, float] = {}
        time_since_death = None
        if self.category in {"harvest", "techtree"}:
            inventory = _inventory_counts(info)
        if self.category == "combat":
            kill_entity = _event_counts(info, "kill_entity")
        if self.category == "techtree":
            use_item = _event_counts(info, "use_item")
        if self.category == "survival":
            time_since_death = _time_since_death(info)
        return _ScoreState(
            inventory=inventory,
            kill_entity=kill_entity,
            use_item=use_item,
            time_since_death=time_since_death,
        )

    def reset(self, info: Mapping[str, Any]) -> MineDojoPortedScore:
        """Capture the baseline after all inventory/mob/setup steps settle."""

        if not isinstance(info, Mapping):
            raise TypeError(f"MineDojo scorer reset info must be a mapping, got {type(info)!r}")
        state = self._capture(info)
        self._initial = state
        self._previous = state
        self._elapsed_steps = 0
        self._successful = False
        return MineDojoPortedScore(
            task_id=self.task_id,
            category=self.category,
            success=False,
            newly_successful=False,
            shaping_reward=0.0,
            elapsed_steps=0,
            criteria=(),
            progress={},
        )

    def step(self, info: Mapping[str, Any]) -> MineDojoPortedScore:
        """Score one successful simulator transition and advance reward state."""

        if self._initial is None or self._previous is None:
            raise RuntimeError("MineDojo scorer.reset(info) must run after environment setup")
        if not isinstance(info, Mapping):
            raise TypeError(f"MineDojo scorer step info must be a mapping, got {type(info)!r}")
        current = self._capture(info)
        self._elapsed_steps += 1
        criteria: list[dict[str, Any]] = []
        progress: dict[str, float] = {}
        reward = 0.0

        if self._compiled_target is not None:
            criteria, progress, current_success = self._evaluate_compiled_target(current)
            reward = self._evaluate_compiled_rewards(current)
        elif self.category == "harvest":
            for target in self._targets:
                delta = current.inventory.get(target.target, 0.0) - self._initial.inventory.get(target.target, 0.0)
                step_delta = current.inventory.get(target.target, 0.0) - self._previous.inventory.get(target.target, 0.0)
                passed = delta >= target.quantity
                progress[target.target] = delta
                reward += step_delta * target.reward_weight
                criteria.append(self._criterion(target, delta, passed, event="inventory_delta"))
            current_success = any(item["passed"] for item in criteria)
        elif self.category == "combat":
            for target in self._targets:
                delta = current.kill_entity.get(target.target, 0.0) - self._initial.kill_entity.get(target.target, 0.0)
                step_delta = current.kill_entity.get(target.target, 0.0) - self._previous.kill_entity.get(
                    target.target, 0.0
                )
                passed = delta >= target.quantity
                progress[target.target] = delta
                reward += step_delta * target.reward_weight
                criteria.append(self._criterion(target, delta, passed, event="kill_entity_delta"))
            current_success = any(item["passed"] for item in criteria)
        elif self.category == "techtree":
            for target in self._targets:
                used = current.use_item.get(target.target, 0.0) - self._initial.use_item.get(target.target, 0.0)
                obtained_step = current.inventory.get(target.target, 0.0) - self._previous.inventory.get(target.target, 0.0)
                used_step = current.use_item.get(target.target, 0.0) - self._previous.use_item.get(target.target, 0.0)
                reward += obtained_step * self._tech_obtain_weights[target.target]
                reward += used_step * self._tech_use_weights[target.target]
                passed = used >= 1
                progress[target.target] = used
                criteria.append(self._criterion(target, used, passed, event="use_item_delta"))
            current_success = all(item["passed"] for item in criteria)
        else:
            assert current.time_since_death is not None
            assert self._previous.time_since_death is not None
            assert self._survival_target_days is not None
            target_ticks = self._survival_target_days * MINECRAFT_TICKS_PER_DAY
            previous_days = int(self._previous.time_since_death) // MINECRAFT_TICKS_PER_DAY
            current_days = int(current.time_since_death) // MINECRAFT_TICKS_PER_DAY
            reward += (current_days - previous_days) * self._survival_per_day_reward
            current_success = current.time_since_death >= target_ticks
            if current_success:
                reward += self._survival_success_reward
            progress["time_since_death"] = current.time_since_death
            criteria.append(
                {
                    "event": "time_since_death_absolute",
                    "target": "time_since_death",
                    "value": current.time_since_death,
                    "threshold": target_ticks,
                    "passed": current_success,
                }
            )

        newly_successful = current_success and not self._successful
        self._successful = self._successful or current_success
        self._previous = current
        return MineDojoPortedScore(
            task_id=self.task_id,
            category=self.category,
            success=self._successful,
            newly_successful=newly_successful,
            shaping_reward=reward,
            elapsed_steps=self._elapsed_steps,
            criteria=tuple(criteria),
            progress=progress,
        )

    def _validate_compiled_contract(self) -> None:
        assert self._compiled_target is not None
        target = self._compiled_target
        kind = str(target.get("kind") or "")
        if kind not in {"inventory_delta", "stat_delta", "stat_value"}:
            raise ValueError(f"Unsupported compiled MineDojo target kind: {kind!r}")
        objects = target.get("objects")
        if (
            not isinstance(objects, Sequence)
            or isinstance(objects, (str, bytes))
            or not objects
            or not all(isinstance(item, str) and item for item in objects)
        ):
            raise ValueError("Compiled MineDojo target.objects must be a non-empty string sequence")
        aggregation = str(target.get("aggregation") or "")
        if aggregation not in {"sum", "all", "any"}:
            raise ValueError(f"Unsupported compiled MineDojo target aggregation: {aggregation!r}")
        threshold = target.get("gte")
        if (
            isinstance(threshold, bool)
            or not isinstance(threshold, (int, float))
            or not math.isfinite(float(threshold))
            or float(threshold) <= 0
        ):
            raise ValueError("Compiled MineDojo target.gte must be finite and positive")
        if kind in {"stat_delta", "stat_value"} and str(target.get("stat") or "") not in {
            "kill_entity",
            "use_item",
            "custom",
        }:
            raise ValueError(f"Unsupported compiled MineDojo target stat: {target.get('stat')!r}")
        object_keys = [self._object_key(item) for item in objects]
        if any(not key for key in object_keys) or len(set(object_keys)) != len(object_keys):
            raise ValueError("Compiled MineDojo target.objects must have unique non-empty canonical keys")

        expected_target_contract = {
            "harvest": ("inventory_delta", "", "sum", "post_initialization"),
            "combat": ("stat_delta", "kill_entity", "sum", "post_initialization"),
            "techtree": ("stat_delta", "use_item", "all", "post_initialization"),
            "survival": ("stat_value", "custom", "all", "absolute"),
        }[self.category]
        actual_target_contract = (
            kind,
            str(target.get("stat") or ""),
            aggregation,
            str(target.get("baseline") or ""),
        )
        if actual_target_contract != expected_target_contract:
            raise ValueError(
                f"Compiled MineDojo {self.category} target contract must be {expected_target_contract!r}, "
                f"got {actual_target_contract!r}"
            )

        for reward in self._compiled_rewards:
            reward_kind = str(reward.get("kind") or "")
            if reward_kind not in {"inventory_delta", "stat_delta", "stat_bucket_delta", "stat_value_once"}:
                raise ValueError(f"Unsupported compiled MineDojo reward kind: {reward_kind!r}")
            try:
                weight = float(reward.get("weight", 1.0))
            except (TypeError, ValueError) as exc:
                raise ValueError("Compiled MineDojo reward weight must be numeric") from exc
            if not math.isfinite(weight):
                raise ValueError("Compiled MineDojo reward weight must be finite")

            if reward_kind in {"inventory_delta", "stat_delta"}:
                reward_objects = reward.get("objects")
                if (
                    not isinstance(reward_objects, Sequence)
                    or isinstance(reward_objects, (str, bytes))
                    or not reward_objects
                    or not all(isinstance(item, str) and item for item in reward_objects)
                ):
                    raise ValueError(f"Compiled MineDojo {reward_kind} reward requires non-empty objects")
                reward_keys = [self._object_key(item) for item in reward_objects]
                if len(set(reward_keys)) != len(reward_keys):
                    raise ValueError(f"Compiled MineDojo {reward_kind} reward objects must be unique")
                if reward_keys != object_keys:
                    raise ValueError("Compiled MineDojo reward objects must match the success target objects")
                if str(reward.get("aggregation") or "") != "sum":
                    raise ValueError(f"Compiled MineDojo {reward_kind} reward aggregation must be 'sum'")
                reward_stat = str(reward.get("stat") or "")
                if reward_kind == "inventory_delta":
                    if self.category not in {"harvest", "techtree"} or reward_stat:
                        raise ValueError("Compiled inventory_delta reward is invalid for this task category")
                elif (self.category, reward_stat) not in {
                    ("combat", "kill_entity"),
                    ("techtree", "use_item"),
                }:
                    raise ValueError("Compiled stat_delta reward is invalid for this task category")
                continue

            if self.category != "survival" or str(reward.get("stat") or "") != "custom":
                raise ValueError(f"Compiled MineDojo {reward_kind} reward is valid only for Survival custom stats")
            if self._object_key(reward.get("object")) != object_keys[0]:
                raise ValueError("Compiled MineDojo survival reward object must match the success target")
            numeric_field = "bucket_size" if reward_kind == "stat_bucket_delta" else "gte"
            numeric_value = reward.get(numeric_field)
            if (
                isinstance(numeric_value, bool)
                or not isinstance(numeric_value, (int, float))
                or not math.isfinite(float(numeric_value))
                or float(numeric_value) <= 0
            ):
                raise ValueError(f"Compiled MineDojo {reward_kind} reward {numeric_field} must be positive")

    @staticmethod
    def _object_key(value: Any) -> str:
        return _bare_identifier(value)

    @staticmethod
    def _event_state(state: _ScoreState, event: str) -> Mapping[str, float]:
        if event == "inventory":
            return state.inventory
        if event == "kill_entity":
            return state.kill_entity
        if event == "use_item":
            return state.use_item
        if event == "custom":
            if state.time_since_death is None:
                raise MineDojoScorerStateError("MineStudio state lacks custom.time_since_death")
            return {"time_since_death": state.time_since_death}
        raise ValueError(f"Unsupported MineDojo compiled event: {event!r}")

    def _compiled_values(self, contract: Mapping[str, Any], current: _ScoreState) -> dict[str, float]:
        assert self._initial is not None
        kind = str(contract["kind"])
        if kind == "inventory_delta":
            event = "inventory"
        else:
            event = str(contract.get("stat") or "")
        current_values = self._event_state(current, event)
        initial_values = self._event_state(self._initial, event)
        objects_value = contract.get("objects")
        if isinstance(objects_value, Sequence) and not isinstance(objects_value, (str, bytes)):
            objects = list(objects_value)
        else:
            objects = [contract.get("object")]
        result: dict[str, float] = {}
        for raw_object in objects:
            key = self._object_key(raw_object)
            current_value = current_values.get(key, 0.0)
            result[key] = current_value if kind == "stat_value" else current_value - initial_values.get(key, 0.0)
        return result

    def _evaluate_compiled_target(
        self,
        current: _ScoreState,
    ) -> tuple[list[dict[str, Any]], dict[str, float], bool]:
        assert self._compiled_target is not None
        values = self._compiled_values(self._compiled_target, current)
        aggregation = str(self._compiled_target["aggregation"])
        threshold = float(self._compiled_target["gte"])
        event = str(self._compiled_target["kind"])
        if aggregation == "sum":
            total = sum(values.values())
            criteria = [
                {
                    "event": event,
                    "objects": list(values),
                    "aggregation": "sum",
                    "value": total,
                    "threshold": threshold,
                    "passed": total >= threshold,
                }
            ]
            return criteria, values, criteria[0]["passed"]
        criteria = [
            {
                "event": event,
                "target": item,
                "aggregation": aggregation,
                "value": value,
                "threshold": threshold,
                "passed": value >= threshold,
            }
            for item, value in values.items()
        ]
        success = all(item["passed"] for item in criteria) if aggregation == "all" else any(
            item["passed"] for item in criteria
        )
        return criteria, values, success

    def _evaluate_compiled_rewards(self, current: _ScoreState) -> float:
        assert self._previous is not None
        reward_total = 0.0
        for reward in self._compiled_rewards:
            kind = str(reward["kind"])
            weight = float(reward.get("weight", 1.0))
            if kind in {"inventory_delta", "stat_delta"}:
                event = "inventory" if kind == "inventory_delta" else str(reward.get("stat") or "")
                current_values = self._event_state(current, event)
                previous_values = self._event_state(self._previous, event)
                objects = reward.get("objects")
                if not isinstance(objects, Sequence) or isinstance(objects, (str, bytes)):
                    raise ValueError(f"Compiled MineDojo {kind} reward requires objects")
                delta = sum(
                    current_values.get(self._object_key(item), 0.0)
                    - previous_values.get(self._object_key(item), 0.0)
                    for item in objects
                )
                reward_total += delta * weight
            elif kind == "stat_bucket_delta":
                current_values = self._event_state(current, str(reward.get("stat") or ""))
                previous_values = self._event_state(self._previous, str(reward.get("stat") or ""))
                key = self._object_key(reward.get("object"))
                bucket_size = float(reward["bucket_size"])
                reward_total += (
                    current_values.get(key, 0.0) // bucket_size
                    - previous_values.get(key, 0.0) // bucket_size
                ) * weight
            else:
                current_values = self._event_state(current, str(reward.get("stat") or ""))
                previous_values = self._event_state(self._previous, str(reward.get("stat") or ""))
                key = self._object_key(reward.get("object"))
                threshold = float(reward["gte"])
                if current_values.get(key, 0.0) >= threshold > previous_values.get(key, 0.0):
                    reward_total += weight
        return reward_total

    @staticmethod
    def _criterion(target: _Target, value: float, passed: bool, *, event: str) -> dict[str, Any]:
        return {
            "event": event,
            "source_target": target.source,
            "target": target.target,
            "value": value,
            "threshold": target.quantity,
            "passed": passed,
            "mapping_status": target.mapping.status,
        }


__all__ = [
    "MINECRAFT_TICKS_PER_DAY",
    "SCORER_PROTOCOL",
    "TECH_ITEMS",
    "MineDojoPortedScore",
    "MineDojoPortedScorer",
    "MineDojoScorerStateError",
]

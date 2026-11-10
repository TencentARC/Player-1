"""Player-1-Gym browser step validation and runtime health checks."""
from __future__ import annotations
import math
from dataclasses import dataclass
from typing import Any, Mapping
from player1.runtime.contracts import (
    RuntimeContractError, copy_json_value, _finite_number, _freeze_json,
    _require_nonempty_string, _require_optional_string, _require_bool,
    _require_mapping_frozen,
)

def _require_positive_int(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise RuntimeContractError(f"{field_name} must be a positive integer")
    return value


def _require_int(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeContractError(f"{field_name} must be an integer")
    return value


def _require_nonnegative_number(value: Any, *, field_name: str) -> float:
    numeric = _finite_number(value)
    if numeric is None or numeric < 0.0:
        raise RuntimeContractError(f"{field_name} must be a finite non-negative number")
    return numeric



RUNTIME_HEALTH_VERSION = "game-gym.health.v1"


PLAYER1_RUNTIME_API_VERSION = "1.0"


GAME_STATE_SCHEMA_VERSION = "2.0"


RUNTIME_HEALTH_PROBE_SCRIPT = """
() => {
    const gameGymAPI = window.gameGymAPI;
    const gameAPI = window.gameAPI;
    const methodFlags = (value, methods) => {
        const result = {};
        for (const method of methods) {
            result[method] = Boolean(value && typeof value[method] === "function");
        }
        return result;
    };
    let state = null;
    try {
        if (gameAPI && typeof gameAPI.getState === "function") {
            state = gameAPI.getState();
        } else if (gameGymAPI && typeof gameGymAPI.getState === "function") {
            state = gameGymAPI.getState();
        }
    } catch (error) {
        return {
            probe_error: String(error && error.message ? error.message : error),
            player1_gym_api: null,
            game_api: null,
            viewport: null,
            state: null,
        };
    }
    const capabilities = gameAPI && gameAPI.capabilities && typeof gameAPI.capabilities === "object"
        ? gameAPI.capabilities
        : {};
    return {
        probe_error: null,
        player1_gym_api: {
            version: gameGymAPI ? gameGymAPI.version : null,
            methods: methodFlags(gameGymAPI, ["step"]),
        },
        game_api: {
            version: gameAPI ? gameAPI.version : null,
            methods: methodFlags(gameAPI, ["reset", "getState"]),
            capabilities: {
                supports_seed: capabilities.supports_seed === true,
                supports_inplace_reset: capabilities.supports_inplace_reset === true,
                provides_actionable_flag: capabilities.provides_actionable_flag === true,
                provides_gamelet_step_api: capabilities.provides_gamelet_step_api === true,
            },
        },
        runtime_hooks: {
            pause: typeof window.__pauseGame === "function",
            resume: typeof window.__resumeGame === "function",
            advance_time: typeof window.advanceTime === "function",
        },
        viewport: {
            width: Number(window.innerWidth),
            height: Number(window.innerHeight),
        },
        state: state && typeof state === "object" ? {
            schemaVersion: state.schemaVersion,
            gameId: state.gameId,
            seed: state.seed,
            status: state.status,
            runtime_paused: state.runtime_paused,
            is_actionable: state.is_actionable,
            terminal: state.terminal,
            metrics: state.metrics,
        } : null,
    };
}
""".strip()


class RuntimeHealthError(RuntimeError):
    """Raised when a required runtime health check fails."""

    def __init__(self, report: "RuntimeHealthReport"):
        self.report = report
        failed = ", ".join(report.failed_checks)
        super().__init__(f"Player-1 runtime health check failed during {report.stage}: {failed or 'unknown failure'}")


def validate_runtime_step_result(step_result: Any) -> dict[str, Any]:
    """Validate the fresh browser-side ``gameGymAPI.step`` result in place."""

    if not isinstance(step_result, dict):
        raise RuntimeContractError("gameGymAPI.step must return an object")

    required_fields = ("state", "observation", "reward", "done", "info")
    missing_fields = [field_name for field_name in required_fields if field_name not in step_result]
    if missing_fields:
        raise RuntimeContractError(f"gameGymAPI.step result is missing required fields: {', '.join(missing_fields)}")

    state = step_result["state"]
    if not isinstance(state, dict):
        raise RuntimeContractError("gameGymAPI.step state must be an object")
    if str(state.get("schemaVersion") or "") != "2.0":
        raise RuntimeContractError("gameGymAPI.step state must use schemaVersion '2.0'")
    _require_nonempty_string(state.get("gameId"), field_name="gameGymAPI.step state.gameId")
    _require_nonempty_string(state.get("status"), field_name="gameGymAPI.step state.status")
    if not isinstance(state.get("game_state"), dict) or not isinstance(state.get("metrics"), dict):
        raise RuntimeContractError("gameGymAPI.step state must contain game_state and metrics objects")

    numeric_seed = _finite_number(state.get("seed"))
    if numeric_seed is None or not numeric_seed.is_integer():
        raise RuntimeContractError("gameGymAPI.step state.seed must be a finite integer")

    terminal = state.get("terminal")
    if not isinstance(terminal, dict) or not isinstance(terminal.get("isTerminal"), bool):
        raise RuntimeContractError("gameGymAPI.step state.terminal.isTerminal must be a boolean")
    for terminal_field in ("outcome", "reason"):
        terminal_value = terminal.get(terminal_field)
        if terminal_value is not None and not isinstance(terminal_value, str):
            raise RuntimeContractError(f"gameGymAPI.step state.terminal.{terminal_field} must be a string or null")
        if not terminal["isTerminal"] and terminal_value is not None:
            raise RuntimeContractError(f"gameGymAPI.step non-terminal state cannot carry terminal.{terminal_field}")
    if not isinstance(state.get("is_actionable"), bool):
        raise RuntimeContractError("gameGymAPI.step state.is_actionable must be a boolean")

    reward = _finite_number(step_result["reward"])
    if reward is None:
        raise RuntimeContractError("gameGymAPI.step reward must be finite")

    done = step_result["done"]
    if not isinstance(done, bool):
        raise RuntimeContractError("gameGymAPI.step done must be a boolean")
    if done is not terminal["isTerminal"]:
        raise RuntimeContractError("gameGymAPI.step done disagrees with state.terminal.isTerminal")

    info = step_result["info"]
    if not isinstance(info, dict):
        raise RuntimeContractError("gameGymAPI.step info must be an object")
    receipt = info.get("action")
    if not isinstance(receipt, dict):
        raise RuntimeContractError("gameGymAPI.step info.action must be an object")
    _require_nonempty_string(
        receipt.get("type"),
        field_name="gameGymAPI.step info.action.type",
    )
    _require_nonempty_string(
        receipt.get("id"),
        field_name="gameGymAPI.step info.action.id",
    )
    if "args" in receipt and not isinstance(receipt["args"], dict):
        raise RuntimeContractError("gameGymAPI.step info.action.args must be an object when present")

    reward_metrics: dict[str, float] = {}
    for reward_field in ("env_reward_step", "env_reward_episode", "primary_score"):
        metric_value = _finite_number(state["metrics"].get(reward_field))
        if metric_value is None:
            raise RuntimeContractError(f"gameGymAPI.step state.metrics.{reward_field} must be finite")
        reward_metrics[reward_field] = metric_value
    if not math.isclose(
        reward,
        reward_metrics["env_reward_step"],
        rel_tol=1e-9,
        abs_tol=1e-9,
    ):
        raise RuntimeContractError(
            "gameGymAPI.step reward disagrees with state.metrics.env_reward_step "
            f"(gameId={state['gameId']!r}, seed={state['seed']!r}, "
            f"terminal={terminal['isTerminal']!r}, reward={reward!r}, "
            f"env_reward_step={reward_metrics['env_reward_step']!r})"
        )
    return step_result


@dataclass(frozen=True, slots=True)
class RuntimeHealthExpectations:
    """Core runtime values that must agree with one ``GameEnv``."""

    game_id: str
    viewport_width: int
    viewport_height: int
    random_seed: int | None
    training_reward_field: str | None
    require_virtual_time: bool
    require_pause: bool = False

    def __post_init__(self) -> None:
        game_id = _require_nonempty_string(self.game_id, field_name="health game_id")
        viewport_width = _require_positive_int(self.viewport_width, field_name="health viewport_width")
        viewport_height = _require_positive_int(self.viewport_height, field_name="health viewport_height")
        random_seed = self.random_seed
        if random_seed is not None:
            random_seed = _require_int(random_seed, field_name="health random_seed")
        training_reward_field = _require_optional_string(
            self.training_reward_field,
            field_name="health training_reward_field",
        )
        require_virtual_time = _require_bool(self.require_virtual_time, field_name="health require_virtual_time")
        require_pause = _require_bool(self.require_pause, field_name="health require_pause")
        object.__setattr__(self, "game_id", game_id)
        object.__setattr__(self, "viewport_width", viewport_width)
        object.__setattr__(self, "viewport_height", viewport_height)
        object.__setattr__(self, "random_seed", random_seed)
        object.__setattr__(self, "training_reward_field", training_reward_field)
        object.__setattr__(self, "require_virtual_time", require_virtual_time)
        object.__setattr__(self, "require_pause", require_pause)


@dataclass(frozen=True, slots=True)
class RuntimeHealthReport:
    """Compact machine-readable result of one startup/reset handshake."""

    stage: str
    checks: Mapping[str, bool]
    observed: Mapping[str, Any]
    timing_ms: float
    schema_version: str = RUNTIME_HEALTH_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != RUNTIME_HEALTH_VERSION:
            raise RuntimeContractError(f"unsupported runtime health version {self.schema_version!r}")
        stage = _require_nonempty_string(self.stage, field_name="runtime health stage")
        if not isinstance(self.checks, Mapping) or not self.checks:
            raise RuntimeContractError("runtime health report must contain at least one check")
        normalized_checks: dict[str, bool] = {}
        for raw_name, raw_passed in self.checks.items():
            name = _require_nonempty_string(raw_name, field_name="runtime health check name")
            normalized_checks[name] = _require_bool(raw_passed, field_name=f"runtime health check {name}")
        observed = _require_mapping_frozen(self.observed, field_name="runtime health observed")
        timing_ms = _require_nonnegative_number(self.timing_ms, field_name="runtime health timing_ms")
        object.__setattr__(self, "stage", stage)
        object.__setattr__(self, "checks", _freeze_json(normalized_checks))
        object.__setattr__(self, "observed", observed)
        object.__setattr__(self, "timing_ms", timing_ms)

    @property
    def status(self) -> str:
        return "healthy" if all(self.checks.values()) else "failed"

    @property
    def failed_checks(self) -> tuple[str, ...]:
        return tuple(sorted(name for name, passed in self.checks.items() if not passed))

    def require_healthy(self) -> None:
        if self.status == "failed":
            raise RuntimeHealthError(self)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "stage": self.stage,
            "status": self.status,
            "checks": {str(name): bool(passed) for name, passed in self.checks.items()},
            "failed_checks": list(self.failed_checks),
            "observed": copy_json_value(self.observed),
            "timing_ms": float(self.timing_ms),
        }


def _get_path(value: Any, path: str) -> tuple[bool, Any]:
    current = value
    for part in str(path or "").split("."):
        if not part:
            return False, None
        if not isinstance(current, Mapping) or part not in current:
            return False, None
        current = current[part]
    return True, current


def build_runtime_health_report(
    *,
    stage: str,
    probe: Mapping[str, Any],
    screenshot: Mapping[str, Any],
    expectations: RuntimeHealthExpectations,
    timing_ms: float,
) -> RuntimeHealthReport:
    """Validate only fields required by the maintained runtime."""

    try:
        probe_copy = copy_json_value(probe)
        screenshot_copy = copy_json_value(screenshot)
    except RuntimeContractError as exc:
        return RuntimeHealthReport(
            stage=stage,
            checks={"payload.json": False},
            observed={"payload_error": str(exc)},
            timing_ms=timing_ms,
        )
    if not isinstance(probe_copy, dict) or not isinstance(screenshot_copy, dict):
        return RuntimeHealthReport(
            stage=stage,
            checks={"payload.object": False},
            observed={"probe_type": type(probe_copy).__name__, "screenshot_type": type(screenshot_copy).__name__},
            timing_ms=timing_ms,
        )

    checks: dict[str, bool] = {}

    def add(name: str, passed: bool) -> None:
        checks[name] = bool(passed)

    add("probe.execution", probe_copy.get("probe_error") is None)

    player1_gym_api = probe_copy.get("player1_gym_api")
    player1_gym_api = player1_gym_api if isinstance(player1_gym_api, dict) else {}
    game_api = probe_copy.get("game_api")
    game_api = game_api if isinstance(game_api, dict) else {}
    runtime_methods = player1_gym_api.get("methods")
    runtime_methods = runtime_methods if isinstance(runtime_methods, dict) else {}
    game_methods = game_api.get("methods")
    game_methods = game_methods if isinstance(game_methods, dict) else {}

    add("player1_gym_api.version", player1_gym_api.get("version") == PLAYER1_RUNTIME_API_VERSION)
    add("game_api.version", game_api.get("version") == PLAYER1_RUNTIME_API_VERSION)

    add("player1_gym_api.method.step", runtime_methods.get("step") is True)
    for method in ("reset", "getState"):
        add(f"game_api.method.{method}", game_methods.get(method) is True)

    runtime_hooks = probe_copy.get("runtime_hooks")
    runtime_hooks = runtime_hooks if isinstance(runtime_hooks, dict) else {}
    if expectations.require_virtual_time:
        add("runtime_hook.advance_time", runtime_hooks.get("advance_time") is True)
    if expectations.require_pause:
        add("runtime_hook.pause", runtime_hooks.get("pause") is True)
        add("runtime_hook.resume", runtime_hooks.get("resume") is True)

    capabilities = game_api.get("capabilities")
    capabilities = capabilities if isinstance(capabilities, dict) else {}
    for capability in (
        "supports_seed",
        "supports_inplace_reset",
        "provides_actionable_flag",
        "provides_gamelet_step_api",
    ):
        add(f"game_api.capability.{capability}", capabilities.get(capability) is True)

    viewport = probe_copy.get("viewport")
    viewport = viewport if isinstance(viewport, dict) else {}
    add("viewport.width", viewport.get("width") == expectations.viewport_width)
    add("viewport.height", viewport.get("height") == expectations.viewport_height)

    add("screenshot.capture", screenshot_copy.get("error") is None)
    add("screenshot.capture_backend", screenshot_copy.get("capture_backend") == "playwright")
    add("screenshot.mime_type", screenshot_copy.get("mime_type") == "image/png")
    add("screenshot.encoded_mime_type", screenshot_copy.get("encoded_mime_type") == "image/png")
    width_value = screenshot_copy.get("width")
    height_value = screenshot_copy.get("height")
    width_matches = (
        isinstance(width_value, int)
        and not isinstance(width_value, bool)
        and abs(width_value - expectations.viewport_width) <= 1
    )
    height_matches = (
        isinstance(height_value, int)
        and not isinstance(height_value, bool)
        and abs(height_value - expectations.viewport_height) <= 1
    )
    add("screenshot.width", width_matches)
    add("screenshot.height", height_matches)
    byte_length = screenshot_copy.get("byte_length")
    add(
        "screenshot.byte_length", isinstance(byte_length, int) and not isinstance(byte_length, bool) and byte_length > 0
    )

    state = probe_copy.get("state")
    state = state if isinstance(state, dict) else {}
    add("state.schema_version", state.get("schemaVersion") == GAME_STATE_SCHEMA_VERSION)
    add("state.game_id", state.get("gameId") == expectations.game_id)

    observed_seed = state.get("seed")
    expected_seed = None if expectations.random_seed is None else int(expectations.random_seed) & 0xFFFFFFFF
    numeric_seed = _finite_number(observed_seed)
    seed_is_integer = numeric_seed is not None and numeric_seed.is_integer()
    seed_matches = seed_is_integer and (expected_seed is None or int(numeric_seed) & 0xFFFFFFFF == expected_seed)
    add("state.seed", bool(seed_matches))
    status = state.get("status")
    add("state.status", isinstance(status, str) and bool(status.strip()))

    terminal = state.get("terminal")
    terminal = terminal if isinstance(terminal, dict) else {}
    add("state.terminal.is_terminal", terminal.get("isTerminal") is False)
    add("state.is_actionable", state.get("is_actionable") is True)
    if expectations.require_pause:
        add("state.runtime_paused", state.get("runtime_paused") is True)

    reward_paths = [
        "metrics.env_reward_step",
        "metrics.env_reward_episode",
        "metrics.primary_score",
    ]
    if expectations.training_reward_field:
        reward_paths.append(expectations.training_reward_field)
    observed_rewards: dict[str, Any] = {}
    for path in dict.fromkeys(reward_paths):
        found, value = _get_path(state, path)
        observed_rewards[path] = value if found else None
        add(f"reward_field.{path}", found and _finite_number(value) is not None)

    observed = {
        "probe_error": probe_copy.get("probe_error"),
        "player1_gym_api_version": player1_gym_api.get("version"),
        "game_api_version": game_api.get("version"),
        "state_schema_version": state.get("schemaVersion"),
        "game_id": state.get("gameId"),
        "seed": observed_seed,
        "viewport": viewport,
        "screenshot": screenshot_copy,
        "rewards": observed_rewards,
    }
    return RuntimeHealthReport(
        stage=stage,
        checks=checks,
        observed=observed,
        timing_ms=timing_ms,
    )

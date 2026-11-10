"""Load strict GameGym validation prompts without changing GameWorld's catalog."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

from catalog._yaml import as_mapping, as_optional_text, as_string_list, load_yaml_mapping


GAME_GYM_PROMPT_PROFILE = "game-gym"
GAME_GYM_ACTION_SPACE_MODE = "control_v0_5"
_PROFILES_DIR = Path(__file__).resolve().parent / "games"


def _required_text(value: Any, *, field: str, context: str) -> str:
    text = as_optional_text(value)
    if text is None:
        raise ValueError(f"{context} requires non-empty {field}")
    return text


def _without_markdown_headings(value: str, *, field: str, context: str) -> str:
    if any(line.lstrip().startswith("#") for line in value.splitlines()):
        raise ValueError(f"{context} {field} must not define nested Markdown headings")
    return value


@dataclass(frozen=True)
class GameGymInContextExample:
    """One named, complete response example in a GameWorld prompt profile."""

    name: str
    response: str

    @classmethod
    def from_mapping(cls, value: Any, *, context: str) -> GameGymInContextExample:
        if not isinstance(value, Mapping):
            raise ValueError(f"{context} must be a mapping with name and response")
        raw = dict(value)
        if set(raw) != {"name", "response"}:
            raise ValueError(f"{context} must define exactly name and response")
        name = _required_text(raw.get("name"), field="name", context=context)
        response = _required_text(raw.get("response"), field="response", context=context)
        if "\n" in name or name.endswith(":"):
            raise ValueError(f"{context} name must be single-line text without a trailing colon")
        return cls(name=name, response=response)


@dataclass(frozen=True)
class GameGymRolePrompt:
    """Normalized role prose and wire examples for one GameWorld role."""

    description: str
    controls: tuple[str, ...]
    in_context_examples: Mapping[str, tuple[GameGymInContextExample, ...]]

    @classmethod
    def from_mapping(cls, value: Any, *, context: str) -> GameGymRolePrompt:
        raw = as_mapping(value)
        description = _without_markdown_headings(
            _required_text(raw.get("description"), field="description", context=context),
            field="description",
            context=context,
        )
        controls = tuple(as_string_list(raw.get("controls")))
        if not controls:
            raise ValueError(f"{context} requires at least one control instruction")
        if any("\n" in control or control.lstrip().startswith(("#", "-")) for control in controls):
            raise ValueError(f"{context} controls must be single-line prose without list markers")

        raw_examples = raw.get("in_context_examples")
        if not isinstance(raw_examples, Mapping):
            raise ValueError(f"{context}.in_context_examples must be a mapping")
        if set(raw_examples) != {GAME_GYM_ACTION_SPACE_MODE}:
            raise ValueError(f"{context}.in_context_examples must define exactly {GAME_GYM_ACTION_SPACE_MODE!r}")

        raw_mode_examples = raw_examples[GAME_GYM_ACTION_SPACE_MODE]
        example_context = f"{context}.in_context_examples.{GAME_GYM_ACTION_SPACE_MODE}"
        if not isinstance(raw_mode_examples, list) or len(raw_mode_examples) != 2:
            raise ValueError(f"{example_context} must contain exactly two named examples")
        mode_examples = tuple(
            GameGymInContextExample.from_mapping(
                raw_example,
                context=f"{example_context}[{index}]",
            )
            for index, raw_example in enumerate(raw_mode_examples, start=1)
        )
        normalized_names = [example.name.casefold() for example in mode_examples]
        if len(set(normalized_names)) != len(normalized_names):
            raise ValueError(f"{example_context} example names must be unique")
        examples = {GAME_GYM_ACTION_SPACE_MODE: mode_examples}
        return cls(description=description, controls=controls, in_context_examples=examples)

    def render_role_section(self) -> str:
        return f"Role:\n{self.description}"

    def render_controls_section(self) -> str:
        return "Controls:\n" + "\n".join(f"- {control}" for control in self.controls)


@dataclass(frozen=True)
class GameGymPromptProfile:
    """One Agent-visible validation prompt for a GameWorld game."""

    profile: str
    game_id: str
    game_rules: str
    roles: Mapping[str, GameGymRolePrompt]

    @classmethod
    def from_mapping(cls, value: Any, *, path: Path) -> GameGymPromptProfile:
        raw = as_mapping(value)
        context = f"GameGym prompt profile {path}"
        profile = _required_text(raw.get("profile"), field="profile", context=context)
        if profile != GAME_GYM_PROMPT_PROFILE:
            raise ValueError(f"{context} profile must be {GAME_GYM_PROMPT_PROFILE!r}, got {profile!r}")
        game_id = _required_text(raw.get("game_id"), field="game_id", context=context)
        if game_id != path.stem:
            raise ValueError(f"{context} game_id must match filename stem {path.stem!r}")
        game_rules = _without_markdown_headings(
            _required_text(raw.get("game_rules"), field="game_rules", context=context),
            field="game_rules",
            context=context,
        )
        raw_roles = raw.get("roles")
        if not isinstance(raw_roles, Mapping) or not raw_roles:
            raise ValueError(f"{context} requires a non-empty roles mapping")
        roles = {
            str(role_name).strip(): GameGymRolePrompt.from_mapping(
                role_prompt,
                context=f"{context}.roles.{role_name}",
            )
            for role_name, role_prompt in raw_roles.items()
        }
        if any(not role_name for role_name in roles):
            raise ValueError(f"{context} role names must be non-empty")
        return cls(
            profile=profile,
            game_id=game_id,
            game_rules=game_rules,
            roles=roles,
        )

    def require_roles(self, role_names: set[str]) -> None:
        configured = set(self.roles)
        if configured != role_names:
            raise ValueError(
                f"GameGym prompt profile {self.game_id!r} roles do not match GameWorld catalog: "
                f"configured={sorted(configured)!r}, catalog={sorted(role_names)!r}"
            )


@cache
def load_game_gym_prompt_profile(game_id: str) -> GameGymPromptProfile:
    """Load the required GameGym validation prompt for one GameWorld game."""

    normalized = str(game_id or "").strip()
    if not normalized:
        raise ValueError("GameGym prompt profile game_id must be non-empty")
    path = _PROFILES_DIR / f"{normalized}.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"Missing GameGym validation prompt for {normalized!r}: {path}")
    return GameGymPromptProfile.from_mapping(load_yaml_mapping(path), path=path)


__all__ = [
    "GAME_GYM_ACTION_SPACE_MODE",
    "GAME_GYM_PROMPT_PROFILE",
    "GameGymInContextExample",
    "GameGymPromptProfile",
    "GameGymRolePrompt",
    "load_game_gym_prompt_profile",
]

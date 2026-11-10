"""Public runtime package API."""

from __future__ import annotations

_EXPORTS = {
    "ActionProposal": (".episode", "ActionProposal"),
    "ActionProposalDraft": (".episode", "ActionProposalDraft"),
    "ActionPayload": (".types", "ActionPayload"),
    "Agent": (".types", "Agent"),
    "EpisodeController": (".episode", "EpisodeController"),
    "EpisodePolicy": (".episode", "EpisodePolicy"),
    "EpisodeProtocolError": (".episode", "EpisodeProtocolError"),
    "EpisodeRequest": (".episode", "EpisodeRequest"),
    "EpisodeStateError": (".episode", "EpisodeStateError"),
    "EpisodeTurn": (".episode", "EpisodeTurn"),
    "Evaluator": (".evaluator", "Evaluator"),
    "GameControls": (".types", "GameControls"),
    "GenerationEnvelope": (".episode", "GenerationEnvelope"),
    "RoleControls": (".types", "RoleControls"),
    "RuntimeConfig": (".config", "RuntimeConfig"),
}

__all__ = [
    "ActionProposal",
    "ActionProposalDraft",
    "ActionPayload",
    "Agent",
    "EpisodeController",
    "EpisodePolicy",
    "EpisodeProtocolError",
    "EpisodeRequest",
    "EpisodeStateError",
    "EpisodeTurn",
    "Evaluator",
    "GameControls",
    "GenerationEnvelope",
    "RoleControls",
    "RuntimeConfig",
]


def __getattr__(name: str):
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name = target
    from importlib import import_module

    value = getattr(import_module(module_name, __name__), attr_name)
    globals()[name] = value
    return value

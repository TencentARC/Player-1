"""Browser game state normalization, summaries and WebGL capture setup."""

from __future__ import annotations

import json


EXCLUDE_FROM_SUMMARY = {"raw", "timestampMs", "schemaVersion"}
NO_GAME_STATE_SUMMARY = "(no game state)"


PRESERVE_WEBGL_DRAWING_BUFFER_SCRIPT = """(function() {
    const origGetContext = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function(type, attrs) {
        if (type === "webgl" || type === "webgl2" || type === "experimental-webgl") {
            attrs = Object.assign({}, attrs || {}, { preserveDrawingBuffer: true });
        }
        return origGetContext.call(this, type, attrs);
    };
})();"""


class GameAPIStateTracker:
    """Normalize and summarize browser game state."""

    name = "game_api"

    def _strip_nulls(self, value: object) -> object:
        if isinstance(value, dict):
            cleaned: dict = {}
            for key, item in value.items():
                cleaned_item = self._strip_nulls(item)
                if cleaned_item is None:
                    continue
                cleaned[key] = cleaned_item
            return cleaned or None
        if isinstance(value, list):
            cleaned_items = []
            for item in value:
                cleaned_item = self._strip_nulls(item)
                if cleaned_item is None:
                    continue
                cleaned_items.append(cleaned_item)
            return cleaned_items or None
        return value

    def normalize_state(self, state: dict | None) -> dict | None:
        """Return the canonical state representation consumed by runtime clients."""

        if not state or not isinstance(state, dict):
            return None
        cleaned = self._strip_nulls(state)
        return cleaned if isinstance(cleaned, dict) else None

    def summarize(self, state: dict | None) -> str:
        """Create summary by including all fields except internal metadata.

        This is adaptive - any new field added to a game API automatically
        appears in the summary without manual configuration.
        """
        if not state or not isinstance(state, dict):
            return NO_GAME_STATE_SUMMARY

        summary = {key: value for key, value in state.items() if key not in EXCLUDE_FROM_SUMMARY}
        if not summary:
            return NO_GAME_STATE_SUMMARY
        return json.dumps(summary, ensure_ascii=False)


__all__ = [
    "GameAPIStateTracker",
    "NO_GAME_STATE_SUMMARY",
    "PRESERVE_WEBGL_DRAWING_BUFFER_SCRIPT",
]

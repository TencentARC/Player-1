import ast
from pathlib import Path


ENGINE_WORKERS = Path(__file__).resolve().parents[2] / "verl" / "workers" / "engine_workers.py"


def test_weight_sync_clears_cached_memory_before_resuming_rollout_weights() -> None:
    tree = ast.parse(ENGINE_WORKERS.read_text())
    update_weights = next(
        node for node in ast.walk(tree) if isinstance(node, ast.AsyncFunctionDef) and node.name == "update_weights"
    )

    cleanup = next(
        node
        for node in ast.walk(update_weights)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "aggressive_empty_cache"
    )
    force_sync = next(keyword.value for keyword in cleanup.keywords if keyword.arg == "force_sync")

    resume_weights = next(
        node
        for node in ast.walk(update_weights)
        if isinstance(node, ast.Await)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Attribute)
        and node.value.func.attr == "resume"
        and any(
            keyword.arg == "tags"
            and isinstance(keyword.value, ast.List)
            and [element.value for element in keyword.value.elts] == ["weights"]
            for keyword in node.value.keywords
        )
    )

    assert isinstance(force_sync, ast.Constant) and force_sync.value is True
    assert cleanup.lineno < resume_weights.lineno

"""Published MineDojo artifacts load directly and reject protocol drift."""
import json
from copy import deepcopy

import pytest

from player1.evaluation.minestudio.minedojo_ported import (
    MINEDOJO_PORTED_SUITE_IDS,
    load_compiled_manifest,
    load_minedojo_ported_suite,
)


def test_frozen_manifest_loads_without_source_bundle():
    manifest = load_compiled_manifest()
    assert len(manifest['tasks']) == 1581
    assert {task['category'] for task in manifest['tasks']} == {'combat', 'harvest', 'survival', 'techtree'}


def test_published_suite_selections():
    assert MINEDOJO_PORTED_SUITE_IDS == ('minedojo-full', 'minedojo-300')
    full = load_minedojo_ported_suite('minedojo-full')
    benchmark = load_minedojo_ported_suite('minedojo-300')
    assert (len(full.tasks), full.default_trials_per_task, full.default_max_decisions) == (1581, 3, 1000)
    assert (len(benchmark.tasks), benchmark.default_trials_per_task) == (300, 8)


@pytest.mark.parametrize('change', ['schema', 'count', 'target', 'source'])
def test_manifest_loader_validates_custom_artifacts(tmp_path, change):
    manifest = deepcopy(load_compiled_manifest())
    if change == 'schema':
        manifest['schema_version'] = 99
    elif change == 'count':
        manifest['tasks'].pop()
    elif change == 'source':
        manifest['source'].pop('repository')
    else:
        manifest['tasks'][0]['target']['gte'] = 0
    path = tmp_path / 'manifest.json'
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        load_compiled_manifest(path)

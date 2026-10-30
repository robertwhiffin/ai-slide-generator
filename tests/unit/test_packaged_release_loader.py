"""Test suite for the test-only packaged Graph Version 1 loader.

Its parity half (``packaged_v1_runtime`` against the code-owned compatibility
runtime) was deleted with that runtime in #271 Task 12.  The literal content
hashes below remain the byte-identity oracle.
"""

from __future__ import annotations

import pytest

from src.services.graph_definition_manifest import GRAPH_V1_AGENT_KEYS
from src.services.persisted_graph_release import GraphReleaseNotFoundError
from tests.fixtures.packaged_release_loader import (
    PACKAGED_GRAPH_VERSION,
    PACKAGED_RELEASE_ID,
    PackagedGraphV1Loader,
)

# The seven packaged v1 content hashes — copied verbatim from
# test_graph_definition_manifest.py:744.  Do NOT import; a copy that cannot
# drift is the oracle (epic correction C-24).
PACKAGED_V1_CONTENT_HASHES = {
    "architect": "3da09952e7751cd967c3cee11b77628c51565e37fa1b75c1c6e9f92a92d3126b",
    "data_analyst": "5fd364e1936f58582a43eba1ef74a88166d698db644ff0b9562f3728f36210b2",
    "builder": "025f6a714ecd88ce68f7ba289f0fdc302298ab4ed66d456a7fcae45f46ca5f7d",
    "build_reviewer": "0a8f6a7c6ef13c1acd89960f44a0eaa57ea2e7b1074a1ec191654229d268461f",
    "fixer": "8342438644d4665e929d7fdbd694d0024e401546ae06a9566161b309adb4c82a",
    "fix_reviewer": "ff14c8e8b1622482f675f726eaeb10db2618b28afdce9598f1a6198ce36f04c0",
    "deck_reviewer": "7f015a2cb032f3d528ec9e5391e79ec21d7fe77514dcf33855734571c0bced1b",
}


@pytest.mark.parametrize("agent_key", GRAPH_V1_AGENT_KEYS)
def test_all_roles_resolve_with_correct_version_release_and_revision_ids(agent_key):
    """All seven roles must resolve with the exact graph_version, graph_release_id and revision."""
    loader = PackagedGraphV1Loader()
    resolved = loader.resolve(PACKAGED_RELEASE_ID, agent_key)
    assert resolved.graph_version == PACKAGED_GRAPH_VERSION  # 1
    assert resolved.graph_release_id == PACKAGED_RELEASE_ID  # 1
    assert resolved.agent_definition_revision_id == 2  # content.definition_version


@pytest.mark.parametrize("agent_key", GRAPH_V1_AGENT_KEYS)
def test_content_hashes_match_stored_literals(agent_key):
    """Content hashes must equal the byte-identity oracle literals (C-24)."""
    loader = PackagedGraphV1Loader()
    resolved = loader.resolve(PACKAGED_RELEASE_ID, agent_key)
    assert resolved.content_hash == PACKAGED_V1_CONTENT_HASHES[agent_key]


def test_wrong_release_id_raises_graph_release_not_found_error():
    """resolve(2, "architect") must raise GraphReleaseNotFoundError."""
    loader = PackagedGraphV1Loader()
    with pytest.raises(GraphReleaseNotFoundError):
        loader.resolve(2, "architect")


def test_content_override_changes_only_the_overridden_role():
    """An override for architect changes only architect; every other role is unaffected."""
    from src.services.graph_definition_manifest import load_graph_v1_manifest

    manifest = load_graph_v1_manifest()
    architect_content = next(d for d in manifest.definitions if d.agent_key == "architect")
    modified = architect_content.model_copy(
        update={"prompt_text": architect_content.prompt_text + " OVERRIDE"}
    )

    loader_with_override = PackagedGraphV1Loader(content_overrides={"architect": modified})
    loader_baseline = PackagedGraphV1Loader()

    overridden = loader_with_override.resolve(PACKAGED_RELEASE_ID, "architect")
    assert overridden.content.prompt_text.endswith(" OVERRIDE")

    for agent_key in GRAPH_V1_AGENT_KEYS:
        if agent_key == "architect":
            continue
        resolved = loader_with_override.resolve(PACKAGED_RELEASE_ID, agent_key)
        baseline = loader_baseline.resolve(PACKAGED_RELEASE_ID, agent_key)
        assert resolved.content == baseline.content

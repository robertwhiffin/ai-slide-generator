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
    "architect": "7b492c442c7406c5cb9c059e7e421875e1a65fab703b7d2ba2304a4629181aa4",
    "data_analyst": "1ffb1fb3f31a20b9424007eefdf918620f1058386a2ba81bfd22347510ce6803",
    "builder": "4310de2a987378777c089eddee192d45c7a824ec169457f39aa3b8fe4c0f0f4a",
    "build_reviewer": "1a895f4bee426041088635f7fa182200827db14ab35a229def6f8932d1516b18",
    "fixer": "a4fdb3e6fa54d8e2acf5507d9c2e6c024058c072dfab82373e2104f015856d7b",
    "fix_reviewer": "eed6c4ed4d363e32f4fd612daac03a32ca195bba07a3b7a026b64fcbe35d4558",
    "deck_reviewer": "ed5df628c3ea4c81091fa9d621a1c1d7a8a1089edf1a4f81f335671ac47c0cb5",
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

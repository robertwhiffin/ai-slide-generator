"""Test suite for the test-only packaged Graph Version 1 loader.

The parity half of this test (packaged_v1_runtime vs AgentRuntime.compatibility)
is possible only while the compatibility code still exists.  Task 12 deletes the
compatibility runtime together with the parity assertion at the bottom of this file.
"""

from __future__ import annotations

import pytest

from src.services.agent_runtime import (
    MODEL_DRIVEN_AGENT_KEYS,
    AgentAssemblyContext,
    AgentModelConfiguration,
    AgentRuntime,
)
from src.services.graph_definition_manifest import GRAPH_V1_AGENT_KEYS
from src.services.persisted_graph_release import GraphReleaseNotFoundError
from tests.fixtures.deterministic_model_adapter import FAKE_OUTPUTS
from tests.fixtures.packaged_release_loader import (
    PACKAGED_GRAPH_VERSION,
    PACKAGED_RELEASE_ID,
    PackagedGraphV1Loader,
    packaged_v1_runtime,
)

# The seven packaged v1 content hashes — copied verbatim from
# test_graph_definition_manifest.py:744.  Do NOT import; a copy that cannot
# drift is the oracle (epic correction C-24).
PACKAGED_V1_CONTENT_HASHES = {
    "architect": "e77e69b18cb9d843a1754dab65a79941ede8cfa7c8266292580ff7566d1dcb33",
    "data_analyst": "1ffb1fb3f31a20b9424007eefdf918620f1058386a2ba81bfd22347510ce6803",
    "builder": "1549a4231b3a4a6221842f3eca6699097199b28d8283b8995af7c90b406fe5c4",
    "build_reviewer": "1a895f4bee426041088635f7fa182200827db14ab35a229def6f8932d1516b18",
    "fixer": "fb9dc5a2bddb783ff2fd2eec54a3809e38cef2d0bc683daec3568005b8643c7b",
    "fix_reviewer": "e6d4a4801abc7b654f262f905f4b198d4c134d29801d2ecd09ed09cff2ec164f",
    "deck_reviewer": "8c876db55cddbaa2f9015321117e36adb5b63fb7c47dbb067a432d04c30cf54e",
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


# ---------------------------------------------------------------------------
# Parity: packaged_v1_runtime must be byte-identical to AgentRuntime.compatibility.
# This half is deleted in Task 12 together with the compatibility code itself.
# ---------------------------------------------------------------------------


class _RecordingAdapter:
    """Minimal model adapter that records every invoke call."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def invoke(
        self,
        *,
        agent_key: str,
        configuration: AgentModelConfiguration,
        schema: type,
        prompt: str,
    ) -> object:
        self.calls.append(
            {
                "agent_key": agent_key,
                "configuration": configuration,
                "schema": schema,
                "prompt": prompt,
            }
        )
        from pydantic import BaseModel
        assert issubclass(schema, BaseModel)
        return schema.model_validate(FAKE_OUTPUTS[agent_key])


@pytest.mark.parametrize("agent_key", MODEL_DRIVEN_AGENT_KEYS)
@pytest.mark.parametrize("design_system_active", [False, True])
def test_packaged_v1_runtime_prompt_configuration_and_schema_are_identical_to_compatibility(
    agent_key, design_system_active
):
    """Byte-for-byte parity between packaged_v1_runtime and AgentRuntime.compatibility.

    This is only verifiable while the compatibility code still exists.
    Task 12 deletes AgentRuntime.compatibility together with the comparison half.
    """
    payload = {"agent_key": agent_key, "sequence": 7, "optional": None}
    context = AgentAssemblyContext(design_system_active=design_system_active)

    packed_adapter = _RecordingAdapter()
    packaged_v1_runtime(model_adapter=packed_adapter).run(agent_key, 1, payload, context)

    compat_adapter = _RecordingAdapter()
    AgentRuntime.compatibility(model_adapter=compat_adapter).run(agent_key, 1, payload, context)

    assert len(packed_adapter.calls) == 1
    assert len(compat_adapter.calls) == 1

    packed_call = packed_adapter.calls[0]
    compat_call = compat_adapter.calls[0]

    assert packed_call["prompt"] == compat_call["prompt"]
    assert packed_call["configuration"] == compat_call["configuration"]
    assert packed_call["schema"].model_json_schema() == compat_call["schema"].model_json_schema()

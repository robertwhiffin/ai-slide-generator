"""The Graph Version 1 data analyst as first shipped, for tests of the legacy v1 path.

The packaged data analyst was upgraded to protected assembly v2 with its Genie One
prompt (``PromptAssembler().upgrade_definition_to_v2`` plus a new authored prompt), so
the packaged manifest no longer holds a v1 data analyst.  Installs bootstrapped before
that upgrade still do, and the v1 -> v2 transition, the legacy-source recovery and the
v1 replay are about exactly that definition.

``LEGACY_V1_DATA_ANALYST`` rebuilds it from literals and the frozen skill composite
(the transition record's ``source_composite_prompt``) and is pinned to the content hash
it shipped with, so it cannot drift from what those installs hold.
"""

from __future__ import annotations

import src.core.database  # noqa: F401  (break the src.* import cycle first)
from src.core.skills.data_analyst import INSTRUCTIONS as ANALYST_V1_PROMPT
from src.services.graph_definition_manifest import (
    AgentKey,
    DefinitionContent,
    GraphV1Manifest,
    assembly_rules_for,
    definition_content_hash,
    load_graph_v1_manifest,
)

#: The packaged data analyst's content hash before its v2 upgrade.
LEGACY_V1_DATA_ANALYST_HASH = "5fd364e1936f58582a43eba1ef74a88166d698db644ff0b9562f3728f36210b2"

LEGACY_V1_DATA_ANALYST = DefinitionContent.model_validate(
    {
        "agent_key": "data_analyst",
        "definition_version": 2,
        "prompt_text": ANALYST_V1_PROMPT,
        "model": {
            "endpoint_name": "system.ai.claude-opus-5-5",
            "temperature": 0.7,
            "max_tokens": 60000,
            "top_p": 0.95,
        },
        "schema_overlay": {"field_overrides": {}, "additional_optional_fields": []},
        "assembly_rules": assembly_rules_for("data_analyst"),
        "protected_assembly": {
            "version": 1,
            "digest": "e4ff3d6197ea926de2a4b7445c57a1d8b7cb906453ad76345ffd0666a0976852",
        },
        "schema_contract": {
            "version": 1,
            "digest": "610545fe1d094f2544a5c602c2ebb45f542b813bf47e347e96ba7e22a6bfc281",
        },
    }
)
if definition_content_hash(LEGACY_V1_DATA_ANALYST) != LEGACY_V1_DATA_ANALYST_HASH:
    raise RuntimeError("LEGACY_V1_DATA_ANALYST no longer hashes to its shipped content hash")


def legacy_v1_manifest(manifest: GraphV1Manifest | None = None) -> GraphV1Manifest:
    """``manifest`` (default: the packaged one) with its data analyst put back to v1."""
    source = manifest if manifest is not None else load_graph_v1_manifest()
    return GraphV1Manifest(
        manifest_version=1,
        definitions=tuple(
            LEGACY_V1_DATA_ANALYST if item.agent_key == "data_analyst" else item
            for item in source.definitions
        ),
    )


def legacy_v1_definition(agent_key: AgentKey) -> DefinitionContent:
    """One role of :func:`legacy_v1_manifest`: every role still v1 as first shipped."""
    return next(d for d in legacy_v1_manifest().definitions if d.agent_key == agent_key)

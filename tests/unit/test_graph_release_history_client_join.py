"""Join #270's history/rollback wire to the client (Correction 46; #269's join pattern).

Task 6 owns the server wire (``src/api/schemas/graph_release_history.py``) and the
widened evidence item (Correction 38).  The client's history/rollback parsers are
Task 7's, so this file pins, for now:

* the widened evidence item against the client's existing ``RELEASE_EVIDENCE_KEYS``
  and its kind/source pairing (both halves exist today);
* every new server model's exact field list and literals, as the contract Task 7's
  exact-key parsers must mirror.  Task 7 extends this file with the TS-side lists.
"""

from __future__ import annotations

import pathlib
import re
from typing import get_args

import pytest

from src.api.schemas import graph_release_history as history
from src.api.schemas import graph_releases as releases
from src.services import graph_configuration_rollback as rollback

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CLIENT_API = _REPO_ROOT / "frontend" / "src" / "api" / "agentDefinitions.ts"
_QUOTED = re.compile(r"'([^'\\\n]*)'")


def _client_names(opening: str) -> list[str]:
    source = _CLIENT_API.read_text(encoding="utf-8")
    assert source.count(opening) == 1, opening
    start = source.index(opening) + len(opening)
    return _QUOTED.findall(source[start : source.index("]", start)])


def test_the_client_evidence_keys_are_the_widened_server_item():
    assert _client_names("\nconst RELEASE_EVIDENCE_KEYS = [") == list(
        releases.ReleaseEvidenceResponse.model_fields
    ) == [
        "agent_test_run_id",
        "agent_key",
        "test_case_id",
        "evidence_kind",
        "source_release_id",
    ]


def test_the_client_pairs_each_evidence_kind_with_its_source():
    source = _CLIENT_API.read_text(encoding="utf-8")
    assert (
        "if (value.evidence_kind === 'approval') return value.source_release_id === null;"
    ) in source
    assert (
        "if (value.evidence_kind === 'historical_restore') "
        "return isPositiveInteger(value.source_release_id);"
    ) in source
    # Publication stays approval-only on both sides.
    assert "item.evidence_kind === 'approval')" in source


#: The contract Task 7's parsers mirror, key for key and in order.
_CONTRACT = {
    history.ReleaseHistoryListResponse: ["active_release", "releases"],
    history.ReleaseHistoryEntryResponse: [
        "release_id", "version_number", "is_active", "release_note", "published_by",
        "published_at", "effective_from", "effective_to", "previous", "restored_from",
        "restored_by", "changed_agents",
    ],
    history.ReleaseDetailResponse: ["release", "definitions", "evidence"],
    history.ReleaseDefinitionResponse: ["agent_definition_revision_id", "content_hash", "content"],
    history.ReleaseHistoryEvidenceResponse: [
        "agent_test_run_id", "agent_key", "test_case_id", "test_case_version",
        "evidence_kind", "source", "verdict", "verdict_reviewer", "verdict_at",
        "execution_status", "deterministic_checks_passed", "run_at",
    ],
    history.ReleaseComparisonResponse: ["active_release", "release", "agents"],
    history.AgentComparisonResponse: [
        "agent_key", "active_revision_id", "historical_revision_id", "same_revision",
        "field_diffs",
    ],
    history.ReleaseFieldDiffResponse: ["field", "active", "historical"],
    history.RollbackPreviewResponse: [
        "source", "active_release", "next_version_number", "lock_version",
        "default_release_note", "restorable", "blocked", "issues", "warnings", "agents",
        "evidence", "draft_effect",
    ],
    history.RollbackPreviewEvidenceResponse: ["agent_test_run_id", "agent_key", "test_case_id"],
    history.RollbackRequest: ["lock_version", "release_note"],
    history.RollbackSuccessResponse: [
        "release", "restored_from", "previous_release_id", "changed_agents", "mappings",
        "evidence", "draft", "draft_effect",
    ],
    history.RollbackValidationErrorResponse: ["code", "errors"],
    history.RollbackIncompatibleResponse: ["code", "source", "errors"],
    history.StaleRollbackResponse: [
        "code", "expected_lock_version", "current_lock_version", "active_release", "draft",
    ],
    history.RollbackSourceActiveResponse: ["code", "active_release"],
    history.RollbackMatchesActiveResponse: ["code", "active_release", "source"],
}


@pytest.mark.parametrize("model", list(_CONTRACT), ids=[m.__name__ for m in _CONTRACT])
def test_each_history_model_is_the_published_contract(model):
    assert list(model.model_fields) == _CONTRACT[model]
    assert model.model_config.get("extra") == "forbid"


def test_the_history_literals_are_the_service_vocabulary():
    assert get_args(history.DraftEffectWire) == get_args(rollback.DraftEffect)
    assert get_args(history.RollbackBlockWire) == get_args(rollback.RollbackBlock)
    assert history.ReleaseFieldDiffResponse.model_fields["field"].annotation is (
        releases.DiffFieldName
    )
    codes = {
        get_args(model.model_fields["code"].annotation)
        for model in _CONTRACT
        if "code" in model.model_fields
    }
    assert codes == {
        ("invalid_rollback",),
        ("rollback_incompatible",),
        ("stale_rollback",),
        ("rollback_source_active",),
        ("rollback_matches_active",),
    }

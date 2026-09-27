"""Join #270's history/rollback wire to the client (Correction 46; #269's join pattern).

Task 6 owns the server wire (``src/api/schemas/graph_release_history.py``) and the
widened evidence item (Correction 38).  The client's history/rollback parsers are
Task 7's, so this file pins, for now:

* the widened evidence item against the client's existing ``RELEASE_EVIDENCE_KEYS``
  and its kind/source pairing (both halves exist today);
* every new server model's exact field list and literals, as the contract Task 7's
  exact-key parsers must mirror.

Task 7 extends it with the TS side: each client ``const <NAME>_KEYS = [`` list is the
server model's field list in order, each literal array is the server literal, every
refusal code is spelled in the client, the client's routes are the mounted routes,
and the client's draft-effect labels cover exactly the server vocabulary.

Text-read rules for those client lines (keep them, or this join cannot read them):
each opening below appears exactly once in ``agentDefinitions.ts`` and lists
single-quoted names up to the closing ``]``; ``DRAFT_EFFECT_LABELS`` in
``reviewAndPublishState.ts`` lists one ``key: 'Label',`` pair per line.
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


# --- Task 7: the client's parsers mirror the contract ---------------------------------

_CLIENT_STATE = (
    _REPO_ROOT / "frontend" / "src" / "components" / "Admin" / "GraphRelease"
    / "reviewAndPublishState.ts"
)

#: Every #270 model the client parses or sends, and its client key list.
_CLIENT_KEY_LISTS = (
    (history.ReleaseHistoryListResponse, "\nconst RELEASE_HISTORY_LIST_KEYS = ["),
    (history.ReleaseHistoryEntryResponse, "\nconst RELEASE_HISTORY_ENTRY_KEYS = ["),
    (history.ReleaseDetailResponse, "\nconst RELEASE_DETAIL_KEYS = ["),
    (history.ReleaseDefinitionResponse, "\nconst RELEASE_DEFINITION_KEYS = ["),
    (history.ReleaseHistoryEvidenceResponse, "\nconst RELEASE_HISTORY_EVIDENCE_KEYS = ["),
    (history.ReleaseComparisonResponse, "\nconst RELEASE_COMPARISON_KEYS = ["),
    (history.AgentComparisonResponse, "\nconst AGENT_COMPARISON_KEYS = ["),
    (history.ReleaseFieldDiffResponse, "\nconst RELEASE_COMPARISON_FIELD_DIFF_KEYS = ["),
    (history.RollbackPreviewResponse, "\nconst ROLLBACK_PREVIEW_KEYS = ["),
    (history.RollbackPreviewEvidenceResponse, "\nconst ROLLBACK_PREVIEW_EVIDENCE_KEYS = ["),
    (history.RollbackRequest, "\nconst ROLLBACK_REQUEST_KEYS = ["),
    (history.RollbackSuccessResponse, "\nconst ROLLBACK_SUCCESS_KEYS = ["),
    (history.RollbackValidationErrorResponse, "\nconst ROLLBACK_VALIDATION_KEYS = ["),
    (history.RollbackIncompatibleResponse, "\nconst ROLLBACK_INCOMPATIBLE_KEYS = ["),
    (history.StaleRollbackResponse, "\nconst STALE_ROLLBACK_KEYS = ["),
    (history.RollbackSourceActiveResponse, "\nconst ROLLBACK_SOURCE_ACTIVE_KEYS = ["),
    (history.RollbackMatchesActiveResponse, "\nconst ROLLBACK_MATCHES_ACTIVE_KEYS = ["),
)


def test_every_contract_model_has_a_client_key_list():
    assert {model for model, _ in _CLIENT_KEY_LISTS} == set(_CONTRACT)


@pytest.mark.parametrize(
    ("model", "opening"),
    _CLIENT_KEY_LISTS,
    ids=[model.__name__ for model, _ in _CLIENT_KEY_LISTS],
)
def test_each_client_key_list_is_exactly_the_server_model(model, opening):
    client = _client_names(opening)
    assert len(client) == len(set(client)), client
    # Order too: the lists mirror the server models field for field.
    assert client == list(model.model_fields) == _CONTRACT[model], model.__name__


def _literal(annotation) -> list[str]:
    """The string members of a ``Literal`` or ``Literal | None`` annotation, in order."""
    members = []
    for arg in get_args(annotation):
        inner = get_args(arg)
        members.extend(inner if inner else [arg])
    return [member for member in members if isinstance(member, str)]


@pytest.mark.parametrize(
    ("opening", "annotation"),
    [
        ("\nexport const DRAFT_EFFECTS: readonly DraftEffect[] = [", history.DraftEffectWire),
        ("\nexport const ROLLBACK_BLOCKS: readonly RollbackBlock[] = [", history.RollbackBlockWire),
        (
            "\nconst RELEASE_RUN_VERDICTS: readonly ReleaseRunVerdict[] = [",
            history.ReleaseHistoryEvidenceResponse.model_fields["verdict"].annotation,
        ),
        (
            "\nconst RELEASE_RUN_EXECUTION_STATUSES: readonly ReleaseRunExecutionStatus[] = [",
            history.ReleaseHistoryEvidenceResponse.model_fields["execution_status"].annotation,
        ),
    ],
    ids=["draft_effect", "blocked", "verdict", "execution_status"],
)
def test_each_client_literal_is_the_server_literal(opening, annotation):
    assert _client_names(opening) == _literal(annotation)


def test_the_client_names_every_evidence_kind_and_refusal_code():
    source = _CLIENT_API.read_text(encoding="utf-8")
    kinds = _literal(
        history.ReleaseHistoryEvidenceResponse.model_fields["evidence_kind"].annotation
    )
    assert kinds == ["approval", "historical_restore"]
    assert (
        "export type ReleaseEvidenceKind = 'approval' | 'historical_restore';" in source
    )
    for kind in kinds:
        assert f"if (value.evidence_kind === '{kind}') return" in source, kind
    for model in _CONTRACT:
        if "code" in model.model_fields:
            (code,) = get_args(model.model_fields["code"].annotation)
            # The type, the parser's case and the state's failure mapping.
            assert source.count(f"'{code}'") >= 2, code


def test_the_client_draft_effect_labels_cover_exactly_the_server_vocabulary():
    source = _CLIENT_STATE.read_text(encoding="utf-8")
    opening = "\nexport const DRAFT_EFFECT_LABELS: Record<DraftEffect, string> = {"
    assert source.count(opening) == 1
    start = source.index(opening) + len(opening)
    block = source[start : source.index("\n}", start)]
    pairs = re.findall(r"^\s+([a-z_]+): '([^'\\\n]+)',$", block, re.MULTILINE)
    assert [key for key, _ in pairs] == list(get_args(history.DraftEffectWire))
    # Ruling Q7's labels (the #270 ledger).
    assert dict(pairs) == {
        "reset": "Reset to restored content",
        "kept": "Pending edit kept",
        "unchanged": "Unchanged",
    }


def test_the_client_routes_are_the_mounted_routes():
    from src.api.main import app

    mounted = {
        (method, getattr(route, "path", None))
        for route in app.routes
        for method in getattr(route, "methods", set())
    }
    prefix = "/api/admin/agent-definitions/releases"
    for method, path in (
        ("GET", prefix),
        ("GET", f"{prefix}/{{version_number}}"),
        ("GET", f"{prefix}/{{version_number}}/comparison"),
        ("GET", f"{prefix}/{{version_number}}/rollback-preview"),
        ("POST", f"{prefix}/{{version_number}}/rollback"),
    ):
        assert (method, path) in mounted, (method, path)
    source = _CLIENT_API.read_text(encoding="utf-8")
    assert "return `${RELEASES_URL}/${versionNumber}${suffix}`;" in source
    for suffix in ("'/comparison'", "'/rollback-preview'", "'/rollback'"):
        assert f"releaseVersionUrl(versionNumber, {suffix})" in source, suffix
    assert "getStrict(releaseVersionUrl(versionNumber), parseReleaseDetailResponse)" in source
    assert "getStrict(RELEASES_URL, parseReleaseHistoryListResponse)" in source

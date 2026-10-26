"""Join the client's Graph Release preview/publication contract to the server's (#269 Task 6).

The wire is owned by ``src/api/schemas/graph_releases.py`` (Task 5) and embeds #268's
readiness and the existing ``ActiveReleaseResponse`` / ``DraftMetadataResponse``. The
client holds hand copies in ``frontend/src/api/agentDefinitions.ts`` that nothing
typechecks against the server, so this module reads them as text, as
``test_draft_readiness_client_join.py`` does.

Text-read rules for those lines (keep them, or this join cannot read them):

* Each ``const <NAME>_KEYS = [`` opening below, ``export const RELEASE_DIFF_FIELDS = [``
  and ``const PUBLICATION_GAP_CODES: readonly PublicationGapCode[] = [`` appears exactly
  once and lists single-quoted names up to the closing ``]``.
* ``export const RELEASE_NOTE_MAX_LENGTH = <int>;`` is one line.
* In ``reviewAndPublishState.ts``, ``export const ROLE_LABELS`` lists one
  ``key: 'Label',`` pair per line up to its closing ``}``.
* In ``mocks.ts``, ``RELEASE_NOTE_BLANK_ERROR`` keeps its single-quoted triple.

Gap codes and 422 issue codes are snake_case codes with no server message table: the
client owns every label (Correction 1; Task 5 concerns 1-2).
"""

from __future__ import annotations

import pathlib
import re
from typing import get_args

import pytest

from src.api.schemas import agent_definitions as base_schemas
from src.api.schemas import graph_releases as schemas
from src.services import graph_configuration_publication as publication
from src.services import graph_configuration_workbench as workbench
from src.services.graph_definition_manifest import GRAPH_V1_AGENT_KEYS

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CLIENT_API = _REPO_ROOT / "frontend" / "src" / "api" / "agentDefinitions.ts"
_CLIENT_STATE = (
    _REPO_ROOT
    / "frontend"
    / "src"
    / "components"
    / "Admin"
    / "GraphRelease"
    / "reviewAndPublishState.ts"
)
_CLIENT_MOCKS = _REPO_ROOT / "frontend" / "tests" / "fixtures" / "mocks.ts"
_QUOTED = re.compile(r"'([^'\\\n]*)'")
_SNAKE_CASE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")


def _read(path: pathlib.Path) -> str:
    assert path.is_file(), f"client source missing: {path}"
    return path.read_text(encoding="utf-8")


def _block(source: str, opening: str, closing: str) -> str:
    assert source.count(opening) == 1, f"expected exactly one {opening.strip()!r}"
    start = source.index(opening) + len(opening)
    return source[start : source.index(closing, start)]


def _names(opening: str) -> list[str]:
    names = _QUOTED.findall(_block(_read(_CLIENT_API), opening, "]"))
    assert names, f"no names under {opening.strip()!r}"
    assert len(names) == len(set(names)), names
    return names


#: Every strict model the release client parses or sends, and its client key list.
_KEY_LISTS = (
    (schemas.ReleasePreviewResponse, "\nconst RELEASE_PREVIEW_KEYS = ["),
    (schemas.ChangedDefinitionResponse, "\nconst CHANGED_DEFINITION_KEYS = ["),
    (schemas.FieldDiffResponse, "\nconst FIELD_DIFF_KEYS = ["),
    (schemas.PublishReleaseRequest, "\nconst PUBLISH_RELEASE_REQUEST_KEYS = ["),
    (schemas.PublishReleaseSuccessResponse, "\nconst PUBLISH_RELEASE_SUCCESS_KEYS = ["),
    (schemas.PublishedMappingResponse, "\nconst PUBLISHED_MAPPING_KEYS = ["),
    (schemas.ReleaseEvidenceResponse, "\nconst RELEASE_EVIDENCE_KEYS = ["),
    (schemas.ReleaseIdentityResponse, "\nconst RELEASE_IDENTITY_KEYS = ["),
    (schemas.StalePublicationResponse, "\nconst STALE_PUBLICATION_KEYS = ["),
    (schemas.NothingToPublishResponse, "\nconst NOTHING_TO_PUBLISH_KEYS = ["),
    (schemas.PublicationNotReadyResponse, "\nconst PUBLICATION_NOT_READY_KEYS = ["),
    (schemas.PublicationGapResponse, "\nconst PUBLICATION_GAP_KEYS = ["),
    (schemas.PublicationValidationErrorResponse, "\nconst PUBLICATION_VALIDATION_KEYS = ["),
    (base_schemas.ActiveReleaseResponse, "\nconst ACTIVE_RELEASE_KEYS = ["),
)


@pytest.mark.parametrize(
    ("model", "opening"), _KEY_LISTS, ids=[model.__name__ for model, _ in _KEY_LISTS]
)
def test_each_client_key_list_is_exactly_the_server_model(model, opening) -> None:
    client = _names(opening)
    # Order too: the lists mirror the server models field for field.
    assert client == list(model.model_fields), model.__name__
    for name in client:
        assert _SNAKE_CASE.match(name), name


def test_every_release_model_the_client_mirrors_forbids_extra_keys() -> None:
    # The TS parsers are exact-key; that only mirrors the server if the server is too.
    for model, _opening in _KEY_LISTS:
        if model is base_schemas.ActiveReleaseResponse:
            continue
        assert model.model_config.get("extra") == "forbid", model.__name__


def test_the_client_diff_fields_are_the_server_literal_in_order() -> None:
    client = _names("\nexport const RELEASE_DIFF_FIELDS = [")
    assert client == list(get_args(schemas.DiffFieldName))
    assert client == list(publication.DIFF_FIELD_NAMES)


def test_the_client_gap_codes_are_the_server_literal() -> None:
    client = _names("\nconst PUBLICATION_GAP_CODES: readonly PublicationGapCode[] = [")
    assert client == list(get_args(schemas.PublicationGapCodeWire))
    assert set(client) == {"no_required_case", "no_eligible_approval"}


def test_the_client_refusal_codes_are_the_server_literals() -> None:
    source = _read(_CLIENT_API)
    for model in (
        schemas.StalePublicationResponse,
        schemas.NothingToPublishResponse,
        schemas.PublicationNotReadyResponse,
        schemas.PublicationValidationErrorResponse,
    ):
        (code,) = get_args(model.model_fields["code"].annotation)
        assert source.count(f"'{code}'") >= 2, code  # the type and the parser
    # #270 C38: the evidence item carries both kinds; the client checks each one
    # (and publication's approval-only rule) by name.
    kinds = get_args(
        schemas.ReleaseEvidenceResponse.model_fields["evidence_kind"].annotation
    )
    assert set(kinds) == {"approval", "historical_restore"}
    for kind in kinds:
        assert f"evidence_kind === '{kind}'" in source, kind


def test_the_client_note_cap_is_the_service_cap() -> None:
    line = re.search(
        r"^export const RELEASE_NOTE_MAX_LENGTH = (\d+);$",
        _read(_CLIENT_API),
        re.MULTILINE,
    )
    assert line is not None
    assert int(line.group(1)) == publication.RELEASE_NOTE_MAX_LENGTH == 2000


def test_the_client_routes_are_the_mounted_routes() -> None:
    from src.api.main import app

    paths = {getattr(route, "path", None) for route in app.routes}
    source = _read(_CLIENT_API)
    for suffix in ("release-preview", "releases"):
        assert f"/api/admin/agent-definitions/{suffix}" in paths, suffix
        assert f"`${{AGENT_DEFINITIONS_URL}}/{suffix}`" in source, suffix


def test_the_client_role_labels_are_the_workbench_display_names() -> None:
    block = _block(_read(_CLIENT_STATE), "\nexport const ROLE_LABELS", "\n}")
    pairs = re.findall(r"^\s+([a-z_]+): '([^'\\\n]+)',$", block, re.MULTILINE)
    assert [key for key, _ in pairs] == list(GRAPH_V1_AGENT_KEYS)
    assert dict(pairs) == {key: workbench._DISPLAY_NAMES[key] for key in GRAPH_V1_AGENT_KEYS}


def test_the_served_blank_note_fixture_is_the_service_triple() -> None:
    block = _block(
        _read(_CLIENT_MOCKS), "\nexport const RELEASE_NOTE_BLANK_ERROR", "\n};"
    )
    issue = publication._BLANK_NOTE
    for value in (issue.field, issue.code, issue.message):
        assert f"'{value}'" in block, value

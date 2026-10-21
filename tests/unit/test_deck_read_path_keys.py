"""B3.2: ``get_slide_deck`` serves ``deck_spec`` and ``findings`` on ALL THREE
of its dict-returning read paths.

Why three, not two.  ``SessionManager.get_slide_deck`` returns a dict in three
distinct places:

  1. the ROW-READ path      — ``session_slides`` rows exist, dict built from columns
  2. the DECK_JSON BLOB path — no rows, ``deck_json`` populated, dict parsed from it
  3. the LEGACY fallback     — no rows and no ``deck_json``; NO ``slides`` array

Adding the keys to only two of them is the defect this file exists to catch: a
deck whose ``deck_json`` happens to be populated would then return ``undefined``
for both keys, and which path a deck takes is invisible to its consumer.

Every test drives the real ``SessionManager`` against a real in-memory SQLite
database through the shared fixtures — no mock of the read path, because a mock
cannot tell you which of the three branches ran.

THE KEY-SET BASELINES BELOW ARE MEASURED, not asserted from the source: each was
printed from ``get_slide_deck()`` on this branch BEFORE the two keys were added.
They are the parity guarantee the export chain and every ``html_content``
consumer depend on — adding these two keys must change no other key.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from src.api.services.session_manager import SessionManager
from src.domain.finding import (
    VERDICT_KEY,
    Finding,
    build_verification_record,
    make_finding_id,
)
from src.domain.finding_copy import (
    FIXED_AUTOMATICALLY,
    NOT_FIXED_AUTOMATICALLY,
    PLAIN_ISSUES,
)
from src.utils.slide_hash import compute_slide_hash
from tests.unit.test_finding_copy import ISSUE_316_MESSAGE

# ---------------------------------------------------------------------------
# Measured pre-change key sets (see module docstring).
#
# ``html_content`` is deliberately absent from the row-read and blob baselines:
# both paths add it only ``if deck.html_content`` is truthy, and these fixtures
# store "".  The legacy path emits it unconditionally, so it IS in that baseline.
# ---------------------------------------------------------------------------

_ROW_BASELINE_KEYS = {
    "created_at",
    "created_by",
    "css",
    "external_scripts",
    "head_meta",
    "modified_at",
    "modified_by",
    "scripts",
    "slide_count",
    "slides",
    "title",
    "version",
}

# Measured identical to the row-read baseline — that is the F5 parity the
# existing head_meta setdefault was written to preserve.
_BLOB_BASELINE_KEYS = set(_ROW_BASELINE_KEYS)

_LEGACY_BASELINE_KEYS = {
    "created_at",
    "created_by",
    "html_content",
    "modified_at",
    "modified_by",
    "scripts_content",
    "slide_count",
    "title",
    "version",
}

_NEW_KEYS = {"deck_spec", "findings"}

# Measured pre-change per-slide key set on the row-read path.
_ROW_SLIDE_BASELINE_KEYS = {
    "content_hash",
    "created_at",
    "created_by",
    "html",
    "index",
    "modified_at",
    "modified_by",
    "scripts",
    "slide_id",
    "verification",
}

# The frontend SlideFinding declaration, field for field.  ``plainMessage`` and
# ``plainIssue`` are derived by the read path (#316), not Finding fields; see
# PROJECTION_ONLY_FIELDS in tests/unit/test_finding_conformance.py.
_SLIDE_FINDING_KEYS = {
    "id",
    "slideIndex",
    "category",
    "criterion",
    "message",
    "objective",
    "status",
    "seen",
    "plainMessage",
    "plainIssue",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _findings_for(html: str, slide_index: int, count: int = 2) -> List[Finding]:
    """Build *count* real, registry-valid findings for the slide with *html*."""
    content_hash = compute_slide_hash(html)
    return [
        Finding(
            id=make_finding_id("overflow", content_hash, ordinal),
            slide_index=slide_index,
            category="design",
            criterion="overflow",
            message=f"Content overflows the frame ({ordinal}).",
            objective=True,
        )
        for ordinal in range(count)
    ]


def _write_findings(fixture: Any, session_id: str, position: int, html: str, count: int = 2) -> None:
    """Persist *count* findings for *html* through the production writer.

    ``SessionManager.write_slide_verification`` is the only writer of the blobs
    the read path reads back, so driving it means these tests assert against a
    record shape production actually produces rather than one invented here.

    ``fixture._patched()`` is used deliberately: the shared fixtures' public
    surface is a frozen contract with no findings writer on it, and that base
    class context manager is the documented way to point ``SessionManager`` at a
    fixture's own engine.  Nothing is added to the fixtures themselves.
    """
    record = build_verification_record(
        content_hash=compute_slide_hash(html),
        findings=_findings_for(html, position, count),
        verdict="surfaced",
    )
    with fixture._patched():
        SessionManager().write_slide_verification(
            session_id=session_id,
            position=position,
            verification_record=record,
        )


def _assert_flat_finding_list(findings: Any, context: str) -> None:
    """Assert *findings* is a FLAT list of SlideFinding-shaped dicts.

    The failure this guards is emitting a ``{position: [...]}`` index instead of
    one deck-level list: the drawer holds a single flat list and filters it by
    ``slideIndex``, and the legacy read path has no ``slides`` array to key a
    position index against.
    """
    assert isinstance(findings, list), (
        f"{context}: findings must be a FLAT list, got {type(findings).__name__}. "
        f"A per-position dict/index is exactly the shape the drawer cannot consume."
    )
    for entry in findings:
        assert isinstance(entry, dict), (
            f"{context}: every findings entry must be a dict, got {type(entry).__name__}"
        )
        assert "slideIndex" in entry, (
            f"{context}: findings entry {entry!r} carries no slideIndex — the entry's "
            f"own slideIndex is what makes a flat deck-level list possible."
        )
        assert isinstance(entry["slideIndex"], int), (
            f"{context}: slideIndex must be an int, got {entry['slideIndex']!r}"
        )
        assert set(entry) == _SLIDE_FINDING_KEYS, (
            f"{context}: findings entry keys {sorted(entry)} != the declared "
            f"SlideFinding fields {sorted(_SLIDE_FINDING_KEYS)}"
        )


# ---------------------------------------------------------------------------
# PATH 1 — the row-read path
# ---------------------------------------------------------------------------


class TestRowReadPath:
    """Slide rows exist, so the deck dict is built from the deck-level columns."""

    def test_both_keys_present_and_parsed(self, deck_with_spec):
        rows = deck_with_spec.rows()
        _write_findings(deck_with_spec, deck_with_spec.session_id, 0, rows[0].html, count=2)

        result = deck_with_spec.get_slide_deck()

        assert result is not None
        # Proof this is the row path and not a blob read: the rows are the source.
        assert len(result["slides"]) == len(rows) == 3

        assert isinstance(result["deck_spec"], dict), (
            f"deck_spec was not parsed into an object: {result['deck_spec']!r}"
        )
        assert result["deck_spec"]["audience"] == "Test audience"
        assert result["deck_spec"]["title"] == "Test Deck"

        assert len(result["findings"]) == 2, (
            f"expected the 2 written findings, got {result['findings']!r}"
        )
        _assert_flat_finding_list(result["findings"], "row-read path")
        assert {f["slideIndex"] for f in result["findings"]} == {0}
        assert {f["criterion"] for f in result["findings"]} == {"overflow"}

    def test_specless_deck_reports_deck_spec_as_none_not_absent(self, deck_with_three_rows):
        """A deck with no deck_spec_json must still EMIT the key, valued None."""
        result = deck_with_three_rows.get_slide_deck()

        assert deck_with_three_rows.deck_row().deck_spec_json is None
        assert "deck_spec" in result, (
            "row-read path omitted deck_spec for a specless deck — the consumer "
            "would see undefined rather than a null spec"
        )
        assert result["deck_spec"] is None

    def test_findingless_deck_reports_findings_as_empty_list(self, deck_with_verdicts):
        """Verification present but no findings in it: [] , never absent.

        ``deck_with_verdicts`` writes score/rating verdicts with no findings
        payload, which is also the pre-LangGraph record shape — so this covers
        both "no verification at all" and "verification without findings".
        """
        result = deck_with_verdicts.get_slide_deck()

        assert result["slides"][0]["verification"] is not None, (
            "fixture precondition: a verdict should be present on slide 0"
        )
        assert "findings" in result, "row-read path omitted findings"
        assert result["findings"] == []

    def test_unparseable_deck_spec_json_reports_none_and_does_not_raise(self, deck_with_spec):
        deck_with_spec.set_raw_deck_spec_json("{ this is not json")

        result = deck_with_spec.get_slide_deck()

        assert result is not None, "a malformed spec blob must not fail the deck read"
        assert result["deck_spec"] is None, (
            f"unparseable deck_spec_json must degrade to None, got {result['deck_spec']!r}"
        )
        # The rest of the deck is untouched by the bad spec.
        assert len(result["slides"]) == 3

    def test_deck_spec_json_that_is_not_an_object_reports_none(self, deck_with_spec):
        deck_with_spec.set_raw_deck_spec_json(json.dumps(["not", "an", "object"]))

        assert deck_with_spec.get_slide_deck()["deck_spec"] is None

    def test_corrupt_verification_record_yields_no_findings_and_does_not_raise(
        self, deck_with_spec
    ):
        rows = deck_with_spec.rows()
        _write_findings(deck_with_spec, deck_with_spec.session_id, 0, rows[0].html, count=1)
        assert len(deck_with_spec.get_slide_deck()["findings"]) == 1

        # Corrupt the record the same way a truncated write would.
        row_html = rows[1].html
        record = build_verification_record(
            content_hash=compute_slide_hash(row_html),
            findings=_findings_for(row_html, 1, 1),
            verdict="surfaced",
        )
        del record[compute_slide_hash(row_html)]["tellr_review"]["findings"]
        with deck_with_spec._patched():
            SessionManager().write_slide_verification(
                session_id=deck_with_spec.session_id, position=1, verification_record=record
            )

        result = deck_with_spec.get_slide_deck()
        assert result is not None
        assert len(result["findings"]) == 1, (
            f"a findings-less record must contribute nothing, got {result['findings']!r}"
        )

    def test_adding_the_keys_changes_no_other_key(self, deck_with_spec):
        """Full key set, before and after, on the row-read path."""
        result = deck_with_spec.get_slide_deck()

        assert set(result) == _ROW_BASELINE_KEYS | _NEW_KEYS, (
            f"row-read key set drifted.\n"
            f"  unexpectedly added:   {sorted(set(result) - (_ROW_BASELINE_KEYS | _NEW_KEYS))}\n"
            f"  unexpectedly missing: {sorted((_ROW_BASELINE_KEYS | _NEW_KEYS) - set(result))}"
        )

    def test_per_slide_key_set_is_untouched(self, deck_with_spec):
        """``findings`` is deck-level and additive: no slide gains or loses a key.

        ``verification`` stays canonical and per-slide; ``findings`` is a
        projection of the same blobs, so nothing collides.
        """
        rows = deck_with_spec.rows()
        _write_findings(deck_with_spec, deck_with_spec.session_id, 0, rows[0].html, count=1)

        result = deck_with_spec.get_slide_deck()

        for slide in result["slides"]:
            assert set(slide) == _ROW_SLIDE_BASELINE_KEYS, (
                f"per-slide key set drifted: "
                f"added {sorted(set(slide) - _ROW_SLIDE_BASELINE_KEYS)}, "
                f"missing {sorted(_ROW_SLIDE_BASELINE_KEYS - set(slide))}"
            )
            assert "findings" not in slide, (
                "findings must be ONE deck-level list, not a per-slide key"
            )


# ---------------------------------------------------------------------------
# PATH 2 — the deck_json blob fallback (the path the brief missed)
# ---------------------------------------------------------------------------


class TestBlobFallbackPath:
    """No slide rows, ``deck_json`` populated: the dict is parsed from the blob."""

    def test_both_keys_are_exposed(self, deck_with_spec_but_no_rows):
        result = deck_with_spec_but_no_rows.get_slide_deck()

        assert result is not None
        # Proof of path: this fixture has NO SessionSlide rows, so three slides
        # in the result can only have come from the deck_json blob.
        assert len(result["slides"]) == 3
        assert result["title"] == "Spec-Only Deck"

        assert "deck_spec" in result and "findings" in result, (
            "the deck_json blob path omitted a key — a deck whose blob is "
            "populated would return undefined for it"
        )
        assert result["deck_spec"]["audience"] == "Test audience"
        assert result["findings"] == []

    def test_findings_are_served_from_the_blob_path(self, deck_with_spec_but_no_rows):
        """Findings written for a row-less session land in the deck's
        verification_map, and the blob path must read them back."""
        fixture = deck_with_spec_but_no_rows
        html = fixture.get_slide_deck()["slides"][1]["html"]
        _write_findings(fixture, fixture.session_id, 1, html, count=3)

        result = fixture.get_slide_deck()

        assert len(result["findings"]) == 3, (
            f"blob path served {result['findings']!r} — findings written for a "
            f"row-less session go to the deck-level verification_map, which is "
            f"the record this path must consult"
        )
        _assert_flat_finding_list(result["findings"], "deck_json blob path")
        assert {f["slideIndex"] for f in result["findings"]} == {1}

    def test_specless_blob_deck_reports_deck_spec_as_none(self, deck_with_spec_but_no_rows):
        """Blank the column and the key must still be there, valued None.

        This is also the regression guard for using ``setdefault`` here: the blob
        path re-persists its own dict, so a ``setdefault`` would serve a stale
        spec out of ``deck_json`` and never notice the column had changed.
        """
        fixture = deck_with_spec_but_no_rows
        assert fixture.get_slide_deck()["deck_spec"] is not None

        _blank_deck_spec(fixture)

        result = fixture.get_slide_deck()
        assert "deck_spec" in result
        assert result["deck_spec"] is None, (
            "the blob path served a stale deck_spec after the column was cleared"
        )

    def test_adding_the_keys_changes_no_other_key(self, deck_with_spec_but_no_rows):
        result = deck_with_spec_but_no_rows.get_slide_deck()

        assert set(result) == _BLOB_BASELINE_KEYS | _NEW_KEYS, (
            f"deck_json blob key set drifted.\n"
            f"  unexpectedly added:   "
            f"{sorted(set(result) - (_BLOB_BASELINE_KEYS | _NEW_KEYS))}\n"
            f"  unexpectedly missing: "
            f"{sorted((_BLOB_BASELINE_KEYS | _NEW_KEYS) - set(result))}"
        )

    def test_derived_keys_are_not_persisted_into_deck_json(self, deck_with_spec_but_no_rows):
        """The blob path may re-dump its dict into ``deck_json``; the two derived
        keys must not be baked in there, or a later read could serve a stale copy."""
        fixture = deck_with_spec_but_no_rows
        fixture.get_slide_deck()

        stored = _stored_deck_json(fixture)
        assert "deck_spec" not in stored, "deck_spec was persisted into deck_json"
        assert "findings" not in stored, "findings were persisted into deck_json"


# ---------------------------------------------------------------------------
# PATH 3 — the legacy fallback (no rows, no deck_json, no slides array)
# ---------------------------------------------------------------------------


class TestLegacyFallbackPath:
    """Reachable on a live session: a deck row written before any slides exist."""

    def test_both_keys_are_exposed_without_a_slides_array(self, contributor_session_with_spec):
        result = contributor_session_with_spec.get_slide_deck_as_contributor()

        assert result is not None
        # Proof of path: the legacy fallback is the only branch with no slides.
        assert "slides" not in result, (
            f"expected the legacy fallback (no slides array), got keys {sorted(result)}"
        )

        assert "deck_spec" in result and "findings" in result, (
            "the legacy fallback omitted a key — this is the path a session takes "
            "on its first read, before any slide rows exist"
        )
        assert result["deck_spec"]["audience"] == "Test audience"
        assert result["findings"] == []

    def test_findings_are_served_with_no_slides_array_to_index_against(
        self, contributor_session_with_spec
    ):
        """The flat list is what makes findings servable here at all."""
        fixture = contributor_session_with_spec
        html = "<div class='slide'><h1>Legacy</h1></div>"
        _write_findings(fixture, fixture.contributor_session_id, 0, html, count=2)

        result = fixture.get_slide_deck_as_contributor()

        assert "slides" not in result
        assert len(result["findings"]) == 2, (
            f"legacy path served {result['findings']!r}; findings for a session "
            f"with no rows live in the deck-level verification_map"
        )
        _assert_flat_finding_list(result["findings"], "legacy fallback path")

    def test_specless_legacy_deck_reports_deck_spec_as_none(self, contributor_session):
        """``contributor_session`` has no deck_spec_json at all."""
        fixture = contributor_session
        assert fixture.owner_deck_row().deck_spec_json is None

        with fixture._patched():
            result = SessionManager().get_slide_deck(fixture.contributor_session_id)

        assert "slides" not in result, "expected the legacy fallback"
        assert "deck_spec" in result and result["deck_spec"] is None
        assert "findings" in result and result["findings"] == []

    def test_adding_the_keys_changes_no_other_key(self, contributor_session_with_spec):
        result = contributor_session_with_spec.get_slide_deck_as_contributor()

        assert set(result) == _LEGACY_BASELINE_KEYS | _NEW_KEYS, (
            f"legacy fallback key set drifted.\n"
            f"  unexpectedly added:   "
            f"{sorted(set(result) - (_LEGACY_BASELINE_KEYS | _NEW_KEYS))}\n"
            f"  unexpectedly missing: "
            f"{sorted((_LEGACY_BASELINE_KEYS | _NEW_KEYS) - set(result))}"
        )


# ---------------------------------------------------------------------------
# §7.5 — spec and findings visibility equals deck visibility
# ---------------------------------------------------------------------------


class TestContributorSeesTheOwnersSpecAndFindings:

    def test_contributor_read_carries_the_owners_spec(self, contributor_session_with_spec):
        fixture = contributor_session_with_spec
        owner_spec = json.loads(fixture.owner_deck_row().deck_spec_json)

        result = fixture.get_slide_deck_as_contributor()

        assert result["deck_spec"] == owner_spec, (
            "the contributor did not receive the OWNER's spec — parent_session_id "
            "resolution reached a different deck, or the key was rebuilt locally"
        )

    def test_contributor_read_carries_the_owners_findings(self, contributor_session_with_spec):
        fixture = contributor_session_with_spec
        html = "<div class='slide'><h1>Owner deck</h1></div>"
        _write_findings(fixture, fixture.contributor_session_id, 0, html, count=1)

        result = fixture.get_slide_deck_as_contributor()

        assert len(result["findings"]) == 1
        _assert_flat_finding_list(result["findings"], "contributor read")
        # The finding really is on the owner's deck row, not the contributor's.
        assert fixture.owner_deck_row().verification_map is not None


# ---------------------------------------------------------------------------
# Cross-path: the shape of the two keys does not depend on which path ran
# ---------------------------------------------------------------------------


class TestAllThreePathsAgree:

    def test_no_path_ever_omits_either_key(
        self,
        deck_with_three_rows,
        deck_with_spec_but_no_rows,
        contributor_session_with_spec,
    ):
        """One test, three paths, one requirement: neither key is EVER absent."""
        reads = {
            "row-read": deck_with_three_rows.get_slide_deck(),
            "deck_json blob": deck_with_spec_but_no_rows.get_slide_deck(),
            "legacy fallback": contributor_session_with_spec.get_slide_deck_as_contributor(),
        }
        # Guard that the three fixtures really did take three different paths.
        assert "slides" in reads["row-read"]
        assert "slides" in reads["deck_json blob"]
        assert "slides" not in reads["legacy fallback"]

        missing = {
            name: sorted(_NEW_KEYS - set(result))
            for name, result in reads.items()
            if _NEW_KEYS - set(result)
        }
        assert not missing, (
            f"these read paths omit keys, so a consumer sees undefined: {missing}"
        )

        for name, result in reads.items():
            assert result["deck_spec"] is None or isinstance(result["deck_spec"], dict), (
                f"{name}: deck_spec must be None or a dict, got {result['deck_spec']!r}"
            )
            _assert_flat_finding_list(result["findings"], name)


# ---------------------------------------------------------------------------
# #316 — every read path derives the plain-language keys, at read time only
# ---------------------------------------------------------------------------

#: ``_write_findings`` stores open, objective ``overflow`` findings, so each one
#: must read as the present-tense overflow sentence plus the "not fixed
#: automatically" status sentence.  Composed from the copy module's constants,
#: never from the helpers that derive them.
EXPECTED_MESSAGE = f"{PLAIN_ISSUES['overflow'].present} {NOT_FIXED_AUTOMATICALLY}"
EXPECTED_ISSUE = PLAIN_ISSUES["overflow"].present

#: Every spelling a write-back of the derived keys could take.
_PLAIN_KEY_SPELLINGS = ("plainMessage", "plain_message", "plainIssue", "plain_issue")


def _write_record(fixture: Any, session_id: str, position: int, record: Dict[str, Any]) -> None:
    """Persist a hand-built verification record through the production writer."""
    with fixture._patched():
        SessionManager().write_slide_verification(
            session_id=session_id,
            position=position,
            verification_record=record,
        )


class TestPlainMessage:
    """``plainMessage`` / ``plainIssue`` on every path; ``message`` untouched."""

    @staticmethod
    def _assert_plain_overflow(findings: List[Dict[str, Any]], html: str, position: int,
                               count: int, context: str) -> None:
        expected_messages = [f.message for f in _findings_for(html, position, count)]
        assert [f["message"] for f in findings] == expected_messages, (
            f"{context}: the reviewer's message must reach the frontend unchanged; "
            f"got {[f['message'] for f in findings]!r}"
        )
        for entry in findings:
            assert entry["plainMessage"] == EXPECTED_MESSAGE, f"{context}: {entry!r}"
            assert entry["plainIssue"] == EXPECTED_ISSUE, f"{context}: {entry!r}"

    def test_row_read_path_derives_the_plain_keys(self, deck_with_spec):
        rows = deck_with_spec.rows()
        _write_findings(deck_with_spec, deck_with_spec.session_id, 0, rows[0].html, count=2)

        result = deck_with_spec.get_slide_deck()

        assert len(result["slides"]) == 3, "expected the row-read path"
        self._assert_plain_overflow(result["findings"], rows[0].html, 0, 2, "row-read path")

    def test_blob_path_derives_the_plain_keys(self, deck_with_spec_but_no_rows):
        fixture = deck_with_spec_but_no_rows
        html = fixture.get_slide_deck()["slides"][1]["html"]
        _write_findings(fixture, fixture.session_id, 1, html, count=2)

        result = fixture.get_slide_deck()

        self._assert_plain_overflow(result["findings"], html, 1, 2, "deck_json blob path")

    def test_legacy_fallback_derives_the_plain_keys(self, contributor_session_with_spec):
        """Also the shared-deck contributor read: the owner's findings, plain."""
        fixture = contributor_session_with_spec
        html = "<div class='slide'><h1>Legacy</h1></div>"
        _write_findings(fixture, fixture.contributor_session_id, 0, html, count=2)

        result = fixture.get_slide_deck_as_contributor()

        assert "slides" not in result, "expected the legacy fallback"
        self._assert_plain_overflow(result["findings"], html, 0, 2, "legacy fallback path")

    def test_a_fixed_finding_reads_in_the_past_tense(self, deck_with_spec):
        """An auto-fixed objective finding: past-tense issue, "fixed automatically"."""
        rows = deck_with_spec.rows()
        content_hash = compute_slide_hash(rows[1].html)
        fixed = Finding(
            id=make_finding_id("contrast_failure", content_hash, 0),
            slide_index=1,
            category="design",
            criterion="contrast_failure",
            message=ISSUE_316_MESSAGE,
            objective=True,
            status="fixed",
        )
        _write_record(
            deck_with_spec,
            deck_with_spec.session_id,
            1,
            build_verification_record(
                content_hash=content_hash, findings=[fixed], verdict="fixed"
            ),
        )

        (entry,) = deck_with_spec.get_slide_deck()["findings"]

        assert entry["status"] == "fixed"
        assert entry["plainMessage"] == (
            f"{PLAIN_ISSUES['contrast_failure'].past} {FIXED_AUTOMATICALLY}"
        )
        assert entry["plainIssue"] == PLAIN_ISSUES["contrast_failure"].past
        assert entry["message"] == ISSUE_316_MESSAGE

    def test_a_record_written_before_plain_messages_existed_still_renders(self, deck_with_spec):
        """A record from an older writer (no ``status``, no ``seen``) needs no
        migration: the plain keys are derived on read, with the Finding defaults."""
        rows = deck_with_spec.rows()
        content_hash = compute_slide_hash(rows[0].html)
        legacy_record = {
            content_hash: {
                VERDICT_KEY: {
                    "verdict": "surfaced",
                    "findings": [
                        {
                            "id": f"contrast_failure:{content_hash}:0",
                            "slide_index": 0,
                            "category": "design",
                            "criterion": "contrast_failure",
                            "message": ISSUE_316_MESSAGE,
                            "objective": True,
                        }
                    ],
                }
            }
        }
        _write_record(deck_with_spec, deck_with_spec.session_id, 0, legacy_record)

        (entry,) = deck_with_spec.get_slide_deck()["findings"]

        assert entry["status"] == "open" and entry["seen"] is False
        assert entry["plainMessage"] == (
            f"{PLAIN_ISSUES['contrast_failure'].present} {NOT_FIXED_AUTOMATICALLY}"
        )
        assert entry["plainIssue"] == PLAIN_ISSUES["contrast_failure"].present
        assert entry["message"] == ISSUE_316_MESSAGE

    def test_the_plain_keys_are_never_written_back(
        self, deck_with_spec, deck_with_spec_but_no_rows
    ):
        """Derived on read, so never persisted under any spelling, in any store a
        read could write back to.  Each read first proves the keys WERE served,
        so the absence below is not just "the keys never existed"."""
        # Row path: findings live on the slide row's verification_record.
        rows = deck_with_spec.rows()
        _write_findings(deck_with_spec, deck_with_spec.session_id, 0, rows[0].html, count=2)
        served = deck_with_spec.get_slide_deck()["findings"]
        assert [f["plainMessage"] for f in served] == [EXPECTED_MESSAGE] * 2

        stored_record = deck_with_spec.rows()[0].verification_record
        assert stored_record, "row path: no verification_record was stored"
        for spelling in _PLAIN_KEY_SPELLINGS:
            assert spelling not in stored_record, (
                f"row path: {spelling!r} was written into verification_record"
            )

        # Blob path: findings live on the deck's verification_map; the blob path
        # can also re-dump its deck dict into deck_json.  Check both.
        fixture = deck_with_spec_but_no_rows
        html = fixture.get_slide_deck()["slides"][1]["html"]
        _write_findings(fixture, fixture.session_id, 1, html, count=2)
        served = fixture.get_slide_deck()["findings"]
        assert [f["plainMessage"] for f in served] == [EXPECTED_MESSAGE] * 2

        stored_deck_json = json.dumps(_stored_deck_json(fixture))
        stored_map = _stored_verification_map(fixture)
        assert stored_map, "blob path: no verification_map was stored"
        for spelling in _PLAIN_KEY_SPELLINGS:
            assert spelling not in stored_deck_json, (
                f"blob path: {spelling!r} was written into deck_json"
            )
            assert spelling not in stored_map, (
                f"blob path: {spelling!r} was written into verification_map"
            )


# ---------------------------------------------------------------------------
# Small raw-SQL-free DB helpers, kept out of the fixtures (frozen surface).
# ---------------------------------------------------------------------------


def _blank_deck_spec(fixture: Any) -> None:
    """Set the fixture deck's ``deck_spec_json`` to NULL through its own engine."""
    from src.database.models.session import SessionSlideDeck

    db = fixture._factory()
    try:
        deck = db.query(SessionSlideDeck).one()
        deck.deck_spec_json = None
        db.commit()
    finally:
        db.close()


def _stored_deck_json(fixture: Any) -> Dict[str, Any]:
    """Return the deck's persisted ``deck_json`` blob, parsed."""
    from src.database.models.session import SessionSlideDeck

    db = fixture._factory()
    try:
        raw = db.query(SessionSlideDeck).one().deck_json
        return json.loads(raw) if raw else {}
    finally:
        db.close()


def _stored_verification_map(fixture: Any) -> str:
    """Return the deck's persisted ``verification_map`` column, raw ('' if NULL)."""
    from src.database.models.session import SessionSlideDeck

    db = fixture._factory()
    try:
        return db.query(SessionSlideDeck).one().verification_map or ""
    finally:
        db.close()

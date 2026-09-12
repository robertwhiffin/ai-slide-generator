"""Tests for deck_review_store (B2.2) and Finding.slide_index stability (B2.2b).

Design decisions recorded here
--------------------------------
* ``get_deck_review`` takes an explicit ``digest`` argument so the test for
  "edit-then-revert finds the earlier verdict" can be driven with a plain
  SQLite engine, without SessionManager or any mock.  The production caller
  (architect_node) computes the digest from the current deck HTML before
  calling; ``_get_deck_owner_session`` is the right helper for resolving
  ``deck_id`` from a ``session_id`` string — but that is the caller's concern,
  not the store's.

* **HTML comment decision**: two decks differing only by an HTML comment SHARE
  a digest (comment removal is step 1 of ``normalize_html``).  This is a
  documented property of the normalisation, not a collision.  We ASSERT it as
  a property of the API so that a future change to the normalisation would
  require a deliberate test update.

Sabotage targets (run manually to verify red → restore → green)
----------------------------------------------------------------
1. ``sorted()`` the per-slide hashes before joining in ``compute_deck_digest``
   → ``test_digest_changes_on_reorder`` must go red.
2. Remove the UniqueConstraint from ``DeckReview.__table_args__``
   → ``test_resave_same_digest_updates_not_duplicates`` must fail with a
   duplicate row (count > 1).
3. Comment out ``table.create(...)`` in ``_migrate_deck_reviews``
   → all tests that use the ``session`` fixture go red with
   ``OperationalError: no such table: deck_reviews``.
   If they stay GREEN, the fixture is calling ``create_all`` — fix the
   fixture, not the migration.
"""
import json

import pytest
from sqlalchemy import create_engine, inspect as sa_inspect, text
from sqlalchemy.orm import sessionmaker

from src.database.models.deck_review import DeckReview
from src.database.models.session import SessionSlideDeck, SlideDeckVersion, UserSession
from src.domain.finding import (
    Finding,
    build_verification_record,
    findings_from_record,
    make_finding_id,
)
from src.services.deck_review_store import (
    compute_deck_digest,
    get_deck_review,
    save_deck_review,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _build_tables(engine) -> None:
    """Build deck_reviews via the migration helper ONLY.

    Parent tables (user_sessions, session_slide_decks, slide_deck_versions)
    are created explicitly so that FK references resolve.  deck_reviews itself
    is created ONLY through _migrate_deck_reviews — never via create_all —
    so that disabling the migration correctly reddens the tests (sabotage 3).
    """
    from src.core.database import _migrate_deck_reviews

    with engine.connect() as conn:
        # Parent tables — created explicitly, not via Base.metadata.create_all.
        UserSession.__table__.create(bind=conn, checkfirst=True)
        SessionSlideDeck.__table__.create(bind=conn, checkfirst=True)
        SlideDeckVersion.__table__.create(bind=conn, checkfirst=True)
        # The table under test — driven through the migration helper so that
        # sabotage (commenting out table.create inside the helper) reddens.
        _migrate_deck_reviews(conn, schema=None)
        conn.commit()

    # Assert loudly that the table exists — a fixture that yields an engine
    # with a missing table and no error is the PR1 defect this check guards
    # against (an idempotency test stayed green with its migration disabled).
    inspector = sa_inspect(engine)
    table_names = inspector.get_table_names()
    assert "deck_reviews" in table_names, (
        f"_migrate_deck_reviews did not create deck_reviews. "
        f"Tables present: {sorted(table_names)}"
    )


@pytest.fixture
def engine(tmp_path):
    eng = create_engine(
        f"sqlite:///{tmp_path / 'deck_review_test.sqlite'}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    _build_tables(eng)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def session(engine):
    SessionLocal = sessionmaker(bind=engine)
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session_and_deck(s):
    """Insert a minimal UserSession + SessionSlideDeck; return (user_sess, deck)."""
    user_sess = UserSession(session_id="test-session-001", created_by="tester")
    s.add(user_sess)
    s.flush()
    deck = SessionSlideDeck(session_id=user_sess.id, title="Test Deck")
    s.add(deck)
    s.flush()
    return user_sess, deck


def _arc_gap_finding(slide_index: int = -1, ordinal: int = 0) -> Finding:
    subject = "deck-subject"
    return Finding(
        id=make_finding_id("arc_gap", subject, ordinal),
        slide_index=slide_index,
        category="narrative",
        criterion="arc_gap",
        message="Narrative arc has a gap.",
        objective=False,
    )


# ---------------------------------------------------------------------------
# compute_deck_digest — pure, no DB
# ---------------------------------------------------------------------------


class TestComputeDeckDigest:
    def test_stable_for_identical_ordered_content(self):
        slides = ["<div>slide one</div>", "<div>slide two</div>"]
        assert compute_deck_digest(slides) == compute_deck_digest(slides)

    def test_same_slides_different_instances(self):
        a = ["<h1>Title</h1>", "<p>Body</p>"]
        b = ["<h1>Title</h1>", "<p>Body</p>"]
        assert compute_deck_digest(a) == compute_deck_digest(b)

    def test_digest_changes_on_reorder(self):
        """LOAD-BEARING — sabotage 1 (sorted hashes) must redden this."""
        slides = ["<div>slide one</div>", "<div>slide two</div>"]
        reversed_slides = list(reversed(slides))
        assert compute_deck_digest(slides) != compute_deck_digest(reversed_slides), (
            "Deck digest must encode slide order: a reorder changes the narrative "
            "arc and must invalidate the cached deck review."
        )

    def test_case_insensitive(self):
        """normalise_html lowercases — same content in different case → same digest."""
        lower = ["<div>hello world</div>"]
        upper = ["<DIV>HELLO WORLD</DIV>"]
        assert compute_deck_digest(lower) == compute_deck_digest(upper)

    def test_whitespace_runs_collapsed(self):
        """Multiple whitespace characters inside a token are collapsed to one space."""
        normal = ["<div>hello world</div>"]
        spaced = ["<div>hello   world</div>"]
        assert compute_deck_digest(normal) == compute_deck_digest(spaced)

    def test_inter_token_whitespace_not_removed(self):
        """
        Inter-token whitespace is NOT fully removed — only runs are collapsed.

        "<div>  a  </div>" normalises to "<div> a </div>" (one space around 'a'),
        while "<div>a</div>" normalises to "<div>a</div>" (no space). They differ.
        Do NOT assert equality here; assert the difference.
        """
        with_spaces = ["<div>  a  </div>"]
        without_spaces = ["<div>a</div>"]
        assert compute_deck_digest(with_spaces) != compute_deck_digest(without_spaces), (
            "Inter-token whitespace is not removed — only runs are collapsed to one "
            "space. These two strings normalise differently."
        )

    def test_html_comment_equality(self):
        """
        Two decks differing only by HTML comments share a digest.

        HTML comments are stripped in step 1 of normalize_html (before any
        whitespace collapse), so a comment-only difference is invisible to the
        digest.  We ASSERT this as a property of the API so that a future
        change to normalisation would require a deliberate test update.
        """
        without_comment = ["<div>content</div>"]
        with_comment = ["<div><!-- reviewer note -->content</div>"]
        assert compute_deck_digest(without_comment) == compute_deck_digest(with_comment), (
            "Two decks differing only by HTML comments must share a digest "
            "(comments are stripped before hashing)."
        )

    def test_different_content_differs(self):
        a = ["<div>slide one</div>"]
        b = ["<div>slide two</div>"]
        assert compute_deck_digest(a) != compute_deck_digest(b)

    def test_returns_16_hex_chars(self):
        digest = compute_deck_digest(["<div>test</div>"])
        assert len(digest) == 16
        assert all(c in "0123456789abcdef" for c in digest)

    def test_empty_list(self):
        """Empty deck produces a stable digest (not an error)."""
        d1 = compute_deck_digest([])
        d2 = compute_deck_digest([])
        assert d1 == d2


# ---------------------------------------------------------------------------
# save_deck_review / get_deck_review — require DB
# ---------------------------------------------------------------------------


class TestSaveGetRoundtrip:
    def test_basic_roundtrip(self, session):
        _, deck = _make_session_and_deck(session)
        slides = ["<div>slide one</div>", "<div>slide two</div>"]
        digest = compute_deck_digest(slides)
        findings = [_arc_gap_finding()]

        save_deck_review(session, deck.id, digest, findings, author="deck_reviewer")
        session.commit()

        result = get_deck_review(session, deck.id, digest)
        assert result is not None
        assert result["digest"] == digest
        assert result["author"] == "deck_reviewer"
        assert len(result["findings"]) == 1
        assert result["findings"][0].criterion == "arc_gap"

    def test_returns_none_for_unknown_digest(self, session):
        _, deck = _make_session_and_deck(session)
        result = get_deck_review(session, deck.id, "nonexistentdigest0")
        assert result is None

    def test_findings_serialised_and_deserialised(self, session):
        _, deck = _make_session_and_deck(session)
        slides = ["<div>S1</div>"]
        digest = compute_deck_digest(slides)
        f = Finding(
            id=make_finding_id("missing_conclusion", "deck-subject", 0),
            slide_index=-1,
            category="narrative",
            criterion="missing_conclusion",
            message="No conclusion slide.",
            objective=False,
            status="open",
        )
        save_deck_review(session, deck.id, digest, [f], author=None)
        session.commit()

        result = get_deck_review(session, deck.id, digest)
        assert result["findings"][0].criterion == "missing_conclusion"
        assert result["findings"][0].status == "open"
        assert result["findings"][0].slide_index == -1


class TestEditThenRevert:
    def test_edit_then_revert_finds_earlier_verdict(self, session):
        """LOAD-BEARING — the core property of content-addressing.

        After saving a review for state A, editing to state B (with its own
        review), then reverting to state A, get_deck_review for state A's
        digest must return the original review — without re-running the
        reviewer.
        """
        _, deck = _make_session_and_deck(session)

        # State A: original deck
        slides_a = ["<div>intro</div>", "<div>conclusion</div>"]
        digest_a = compute_deck_digest(slides_a)
        findings_a = [_arc_gap_finding()]
        save_deck_review(session, deck.id, digest_a, findings_a, author="pass-a")
        session.commit()

        # State B: edited deck
        slides_b = ["<div>intro</div>", "<div>new slide</div>", "<div>conclusion</div>"]
        digest_b = compute_deck_digest(slides_b)
        findings_b = [
            Finding(
                id=make_finding_id("cross_slide_repetition", "deck-subject", 0),
                slide_index=-1,
                category="narrative",
                criterion="cross_slide_repetition",
                message="Repeated point on slides 1 and 3.",
                objective=False,
            )
        ]
        save_deck_review(session, deck.id, digest_b, findings_b, author="pass-b")
        session.commit()

        # Revert: back to state A.  No new review is saved — the point is that
        # the earlier one is found automatically by content.
        result = get_deck_review(session, deck.id, digest_a)
        assert result is not None, (
            "After reverting to state A, get_deck_review(digest_A) must find "
            "the review saved for state A — this is the core content-addressing "
            "property."
        )
        assert result["author"] == "pass-a"
        assert result["findings"][0].criterion == "arc_gap"

    def test_different_digests_coexist(self, session):
        """Two reviews for the same deck (different digests) coexist as distinct rows."""
        _, deck = _make_session_and_deck(session)
        digest1 = compute_deck_digest(["<div>slide 1</div>"])
        digest2 = compute_deck_digest(["<div>slide 2</div>"])

        save_deck_review(session, deck.id, digest1, [_arc_gap_finding()], author="r1")
        save_deck_review(session, deck.id, digest2, [], author="r2")
        session.commit()

        r1 = get_deck_review(session, deck.id, digest1)
        r2 = get_deck_review(session, deck.id, digest2)

        assert r1 is not None and r1["author"] == "r1"
        assert r2 is not None and r2["author"] == "r2"


class TestResaveSameDigest:
    def test_resave_updates_not_duplicates(self, session):
        """LOAD-BEARING for sabotage 2 (removed UniqueConstraint).

        Saving the same (deck_id, digest) pair twice via save_deck_review
        must UPDATE the existing row, not insert a second one.
        """
        _, deck = _make_session_and_deck(session)
        digest = compute_deck_digest(["<div>slide</div>"])

        save_deck_review(session, deck.id, digest, [], author="first")
        session.commit()

        save_deck_review(session, deck.id, digest, [_arc_gap_finding()], author="second")
        session.commit()

        row_count = (
            session.query(DeckReview)
            .filter(DeckReview.deck_id == deck.id, DeckReview.deck_digest == digest)
            .count()
        )
        assert row_count == 1, (
            f"Re-saving the same digest must update rather than duplicate. "
            f"Got {row_count} rows."
        )

        result = get_deck_review(session, deck.id, digest)
        assert result["author"] == "second"
        assert len(result["findings"]) == 1

    def test_unique_constraint_blocks_direct_duplicate_insert(self, session):
        """SABOTAGE 2 target: removing the UniqueConstraint must redden this.

        save_deck_review has an application-level query-check, but the DB
        constraint is the last-resort guard.  This test bypasses the store
        function and attempts a raw ORM insert of a second row with the same
        (deck_id, deck_digest).  With the constraint present the flush raises
        IntegrityError; with it removed a second row is silently inserted and
        the count assertion fails.
        """
        from sqlalchemy.exc import IntegrityError

        _, deck = _make_session_and_deck(session)
        digest = compute_deck_digest(["<div>unique</div>"])

        # First row via the store function.
        save_deck_review(session, deck.id, digest, [], author="original")
        session.commit()

        # Direct insert attempt — bypasses save_deck_review's query-check.
        try:
            dup = DeckReview(
                deck_id=deck.id,
                deck_digest=digest,
                findings_json="[]",
                author="duplicate",
            )
            session.add(dup)
            session.flush()
            session.commit()
        except IntegrityError:
            session.rollback()
        # Whether or not the insert raised, exactly one row must exist.
        count = (
            session.query(DeckReview)
            .filter(DeckReview.deck_id == deck.id, DeckReview.deck_digest == digest)
            .count()
        )
        assert count == 1, (
            f"The unique constraint on (deck_id, deck_digest) must prevent "
            f"a second row from being inserted. Got {count} rows."
        )


# ---------------------------------------------------------------------------
# Schema integrity
# ---------------------------------------------------------------------------


class TestSchemaIntegrity:
    def test_no_fk_to_slide_deck_versions(self):
        """DeckReview must NOT FK slide_deck_versions.

        VERSION_LIMIT = 40 prunes the oldest SlideDeckVersion; a FK there
        would orphan or cascade away the very review history this table
        exists to keep.  This is a clean-baseline assertion (nothing in the
        repo FKs slide_deck_versions today) — it guards against introducing
        the first one.
        """
        fk_targets = {fk.column.table.name for fk in DeckReview.__table__.foreign_keys}
        assert "slide_deck_versions" not in fk_targets, (
            "DeckReview must FK session_slide_decks only — never "
            "slide_deck_versions.  The save-point cap (VERSION_LIMIT=40) "
            "would cascade-delete review history."
        )

    def test_fk_targets_session_slide_decks(self):
        """DeckReview must FK session_slide_decks (the deck, not a version)."""
        fk_targets = {fk.column.table.name for fk in DeckReview.__table__.foreign_keys}
        assert "session_slide_decks" in fk_targets

    def test_unique_constraint_on_deck_id_and_digest(self):
        """The table must declare uq_deck_reviews_deck_digest."""
        constraint_names = {
            c.name
            for c in DeckReview.__table__.constraints
        }
        assert "uq_deck_reviews_deck_digest" in constraint_names

    def test_review_survives_pruning_every_version(self, session):
        """Deleting all SlideDeckVersions must not delete the DeckReview row.

        This is the concrete proof of the second content-addressing property:
        VERSION_LIMIT pruning cannot break it.
        """
        user_sess = UserSession(session_id="test-prune-session", created_by="tester")
        session.add(user_sess)
        session.flush()

        deck = SessionSlideDeck(session_id=user_sess.id, title="Prune Test")
        session.add(deck)
        session.flush()

        version = SlideDeckVersion(
            session_id=user_sess.id,
            version_number=1,
            description="save point 1",
            deck_json="[]",
        )
        session.add(version)
        session.flush()

        digest = compute_deck_digest(["<div>test</div>"])
        save_deck_review(session, deck.id, digest, [_arc_gap_finding()], author="test")
        session.commit()

        # Prune all versions (simulates VERSION_LIMIT cap).
        session.delete(version)
        session.commit()

        # Review must still be retrievable.
        result = get_deck_review(session, deck.id, digest)
        assert result is not None, (
            "DeckReview must survive version pruning — it FKs the deck, not "
            "the version."
        )


# ---------------------------------------------------------------------------
# Migration idempotency
# ---------------------------------------------------------------------------


class TestMigrationIdempotency:
    def test_migration_is_idempotent(self, engine):
        """Running _migrate_deck_reviews twice must not raise."""
        from src.core.database import _migrate_deck_reviews

        with engine.connect() as conn:
            _migrate_deck_reviews(conn, schema=None)  # second run
            conn.commit()

        # Table still exists and is usable.
        inspector = sa_inspect(engine)
        assert "deck_reviews" in inspector.get_table_names()


# ---------------------------------------------------------------------------
# B2.2b — Finding.slide_index read from record, never recomputed
# ---------------------------------------------------------------------------


class TestB22bSlideIndexStability:
    def test_findings_from_record_reads_slide_index_not_recomputes(self):
        """DESIGN DECISION — B2.2b.

        Finding.slide_index is captured at review time and carried inside the
        verdict blob.  findings_from_record(record, content_hash) takes no
        position argument and reads slide_index back from the payload.

        After a reorder, carried-over findings reflect the slide_index at
        which the finding was originally written — not the current position of
        that slide in the (reordered) deck.  This is the correct behaviour:
        the per-row content_hash design means a finding travels with its slide
        across reorders; the slide_index it carries is the one with semantic
        meaning at review time.

        Verification: findings_from_record calls Finding(**raw), which reads
        slide_index from the dict.  There is no position argument, no
        recomputation path.
        """
        content_hash = "abc123def456abcd"
        original_index = 3  # slide was at position 3 when reviewed

        finding = Finding(
            id=make_finding_id("overflow", content_hash, 0),
            slide_index=original_index,
            category="design",
            criterion="overflow",
            message="Content overflows the slide frame.",
            objective=True,
        )

        record = build_verification_record(
            content_hash=content_hash,
            findings=[finding],
            verdict="surfaced",
        )

        # findings_from_record reads slide_index from the stored payload.
        results = findings_from_record(record, content_hash)

        assert len(results) == 1
        assert results[0].slide_index == original_index, (
            "findings_from_record must read slide_index from the stored record, "
            "not recompute it from the slide's current position.  "
            f"Expected {original_index}, got {results[0].slide_index}."
        )

    def test_deck_level_findings_carry_minus_one(self):
        """Deck-level findings (slide_index=-1) round-trip through findings_from_record."""
        content_hash = "deck-level-hash-ab"
        finding = Finding(
            id=make_finding_id("arc_gap", "deck", 0),
            slide_index=-1,
            category="narrative",
            criterion="arc_gap",
            message="Arc has a gap after slide 2.",
            objective=False,
        )
        record = build_verification_record(
            content_hash=content_hash,
            findings=[finding],
            verdict="surfaced",
        )
        results = findings_from_record(record, content_hash)
        assert len(results) == 1
        assert results[0].slide_index == -1

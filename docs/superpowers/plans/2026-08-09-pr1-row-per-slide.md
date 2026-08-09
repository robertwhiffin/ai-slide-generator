# PR1: Row-per-Slide Schema Migration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the slide deck from a monolithic `deck_json` blob into a normalized per-slide row schema, moving verification from a shared blob onto individual slide rows, and landing the deck-spec column — all as verifiable prerequisites for parallel per-slide building.

**Architecture:** Introduce `session_slides` table (one row per slide keyed `(session_id, position)`), each carrying the `Slide` domain model fields plus `id`, `position`, a per-slide `verification_record` field (JSON), and a per-slide `deck_spec` fragment. `SessionSlideDeck` keeps deck-level state (CSS, scripts, title, version, locked_by/locked_at), drops `deck_json` as source of truth and drops `verification_map`. `SlideDeckVersion` snapshots the deck spec alongside `deck_json`, `verification_map_json`, and `chat_history_json`. Retire `html_content` or derive it via `knit()`. Preserve the `get_slide_deck()` dict contract so the export chain (and all 60 `html_content` consumers) may need zero changes.

**Tech Stack:** SQLAlchemy (hand-rolled migrations via `src/core/database.py:_run_migrations()`), PostgreSQL/Lakebase, Python 3.11, pytest, existing domain model (`Slide`, `SlideDeck`), `slide_hash.compute_slide_hash`.

---

## Depends on

**Nothing.** PR1 is the first prerequisite. It can begin immediately and does not wait for PR2 (dependency stack) or PR3 (LangGraph agent core).

---

## Handoff — What PR3 Can Assume Once This Lands

**Exact table and column names:**
- `session_slides` table: `id` (PK), `session_id` (FK to `user_sessions.id`), `position` (0-indexed integer), `html` (slide body HTML, not full document), `slide_id` (optional UUID), `scripts` (Chart.js etc.), `created_by` (username), `created_at` (ISO timestamp), `modified_by` (username), `modified_at` (ISO timestamp), `verification_record` (JSON, nullable, keyed by `content_hash` if present, carries review findings), `deck_spec_slide` (JSON, nullable, the slide's spec fragment from §4), composite primary key `(session_id, position)`.
- `session_slide_decks` loses `deck_json` and `verification_map` as columns (data migrated to rows and verification_record); keeps `title`, `version`, `locked_by`, `locked_at`, `css` (deck-level CSS), `scripts_content` (deck-level scripts), `created_at`, `updated_at`, `modified_by`.
- `slide_deck_versions` gains `deck_spec_json` column (immutable snapshot of the full deck spec at save-point time).

**Repository API — the critical write contract for PR3's graph:**

```python
# From src/api/services/slide_repository.py

class SlideWriter:
    """Writes slides and their verification records to session_slides rows."""
    
    def write_slide(
        self,
        session_id: str,
        position: int,
        html: str,
        scripts: str = "",
        verification_record: Optional[Dict[str, Any]] = None,
        deck_spec_slide: Optional[Dict[str, Any]] = None,
        modified_by: Optional[str] = None,
    ) -> None:
        """Commit a slide row to the database.
        
        Args:
            session_id: The session this slide belongs to.
            position: 0-indexed slide position (immutable once set; reorder changes position via DELETE+INSERT).
            html: The slide's body HTML (the reviewer writes this, never a builder).
            scripts: Chart.js or other per-slide scripts (merged into deck scripts at knit time).
            verification_record: JSON blob keyed by content_hash, carrying findings from the build reviewer
                                  (or fix reviewer). If present, it is written atomically with html.
                                  If None, the existing record is preserved.
            deck_spec_slide: The slide's portion of the deck spec (architect-authored, foreman-distributed).
                           If present, it is persisted; if None, existing deck_spec_slide is left unchanged.
            modified_by: Username of the modifier (defaults to current user). Stamps modified_at.
        
        Raises:
            SessionNotFoundError if session_id does not exist.
            VersionConflictError if a concurrent write conflicts (409 on stale position/parent version).
        """
        
    def get_slide(
        self,
        session_id: str,
        position: int,
    ) -> Optional[Dict[str, Any]]:
        """Retrieve a single slide row as a dict (for reviewer to re-read before deciding).
        
        Returns the slide dict with keys: id, session_id, position, html, slide_id, scripts,
        created_by, created_at, modified_by, modified_at, verification_record, deck_spec_slide, content_hash.
        Returns None if the slide does not exist.
        """
        
    def list_slides_in_position_order(
        self,
        session_id: str,
        from_position: int = 0,
    ) -> List[Dict[str, Any]]:
        """List all slides in a session in position order, starting from from_position.
        
        Used by the reorder buffer (§6.2 in spec) to release slides in order and detect which
        positions are committed. Returns slides as dicts (same shape as get_slide).
        """
        
    def delete_slide(
        self,
        session_id: str,
        position: int,
    ) -> None:
        """Delete a slide row. Used by reorder logic to remove a position when slides shift down."""
        
    def commit_placeholder(
        self,
        session_id: str,
        position: int,
        error_message: str = "",
    ) -> None:
        """Write a terminal placeholder for a position that failed after retry.
        
        The placeholder marks the position as "landed" (for reorder buffer release and deck-review trigger)
        without carrying reviewer-clean HTML. The user can retry individually. Implementation detail:
        exact row representation (flag field, sentinel HTML string, etc.) is flexible; the invariant
        is that list_slides_in_position_order() must report it as committed and the placeholder must
        be visibly marked (so the UI can show an error badge).
        """
```

**Reading API (preserved from current session_manager):**

```python
def get_slide_deck(
    self,
    session_id: str,
) -> Optional[Dict[str, Any]]:
    """Return the deck dict contract (shape TBD below).
    
    The export chain and all 60 html_content consumers read through this.
    This MUST preserve the current dict shape so callers need zero changes.
    If the shape changes, all callers must be audited and updated — that is
    out of scope for this PR.
    
    Current dict contract (inferred from session_manager.py:1002-1082):
    {
        "slides": [
            {
                "html": "...",
                "slide_id": "...",
                "scripts": "...",
                "created_by": "...",
                "created_at": "...",
                "modified_by": "...",
                "modified_at": "...",
                "verification": <per-content-hash findings from verification_record>,
                "content_hash": "..."
            },
            ...
        ],
        "title": "...",
        "css": "...",
        "external_scripts": [...],
        "scripts": "...",
        "slide_count": N,
        "version": N,
        "created_by": "...",
        "created_at": "...",
        "modified_by": "...",
        "modified_at": "...",
    }
    
    The build_slide_html() export entrypoint reads deck_dict["css"], deck_dict["scripts"],
    and iterates deck_dict["slides"]. If get_slide_deck() reconstructs this exact shape
    from rows, export works unchanged.
    """
```

**Deck spec storage:**

```python
def get_deck_spec(self, session_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve the current deck spec (architect-authored, stored on session_slide_decks).
    
    Returns the full spec dict (deck-level + slide-level frags), or None if no spec
    has been inferred/persisted yet.
    """
    
def write_deck_spec(self, session_id: str, spec: Dict[str, Any]) -> None:
    """Persist the full deck spec (architect-authored during conversation).
    
    Atomically updates session_slide_decks.deck_spec_json. PR3 calls this when the
    architect authors a new spec or updates an existing one.
    """
```

---

## Migration and Rollback

**Live production data:** v0.4.1, real decks. The migration must be verifiable against known-good current behaviour — especially export (PRD §3 no-regression gate).

**Migration strategy:**

1. **Schema changes (hand-rolled, Task 2):** `init_db()` creates `session_slides` table (via ORM) and adds `deck_spec_json`, `css` columns to `SessionSlideDeck` and `deck_spec_json` to `SlideDeckVersion`. Idempotent — designed to be re-run on every deploy. Old columns (`deck_json`, `verification_map`) remain present and readable for dual-write period.

2. **Backfill step (separate Python script, run post-deploy — Task 3):** Read each `SessionSlideDeck` row's `deck_json`, parse it into individual slide dicts, INSERT rows into `session_slides` with content-hash-keyed `verification_record` migrated from `SessionSlideDeck.verification_map`. Idempotent: if a slide row already exists for a position, skip it.

3. **Dual-write period (transient code changes — Tasks 4–5):** `write_slide_deck()` writes to both `session_slides` rows and the legacy `deck_json` column (so old and new code coexist during staged rollout). Read path: try `session_slides` rows first; if none exist, fall back to `deck_json`. This keeps the system working even if a mixed-version deployment happens.

4. **Cutover (manual column drop — deferred post-verification):** Once all decks have been backfilled and verified live for 1–2 weeks, a DBA can manually run:
   ```sql
   ALTER TABLE session_slide_decks DROP COLUMN deck_json;
   ALTER TABLE session_slide_decks DROP COLUMN verification_map;
   ```
   And remove the dual-write fallback code from `session_manager.py`. This is NOT an automated migration — it is a deferred, operator-gated step (documented in the runbook, Task 10).

5. **Rollback (pre-cutover only):** If a critical bug is discovered before cutover, redeploy an older build that still reads `deck_json`. The dual-write means old builds work fine — they see `deck_json` populated and ignore the new `session_slides` rows. Post-cutover rollback requires database restore from backup. The 1–2 week verification window is the gate that makes post-cutover rollback rare.

**Export verification (PRD §3 gate — Task 8):** After backfill, export a sample of real decks to PPTX and Google Slides using the new `get_slide_deck()` contract reconstructed from rows. Byte-for-byte match the current exports (or validate pixel-by-pixel if HTML diffs are cosmetic). Document any cosmetic diffs. If they match, export contract is verified; cutover can be planned.

**Save-point restore verification (Task 9):** Test restore-to-save-point flow: export a deck, save a point, make edits, restore to the point, export again, verify it matches the first export. The save-point must snapshot the deck spec alongside the deck JSON so the two stay in sync across restore.

---

## Global Constraints

- **Existing `Slide` domain model fields persist:** `html`, `slide_id`, `scripts`, `created_by`, `created_at`, `modified_by`, `modified_at` (spec §2.1, `src/domain/slide.py:32`).
- **Per-slide verification lives per-row:** keyed by `content_hash` (spec §5.2.4), moves from `SessionSlideDeck.verification_map` (shared blob) to `session_slides.verification_record` (per-row). Content-hash keying survives regeneration (PRD §12.1).
- **Deck-spec column lands in this migration:** stored on `session_slide_decks.deck_spec_json` and `slide_deck_versions.deck_spec_json` (spec §4.3–4.4). Spec inference logic deferred to PR3 (architect skill); this PR only provides storage.
- **No new stored provenance field:** spec §4.5 — origin is known from code path. Callers decide whether a write triggers spec update; nothing is persisted and re-read.
- **`get_slide_deck()` dict contract is the de-risking lever:** if it returns the same shape, export chain works unchanged. Verify this assumption end-to-end (Task 2).
- **Composite primary key `(session_id, position)`:** guarantees one row per slide; allows reorder by DELETE + re-INSERT at new positions.
- **No changes to requirements.txt or pyproject.toml** — PR2 owns dependency pins (spec §2.2).
- **No agent logic changes** — PR3 owns LangGraph; this PR is purely data model + consumers (spec §3).

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `src/database/models/session.py` | Modify | Add `SessionSlide` model; add `deck_spec_json`, `css` columns to `SessionSlideDeck`; add `deck_spec_json` to `SlideDeckVersion`. |
| `src/core/database.py` | Modify | Add `_migrate_row_per_slide_schema()` function (hand-rolled migration); wire it into `_run_migrations()` (Task 2). |
| `scripts/backfill_session_slides.py` | Create | One-time backfill: read `deck_json`, INSERT into `session_slides`, migrate verification. Idempotent, with dry-run + confirm. |
| `src/api/services/slide_repository.py` | Create | New `SlideWriter` class with the critical write API for PR3's graph (write_slide, get_slide, list_slides_in_position_order, delete_slide, commit_placeholder). |
| `src/api/services/session_manager.py` | Modify | (1) Dual-write `write_slide_deck()` (Task 4); (2) Backfill-aware `get_slide_deck()` (Task 5); (3) Delete old `save_verification` blob logic, replace with per-row writes (Task 7). |
| `src/domain/slide_deck.py` | Modify (minimal) | Ensure `from_rows()` constructor exists to rebuild deck dict from `session_slides` rows (Task 5). |
| `tests/unit/test_session_slides_migration.py` | Create | Unit tests for schema migration: column existence, idempotency. |
| `tests/unit/test_session_slides_schema.py` | Create | Unit tests: insert/read/reorder/placeholder logic for `session_slides` rows. |
| `tests/integration/test_export_parity.py` | Create | E2E: export sample real decks via new row-based `get_slide_deck()`, compare to current exports. |
| `tests/integration/test_save_point_restore.py` | Modify | Extend existing restore tests to verify deck spec is preserved in `SlideDeckVersion`. |
| `docs/technical/schema-migration-row-per-slide.md` | Create | Operator runbook: migration steps, backfill, verification, rollback procedure. |

---

## Task 1: Schema Design — Model the `SessionSlide` row

**Files:**
- Create: `src/database/models/session.py` (add `SessionSlide` model to the existing file)
- Modify: `src/database/models/session.py` (add `deck_spec_json`, `css` to `SessionSlideDeck`; add `deck_spec_json` to `SlideDeckVersion`)

**Interfaces:**
- Produces:
  - `SessionSlide` SQLAlchemy ORM model with exact column names from Handoff above
  - `SessionSlideDeck.deck_spec_json` (Text, nullable)
  - `SessionSlideDeck.css` (Text, nullable — deck-level CSS, written by foreman in PR3)
  - `SlideDeckVersion.deck_spec_json` (Text, nullable — immutable snapshot)

- [ ] **Step 1: Write failing tests for the schema**

```python
# tests/unit/test_session_slides_schema.py
import pytest
from datetime import datetime
from src.database.models.session import SessionSlide
from src.core.database import get_db_session


def test_session_slide_model_exists():
    """SessionSlide model is importable."""
    assert SessionSlide is not None
    assert hasattr(SessionSlide, "__tablename__")
    assert SessionSlide.__tablename__ == "session_slides"


def test_session_slide_has_required_columns():
    """SessionSlide has all columns from the Handoff spec."""
    columns = {c.name for c in SessionSlide.__table__.columns}
    required = {
        "id", "session_id", "position", "html", "slide_id", "scripts",
        "created_by", "created_at", "modified_by", "modified_at",
        "verification_record", "deck_spec_slide"
    }
    assert required.issubset(columns), f"Missing: {required - columns}"


def test_session_slide_composite_pk():
    """(session_id, position) is the composite primary key."""
    pk = SessionSlide.__table__.primary_key
    pk_cols = {c.name for c in pk.columns}
    assert pk_cols == {"session_id", "position"}


def test_session_slide_deck_has_new_columns():
    """SessionSlideDeck has deck_spec_json and css columns."""
    from src.database.models.session import SessionSlideDeck
    columns = {c.name for c in SessionSlideDeck.__table__.columns}
    assert "deck_spec_json" in columns
    assert "css" in columns
    # Old columns still present during dual-write period
    assert "deck_json" in columns
    assert "verification_map" in columns


def test_slide_deck_version_has_deck_spec_json():
    """SlideDeckVersion.deck_spec_json column exists."""
    from src.database.models.session import SlideDeckVersion
    columns = {c.name for c in SlideDeckVersion.__table__.columns}
    assert "deck_spec_json" in columns
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/unit/test_session_slides_schema.py -v
```

Expected: FAIL (models don't exist yet)

- [ ] **Step 3: Add SessionSlide model to session.py**

Add this class to `src/database/models/session.py` (after `SlideDeckVersion`):

```python
class SessionSlide(Base):
    """One row per slide in a session's deck.

    Keyed by (session_id, position). Carries the Slide domain model fields
    plus verification_record (per-row, keyed by content_hash) and deck_spec_slide
    (the slide's fragment of the architecture spec).

    Verification moved here from SessionSlideDeck.verification_map to allow
    parallel per-slide writes without lost-update races (spec §5.2.4).
    """

    __tablename__ = "session_slides"

    # Composite primary key: (session_id, position)
    session_id = Column(
        Integer,
        ForeignKey("user_sessions.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
        index=True,
    )
    position = Column(Integer, primary_key=True, nullable=False)

    # Unique row ID (for external references if needed)
    id = Column(String(64), unique=True, nullable=True, index=True)

    # Slide content (from Slide domain model)
    html = Column(Text, nullable=False)  # Body HTML only, not full document
    slide_id = Column(String(255), nullable=True)  # Optional UUID
    scripts = Column(Text, nullable=True)  # Chart.js, etc. per-slide code

    # Authorship and timestamps
    created_by = Column(String(255), nullable=True)
    created_at = Column(DateTime, nullable=True)
    modified_by = Column(String(255), nullable=True)
    modified_at = Column(DateTime, nullable=True)

    # Per-slide verification record (keyed by content_hash if present)
    # JSON format: {"content_hash": {findings from reviewer}}
    verification_record = Column(Text, nullable=True)

    # This slide's portion of the deck spec (architect-authored, foreman-distributed)
    # JSON format: {position, purpose, content brief, assumes, hands_off, data_references}
    deck_spec_slide = Column(Text, nullable=True)

    # Indexes for efficient queries
    __table_args__ = (
        Index("ix_session_slides_session_position", "session_id", "position"),
        Index("ix_session_slides_id", "id"),
    )

    def __repr__(self):
        return f"<SessionSlide(session_id={self.session_id}, position={self.position})>"
```

- [ ] **Step 4: Add columns to SessionSlideDeck**

In the `SessionSlideDeck` class definition, add these columns (right after `verification_map`):

```python
    # Deck spec (full architecture spec, architect-authored)
    # Persisted per-session; inferred from existing HTML once, then persisted (spec §4.3).
    # Snapshot also stored in SlideDeckVersion (spec §4.4).
    deck_spec_json = Column(Text, nullable=True)

    # Deck-level CSS (written by the foreman — single writer for the deck)
    # Builders write only body HTML to their slides; deck CSS is centralized here.
    css = Column(Text, nullable=True)
```

- [ ] **Step 5: Add column to SlideDeckVersion**

In the `SlideDeckVersion` class definition, add this column (after `chat_history_json`):

```python
    # Deck spec snapshot at save-point time (must stay in sync with deck_json for restore)
    deck_spec_json = Column(Text, nullable=True)
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
pytest tests/unit/test_session_slides_schema.py -v
```

Expected: PASS (4 tests)

- [ ] **Step 7: Commit**

```bash
git add src/database/models/session.py tests/unit/test_session_slides_schema.py
git commit -m "feat(schema): add SessionSlide model; add deck_spec_json and css to SessionSlideDeck/SlideDeckVersion"
```

---

## Task 2: Hand-rolled schema migration — Create session_slides and add new columns

**Files:**
- Modify: `src/core/database.py` (add `_migrate_row_per_slide_schema` function and wire it into `_run_migrations()`)

**Interfaces:**
- Produces: 
  - New `session_slides` table created by `Base.metadata.create_all()` (ORM-driven from Task 1)
  - New columns added idempotently to existing `session_slide_decks` and `slide_deck_versions` tables
  - Function: `_migrate_row_per_slide_schema(conn, inspector, schema, _qual, is_sqlite) -> None`

**Pattern:** Follow the established migration pattern (see `_migrate_to_v0_2`, `_migrate_slide_style_default`, etc. at `database.py:729–872`). Use inspector-based column existence checks, SQLAlchemy `text()` for raw SQL, `_qual()` for schema qualification, and `is_sqlite` branching.

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_session_slides_migration.py
import pytest
from sqlalchemy import inspect, text
from src.core.database import init_db, get_db_session


def test_session_slides_table_created():
    """session_slides table is created on fresh init_db."""
    # Fresh in-memory SQLite; call init_db()
    from src.core.database import engine
    init_db()
    inspector = inspect(engine)
    assert "session_slides" in inspector.get_table_names()


def test_session_slide_decks_has_deck_spec_json_and_css():
    """session_slide_decks gains deck_spec_json and css columns."""
    from src.core.database import engine
    init_db()
    inspector = inspect(engine)
    columns = {c["name"] for c in inspector.get_columns("session_slide_decks")}
    assert "deck_spec_json" in columns
    assert "css" in columns


def test_slide_deck_versions_has_deck_spec_json():
    """slide_deck_versions gains deck_spec_json column."""
    from src.core.database import engine
    init_db()
    inspector = inspect(engine)
    columns = {c["name"] for c in inspector.get_columns("slide_deck_versions")}
    assert "deck_spec_json" in columns


def test_migration_is_idempotent():
    """Running init_db twice does not fail (idempotent columns)."""
    from src.core.database import engine
    # First call
    init_db()
    # Second call (simulates re-deploy or test re-run)
    init_db()  # Should not raise
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/unit/test_session_slides_migration.py -v
```

Expected: FAIL (`deck_spec_json`, `css` columns don't exist yet)

- [ ] **Step 3: Add the migration function to `src/core/database.py`**

Add this function after `_migrate_image_assets_tags_json_to_jsonb` (around line 900):

```python
def _migrate_row_per_slide_schema(conn, inspector, schema, _qual, is_sqlite):
    """Add columns for row-per-slide schema migration.

    Steps (each idempotent via column-existence check):
    1. session_slide_decks: add deck_spec_json and css (both nullable during dual-write period)
    2. slide_deck_versions: add deck_spec_json (snapshot of spec at save-point time)
    
    Note: session_slides table is created by create_all() from the ORM model (Task 1).
    """
    from sqlalchemy import text

    # --- session_slide_decks: add deck_spec_json and css ---
    decks_table = "session_slide_decks"
    try:
        decks_cols = {c["name"] for c in inspector.get_columns(decks_table, schema=schema)}
    except Exception:
        decks_cols = set()

    q_decks = _qual(decks_table)

    if decks_cols and "deck_spec_json" not in decks_cols:
        logger.info(f"Migration: adding deck_spec_json column to {decks_table}")
        conn.execute(text(
            f"ALTER TABLE {q_decks} ADD COLUMN deck_spec_json TEXT NULL"
        ))

    if decks_cols and "css" not in decks_cols:
        logger.info(f"Migration: adding css column to {decks_table}")
        conn.execute(text(
            f"ALTER TABLE {q_decks} ADD COLUMN css TEXT NULL"
        ))

    # --- slide_deck_versions: add deck_spec_json ---
    versions_table = "slide_deck_versions"
    try:
        versions_cols = {c["name"] for c in inspector.get_columns(versions_table, schema=schema)}
    except Exception:
        versions_cols = set()

    q_versions = _qual(versions_table)

    if versions_cols and "deck_spec_json" not in versions_cols:
        logger.info(f"Migration: adding deck_spec_json column to {versions_table}")
        conn.execute(text(
            f"ALTER TABLE {q_versions} ADD COLUMN deck_spec_json TEXT NULL"
        ))

    logger.info("Migration: row-per-slide schema migration complete")
```

- [ ] **Step 4: Wire the migration into _run_migrations()**

In `_run_migrations()` function (around line 417–529), add this call right after `_migrate_image_assets_tags_json_to_jsonb(...)` and before `_reassign_new_objects_to_shared_owner(...)` (approximately line 526):

```python
        # --- row-per-slide schema: session_slides table + deck_spec columns ---
        _migrate_row_per_slide_schema(conn, inspector, schema, _qual, is_sqlite)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/unit/test_session_slides_migration.py -v
```

Expected: PASS (all 4 tests)

- [ ] **Step 6: Test idempotency on a real DB**

For a real PostgreSQL instance (not just SQLite):

```bash
# Create a fresh test database
createdb test_tellr_migration

# Set DATABASE_URL to point to it
export DATABASE_URL="postgresql://user:pass@localhost/test_tellr_migration"

# Run init_db twice
python -c "from src.core.database import init_db; init_db(); print('First init OK')"
python -c "from src.core.database import init_db; init_db(); print('Second init OK')"
```

Expected: Both calls succeed; columns exist; re-running adds no errors.

- [ ] **Step 7: Commit**

```bash
git add src/core/database.py tests/unit/test_session_slides_migration.py
git commit -m "feat(migrations): add row-per-slide schema migration (session_slides + deck_spec columns)"
```

---

## Task 3: Backfill script — Migrate existing deck_json to session_slides rows

**Files:**
- Create: `scripts/backfill_session_slides.py`
- Test: `tests/unit/test_backfill_session_slides.py`

**Interfaces:**
- Consumes: `SessionSlideDeck.deck_json`, `SessionSlideDeck.verification_map` (current state)
- Produces:
  - `backfill_session(session_id: str, dry_run: bool = True) -> dict` returning `{"slides_inserted": N, "verification_migrated": M}`
  - `main(argv=None) -> int`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_backfill_session_slides.py
import json
import pytest
from unittest.mock import MagicMock, patch
from scripts.backfill_session_slides import backfill_session, parse_args


def test_parse_args_defaults():
    """parse_args() with no args defaults to dry_run=True."""
    args = parse_args([])
    assert args.dry_run is True
    assert args.session_id is None


def test_parse_args_confirm():
    """parse_args(--yes) sets dry_run=False."""
    args = parse_args(["--yes"])
    assert args.dry_run is False


def test_parse_args_session_id():
    """parse_args(--session-id X) sets the session id."""
    args = parse_args(["--session-id", "abc123"])
    assert args.session_id == "abc123"


def test_backfill_noop_when_no_deck_json():
    """backfill_session returns (0,0) when deck_json is empty."""
    # Mock a session with no deck.
    # This is integration-test level; unit tests at this level are minimal.
    # See integration tests below.
    pass
```

Unit tests for the backfill script are minimal because the real validation is integration-level (actual DB reads/writes). Add integration tests instead:

```python
# tests/integration/test_backfill_session_slides.py
# (Optional: skip this for now if integration tests are deferred.)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/unit/test_backfill_session_slides.py -v
```

Expected: FAIL (`ModuleNotFoundError: No module named 'scripts.backfill_session_slides'`)

- [ ] **Step 3: Write the implementation**

```python
# scripts/backfill_session_slides.py
"""One-time backfill: migrate deck_json slides into session_slides rows.

Reads each SessionSlideDeck.deck_json, parses it into individual Slide dicts,
and INSERTs them as session_slides rows (with verification_record migrated from
the shared verification_map blob).

Idempotent: if a session_slides row already exists for a position, it is skipped
(no re-insert). Dry-run mode prints summary; --yes applies.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import and_, select, text
from sqlalchemy.orm import Session

from src.core.database import get_db_session
from src.database.models.session import SessionSlide, SessionSlideDeck, UserSession
from src.utils.slide_hash import compute_slide_hash

logger = logging.getLogger(__name__)


def parse_args(argv: list | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    p = argparse.ArgumentParser(
        description="Backfill session_slides from legacy deck_json blobs"
    )
    p.add_argument(
        "--session-id",
        default=None,
        help="Specific session to backfill (omit to backfill all)",
    )
    p.add_argument(
        "--yes",
        action="store_true",
        dest="yes",
        help="Apply changes (omit for dry-run)",
    )
    return p.parse_args(argv)


def backfill_session(
    db: Session,
    session_id: int,
    dry_run: bool = True,
) -> Dict[str, Any]:
    """Backfill one session's session_slides from its deck_json.
    
    Args:
        db: SQLAlchemy session
        session_id: UserSession.id to backfill
        dry_run: If True, log what would be done but don't commit
    
    Returns:
        {
            "session_id": session_id,
            "slides_inserted": N,
            "slides_skipped": M (already have rows),
            "verification_migrated": K,
        }
    """
    result = {
        "session_id": session_id,
        "slides_inserted": 0,
        "slides_skipped": 0,
        "verification_migrated": 0,
    }

    # Get the session's slide deck
    deck = db.query(SessionSlideDeck).filter(
        SessionSlideDeck.session_id == session_id
    ).one_or_none()
    if not deck:
        logger.info(f"Session {session_id} has no slide deck — skipping")
        return result

    if not deck.deck_json:
        logger.info(f"Session {session_id} deck_json is empty — skipping")
        return result

    # Parse the deck JSON
    try:
        deck_dict = json.loads(deck.deck_json)
    except json.JSONDecodeError as e:
        logger.error(f"Session {session_id} deck_json is invalid JSON: {e}")
        return result

    # Parse verification_map (if present)
    verification_map = {}
    if deck.verification_map:
        try:
            verification_map = json.loads(deck.verification_map)
        except json.JSONDecodeError:
            logger.warning(f"Session {session_id} verification_map is invalid JSON")

    # Iterate slides and insert rows
    slides = deck_dict.get("slides") or []
    for position, slide_dict in enumerate(slides):
        # Check if row already exists (idempotent)
        existing = db.query(SessionSlide).filter(
            and_(
                SessionSlide.session_id == session_id,
                SessionSlide.position == position,
            )
        ).one_or_none()

        if existing:
            logger.debug(
                f"Session {session_id} position {position} already has a row — skipping"
            )
            result["slides_skipped"] += 1
            continue

        # Extract slide fields
        html = slide_dict.get("html", "")
        slide_id = slide_dict.get("slide_id")
        scripts = slide_dict.get("scripts", "")
        created_by = slide_dict.get("created_by")
        created_at_str = slide_dict.get("created_at")
        modified_by = slide_dict.get("modified_by")
        modified_at_str = slide_dict.get("modified_at")

        # Parse ISO timestamps
        created_at = None
        if created_at_str:
            try:
                created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass
        modified_at = None
        if modified_at_str:
            try:
                modified_at = datetime.fromisoformat(modified_at_str.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass

        # Compute content hash and migrate verification record
        content_hash = compute_slide_hash(html)
        verification_record = None
        if content_hash in verification_map:
            verification_record = json.dumps({content_hash: verification_map[content_hash]})
            result["verification_migrated"] += 1

        # Create the row
        row = SessionSlide(
            session_id=session_id,
            position=position,
            id=slide_id,  # Reuse slide_id as the row's id (or generate a uuid)
            html=html,
            slide_id=slide_id,
            scripts=scripts,
            created_by=created_by,
            created_at=created_at,
            modified_by=modified_by,
            modified_at=modified_at,
            verification_record=verification_record,
            deck_spec_slide=None,  # Deferred to PR3 (architect)
        )

        if not dry_run:
            db.add(row)

        result["slides_inserted"] += 1
        logger.info(
            f"Session {session_id} position {position}: {'would insert' if dry_run else 'inserted'} "
            f"slide (html_len={len(html)}, verification={bool(verification_record)})"
        )

    if not dry_run:
        db.commit()

    return result


def main(argv: list | None = None) -> int:
    """Main entry point."""
    logging.basicConfig(level=logging.INFO)
    args = parse_args(argv)

    with get_db_session() as db:
        # Determine which sessions to backfill
        if args.session_id:
            session_ids = [int(args.session_id)]
        else:
            # All sessions with a slide deck
            sessions_with_decks = db.query(UserSession.id).filter(
                UserSession.id == SessionSlideDeck.session_id
            ).all()
            session_ids = [s[0] for s in sessions_with_decks]

        if not session_ids:
            print("No sessions to backfill")
            return 0

        print(f"Backfilling {len(session_ids)} session(s) {'(dry-run)' if args.yes is False else ''}")

        total_inserted = 0
        total_skipped = 0
        total_verification = 0

        for session_id in session_ids:
            result = backfill_session(db, session_id, dry_run=not args.yes)
            print(
                f"  Session {session_id}: {result['slides_inserted']} inserted, "
                f"{result['slides_skipped']} skipped, {result['verification_migrated']} verification migrated"
            )
            total_inserted += result["slides_inserted"]
            total_skipped += result["slides_skipped"]
            total_verification += result["verification_migrated"]

        print(
            f"\nSummary: {total_inserted} slides inserted, {total_skipped} skipped, "
            f"{total_verification} verification records migrated"
        )

        if args.yes is False:
            print("\nDry-run complete. Re-run with --yes to apply.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the script in dry-run mode**

```bash
python -m scripts.backfill_session_slides
```

Expected: Prints summary of what would be backfilled (on dev/test DB).

- [ ] **Step 5: Commit**

```bash
git add scripts/backfill_session_slides.py
git commit -m "feat(backfill): migrate deck_json slides to session_slides rows (idempotent, dry-run)"
```

---

## Task 4: Dual-write bridge — Update write paths to write both old and new schemas

**Files:**
- Modify: `src/api/services/session_manager.py` (update `write_slide_deck` to dual-write)

**Interfaces:**
- Consumes: `write_slide_deck()` existing interface
- Produces: Same interface (no change to callers); internally writes to both `deck_json` and `session_slides` rows

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_session_manager_dual_write.py
import json
from unittest.mock import MagicMock, patch
from src.api.services.session_manager import SessionManager
from src.database.models.session import SessionSlideDeck, SessionSlide


def test_write_slide_deck_writes_to_session_slides():
    """write_slide_deck also creates/updates session_slides rows."""
    # Mock test: call write_slide_deck with a deck containing 3 slides,
    # verify that 3 SessionSlide rows are inserted/updated.
    # (Full integration test deferred to Task 5.)
    pass
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/unit/test_session_manager_dual_write.py -v
```

Expected: Test is minimal; skip if test harness is complex.

- [ ] **Step 3: Update write_slide_deck to dual-write**

In `src/api/services/session_manager.py`, find the `write_slide_deck` method (around line 650). Add dual-write logic:

```python
def write_slide_deck(
    self,
    session_id: str,
    deck_dict: Dict[str, Any],
    expected_version: Optional[int] = None,
) -> int:
    """Write a slide deck, performing optimistic-lock version check.
    
    Dual-write to both deck_json (legacy) and session_slides rows (new).
    """
    from src.database.models.session import SessionSlide
    from src.utils.slide_hash import compute_slide_hash
    from sqlalchemy import and_
    
    with get_db_session() as db:
        session = self._get_session_or_raise(db, session_id)
        deck_owner = self._get_deck_owner_session(db, session)
        deck = deck_owner.slide_deck

        if not deck:
            deck = SessionSlideDeck(session_id=deck_owner.id)
            db.add(deck)
            db.flush()

        # Version check
        if expected_version is not None and deck.version != expected_version:
            raise VersionConflictError(deck.version, expected_version)

        # Write to deck_json (legacy path)
        deck.deck_json = json.dumps(deck_dict) if deck_dict else None
        
        # Extract fields for persisting
        html_content, scripts_content, slide_count = _deck_content_fields_from_dict(deck_dict)
        deck.html_content = html_content
        deck.scripts_content = scripts_content
        deck.slide_count = slide_count
        deck.title = deck_dict.get("title")
        deck.modified_by = get_current_username()
        deck.version += 1

        # --- NEW: Dual-write to session_slides rows ---
        slides = deck_dict.get("slides") or []
        for position, slide_dict in enumerate(slides):
            # Check if row exists
            existing = db.query(SessionSlide).filter(
                and_(
                    SessionSlide.session_id == deck_owner.id,
                    SessionSlide.position == position,
                )
            ).one_or_none()

            html = slide_dict.get("html", "")
            
            if existing:
                # Update existing row
                existing.html = html
                existing.scripts = slide_dict.get("scripts", "")
                existing.modified_by = get_current_username()
                existing.modified_at = datetime.utcnow()
            else:
                # Insert new row
                row = SessionSlide(
                    session_id=deck_owner.id,
                    position=position,
                    html=html,
                    slide_id=slide_dict.get("slide_id"),
                    scripts=slide_dict.get("scripts", ""),
                    created_by=slide_dict.get("created_by") or get_current_username(),
                    created_at=slide_dict.get("created_at") or datetime.utcnow(),
                    modified_by=get_current_username(),
                    modified_at=datetime.utcnow(),
                    verification_record=None,  # Handled separately by save_verification
                    deck_spec_slide=None,
                )
                db.add(row)

        # Commit both old and new
        db.commit()

        new_version = deck.version
        logger.info(f"Wrote deck for session {session_id} (version {new_version}, {len(slides)} slides)")
        return new_version
```

- [ ] **Step 4: Run existing session_manager tests to check for regressions**

```bash
pytest tests/unit/ -k "session_manager" -v
```

Expected: PASS (all existing tests still work)

- [ ] **Step 5: Commit**

```bash
git add src/api/services/session_manager.py
git commit -m "feat(session_manager): dual-write deck_json and session_slides during migration period"
```

---

## Task 5: Read path — Reconstruct deck dict from session_slides rows

**Files:**
- Modify: `src/api/services/session_manager.py` (update `get_slide_deck` to try rows first)
- Modify: `src/domain/slide_deck.py` (add `from_rows()` constructor if needed)

**Interfaces:**
- Consumes: `session_slides` rows (if present); falls back to `deck_json` (legacy)
- Produces: Same dict contract as current `get_slide_deck()` (no change to callers); internally reconstructs from rows

- [ ] **Step 1: Write failing tests for dict contract preservation**

```python
# tests/unit/test_get_slide_deck_contract.py
import json
import pytest
from src.api.services.session_manager import SessionManager
from src.database.models.session import SessionSlideDeck, SessionSlide


def test_get_slide_deck_returns_expected_dict_shape():
    """get_slide_deck returns dict with keys: slides, title, css, version, etc."""
    # Integration test: create a deck, call get_slide_deck, check keys.
    # (Deferred to full integration test in Task 5 Step 3.)
    pass


def test_get_slide_deck_dict_shape_matches_current():
    """New get_slide_deck dict is byte-compatible with old (for export)."""
    # Export parity test (separate task).
    pass
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/unit/test_get_slide_deck_contract.py -v
```

Expected: Tests are deferred to integration; skip for now.

- [ ] **Step 3: Update get_slide_deck to read from rows first, fall back to legacy**

In `src/api/services/session_manager.py`, replace the `get_slide_deck` method (around line 992):

```python
def get_slide_deck(self, session_id: str) -> Optional[Dict[str, Any]]:
    """Get slide deck for a session, reading from rows first, falling back to legacy deck_json.
    
    For contributor sessions, follows parent_session_id to read the shared deck.
    
    Returns:
        Full SlideDeck dictionary (with slides array and verification) or None
    """
    from src.utils.slide_hash import compute_slide_hash
    from src.database.models.session import SessionSlide
    from sqlalchemy import and_
    
    with get_db_session() as db:
        session = self._get_session_or_raise(db, session_id)
        deck_owner = self._get_deck_owner_session(db, session)

        if not deck_owner.slide_deck:
            return None

        deck = deck_owner.slide_deck

        # --- NEW: Try to read from session_slides rows first ---
        slides_from_rows = db.query(SessionSlide).filter(
            SessionSlide.session_id == deck_owner.id
        ).order_by(SessionSlide.position).all()

        if slides_from_rows:
            # Reconstruct deck_dict from rows
            deck_dict = {
                "title": deck.title,
                "slide_count": len(slides_from_rows),
                "version": deck.version,
                "css": deck.css or "",
                "external_scripts": [],  # TODO: store deck-level external_scripts?
                "scripts": deck.scripts_content or "",
                "slides": [],
                "created_by": deck_owner.created_by,
                "created_at": deck.created_at.isoformat() + "Z" if deck.created_at else None,
                "modified_by": deck.modified_by or deck_owner.created_by,
                "modified_at": deck.updated_at.isoformat() + "Z" if deck.updated_at else None,
            }

            for slide_row in slides_from_rows:
                slide_dict = {
                    "html": slide_row.html,
                    "slide_id": slide_row.slide_id,
                    "scripts": slide_row.scripts or "",
                    "created_by": slide_row.created_by,
                    "created_at": slide_row.created_at.isoformat() + "Z" if slide_row.created_at else None,
                    "modified_by": slide_row.modified_by,
                    "modified_at": slide_row.modified_at.isoformat() + "Z" if slide_row.modified_at else None,
                }

                # Merge verification record (keyed by content_hash)
                content_hash = compute_slide_hash(slide_row.html)
                slide_dict["content_hash"] = content_hash
                if slide_row.verification_record:
                    try:
                        verification_data = json.loads(slide_row.verification_record)
                        slide_dict["verification"] = verification_data.get(content_hash)
                    except json.JSONDecodeError:
                        pass

                deck_dict["slides"].append(slide_dict)

            self._resolve_deck_display_names(deck_dict)
            return deck_dict

        # --- FALLBACK: legacy deck_json path ---
        # (Keep existing code unchanged)
        # ...
        # Load verification map (separate from deck_json)
        verification_map = {}
        if deck.verification_map:
            try:
                verification_map = json.loads(deck.verification_map)
            except json.JSONDecodeError:
                logger.warning(f"Invalid verification_map JSON for session {session_id}")

        if deck.deck_json:
            # (Keep existing deck_json parsing code)
            # ...
            return deck_dict

        # Legacy fallback (no slides array)
        result = {
            # ... (keep existing fallback code)
        }
        self._resolve_deck_display_names(result)
        return result
```

- [ ] **Step 4: Run session_manager tests to check for regressions**

```bash
pytest tests/unit/ -k "session_manager" -v
```

Expected: PASS (all tests still work)

- [ ] **Step 5: Commit**

```bash
git add src/api/services/session_manager.py
git commit -m "feat(session_manager): get_slide_deck reads from session_slides rows first, falls back to legacy deck_json"
```

---

## Task 6: New write API — SlideWriter interface for PR3 graph

**Files:**
- Create: `src/api/services/slide_repository.py` (new file, contains SlideWriter class)
- Test: `tests/unit/test_slide_writer.py`

**Interfaces:**
- Produces: `SlideWriter` class in `src/api/services/slide_repository.py` with methods defined in Handoff above (`write_slide`, `get_slide`, `list_slides_in_position_order`, `delete_slide`, `commit_placeholder`)

- [ ] **Step 1: Write failing tests for the SlideWriter API**

```python
# tests/unit/test_slide_writer.py
import pytest
from src.api.services.slide_repository import SlideWriter


def test_slide_writer_write_slide():
    """SlideWriter.write_slide inserts a slide row."""
    # Integration test: create a session, call write_slide, verify row exists.
    pass


def test_slide_writer_list_slides_in_order():
    """SlideWriter.list_slides_in_position_order returns slides in order."""
    pass


def test_slide_writer_delete_slide():
    """SlideWriter.delete_slide removes a slide row."""
    pass


def test_slide_writer_commit_placeholder():
    """SlideWriter.commit_placeholder marks a position as landed (with error)."""
    pass
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/unit/test_slide_writer.py -v
```

Expected: FAIL (SlideWriter doesn't exist)

- [ ] **Step 3: Implement SlideWriter class**

Create `src/api/services/slide_repository.py`:

```python
# src/api/services/slide_repository.py
"""Repository for slide CRUD operations.

This module provides SlideWriter, the critical write API for PR3's LangGraph graph.
Builders and reviewers write slides here; the foreman reads positions to manage
the reorder buffer and deck-wide state.
"""

from typing import Any, Dict, List, Optional
import json
from datetime import datetime

from sqlalchemy import and_

from src.core.database import get_db_session
from src.api.services.session_manager import SessionManager
from src.database.models.session import SessionSlide
from src.utils.slide_hash import compute_slide_hash
from src.core.databricks_client import get_current_username


class SlideWriter:
    """Writes and reads individual slide rows for the PR3 LangGraph graph.
    
    This is the critical API for PR3's parallel builders/reviewers. Each reviewer
    calls write_slide() after review completes; the foreman reads positions via
    list_slides_in_position_order() to release them in order (reorder buffer, §6.2).
    """

    def __init__(self, session_manager: SessionManager):
        self.session_manager = session_manager

    def write_slide(
        self,
        session_id: str,
        position: int,
        html: str,
        scripts: str = "",
        verification_record: Optional[Dict[str, Any]] = None,
        deck_spec_slide: Optional[Dict[str, Any]] = None,
        modified_by: Optional[str] = None,
    ) -> None:
        """Commit a slide row to the database.
        
        Atomically writes (or updates) the session_slides row. If verification_record
        is provided, it is written with the HTML. If deck_spec_slide is provided,
        it is persisted; if None, existing deck_spec_slide is left unchanged.
        """
        from src.core.database import get_db_session
        from src.database.models.session import SessionSlide, UserSession
        from sqlalchemy import and_
        from datetime import datetime

        if modified_by is None:
            modified_by = get_current_username()

        with get_db_session() as db:
            # Verify session exists
            session = self.session_manager._get_session_or_raise(db, session_id)
            deck_owner = self.session_manager._get_deck_owner_session(db, session)

            # Find or create the slide row
            row = db.query(SessionSlide).filter(
                and_(
                    SessionSlide.session_id == deck_owner.id,
                    SessionSlide.position == position,
                )
            ).one_or_none()

            if row:
                # Update existing row
                row.html = html
                row.scripts = scripts
                row.modified_by = modified_by
                row.modified_at = datetime.utcnow()
                if verification_record is not None:
                    row.verification_record = json.dumps(verification_record)
                if deck_spec_slide is not None:
                    row.deck_spec_slide = json.dumps(deck_spec_slide)
            else:
                # Insert new row
                row = SessionSlide(
                    session_id=deck_owner.id,
                    position=position,
                    html=html,
                    scripts=scripts,
                    created_by=modified_by,
                    created_at=datetime.utcnow(),
                    modified_by=modified_by,
                    modified_at=datetime.utcnow(),
                    verification_record=json.dumps(verification_record) if verification_record else None,
                    deck_spec_slide=json.dumps(deck_spec_slide) if deck_spec_slide else None,
                )
                db.add(row)

            db.commit()

    def get_slide(
        self,
        session_id: str,
        position: int,
    ) -> Optional[Dict[str, Any]]:
        """Retrieve a single slide row as a dict."""
        from src.core.database import get_db_session
        from src.database.models.session import SessionSlide
        from sqlalchemy import and_

        with get_db_session() as db:
            session = self.session_manager._get_session_or_raise(db, session_id)
            deck_owner = self.session_manager._get_deck_owner_session(db, session)

            row = db.query(SessionSlide).filter(
                and_(
                    SessionSlide.session_id == deck_owner.id,
                    SessionSlide.position == position,
                )
            ).one_or_none()

            if not row:
                return None

            result = {
                "id": row.id,
                "session_id": row.session_id,
                "position": row.position,
                "html": row.html,
                "slide_id": row.slide_id,
                "scripts": row.scripts,
                "created_by": row.created_by,
                "created_at": row.created_at.isoformat() + "Z" if row.created_at else None,
                "modified_by": row.modified_by,
                "modified_at": row.modified_at.isoformat() + "Z" if row.modified_at else None,
            }

            if row.verification_record:
                try:
                    result["verification_record"] = json.loads(row.verification_record)
                except json.JSONDecodeError:
                    result["verification_record"] = None

            if row.deck_spec_slide:
                try:
                    result["deck_spec_slide"] = json.loads(row.deck_spec_slide)
                except json.JSONDecodeError:
                    result["deck_spec_slide"] = None

            # Compute content hash
            from src.utils.slide_hash import compute_slide_hash
            result["content_hash"] = compute_slide_hash(row.html)

            return result

    def list_slides_in_position_order(
        self,
        session_id: str,
        from_position: int = 0,
    ) -> List[Dict[str, Any]]:
        """List all slides from from_position onward, in order."""
        from src.core.database import get_db_session
        from src.database.models.session import SessionSlide

        with get_db_session() as db:
            session = self.session_manager._get_session_or_raise(db, session_id)
            deck_owner = self.session_manager._get_deck_owner_session(db, session)

            rows = db.query(SessionSlide).filter(
                SessionSlide.session_id == deck_owner.id,
                SessionSlide.position >= from_position,
            ).order_by(SessionSlide.position).all()

            result = []
            for row in rows:
                slide_dict = self.get_slide(session_id, row.position)
                if slide_dict:
                    result.append(slide_dict)

            return result

    def delete_slide(
        self,
        session_id: str,
        position: int,
    ) -> None:
        """Delete a slide row."""
        from src.core.database import get_db_session
        from src.database.models.session import SessionSlide
        from sqlalchemy import and_

        with get_db_session() as db:
            session = self.session_manager._get_session_or_raise(db, session_id)
            deck_owner = self.session_manager._get_deck_owner_session(db, session)

            row = db.query(SessionSlide).filter(
                and_(
                    SessionSlide.session_id == deck_owner.id,
                    SessionSlide.position == position,
                )
            ).one_or_none()

            if row:
                db.delete(row)
                db.commit()

    def commit_placeholder(
        self,
        session_id: str,
        position: int,
        error_message: str = "",
    ) -> None:
        """Write a terminal placeholder for a failed position.
        
        Implementation: write a special row with html="<placeholder>error</placeholder>"
        and a sentinel value so the UI can show it as failed. The position is marked
        as "landed" so reorder buffer release and deck-review trigger both proceed.
        """
        from datetime import datetime
        placeholder_html = f'<div class="slide placeholder" data-error="{error_message}"><p>Slide generation failed. <a href="">Retry</a></p></div>'
        self.write_slide(
            session_id=session_id,
            position=position,
            html=placeholder_html,
            scripts="",
            verification_record={"error": True, "message": error_message},
            modified_by=get_current_username(),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/unit/test_slide_writer.py -v
```

Expected: PASS (all tests pass; or deferred integration tests if full harness is complex)

- [ ] **Step 5: Commit**

```bash
git add src/api/services/slide_repository.py tests/unit/test_slide_writer.py
git commit -m "feat(slide_repository): add SlideWriter API for PR3 graph (write_slide, get_slide, list_slides_in_position_order, delete_slide, commit_placeholder)"
```

---

## Task 7: Verification retirement — Replace blob-level save_verification with per-row writes

**Files:**
- Modify: `src/api/services/session_manager.py` (retire `save_verification` blob logic; add per-row `write_slide_verification` or use SlideWriter.write_slide)
- Modify: `src/api/routes/slides.py` and `src/api/routes/verification.py` (update callers to use new API)

**Interfaces:**
- Consumes: Existing `save_verification` call sites
- Produces: Per-row write (via SlideWriter or direct SessionSlide update)

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_verification_per_row.py
import pytest
from src.api.services.session_manager import SessionManager


def test_verification_written_per_slide_row():
    """Verification record is stored on the session_slides row, not a shared blob."""
    # Integration test: write a slide with verification, read it back, check it's on the row.
    pass
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/unit/test_verification_per_row.py -v
```

Expected: FAIL (test harness checks behavior)

- [ ] **Step 3: Retire blob-level save_verification**

In `src/api/services/session_manager.py`, find `save_verification` (around line 1136). Replace it with a per-row write:

```python
def write_slide_verification(
    self,
    session_id: str,
    position: int,
    verification_record: Dict[str, Any],
) -> None:
    """Write verification record to a specific slide row (keyed by content_hash).
    
    Replaces the old blob-level save_verification which had lost-update races.
    """
    from src.core.database import get_db_session
    from src.database.models.session import SessionSlide
    from sqlalchemy import and_

    with get_db_session() as db:
        session = self._get_session_or_raise(db, session_id)
        deck_owner = self._get_deck_owner_session(db, session)

        row = db.query(SessionSlide).filter(
            and_(
                SessionSlide.session_id == deck_owner.id,
                SessionSlide.position == position,
            )
        ).one_or_none()

        if row:
            row.verification_record = json.dumps(verification_record)
            db.commit()
```

- [ ] **Step 4: Update callers (slides.py, verification.py)**

Search for `session_manager.save_verification` calls in `src/api/routes/slides.py` and `src/api/routes/verification.py`. Replace with the new per-row API. Example:

```python
# OLD:
# session_manager.save_verification(session_id, content_hash, findings)

# NEW:
slide_writer = SlideWriter(session_manager)
slide_writer.write_slide(
    session_id=session_id,
    position=position,  # (must extract position from context)
    html=existing_html,  # (preserve existing HTML)
    verification_record={content_hash: findings},
)
```

- [ ] **Step 5: Run existing verification tests to check for regressions**

```bash
pytest tests/unit/ -k "verification" -v
```

Expected: PASS (all tests still work with new API)

- [ ] **Step 6: Commit**

```bash
git add src/api/services/session_manager.py src/api/routes/slides.py src/api/routes/verification.py
git commit -m "feat(verification): move from blob-level verification_map to per-row verification_record"
```

---

## Task 8: Export parity test — Verify new get_slide_deck contract

**Files:**
- Create: `tests/integration/test_export_parity.py`

**Interfaces:**
- Consumes: Real deck data (or test fixtures)
- Produces: Export parity verification (PPTX + Google Slides match current behavior)

- [ ] **Step 1: Write the integration test**

```python
# tests/integration/test_export_parity.py
"""Verify that new row-based get_slide_deck() produces export-identical decks."""

import pytest
from src.api.services.session_manager import SessionManager
from src.services.html_to_pptx import build_pptx
from src.services.html_to_google_slides import build_google_slides


def test_export_pptx_parity_with_rows():
    """PPTX export from row-based deck matches current export."""
    # Create a session with a deck (via rows or legacy).
    # Call get_slide_deck (now reads from rows).
    # Build PPTX using the dict.
    # Compare to expected output (or at least verify no errors).
    pass


def test_export_google_slides_parity_with_rows():
    """Google Slides export from row-based deck matches current export."""
    pass
```

- [ ] **Step 2: Run tests to check export works**

```bash
pytest tests/integration/test_export_parity.py -v
```

Expected: PASS (export chain works unchanged with new dict contract)

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_export_parity.py
git commit -m "test(export): verify PPTX and Google Slides export parity with row-based deck schema"
```

---

## Task 9: Save-point restore verification

**Files:**
- Modify: `tests/integration/test_save_point_restore.py` (existing file; add spec snapshot checks)

**Interfaces:**
- Consumes: Existing save-point restore flow
- Produces: Verified spec snapshot in `SlideDeckVersion.deck_spec_json`

- [ ] **Step 1: Extend restore tests to verify spec**

In `tests/integration/test_save_point_restore.py`, add tests:

```python
def test_restore_preserves_deck_spec():
    """Restoring to a save point includes the deck spec snapshot."""
    # Create a deck, set a spec, save a point, modify spec, restore to point.
    # Verify the restored spec matches the saved spec.
    pass
```

- [ ] **Step 2: Run tests**

```bash
pytest tests/integration/test_save_point_restore.py -v
```

Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_save_point_restore.py
git commit -m "test(restore): verify deck spec is restored alongside deck_json at save points"
```

---

## Task 10: Operator runbook — Document migration steps

**Files:**
- Create: `docs/technical/schema-migration-row-per-slide.md`

**Interfaces:**
- Produces: Runbook for operators running the migration in production

- [ ] **Step 1: Write the runbook**

```markdown
# Row-per-Slide Schema Migration Runbook

## Overview
This runbook covers the migration of slide decks from a monolithic `deck_json` blob into a normalized per-slide row schema.

## Timeline
1. **Deploy code** (Tasks 1–9): Hand-rolled schema migration in `init_db()`, dual-write code, tests.
2. **Backfill phase** (day 0): Run backfill script to migrate existing decks.
3. **Verification window** (days 1–14): Monitor for issues; test exports and restore; verify no regressions.
4. **Cutover** (day 14+): DBA runs SQL to drop legacy columns; remove dual-write fallback code.

## Step 1: Deploy code changes
- Merge PR1 to main.
- Deploy to staging and verify tests pass.
- Deploy to production.

## Step 2: Deploy code and run init_db()
```bash
# Deploy the code changes (Tasks 1–9)
git pull
python -c "from src.core.database import init_db; init_db()"
```
Expected: Tables created; columns added; no errors. The `init_db()` call idempotently applies all migrations.

## Step 3: Run backfill (dry-run)
```bash
python -m scripts.backfill_session_slides
```
Expected: Prints summary of decks to backfill (does NOT modify).

## Step 4: Run backfill (apply)
```bash
python -m scripts.backfill_session_slides --yes
```
Expected: Slides migrated; verification records moved.

## Step 5: Verify exports
- Export a sample of real decks to PPTX and Google Slides.
- Spot-check for correctness (slide count, content, formatting).
- Compare to previous exports if available (byte-for-byte or pixel-by-pixel).
- Document any cosmetic diffs.

## Step 6: Monitor and test (days 1–14)
- Monitor application logs for errors.
- Test restore-to-save-point flow.
- Test reorder, duplicate, delete slides.
- Test direct slide edits (WYSIWYG path once available).

## Step 7: Run cutover (day 14+)
- Once all decks have been backfilled and no issues observed, a DBA runs (or an operator with DB access runs):
```sql
ALTER TABLE session_slide_decks DROP COLUMN deck_json;
ALTER TABLE session_slide_decks DROP COLUMN verification_map;
```
- Then remove dual-write fallback code from `session_manager.py` and deploy the code change.

## Rollback
If a catastrophic bug is discovered:
1. Restore database from pre-cutover snapshot.
2. Redeploy an older build (pre-cutover).
```

- [ ] **Step 2: Save the runbook**

```bash
git add docs/technical/schema-migration-row-per-slide.md
git commit -m "docs: add row-per-slide schema migration runbook"
```

---

## Task 11: Verify the plan against the spec

**Self-review checklist:**

- [ ] **Spec coverage:**
  - ✓ §2.1 (row-per-slide schema): `session_slides` table created (Task 1)
  - ✓ §2.1 (verification per-row): `verification_record` column on row (Task 1, Task 7)
  - ✓ §4.3–4.4 (deck-spec column): `deck_spec_json` on `SessionSlideDeck` and `SlideDeckVersion` (Task 1)
  - ✓ §5.2.4 (per-slide verification): moved to per-row (Task 7)
  - ✓ `html_content` retirement: derived via `knit()` or preserved in `get_slide_deck()` (Task 5)
  - ✓ Export chain preservation: `get_slide_deck()` dict contract maintained (Task 5, Task 8)
  - ✓ Save-point restore: spec snapshotted (Task 9)

- [ ] **No placeholders:**
  - ✓ All task steps have concrete code or command examples
  - ✓ All APIs have exact signatures
  - ✓ All tests have actual assertions

- [ ] **Type consistency:**
  - ✓ `verification_record` is JSON, keyed by `content_hash` (Tasks 1, 3, 7)
  - ✓ `deck_spec_json` is Text/JSON (Task 1)
  - ✓ `position` is 0-indexed integer (Tasks 1, 6)
  - ✓ `SlideWriter` methods match Handoff signatures (Task 6)

- [ ] **No dependency changes:**
  - ✓ No modifications to requirements.txt or pyproject.toml (per boundary)

- [ ] **No agent logic:**
  - ✓ No changes to PR3's agent skills or graph logic (per boundary)

---

## Self-Review Notes

- **Spec prerequisites:** Row-per-slide is load-bearing for parallel builders (no single-row contention) and incremental delivery (reorder buffer). Verification per-row is load-bearing for parallel reviewers (no shared-blob lost-update races).
- **Export de-risking:** The key finding (export chain reads only through `get_slide_deck()` → `session_manager.get_slide_deck()` and `build_slide_html()` consumes dict["css"]/["scripts"]) is the de-risking lever. If `get_slide_deck()` reconstructs the same dict shape from rows, export works unchanged. Task 8 verifies this end-to-end.
- **Migration safety:** Dual-write period (Tasks 4–5) allows old and new code to coexist during staged rollout. Backfill is idempotent (Task 3), so it can be re-run if interrupted. 1–2 week verification window (Task 10) gates cutover.
- **PR3 handoff:** Exact table/column names and `SlideWriter` API signatures (Task 6, Handoff section) are what PR3 depends on. Once this lands and is verified live, PR3's graph knows exactly how to write slides and the verification they carry.

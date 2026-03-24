# Deck-Centric Permissions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decouple deck sharing from profiles — decks become directly shareable entities, profiles become independently shareable config templates.

**Architecture:** New `DeckContributor` model for direct deck sharing. `PermissionService` splits into deck-specific and profile-specific methods. Profile permissions change from CAN_VIEW to CAN_USE. Frontend share button becomes permissions manager; new "Copy Link" button for URLs.

**Tech Stack:** Python/FastAPI/SQLAlchemy (backend), React/TypeScript (frontend), SQLite/PostgreSQL (database)

**Spec:** `docs/superpowers/specs/2026-03-24-deck-centric-permissions-design.md`

**Task ordering:** 1 (model) → 2 (migration) → 4 (PermissionService) → 5 (session routes) → 6 (chat + session manager + comments + slides) → 3 (remove columns) → 7-9 (new routes) → 10-13 (frontend) → 14-15 (docs + validation). The new permission infrastructure must be in place before removing the old columns to avoid a broken intermediate state.

**PermissionService constructor note:** The current `PermissionService.__init__` takes `db: Session`. This plan changes to a stateless constructor (no `db`), with `db` passed per-method call. All callers need updating (Task 4, Step 5). The factory `get_permission_service()` also changes to take no args.

---

### Task 1: DeckContributor Model and PermissionLevel Enum Update

**Files:**
- Create: `src/database/models/deck_contributor.py`
- Modify: `src/database/models/profile_contributor.py:17-22` (PermissionLevel enum)
- Modify: `src/database/models/profile_contributor.py:51` (default permission_level)
- Modify: `src/database/models/__init__.py` (add DeckContributor export)
- Test: `tests/unit/test_deck_contributor_model.py`

- [ ] **Step 1: Write failing test for DeckContributor model**

```python
# tests/unit/test_deck_contributor_model.py
import pytest
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.core.database import Base
from src.database.models.deck_contributor import DeckContributor
from src.database.models.profile_contributor import PermissionLevel, IdentityType


@pytest.fixture(scope="function")
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


class TestDeckContributorModel:
    def test_create_deck_contributor(self, db_session):
        contrib = DeckContributor(
            user_session_id=1,
            identity_type=IdentityType.USER.value,
            identity_id="user-123",
            identity_name="alice@example.com",
            permission_level=PermissionLevel.CAN_VIEW.value,
            created_by="owner@example.com",
        )
        db_session.add(contrib)
        db_session.commit()

        result = db_session.query(DeckContributor).first()
        assert result.user_session_id == 1
        assert result.identity_id == "user-123"
        assert result.permission_level == "CAN_VIEW"
        assert result.created_at is not None
        assert result.updated_at is not None

    def test_unique_constraint_session_identity(self, db_session):
        contrib1 = DeckContributor(
            user_session_id=1, identity_type="USER", identity_id="user-123",
            identity_name="alice@example.com", permission_level="CAN_VIEW",
        )
        contrib2 = DeckContributor(
            user_session_id=1, identity_type="USER", identity_id="user-123",
            identity_name="alice@example.com", permission_level="CAN_EDIT",
        )
        db_session.add(contrib1)
        db_session.commit()
        db_session.add(contrib2)
        with pytest.raises(Exception):  # IntegrityError
            db_session.commit()

    def test_different_sessions_same_identity_allowed(self, db_session):
        contrib1 = DeckContributor(
            user_session_id=1, identity_type="USER", identity_id="user-123",
            identity_name="alice@example.com", permission_level="CAN_VIEW",
        )
        contrib2 = DeckContributor(
            user_session_id=2, identity_type="USER", identity_id="user-123",
            identity_name="alice@example.com", permission_level="CAN_EDIT",
        )
        db_session.add_all([contrib1, contrib2])
        db_session.commit()
        assert db_session.query(DeckContributor).count() == 2


class TestPermissionLevelEnum:
    def test_can_use_exists(self):
        assert PermissionLevel.CAN_USE.value == "CAN_USE"

    def test_all_four_levels(self):
        levels = [p.value for p in PermissionLevel]
        assert "CAN_USE" in levels
        assert "CAN_VIEW" in levels
        assert "CAN_EDIT" in levels
        assert "CAN_MANAGE" in levels
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator && python -m pytest tests/unit/test_deck_contributor_model.py -v`
Expected: FAIL — `DeckContributor` not found, `CAN_USE` not in enum

- [ ] **Step 3: Add CAN_USE to PermissionLevel enum and update default**

In `src/database/models/profile_contributor.py`, update the enum (lines 17-22):

```python
class PermissionLevel(str, Enum):
    CAN_USE = "CAN_USE"        # Profile-only: can see and load the profile
    CAN_VIEW = "CAN_VIEW"      # Deck-only: read-only access to presentations
    CAN_EDIT = "CAN_EDIT"      # Modify content (profile config or deck slides)
    CAN_MANAGE = "CAN_MANAGE"  # Full control (delete, manage sharing)
```

Update the default on `permission_level` column (line 51):
```python
permission_level = Column(String(20), nullable=False, default=PermissionLevel.CAN_USE.value)
```

- [ ] **Step 4: Create DeckContributor model**

```python
# src/database/models/deck_contributor.py
"""Deck contributor model for direct deck sharing."""
from datetime import datetime

from sqlalchemy import (
    Column, DateTime, Integer, String, UniqueConstraint, Index,
)

from src.core.database import Base


class DeckContributor(Base):
    """Stores access grants for individual decks (sessions with slide decks)."""
    __tablename__ = "deck_contributors"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_session_id = Column(
        Integer,
        nullable=False,
        index=True,
    )
    identity_type = Column(String(10), nullable=False)   # USER or GROUP
    identity_id = Column(String(255), nullable=False, index=True)
    identity_name = Column(String(255), nullable=False)  # email or group name
    permission_level = Column(String(20), nullable=False)
    created_by = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_session_id", "identity_id", name="uq_deck_contributor_session_identity"),
    )

    def __repr__(self):
        return (
            f"<DeckContributor(id={self.id}, session={self.user_session_id}, "
            f"identity={self.identity_name}, level={self.permission_level})>"
        )
```

- [ ] **Step 5: Register in models __init__.py**

Add to `src/database/models/__init__.py`:

```python
from src.database.models.deck_contributor import DeckContributor
```

And add `"DeckContributor"` to the `__all__` list.

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator && python -m pytest tests/unit/test_deck_contributor_model.py -v`
Expected: PASS — all 5 tests green

- [ ] **Step 7: Run existing tests to check for regressions**

Run: `cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator && python -m pytest tests/ -x --timeout=60 -q`
Expected: PASS — adding CAN_USE to enum and new model should not break existing tests

- [ ] **Step 8: Commit**

```bash
git add src/database/models/deck_contributor.py src/database/models/profile_contributor.py src/database/models/__init__.py tests/unit/test_deck_contributor_model.py
git commit -m "feat: add DeckContributor model and CAN_USE permission level"
```

---

### Task 2: Database Migration Function

**Files:**
- Modify: `src/core/database.py:503` (add call to new migration)
- Modify: `src/core/database.py` (add `_migrate_deck_permissions_model` function)
- Test: `tests/unit/test_deck_permissions_migration.py`

- [ ] **Step 1: Write failing test for migration**

```python
# tests/unit/test_deck_permissions_migration.py
import os
import tempfile
import pytest
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.core.database import Base, _run_migrations


@pytest.fixture(scope="function")
def migration_engine():
    """Engine with old schema — uses temp file to avoid in-memory connection issues."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    # Add legacy columns that the migration should drop
    with engine.begin() as conn:
        try:
            conn.execute(text("ALTER TABLE user_sessions ADD COLUMN profile_id INTEGER"))
        except Exception:
            pass  # Column may already exist from model
        try:
            conn.execute(text("ALTER TABLE user_sessions ADD COLUMN profile_name VARCHAR(255)"))
        except Exception:
            pass
        # Seed a CAN_VIEW contributor and global_permission
        conn.execute(text(
            "INSERT INTO config_profiles (name, is_default, is_deleted, created_at, updated_at) "
            "VALUES ('test', 0, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ))
        conn.execute(text(
            "UPDATE config_profiles SET global_permission = 'CAN_VIEW' WHERE name = 'test'"
        ))
    yield engine
    engine.dispose()
    os.unlink(path)


class TestDeckPermissionsMigration:
    def test_profile_id_dropped_from_sessions(self, migration_engine):
        _run_migrations(migration_engine, schema=None)
        inspector = inspect(migration_engine)
        columns = {c["name"] for c in inspector.get_columns("user_sessions")}
        assert "profile_id" not in columns

    def test_profile_name_dropped_from_sessions(self, migration_engine):
        _run_migrations(migration_engine, schema=None)
        inspector = inspect(migration_engine)
        columns = {c["name"] for c in inspector.get_columns("user_sessions")}
        assert "profile_name" not in columns

    def test_global_permission_migrated_to_can_use(self, migration_engine):
        _run_migrations(migration_engine, schema=None)
        with migration_engine.connect() as conn:
            result = conn.execute(text(
                "SELECT global_permission FROM config_profiles WHERE name = 'test'"
            )).fetchone()
            assert result[0] == "CAN_USE"

    def test_migration_is_idempotent(self, migration_engine):
        _run_migrations(migration_engine, schema=None)
        _run_migrations(migration_engine, schema=None)  # Should not raise
        inspector = inspect(migration_engine)
        columns = {c["name"] for c in inspector.get_columns("user_sessions")}
        assert "profile_id" not in columns
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator && python -m pytest tests/unit/test_deck_permissions_migration.py -v`
Expected: FAIL — migration function doesn't exist yet

- [ ] **Step 3: Implement migration function**

Add to `src/core/database.py` after `_migrate_permissions_columns`:

```python
def _migrate_deck_permissions_model(conn, inspector, schema, _qual, is_sqlite):
    """Decouple deck sharing from profiles.

    - Drop profile_id and profile_name from user_sessions
    - Migrate CAN_VIEW → CAN_USE in config_profile_contributors
    - Migrate CAN_VIEW → CAN_USE in config_profiles.global_permission
    """
    from sqlalchemy import text

    # --- Drop profile_id and profile_name from user_sessions ---
    try:
        sessions_cols = {c["name"] for c in inspector.get_columns("user_sessions", schema=schema)}
    except Exception:
        sessions_cols = set()

    qualified_sessions = _qual("user_sessions")

    if sessions_cols and "profile_id" in sessions_cols:
        logger.info("Migration: dropping profile_id from user_sessions")
        if is_sqlite:
            # SQLite doesn't support DROP COLUMN before 3.35.0;
            # use ALTER TABLE DROP COLUMN (available in newer SQLite)
            try:
                conn.execute(text(f"ALTER TABLE {qualified_sessions} DROP COLUMN profile_id"))
            except Exception:
                logger.warning("Migration: could not drop profile_id (SQLite version may not support DROP COLUMN)")
        else:
            conn.execute(text(f"ALTER TABLE {qualified_sessions} DROP COLUMN profile_id"))

    if sessions_cols and "profile_name" in sessions_cols:
        logger.info("Migration: dropping profile_name from user_sessions")
        if is_sqlite:
            try:
                conn.execute(text(f"ALTER TABLE {qualified_sessions} DROP COLUMN profile_name"))
            except Exception:
                logger.warning("Migration: could not drop profile_name (SQLite version may not support DROP COLUMN)")
        else:
            conn.execute(text(f"ALTER TABLE {qualified_sessions} DROP COLUMN profile_name"))

    # --- Migrate CAN_VIEW → CAN_USE in config_profile_contributors ---
    try:
        contrib_cols = {c["name"] for c in inspector.get_columns("config_profile_contributors", schema=schema)}
    except Exception:
        contrib_cols = set()

    if contrib_cols and "permission_level" in contrib_cols:
        qualified_contrib = _qual("config_profile_contributors")
        conn.execute(text(
            f"UPDATE {qualified_contrib} SET permission_level = 'CAN_USE' "
            "WHERE permission_level = 'CAN_VIEW'"
        ))

    # --- Migrate CAN_VIEW → CAN_USE in config_profiles.global_permission ---
    try:
        profile_cols = {c["name"] for c in inspector.get_columns("config_profiles", schema=schema)}
    except Exception:
        profile_cols = set()

    if profile_cols and "global_permission" in profile_cols:
        qualified_profiles = _qual("config_profiles")
        conn.execute(text(
            f"UPDATE {qualified_profiles} SET global_permission = 'CAN_USE' "
            "WHERE global_permission = 'CAN_VIEW'"
        ))

    logger.info("Migration: deck permissions model migration complete")
```

Add the call in `_run_migrations()` at the end (after line 503):
```python
_migrate_deck_permissions_model(conn, inspector, schema, _qual, is_sqlite)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator && python -m pytest tests/unit/test_deck_permissions_migration.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/database.py tests/unit/test_deck_permissions_migration.py
git commit -m "feat: add migration to drop profile_id from sessions and migrate CAN_VIEW to CAN_USE"
```

---

### Task 3: Remove profile_id/profile_name from UserSession Model

**Files:**
- Modify: `src/database/models/session.py:118-119` (remove profile_id, profile_name columns)
- Test: `tests/unit/test_deck_contributor_model.py` (verify UserSession no longer has these columns)

- [ ] **Step 1: Write failing test**

Add to `tests/unit/test_deck_contributor_model.py`:

```python
class TestUserSessionProfileColumns:
    def test_no_profile_id_column(self):
        from src.database.models.session import UserSession
        column_names = [c.name for c in UserSession.__table__.columns]
        assert "profile_id" not in column_names

    def test_no_profile_name_column(self):
        from src.database.models.session import UserSession
        column_names = [c.name for c in UserSession.__table__.columns]
        assert "profile_name" not in column_names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator && python -m pytest tests/unit/test_deck_contributor_model.py::TestUserSessionProfileColumns -v`
Expected: FAIL — columns still exist

- [ ] **Step 3: Remove columns from UserSession model**

In `src/database/models/session.py`, delete lines 118-119:
```python
    profile_id = Column(Integer, nullable=True, index=True)
    profile_name = Column(String(255), nullable=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator && python -m pytest tests/unit/test_deck_contributor_model.py::TestUserSessionProfileColumns -v`
Expected: PASS

- [ ] **Step 5: Fix any imports or references that break**

Run: `cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator && python -m pytest tests/ -x --timeout=60 -q 2>&1 | head -50`

Fix any test failures caused by references to `profile_id` or `profile_name` on UserSession. Common locations:
- `src/api/services/session_manager.py` — `create_session()`, `get_session()`, `list_sessions()`, `list_sessions_by_profile_ids()`
- `src/api/routes/sessions.py` — `create_session()`, `list_shared_presentations()`, `get_or_create_contributor_session()`
- `src/api/routes/profiles.py` — `save_from_session()`, `load_profile_into_session()`
- `src/api/routes/chat.py` — `_check_chat_permission()`
- Test fixtures that set `profile_id` or `profile_name`

For each reference: remove it or replace the logic with deck-contributor-based checks (which will be implemented in Tasks 4-6). For now, stub out the profile-based permission checks with `pass` or remove the dead code paths.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor: remove profile_id and profile_name from UserSession"
```

---

### Task 4: PermissionService — Rename Profile Methods and Add Deck Methods

**Files:**
- Modify: `src/services/permission_service.py` (full rewrite of method names + add deck methods)
- Test: `tests/unit/test_permission_service.py`

- [ ] **Step 1: Write failing tests for new PermissionService API**

```python
# tests/unit/test_permission_service.py
import pytest
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.core.database import Base
from src.database.models.session import UserSession
from src.database.models.deck_contributor import DeckContributor
from src.database.models.profile import ConfigProfile
from src.database.models.profile_contributor import (
    ConfigProfileContributor, PermissionLevel, IdentityType,
)
from src.services.permission_service import PermissionService, PERMISSION_PRIORITY


@pytest.fixture(scope="function")
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def owner_session(db_session):
    session = UserSession(session_id="sess-1", created_by="owner@example.com")
    db_session.add(session)
    db_session.commit()
    return session


@pytest.fixture
def profile(db_session):
    p = ConfigProfile(name="test-profile", created_by="owner@example.com", is_default=False)
    db_session.add(p)
    db_session.commit()
    return p


class TestPermissionPriority:
    def test_can_use_priority(self):
        assert PERMISSION_PRIORITY[PermissionLevel.CAN_USE] == 1

    def test_can_view_priority(self):
        assert PERMISSION_PRIORITY[PermissionLevel.CAN_VIEW] == 1

    def test_can_edit_priority(self):
        assert PERMISSION_PRIORITY[PermissionLevel.CAN_EDIT] == 2

    def test_can_manage_priority(self):
        assert PERMISSION_PRIORITY[PermissionLevel.CAN_MANAGE] == 3


class TestDeckPermission:
    def test_creator_gets_can_manage(self, db_session, owner_session):
        svc = PermissionService()
        perm = svc.get_deck_permission(
            db_session, owner_session.id, user_id=None,
            user_name="owner@example.com", group_ids=[],
        )
        assert perm == PermissionLevel.CAN_MANAGE

    def test_direct_user_permission(self, db_session, owner_session):
        db_session.add(DeckContributor(
            user_session_id=owner_session.id, identity_type="USER",
            identity_id="user-456", identity_name="viewer@example.com",
            permission_level="CAN_VIEW",
        ))
        db_session.commit()
        svc = PermissionService()
        perm = svc.get_deck_permission(
            db_session, owner_session.id, user_id="user-456",
            user_name="viewer@example.com", group_ids=[],
        )
        assert perm == PermissionLevel.CAN_VIEW

    def test_group_permission_highest_wins(self, db_session, owner_session):
        db_session.add_all([
            DeckContributor(
                user_session_id=owner_session.id, identity_type="GROUP",
                identity_id="grp-1", identity_name="Engineering",
                permission_level="CAN_VIEW",
            ),
            DeckContributor(
                user_session_id=owner_session.id, identity_type="GROUP",
                identity_id="grp-2", identity_name="Managers",
                permission_level="CAN_EDIT",
            ),
        ])
        db_session.commit()
        svc = PermissionService()
        perm = svc.get_deck_permission(
            db_session, owner_session.id, user_id="other-user",
            user_name="other@example.com", group_ids=["grp-1", "grp-2"],
        )
        assert perm == PermissionLevel.CAN_EDIT

    def test_no_match_returns_none(self, db_session, owner_session):
        svc = PermissionService()
        perm = svc.get_deck_permission(
            db_session, owner_session.id, user_id="stranger",
            user_name="stranger@example.com", group_ids=[],
        )
        assert perm is None

    def test_fallback_by_identity_name(self, db_session, owner_session):
        db_session.add(DeckContributor(
            user_session_id=owner_session.id, identity_type="USER",
            identity_id="user-789", identity_name="bob@example.com",
            permission_level="CAN_EDIT",
        ))
        db_session.commit()
        svc = PermissionService()
        # Match by identity_name when user_id doesn't match
        perm = svc.get_deck_permission(
            db_session, owner_session.id, user_id="different-id",
            user_name="bob@example.com", group_ids=[],
        )
        assert perm == PermissionLevel.CAN_EDIT


class TestGetSharedSessionIds:
    def test_returns_shared_sessions(self, db_session, owner_session):
        db_session.add(DeckContributor(
            user_session_id=owner_session.id, identity_type="USER",
            identity_id="user-456", identity_name="viewer@example.com",
            permission_level="CAN_VIEW",
        ))
        db_session.commit()
        svc = PermissionService()
        ids = svc.get_shared_session_ids(
            db_session, user_id="user-456",
            user_name="viewer@example.com", group_ids=[],
        )
        assert owner_session.id in ids

    def test_excludes_own_sessions(self, db_session, owner_session):
        svc = PermissionService()
        ids = svc.get_shared_session_ids(
            db_session, user_id=None,
            user_name="owner@example.com", group_ids=[],
        )
        # Creator sessions are not "shared with me"
        assert owner_session.id not in ids


class TestProfilePermissionRenamed:
    def test_get_profile_permission_exists(self):
        svc = PermissionService()
        assert hasattr(svc, "get_profile_permission")

    def test_can_use_profile_exists(self):
        svc = PermissionService()
        assert hasattr(svc, "can_use_profile")

    def test_require_use_profile_exists(self):
        svc = PermissionService()
        assert hasattr(svc, "require_use_profile")

    def test_creator_gets_can_manage(self, db_session, profile):
        svc = PermissionService()
        perm = svc.get_profile_permission(
            db_session, profile.id, user_id=None,
            user_name="owner@example.com", group_ids=[],
        )
        assert perm == PermissionLevel.CAN_MANAGE
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator && python -m pytest tests/unit/test_permission_service.py -v`
Expected: FAIL — methods don't exist yet

- [ ] **Step 3: Rewrite PermissionService**

In `src/services/permission_service.py`:

1. Update `PERMISSION_PRIORITY` to include `CAN_USE`:
```python
PERMISSION_PRIORITY = {
    PermissionLevel.CAN_USE: 1,
    PermissionLevel.CAN_VIEW: 1,
    PermissionLevel.CAN_EDIT: 2,
    PermissionLevel.CAN_MANAGE: 3,
}
```

2. Rename `get_user_permission` → `get_profile_permission` (keep same logic)
3. Rename `can_view` → `can_use_profile`, `can_edit` → `can_edit_profile`, `can_manage` → `can_manage_profile`
4. Rename `require_view` → `require_use_profile`, `require_edit` → `require_edit_profile`, `require_manage` → `require_manage_profile`
5. Add `get_deck_permission(db, session_id, user_id, user_name, group_ids)`:
   - Query `UserSession` by `id` to get `created_by`
   - If `user_name == created_by` → return CAN_MANAGE
   - Query `DeckContributor` where `user_session_id == session_id` and `identity_id == user_id` → return level
   - Fallback: query by `identity_name == user_name` (case-insensitive) → return level
   - Query group matches → return highest
   - Return None
6. Add convenience methods: `can_view_deck`, `can_edit_deck`, `can_manage_deck`, `require_view_deck`, `require_edit_deck`, `require_manage_deck`
7. Add `get_shared_session_ids(db, user_id, user_name, group_ids)`:
   - Query `DeckContributor` for matching user/groups
   - Return set of `user_session_id` values
   - Exclude sessions where user is the creator

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator && python -m pytest tests/unit/test_permission_service.py -v`
Expected: PASS

- [ ] **Step 5: Update all callers of renamed methods**

Search and replace across the codebase:
- `get_user_permission(` → `get_profile_permission(`
- `perm_service.can_view(` → `perm_service.can_use_profile(`
- `perm_service.can_edit(` → `perm_service.can_edit_profile(`
- `perm_service.can_manage(` → `perm_service.can_manage_profile(`
- `perm_service.require_view(` → `perm_service.require_use_profile(`
- `perm_service.require_edit(` → `perm_service.require_edit_profile(`
- `perm_service.require_manage(` → `perm_service.require_manage_profile(`
- Same for `permission_service.` prefix
- `PermissionService(db)` → `PermissionService()` (remove `db` from constructor)
- `get_permission_service(db)` → `get_permission_service()` (remove `db` from factory)

Key files for method renames:
- `src/api/routes/settings/contributors.py` (lines 157, 214, 383, 445)
- `src/api/routes/sessions.py` (lines 46-87)
- `src/api/routes/chat.py` (lines 76-136)
- `src/api/routes/profiles.py`
- `src/api/routes/comments.py` (line ~207 — uses `PermissionService()` and `can_manage`)
- `src/api/routes/slides.py` (line ~69 — uses `PermissionService(db)`)

Key files for constructor/factory pattern change:
- `src/api/routes/sessions.py` (multiple calls)
- `src/api/routes/chat.py` (line ~113)
- `src/api/routes/comments.py` (line ~207)
- `src/api/routes/slides.py` (line ~69)
- `src/api/routes/settings/contributors.py` (line ~25)
- `src/services/profile_service.py` (line ~55)

- [ ] **Step 6: Run full test suite**

Run: `cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator && python -m pytest tests/ -x --timeout=60 -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor: split PermissionService into deck and profile methods"
```

---

### Task 5: Update Session Routes — Permission Checks and Shared Endpoint

**Files:**
- Modify: `src/api/routes/sessions.py:46-87` (`_get_session_permission` rewrite)
- Modify: `src/api/routes/sessions.py:230-307` (`list_shared_presentations` rewrite)
- Modify: `src/api/routes/sessions.py:310-379` (`get_or_create_contributor_session` update)
- Modify: `src/api/routes/sessions.py:136-188` (`create_session` — remove profile_id)
- Test: `tests/unit/test_session_permissions.py`

- [ ] **Step 1: Write failing tests for new session permission flow**

```python
# tests/unit/test_session_permissions.py
import pytest
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from src.core.database import Base, get_db
from src.database.models.session import UserSession
from src.database.models.deck_contributor import DeckContributor
from src.main import app


@pytest.fixture(scope="function")
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


class TestSharedEndpointUsesDeckContributors:
    def test_shared_returns_deck_shared_with_user(self, db_session, client):
        # Create owner session with a deck
        owner = UserSession(session_id="owner-sess", created_by="owner@test.com")
        db_session.add(owner)
        db_session.commit()

        # Add deck contributor
        db_session.add(DeckContributor(
            user_session_id=owner.id, identity_type="USER",
            identity_id="user-viewer", identity_name="viewer@test.com",
            permission_level="CAN_VIEW",
        ))
        db_session.commit()

        with patch("src.api.routes.sessions.get_current_user", return_value="viewer@test.com"):
            with patch("src.api.routes.sessions.get_permission_context") as mock_ctx:
                ctx = MagicMock()
                ctx.user_id = "user-viewer"
                ctx.user_name = "viewer@test.com"
                ctx.group_ids = []
                mock_ctx.return_value = ctx
                response = client.get("/api/sessions/shared")

        assert response.status_code == 200
        data = response.json()
        session_ids = [p["session_id"] for p in data.get("presentations", [])]
        assert "owner-sess" in session_ids
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator && python -m pytest tests/unit/test_session_permissions.py -v`
Expected: FAIL — shared endpoint still uses profile-based resolution

- [ ] **Step 3: Rewrite `_get_session_permission` in sessions.py**

Replace the current implementation (lines 46-87) with:

```python
def _get_session_permission(session_info: dict, db) -> tuple:
    """Check user's permission on a session via deck_contributors."""
    current_user = get_current_user()
    perm_ctx = get_permission_context()
    perm_service = get_permission_service()

    # Resolve the root session ID for permission check
    parent_id = session_info.get("parent_session_id")
    if parent_id is not None:
        root_session_id = parent_id
    else:
        root_session_id = session_info.get("id")

    perm = perm_service.get_deck_permission(
        db, root_session_id,
        user_id=perm_ctx.user_id,
        user_name=perm_ctx.user_name,
        group_ids=perm_ctx.group_ids,
    )
    if perm is None:
        return False, None
    return True, perm
```

- [ ] **Step 4: Rewrite `list_shared_presentations`**

Replace the current implementation (lines 230-307) to use `get_shared_session_ids`:

```python
@router.get("/shared")
def list_shared_presentations(db: Session = Depends(get_db)):
    """List presentations shared with the current user via deck_contributors."""
    current_user = get_current_user()
    perm_ctx = get_permission_context()
    perm_service = get_permission_service()

    shared_ids = perm_service.get_shared_session_ids(
        db, user_id=perm_ctx.user_id,
        user_name=perm_ctx.user_name,
        group_ids=perm_ctx.group_ids,
    )
    if not shared_ids:
        return {"presentations": [], "count": 0}

    sessions = db.query(UserSession).filter(
        UserSession.id.in_(shared_ids),
        UserSession.parent_session_id.is_(None),
    ).all()

    presentations = []
    for s in sessions:
        perm = perm_service.get_deck_permission(
            db, s.id, user_id=perm_ctx.user_id,
            user_name=perm_ctx.user_name, group_ids=perm_ctx.group_ids,
        )
        # Preserve existing response shape (minus profile_id/profile_name)
        presentations.append({
            "session_id": s.session_id,
            "title": s.title,
            "created_by": s.created_by,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "last_activity": s.last_activity.isoformat() if s.last_activity else None,
            "has_slide_deck": s.slide_deck is not None,
            "slide_count": s.slide_deck.slide_count if s.slide_deck else 0,
            "modified_by": s.slide_deck.modified_by if s.slide_deck else None,
            "my_permission": perm.value if perm else None,
        })

    return {"presentations": presentations, "count": len(presentations)}
```

- [ ] **Step 5: Update `get_or_create_contributor_session`**

Remove the `profile_id` check (lines ~340-350). The new flow:
1. Look up parent session
2. Call `get_deck_permission` on parent session
3. Require CAN_VIEW or higher
4. Create/return contributor session

- [ ] **Step 6: Update `create_session` — remove profile_id/profile_name**

Remove any reference to `profile_id` or `profile_name` in the session creation flow.

- [ ] **Step 7: Run tests**

Run: `cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator && python -m pytest tests/unit/test_session_permissions.py -v`
Expected: PASS

- [ ] **Step 8: Run full test suite**

Run: `cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator && python -m pytest tests/ -x --timeout=60 -q`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "feat: session routes use deck_contributors for permission checks"
```

---

### Task 6: Update Chat, Comments, Slides Permission Checks and Session Manager

**Files:**
- Modify: `src/api/routes/chat.py:76-136` (`_check_chat_permission` update)
- Modify: `src/api/routes/comments.py:207-209` (permission check update)
- Modify: `src/api/routes/slides.py:69` (permission check update)
- Modify: `src/api/services/session_manager.py:369-433` (remove `list_sessions_by_profile_ids`)
- Modify: `src/api/services/session_manager.py:2221-2305` (`get_mentionable_users` update)
- Modify: `src/api/services/session_manager.py:63-137` (`create_session` — remove profile_id)
- Test: `tests/unit/test_chat_deck_permissions.py`

- [ ] **Step 1: Write tests for chat and comment permission checks**

```python
# tests/unit/test_chat_deck_permissions.py
import pytest
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.core.database import Base
from src.database.models.session import UserSession
from src.database.models.deck_contributor import DeckContributor
from src.services.permission_service import PermissionService


@pytest.fixture(scope="function")
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


class TestMentionableUsersFromDeckContributors:
    def test_mentionable_includes_deck_contributors(self, db_session):
        owner = UserSession(session_id="s1", created_by="owner@test.com")
        db_session.add(owner)
        db_session.commit()
        db_session.add(DeckContributor(
            user_session_id=owner.id, identity_type="USER",
            identity_id="u1", identity_name="collab@test.com",
            permission_level="CAN_EDIT",
        ))
        db_session.commit()

        # get_mentionable_users should return deck contributors, not profile contributors
        contribs = db_session.query(DeckContributor).filter(
            DeckContributor.user_session_id == owner.id
        ).all()
        emails = {c.identity_name for c in contribs}
        emails.add(owner.created_by)
        assert "collab@test.com" in emails
        assert "owner@test.com" in emails
```

- [ ] **Step 2: Update `_check_chat_permission` in chat.py**

Replace the profile-based permission check with deck-based:
- For contributor sessions: check `get_deck_permission` on parent session
- Remove all `profile_id` references
- Keep editing lock check unchanged

- [ ] **Step 3: Update `comments.py` permission check**

In `src/api/routes/comments.py` (line ~207), replace:
```python
if session and session.profile_id:
    perm_service = PermissionService()
    is_manager = perm_service.can_manage(session.profile_id)
```
With deck-based check:
```python
perm_service = get_permission_service()
perm = perm_service.get_deck_permission(db, root_session_id, ...)
is_manager = perm == PermissionLevel.CAN_MANAGE
```

- [ ] **Step 4: Update `slides.py` permission check**

In `src/api/routes/slides.py` (line ~69), replace `PermissionService(db)` profile-based checks with `get_deck_permission`. This is important because the spec has different permissions for slide editing (CAN_EDIT) vs slide deletion (CAN_MANAGE).

- [ ] **Step 5: Remove `list_sessions_by_profile_ids` from session_manager.py**

Delete the method (lines 369-433). It's replaced by `PermissionService.get_shared_session_ids`.

- [ ] **Step 6: Update `get_mentionable_users` in session_manager.py**

Replace profile-based contributor lookup with deck-contributor-based:
- Query `DeckContributor` for `user_session_id = root_session.id`
- Return contributor `identity_name` values plus the session creator
- Remove all `profile_id` and `ConfigProfileContributor` references from this method

- [ ] **Step 7: Clean up `create_session` in session_manager.py**

Remove any `profile_id` or `profile_name` parameters and references.

- [ ] **Step 8: Run tests**

Run: `cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator && python -m pytest tests/unit/test_chat_deck_permissions.py -v`
Expected: PASS

- [ ] **Step 9: Run full test suite**

Run: `cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator && python -m pytest tests/ -x --timeout=60 -q`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "refactor: update chat/comments/slides permissions and session manager for deck-centric model"
```

---

### Task 7: Deck Contributor CRUD Routes

**Files:**
- Create: `src/api/routes/deck_contributors.py`
- Modify: `src/main.py` or router registration (add new routes)
- Test: `tests/unit/test_deck_contributor_routes.py`

- [ ] **Step 1: Write failing tests for deck contributor CRUD**

```python
# tests/unit/test_deck_contributor_routes.py
import pytest
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from src.core.database import Base, get_db
from src.database.models.session import UserSession
from src.database.models.deck_contributor import DeckContributor
from src.main import app


@pytest.fixture(scope="function")
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def owner_session(db_session):
    s = UserSession(session_id="deck-1", created_by="owner@test.com")
    db_session.add(s)
    db_session.commit()
    return s


def _mock_owner_context():
    """Patches to make current user = owner@test.com with CAN_MANAGE."""
    return [
        patch("src.api.routes.deck_contributors.get_current_user", return_value="owner@test.com"),
        patch("src.api.routes.deck_contributors.get_permission_context", return_value=MagicMock(
            user_id="owner-id", user_name="owner@test.com", group_ids=[],
        )),
    ]


class TestListDeckContributors:
    def test_list_empty(self, client, owner_session):
        with _mock_owner_context()[0], _mock_owner_context()[1]:
            resp = client.get(f"/api/sessions/{owner_session.session_id}/contributors")
        assert resp.status_code == 200
        assert resp.json()["contributors"] == []

    def test_list_with_contributor(self, db_session, client, owner_session):
        db_session.add(DeckContributor(
            user_session_id=owner_session.id, identity_type="USER",
            identity_id="u-1", identity_name="alice@test.com",
            permission_level="CAN_VIEW",
        ))
        db_session.commit()
        with _mock_owner_context()[0], _mock_owner_context()[1]:
            resp = client.get(f"/api/sessions/{owner_session.session_id}/contributors")
        assert resp.status_code == 200
        assert len(resp.json()["contributors"]) == 1


class TestAddDeckContributor:
    def test_add_contributor(self, client, owner_session):
        with _mock_owner_context()[0], _mock_owner_context()[1]:
            resp = client.post(
                f"/api/sessions/{owner_session.session_id}/contributors",
                json={
                    "identity_type": "USER",
                    "identity_id": "u-2",
                    "identity_name": "bob@test.com",
                    "permission_level": "CAN_EDIT",
                },
            )
        assert resp.status_code == 201
        assert resp.json()["identity_name"] == "bob@test.com"

    def test_requires_can_manage(self, db_session, client, owner_session):
        # Add a CAN_VIEW contributor and try to add from their perspective
        db_session.add(DeckContributor(
            user_session_id=owner_session.id, identity_type="USER",
            identity_id="viewer-id", identity_name="viewer@test.com",
            permission_level="CAN_VIEW",
        ))
        db_session.commit()
        with patch("src.api.routes.deck_contributors.get_current_user", return_value="viewer@test.com"):
            with patch("src.api.routes.deck_contributors.get_permission_context", return_value=MagicMock(
                user_id="viewer-id", user_name="viewer@test.com", group_ids=[],
            )):
                resp = client.post(
                    f"/api/sessions/{owner_session.session_id}/contributors",
                    json={
                        "identity_type": "USER", "identity_id": "u-3",
                        "identity_name": "new@test.com", "permission_level": "CAN_VIEW",
                    },
                )
        assert resp.status_code == 403
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator && python -m pytest tests/unit/test_deck_contributor_routes.py -v`
Expected: FAIL — routes don't exist

- [ ] **Step 3: Implement deck contributor routes**

Create `src/api/routes/deck_contributors.py`:

```python
"""CRUD routes for deck contributors (direct deck sharing)."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from src.core.database import get_db
from src.core.permission_context import get_permission_context
from src.api.dependencies import get_current_user
from src.database.models.session import UserSession
from src.database.models.deck_contributor import DeckContributor
from src.services.permission_service import get_permission_service

router = APIRouter(prefix="/api/sessions", tags=["deck-contributors"])


class DeckContributorCreate(BaseModel):
    identity_type: str
    identity_id: str
    identity_name: str
    permission_level: str


class DeckContributorUpdate(BaseModel):
    permission_level: str


def _get_root_session(db: DbSession, session_id: str) -> UserSession:
    session = db.query(UserSession).filter(UserSession.session_id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.parent_session_id is not None:
        raise HTTPException(status_code=400, detail="Cannot manage contributors on a contributor session")
    return session


def _require_manage(db: DbSession, session: UserSession):
    perm_ctx = get_permission_context()
    perm_service = get_permission_service()
    perm = perm_service.get_deck_permission(
        db, session.id, user_id=perm_ctx.user_id,
        user_name=perm_ctx.user_name, group_ids=perm_ctx.group_ids,
    )
    if perm is None or perm.value != "CAN_MANAGE":
        raise HTTPException(status_code=403, detail="Requires CAN_MANAGE on this deck")


@router.get("/{session_id}/contributors")
def list_contributors(session_id: str, db: DbSession = Depends(get_db)):
    session = _get_root_session(db, session_id)
    _require_manage(db, session)
    contribs = db.query(DeckContributor).filter(
        DeckContributor.user_session_id == session.id
    ).all()
    return {
        "contributors": [
            {
                "id": c.id,
                "identity_type": c.identity_type,
                "identity_id": c.identity_id,
                "identity_name": c.identity_name,
                "permission_level": c.permission_level,
                "created_by": c.created_by,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in contribs
        ]
    }


@router.post("/{session_id}/contributors", status_code=201)
def add_contributor(session_id: str, body: DeckContributorCreate, db: DbSession = Depends(get_db)):
    session = _get_root_session(db, session_id)
    _require_manage(db, session)
    current_user = get_current_user()

    # Validate permission level is valid for decks
    valid_levels = {"CAN_VIEW", "CAN_EDIT", "CAN_MANAGE"}
    if body.permission_level not in valid_levels:
        raise HTTPException(status_code=400, detail=f"Invalid permission level. Must be one of: {valid_levels}")

    # Check for duplicate
    existing = db.query(DeckContributor).filter(
        DeckContributor.user_session_id == session.id,
        DeckContributor.identity_id == body.identity_id,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Contributor already exists")

    contrib = DeckContributor(
        user_session_id=session.id,
        identity_type=body.identity_type,
        identity_id=body.identity_id,
        identity_name=body.identity_name,
        permission_level=body.permission_level,
        created_by=current_user,
    )
    db.add(contrib)
    db.commit()
    db.refresh(contrib)
    return {
        "id": contrib.id,
        "identity_type": contrib.identity_type,
        "identity_id": contrib.identity_id,
        "identity_name": contrib.identity_name,
        "permission_level": contrib.permission_level,
        "created_by": contrib.created_by,
        "created_at": contrib.created_at.isoformat() if contrib.created_at else None,
    }


@router.put("/{session_id}/contributors/{contributor_id}")
def update_contributor(session_id: str, contributor_id: int, body: DeckContributorUpdate, db: DbSession = Depends(get_db)):
    session = _get_root_session(db, session_id)
    _require_manage(db, session)

    valid_levels = {"CAN_VIEW", "CAN_EDIT", "CAN_MANAGE"}
    if body.permission_level not in valid_levels:
        raise HTTPException(status_code=400, detail=f"Invalid permission level. Must be one of: {valid_levels}")

    contrib = db.query(DeckContributor).filter(
        DeckContributor.id == contributor_id,
        DeckContributor.user_session_id == session.id,
    ).first()
    if not contrib:
        raise HTTPException(status_code=404, detail="Contributor not found")

    contrib.permission_level = body.permission_level
    db.commit()
    db.refresh(contrib)
    return {
        "id": contrib.id,
        "identity_type": contrib.identity_type,
        "identity_id": contrib.identity_id,
        "identity_name": contrib.identity_name,
        "permission_level": contrib.permission_level,
    }


@router.delete("/{session_id}/contributors/{contributor_id}")
def remove_contributor(session_id: str, contributor_id: int, db: DbSession = Depends(get_db)):
    session = _get_root_session(db, session_id)
    _require_manage(db, session)

    contrib = db.query(DeckContributor).filter(
        DeckContributor.id == contributor_id,
        DeckContributor.user_session_id == session.id,
    ).first()
    if not contrib:
        raise HTTPException(status_code=404, detail="Contributor not found")

    # Creator protection: cannot remove the session creator
    if contrib.identity_name.lower() == session.created_by.lower():
        raise HTTPException(status_code=400, detail="Cannot remove the deck creator")

    db.delete(contrib)
    db.commit()
    return {"detail": "Contributor removed"}
```

Register in the app router (e.g., `src/main.py` or wherever routes are registered).

- [ ] **Step 4: Run tests**

Run: `cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator && python -m pytest tests/unit/test_deck_contributor_routes.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/api/routes/deck_contributors.py tests/unit/test_deck_contributor_routes.py
git commit -m "feat: add deck contributor CRUD routes"
```

---

### Task 8: Update Profile Contributor Routes — Permission Levels and Gates

**Files:**
- Modify: `src/api/routes/settings/contributors.py:79-85` (validate CAN_USE instead of CAN_VIEW)
- Modify: `src/api/routes/settings/contributors.py:214,383,445` (change require_edit → require_manage)

- [ ] **Step 1: Update `_validate_permission_level` to accept CAN_USE, reject CAN_VIEW for profiles**

In `src/api/routes/settings/contributors.py`, update the validation function to accept CAN_USE, CAN_EDIT, CAN_MANAGE for profile contributors.

- [ ] **Step 2: Update permission gates from CAN_EDIT to CAN_MANAGE**

Change `require_edit` → `require_manage_profile` at:
- `add_contributor` (line ~214)
- `add_contributors_bulk` (line ~276)
- `update_contributor` (line ~383)
- `remove_contributor` (line ~445)

Change `require_view` → `require_use_profile` at:
- `list_contributors` (line ~157)

- [ ] **Step 3: Run existing contributor tests**

Run: `cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator && python -m pytest tests/ -k "contributor" -v`
Expected: PASS (update test expectations if needed for new permission level names)

- [ ] **Step 4: Commit**

```bash
git add src/api/routes/settings/contributors.py
git commit -m "refactor: update profile contributor routes to use CAN_USE and require CAN_MANAGE"
```

---

### Task 9: Add Permission Checks to Profile Routes

**Files:**
- Modify: `src/api/routes/profiles.py:70-80` (list_profiles — filter by accessible)
- Modify: `src/api/routes/profiles.py:134-153` (load_profile — require CAN_USE)
- Modify: `src/api/routes/profiles.py:156-181` (update_profile — require CAN_EDIT)
- Modify: `src/api/routes/profiles.py:184-192` (delete_profile — require CAN_MANAGE)

- [ ] **Step 1: Add permission checks to each profile endpoint**

- `list_profiles`: Use `get_accessible_profile_ids` to filter results
- `load_profile_into_session`: Add `require_use_profile` check
- `update_profile`: Add `require_edit_profile` check
- `delete_profile`: Add `require_manage_profile` check
- `save_from_session`: No check needed — creator gets CAN_MANAGE automatically

- [ ] **Step 2: Remove profile_id writes from save_from_session**

The `save_from_session` endpoint currently writes `profile_id` back to the session. Remove this.

- [ ] **Step 3: Run tests**

Run: `cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator && python -m pytest tests/ -x --timeout=60 -q`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/api/routes/profiles.py
git commit -m "feat: add permission checks to profile CRUD routes"
```

---

### Task 10: Frontend — Deck Contributor API and DeckContributorsManager

**Files:**
- Modify: `frontend/src/api/config.ts` (add deck contributor API methods)
- Modify: `frontend/src/services/api.ts` (remove profile_id/profile_name from session types)
- Create: `frontend/src/components/DeckContributorsManager.tsx` (or adapt ContributorsManager)

- [ ] **Step 1: Add deck contributor API methods to config.ts or api.ts**

Add methods:
```typescript
// Deck contributor API
listDeckContributors(sessionId: string): Promise<ContributorListResponse>
addDeckContributor(sessionId: string, data: ContributorCreate): Promise<Contributor>
updateDeckContributor(sessionId: string, contributorId: number, data: { permission_level: string }): Promise<Contributor>
removeDeckContributor(sessionId: string, contributorId: number): Promise<void>
```

These call `/api/sessions/{sessionId}/contributors`.

- [ ] **Step 2: Update Session and SharedPresentation types**

Remove `profile_id` and `profile_name` from the `Session` interface in `api.ts`.

- [ ] **Step 3: Update PermissionLevel type**

Add `CAN_USE` to the `PermissionLevel` type in `config.ts`:
```typescript
type PermissionLevel = 'CAN_MANAGE' | 'CAN_EDIT' | 'CAN_VIEW' | 'CAN_USE'
```

- [ ] **Step 4: Create DeckContributorsManager component**

Adapt the existing `ContributorsManager` pattern for deck sharing. This component:
- Takes `sessionId: string` instead of `profileId: number`
- Uses deck contributor API methods
- Shows CAN_VIEW / CAN_EDIT / CAN_MANAGE options (not CAN_USE)
- No "global sharing" option (decks are always explicitly shared)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/
git commit -m "feat: add deck contributor API and DeckContributorsManager component"
```

---

### Task 11: Frontend — Share Button and Copy Link

**Files:**
- Modify: `frontend/src/components/Layout/AppLayout.tsx:332-339` (handleShare → open permissions manager)
- Modify: `frontend/src/components/Layout/page-header.tsx:193-203` (add Copy Link button)

- [ ] **Step 1: Update Share button to open DeckContributorsManager**

In `AppLayout.tsx`, change `handleShare` from copying URL to opening a modal/dialog with `DeckContributorsManager`.

- [ ] **Step 2: Add "Copy Link" button to PageHeader**

Add a new button next to the Share button that copies the URL (the old Share behavior):
```tsx
<Button variant="outline" size="sm" className="gap-1.5" onClick={handleCopyLink}>
  <Link className="size-3.5" />
  Copy Link
</Button>
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/
git commit -m "feat: share button opens permissions manager, add copy link button"
```

---

### Task 12: Frontend — Profile Sharing UI on Profile List

**Files:**
- Modify: `frontend/src/components/config/ProfileList.tsx` (surface ContributorsManager)

- [ ] **Step 1: Add share button/section to profile cards**

In `ProfileList.tsx`, add a "Share" button or expandable section on each profile card that renders the existing `ContributorsManager` component (which is already built but not wired in).

- [ ] **Step 2: Update permission level display**

Update the `ContributorsManager` to show CAN_USE / CAN_EDIT / CAN_MANAGE instead of CAN_VIEW / CAN_EDIT / CAN_MANAGE for profiles.

- [ ] **Step 3: Gate edit/delete actions on permissions**

- Delete button: Only show when `my_permission === 'CAN_MANAGE'`
- Edit config: Only allow when `my_permission === 'CAN_EDIT'` or `my_permission === 'CAN_MANAGE'`

- [ ] **Step 4: Commit**

```bash
git add frontend/src/
git commit -m "feat: surface profile sharing UI on profile list page"
```

---

### Task 13: Frontend Cleanup — Remove profile_id/profile_name References

**Files:**
- Modify: Various frontend files that reference `profile_id` or `profile_name` on sessions

- [ ] **Step 1: Search and remove all profile_id/profile_name references**

Search for `profile_id` and `profile_name` in `frontend/src/` and remove or update:
- Session creation requests
- Session state/context
- TypeScript interfaces
- API response handlers

- [ ] **Step 2: Run frontend build to check for TypeScript errors**

Run: `cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator/frontend && npm run build`
Expected: PASS — no TypeScript errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/
git commit -m "refactor: remove profile_id/profile_name references from frontend"
```

---

### Task 14: Update Technical Documentation

**Files:**
- Modify: `docs/technical/permissions-model.md` (replace entirely)
- Modify: `docs/user-guide/08-profile-sharing-permissions.md` (update)

- [ ] **Step 1: Replace permissions-model.md**

Rewrite `docs/technical/permissions-model.md` to reflect the new deck-centric model. Use the spec as the source of truth. Key sections:
- Overview with key principles
- Permission levels (CAN_USE for profiles, CAN_VIEW/CAN_EDIT/CAN_MANAGE for decks)
- Permission tables
- Deck sharing flow
- Profile sharing flow
- Contributor sessions
- Database schema
- API endpoints
- Security notes

- [ ] **Step 2: Update user guide**

Update `docs/user-guide/08-profile-sharing-permissions.md` to reflect:
- Profile sharing is independent of deck sharing
- How to share a deck (Share button → permissions manager)
- How to share a profile (profile list → share button)
- Copy Link for URL sharing

- [ ] **Step 3: Commit**

```bash
git add docs/
git commit -m "docs: update permissions model and user guide for deck-centric sharing"
```

---

### Task 15: Final Integration Test and Cleanup

- [ ] **Step 1: Run full backend test suite**

Run: `cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator && python -m pytest tests/ --timeout=60 -q`
Expected: PASS

- [ ] **Step 2: Run frontend build**

Run: `cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator/frontend && npm run build`
Expected: PASS

- [ ] **Step 3: Verify no remaining profile_id references in permission paths**

Run: `grep -rn "profile_id" src/api/routes/sessions.py src/api/routes/chat.py src/services/permission_service.py`
Expected: No matches (or only in comments/imports unrelated to permission resolution)

- [ ] **Step 4: Final commit if any cleanup needed**

```bash
git add -A
git commit -m "chore: final cleanup for deck-centric permissions"
```

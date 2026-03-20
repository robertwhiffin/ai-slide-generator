# Profile Reconciliation Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unify the two competing profile systems so both the generator page and the sidebar Agent Profiles page use the same `/api/profiles` backend routes.

**Architecture:** Repoint `api/config.ts` profile methods from `/api/settings/profiles` to `/api/profiles`. Trim `ProfileContext` to list + rename + delete. Add deduplication and `conversation_id` stripping to the backend save route. TDD throughout.

**Tech Stack:** FastAPI (Python), React (TypeScript), Pytest, Playwright

**Spec:** `docs/superpowers/specs/2026-03-20-profile-reconciliation-design.md`

---

## Chunk 1: Backend — deduplication and conversation_id stripping

### Task 1: Add deduplication check to save-from-session

**Files:**
- Test: `tests/unit/test_profiles_routes.py`
- Modify: `src/api/routes/profiles.py:82-105`

- [ ] **Step 1: Write the failing test — duplicate config rejected**

Add to `tests/unit/test_profiles_routes.py` in `TestSaveFromSession`:

```python
@patch("src.api.routes.profiles.get_db_session")
@patch("src.api.routes.profiles.get_session_manager")
def test_save_from_session_rejects_duplicate_config(self, mock_get_mgr, mock_get_db, client):
    """POST /api/profiles/save-from-session rejects when identical agent_config already exists."""
    config = {"tools": [{"type": "genie", "space_id": "g1", "space_name": "Sales"}]}
    mgr = MagicMock()
    mgr.get_session.return_value = {
        "session_id": "sess-1",
        "agent_config": config,
    }
    mock_get_mgr.return_value = mgr

    existing_profile = _make_profile(id=99, name="Existing", agent_config=config)

    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    # list query returns the existing profile with matching config
    mock_db.query.return_value.filter.return_value.all.return_value = [existing_profile]
    mock_get_db.return_value = mock_db

    response = client.post(
        "/api/profiles/save-from-session/sess-1",
        json={"name": "New Profile"},
    )
    assert response.status_code == 409
    assert "Existing" in response.json()["detail"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_profiles_routes.py::TestSaveFromSession::test_save_from_session_rejects_duplicate_config -v`
Expected: FAIL (no deduplication logic exists yet, will return 201)

- [ ] **Step 3: Write the failing test — unique config succeeds**

Add to `TestSaveFromSession` to ensure the dedup query doesn't break normal saves:

```python
@patch("src.api.routes.profiles.get_db_session")
@patch("src.api.routes.profiles.get_session_manager")
def test_save_from_session_allows_unique_config(self, mock_get_mgr, mock_get_db, client):
    """POST /api/profiles/save-from-session succeeds when no matching config exists."""
    config = {"tools": [{"type": "genie", "space_id": "g1", "space_name": "Sales"}]}
    mgr = MagicMock()
    mgr.get_session.return_value = {
        "session_id": "sess-1",
        "agent_config": config,
    }
    mock_get_mgr.return_value = mgr

    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    # No existing profiles with matching config
    mock_db.query.return_value.filter.return_value.all.return_value = []
    mock_get_db.return_value = mock_db

    def set_id_on_flush():
        added_obj = mock_db.add.call_args[0][0]
        added_obj.id = 50

    mock_db.flush.side_effect = set_id_on_flush

    response = client.post(
        "/api/profiles/save-from-session/sess-1",
        json={"name": "New Profile"},
    )
    assert response.status_code == 201
```

- [ ] **Step 4: Implement deduplication in `save_from_session`**

In `src/api/routes/profiles.py`, add `GenieTool` import at the top:

```python
from src.api.schemas.agent_config import AgentConfig, GenieTool, resolve_agent_config
```

Then modify `save_from_session` (line 82-105):

```python
@router.post("/save-from-session/{session_id}", status_code=201)
async def save_from_session(session_id: str, body: SaveProfileRequest):
    """Snapshot a session's agent_config into a new named profile."""
    # Get agent_config from session
    try:
        mgr = get_session_manager()
        session = mgr.get_session(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    raw_config = session.get("agent_config")
    config = resolve_agent_config(raw_config)

    # Strip session-specific conversation_ids before persisting
    for tool in config.tools:
        if isinstance(tool, GenieTool):
            tool.conversation_id = None

    config_dict = config.model_dump()

    with get_db_session() as db:
        # Check for duplicate agent_config among non-deleted profiles
        existing_profiles = (
            db.query(ConfigProfile)
            .filter(ConfigProfile.is_deleted == False)  # noqa: E712
            .all()
        )
        for existing in existing_profiles:
            existing_config = resolve_agent_config(existing.agent_config)
            # Strip conversation_ids from existing for fair comparison
            for tool in existing_config.tools:
                if isinstance(tool, GenieTool):
                    tool.conversation_id = None
            if existing_config.model_dump() == config_dict:
                raise HTTPException(
                    status_code=409,
                    detail=f"A profile with this configuration already exists: '{existing.name}'",
                )

        profile = ConfigProfile(
            name=body.name,
            description=body.description,
            agent_config=config_dict,
        )
        db.add(profile)
        db.flush()  # get the id
        result = _profile_to_dict(profile)

    return result
```

- [ ] **Step 5: Update existing save-from-session test mocks for dedup query path**

The two existing tests (`test_save_from_session_creates_profile` and `test_save_from_session_defaults_when_no_config`) need their mocks updated to include the dedup query. Add this line to both tests' mock setup, after the `mock_db.__exit__` line:

```python
    mock_db.query.return_value.filter.return_value.all.return_value = []
```

This ensures the dedup check finds no matches in existing tests.

- [ ] **Step 6: Run both dedup tests to verify they pass**

Run: `pytest tests/unit/test_profiles_routes.py::TestSaveFromSession -v`
Expected: All tests PASS

- [ ] **Step 7: Run all existing profile route tests to verify no regression**

Run: `pytest tests/unit/test_profiles_routes.py -v`
Expected: All tests PASS

- [ ] **Step 8: Commit**

```bash
git add tests/unit/test_profiles_routes.py src/api/routes/profiles.py
git commit -m "feat: add deduplication and conversation_id stripping to save-from-session"
```

### Task 2: Add conversation_id stripping test

**Files:**
- Test: `tests/unit/test_profiles_routes.py`

- [ ] **Step 1: Write the failing test — conversation_id stripped on save**

```python
@patch("src.api.routes.profiles.get_db_session")
@patch("src.api.routes.profiles.get_session_manager")
def test_save_from_session_strips_conversation_id(self, mock_get_mgr, mock_get_db, client):
    """Saved profile should have conversation_id set to None."""
    config = {
        "tools": [
            {"type": "genie", "space_id": "g1", "space_name": "Sales", "conversation_id": "conv-abc"},
            {"type": "genie", "space_id": "g2", "space_name": "Support", "conversation_id": "conv-def"},
        ]
    }
    mgr = MagicMock()
    mgr.get_session.return_value = {"session_id": "sess-1", "agent_config": config}
    mock_get_mgr.return_value = mgr

    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.query.return_value.filter.return_value.all.return_value = []
    mock_get_db.return_value = mock_db

    def set_id_on_flush():
        added_obj = mock_db.add.call_args[0][0]
        added_obj.id = 60

    mock_db.flush.side_effect = set_id_on_flush

    response = client.post(
        "/api/profiles/save-from-session/sess-1",
        json={"name": "Stripped Config"},
    )
    assert response.status_code == 201
    data = response.json()
    for tool in data["agent_config"]["tools"]:
        assert tool.get("conversation_id") is None
```

- [ ] **Step 2: Run test to verify it passes** (should already pass from Task 1 implementation)

Run: `pytest tests/unit/test_profiles_routes.py::TestSaveFromSession::test_save_from_session_strips_conversation_id -v`
Expected: PASS

- [ ] **Step 3: Write test — configs differing only by conversation_id are detected as duplicates**

```python
@patch("src.api.routes.profiles.get_db_session")
@patch("src.api.routes.profiles.get_session_manager")
def test_save_rejects_duplicate_ignoring_conversation_id(self, mock_get_mgr, mock_get_db, client):
    """Two configs identical except for conversation_id should be treated as duplicates."""
    session_config = {
        "tools": [{"type": "genie", "space_id": "g1", "space_name": "Sales", "conversation_id": "conv-new"}]
    }
    existing_config = {
        "tools": [{"type": "genie", "space_id": "g1", "space_name": "Sales", "conversation_id": "conv-old"}]
    }
    mgr = MagicMock()
    mgr.get_session.return_value = {"session_id": "sess-1", "agent_config": session_config}
    mock_get_mgr.return_value = mgr

    existing_profile = _make_profile(id=99, name="Existing", agent_config=existing_config)

    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.query.return_value.filter.return_value.all.return_value = [existing_profile]
    mock_get_db.return_value = mock_db

    response = client.post(
        "/api/profiles/save-from-session/sess-1",
        json={"name": "Should Fail"},
    )
    assert response.status_code == 409
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_profiles_routes.py::TestSaveFromSession::test_save_rejects_duplicate_ignoring_conversation_id -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_profiles_routes.py
git commit -m "test: add conversation_id stripping and dedup edge case tests"
```

### Task 3: Add `updated_at` to `_profile_to_dict`

**Files:**
- Test: `tests/unit/test_profiles_routes.py`
- Modify: `src/api/routes/profiles.py:39-49`

- [ ] **Step 1: Add `updated_at` parameter to `_make_profile` helper**

Update the `_make_profile` helper at the top of the file to include `updated_at` with a default, so existing tests don't break when `_profile_to_dict` starts calling `.isoformat()` on it:

```python
def _make_profile(
    id=1,
    name="My Profile",
    description="desc",
    is_default=False,
    agent_config=None,
    created_at=None,
    created_by="user@test.com",
    is_deleted=False,
    updated_at=None,
):
    """Create a mock ConfigProfile object."""
    p = MagicMock()
    p.id = id
    p.name = name
    p.description = description
    p.is_default = is_default
    p.agent_config = agent_config
    p.created_at = created_at or datetime(2026, 1, 1, 12, 0, 0)
    p.created_by = created_by
    p.is_deleted = is_deleted
    p.deleted_at = None
    p.updated_at = updated_at or datetime(2026, 1, 1, 12, 0, 0)
    return p
```

- [ ] **Step 2: Write the failing test**

Add a new test class:

```python
class TestProfileSerialization:
    @patch("src.api.routes.profiles.get_db_session")
    def test_profile_response_includes_updated_at(self, mock_get_db, client):
        """Profile responses should include updated_at field."""
        updated_time = datetime(2026, 3, 15, 10, 30, 0)
        p = _make_profile(id=1, name="Test", updated_at=updated_time)

        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [p]
        mock_get_db.return_value = mock_db

        response = client.get("/api/profiles")
        assert response.status_code == 200
        data = response.json()
        assert data[0]["updated_at"] == "2026-03-15T10:30:00"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/unit/test_profiles_routes.py::TestProfileSerialization::test_profile_response_includes_updated_at -v`
Expected: FAIL (KeyError or missing field)

- [ ] **Step 4: Add `updated_at` to `_profile_to_dict`**

In `src/api/routes/profiles.py`, modify `_profile_to_dict` (line 39-49):

```python
def _profile_to_dict(profile: ConfigProfile) -> dict:
    """Serialize a profile to a dict, eagerly reading all fields."""
    return {
        "id": profile.id,
        "name": profile.name,
        "description": profile.description,
        "is_default": profile.is_default,
        "agent_config": profile.agent_config,
        "created_at": profile.created_at.isoformat() if profile.created_at else None,
        "created_by": profile.created_by,
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
    }
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/unit/test_profiles_routes.py::TestProfileSerialization -v`
Expected: PASS

- [ ] **Step 6: Run all backend profile tests**

Run: `pytest tests/unit/test_profiles_routes.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add tests/unit/test_profiles_routes.py src/api/routes/profiles.py
git commit -m "feat: add updated_at to profile API response"
```

---

## Chunk 2: Frontend — repoint API client and trim types

### Task 4: Repoint `configApi` profile methods to `/api/profiles`

**Files:**
- Modify: `frontend/src/api/config.ts:13,17-70,274-338`

- [ ] **Step 1: Update `Profile` type to match actual backend response**

In `frontend/src/api/config.ts`, replace the `Profile` interface and remove dead types:

Replace lines 17-70:

```typescript
export interface Profile {
  id: number;
  name: string;
  description: string | null;
  is_default: boolean;
  agent_config: Record<string, unknown> | null;
  created_at: string;
  created_by: string | null;
  updated_at: string | null;
}

export interface ProfileUpdate {
  name?: string;
  description?: string | null;
}
```

Remove: `ProfileDetail`, `ProfileCreate`, `ProfileCreateWithConfig`, `ProfileDuplicate`.

- [ ] **Step 2: Add a profile-specific API_BASE constant**

Add below line 13:

```typescript
const PROFILES_API_BASE = `${API_BASE_URL}/api/profiles`;
```

- [ ] **Step 3: Trim `configApi` profile methods**

Replace the profile section of `configApi` (lines ~274-338) with:

```typescript
  // Profiles (simplified — list, rename, delete only)

  listProfiles: (): Promise<Profile[]> =>
    fetchJson(`${PROFILES_API_BASE}`),

  updateProfile: (id: number, data: ProfileUpdate): Promise<Profile> =>
    fetchJson(`${PROFILES_API_BASE}/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),

  deleteProfile: (id: number): Promise<void> =>
    fetchJson(`${PROFILES_API_BASE}/${id}`, {
      method: 'DELETE',
    }),
```

Remove: `getProfile`, `getDefaultProfile`, `createProfile`, `createProfileWithConfig`, `duplicateProfile`, `setDefaultProfile`, `loadProfile`, `reloadConfiguration`.

- [ ] **Step 4: Remove unused type imports from `ProfileContext`**

In `frontend/src/contexts/ProfileContext.tsx`, update import (line 9-14):

```typescript
import type {
  Profile,
  ProfileUpdate,
} from '../api/config';
import { configApi, ConfigApiError } from '../api/config';
```

Remove: `ProfileCreate`, `ProfileDuplicate`.

- [ ] **Step 5: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit 2>&1 | head -30`
Expected: May have errors from `ProfileContext` still referencing removed methods — that's expected, we fix in Task 5.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/config.ts frontend/src/contexts/ProfileContext.tsx
git commit -m "refactor: repoint configApi profile methods to /api/profiles and trim dead types"
```

### Task 5: Trim `ProfileContext` to list + rename + delete

**Files:**
- Modify: `frontend/src/contexts/ProfileContext.tsx`
- Verify: `frontend/src/hooks/useProfiles.ts` (pass-through re-export, no changes needed — TypeScript compilation will catch any type mismatches from the trimmed `ProfileContextValue`)

**TDD note:** `ProfileContext` and `ProfileList` (Task 6) are validated by E2E tests in Task 8. The TypeScript compiler serves as the first gate — compilation errors will surface any consumers referencing removed properties. Full behavioral validation happens when E2E tests run in Task 8.

- [ ] **Step 1: Rewrite `ProfileContext` to only expose list, rename, delete**

Replace the full contents of `frontend/src/contexts/ProfileContext.tsx`:

```typescript
/**
 * Profile context for managing saved agent profiles.
 *
 * Provides list, rename, and delete operations.
 * Profile saving and loading happen via AgentConfigContext on the generator page.
 */

import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import type { Profile, ProfileUpdate } from '../api/config';
import { configApi, ConfigApiError } from '../api/config';

interface ProfileContextValue {
  profiles: Profile[];
  loading: boolean;
  error: string | null;
  reload: () => Promise<void>;
  updateProfile: (id: number, data: ProfileUpdate) => Promise<Profile>;
  deleteProfile: (id: number) => Promise<void>;
}

const ProfileContext = createContext<ProfileContextValue | undefined>(undefined);

export const ProfileProvider: React.FC<React.PropsWithChildren> = ({ children }) => {
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadProfiles = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await configApi.listProfiles();
      setProfiles(data);
    } catch (err) {
      const message = err instanceof ConfigApiError
        ? err.message
        : 'Failed to load profiles';
      setError(message);
      console.error('Error loading profiles:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadProfiles();
  }, [loadProfiles]);

  const updateProfile = useCallback(async (
    id: number,
    data: ProfileUpdate
  ): Promise<Profile> => {
    try {
      setError(null);
      const updated = await configApi.updateProfile(id, data);
      await loadProfiles();
      return updated;
    } catch (err) {
      const message = err instanceof ConfigApiError
        ? err.message
        : 'Failed to update profile';
      setError(message);
      throw err;
    }
  }, [loadProfiles]);

  const deleteProfile = useCallback(async (id: number): Promise<void> => {
    try {
      setError(null);
      await configApi.deleteProfile(id);
      await loadProfiles();
    } catch (err) {
      const message = err instanceof ConfigApiError
        ? err.message
        : 'Failed to delete profile';
      setError(message);
      throw err;
    }
  }, [loadProfiles]);

  const value: ProfileContextValue = {
    profiles,
    loading,
    error,
    reload: loadProfiles,
    updateProfile,
    deleteProfile,
  };

  return (
    <ProfileContext.Provider value={value}>
      {children}
    </ProfileContext.Provider>
  );
};

export const useProfiles = (): ProfileContextValue => {
  const context = useContext(ProfileContext);
  if (!context) {
    throw new Error('useProfiles must be used within a ProfileProvider');
  }
  return context;
};
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit 2>&1 | head -30`
Expected: May have errors from `ProfileList` still referencing removed properties — fixed in Task 6.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/contexts/ProfileContext.tsx
git commit -m "refactor: trim ProfileContext to list, rename, delete only"
```

### Task 6: Simplify `ProfileList` component

**Files:**
- Modify: `frontend/src/components/config/ProfileList.tsx`

- [ ] **Step 1: Rewrite `ProfileList` to only show list, rename, delete**

The component should use `useProfiles()` which now only provides `profiles`, `loading`, `error`, `updateProfile`, `deleteProfile`, and `reload`. Remove all references to `currentProfile`, `loadProfile`, `setDefaultProfile`, `duplicateProfile`.

Key removals:
- The "Currently Loaded" section (old line ~206-213)
- Per-card "Loaded" badge (old `currentProfile?.id === profile.id` check)
- The "Load" button and `handleLoadProfile`
- The "Set Default" button
- The "Duplicate" button
- The helper text about creating profiles should say: "Use 'Save as Profile' from the generator to create one."

Keep:
- Profile list with name, description, badges (default badge can stay as informational)
- Rename inline edit
- Delete with confirmation dialog

- [ ] **Step 2: Verify TypeScript compiles clean**

Run: `cd frontend && npx tsc --noEmit 2>&1 | head -30`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/config/ProfileList.tsx
git commit -m "refactor: simplify ProfileList to rename and delete only"
```

---

## Chunk 3: Frontend tests — update mocks and E2E tests

### Task 7: Update shared mock setup

**Files:**
- Modify: `frontend/tests/helpers/setup-mocks.ts`
- Modify: `frontend/tests/fixtures/mocks.ts`

- [ ] **Step 1: Remove legacy `/api/settings/profiles` mock from `setup-mocks.ts`**

In `frontend/tests/helpers/setup-mocks.ts`, remove the block (around line 42-49):

```typescript
  // Mock legacy profiles endpoint (GET /api/settings/profiles) — used by ProfileList page
  await page.route(/\/api\/settings\/profiles$/, (route) => {
    ...
  });
```

The `/api/profiles` mock (line 34-40) already returns `mockProfileSummaries` — this is what `ProfileContext` will now call.

- [ ] **Step 2: Update `mockProfiles` in `mocks.ts` to match new response shape**

Update `mockProfiles` in `frontend/tests/fixtures/mocks.ts` to include `agent_config` and drop `updated_by`:

```typescript
export const mockProfiles = [
  {
    id: 1,
    name: "Sales Analytics",
    description: "Analytics profile for sales data insights",
    is_default: true,
    agent_config: { tools: [], slide_style_id: null, deck_prompt_id: null, system_prompt: null, slide_editing_instructions: null },
    created_at: "2026-01-08T20:10:29.720015",
    created_by: "system",
    updated_at: "2026-01-08T20:10:29.720025",
  },
  {
    id: 2,
    name: "Marketing Reports",
    description: "Marketing campaign performance reports",
    is_default: false,
    agent_config: { tools: [{ type: "genie", space_id: "g1", space_name: "Sales", description: null, conversation_id: null }], slide_style_id: null, deck_prompt_id: null, system_prompt: null, slide_editing_instructions: null },
    created_at: "2026-01-08T20:10:29.724407",
    created_by: "system",
    updated_at: "2026-01-08T20:10:29.724411",
  }
];
```

- [ ] **Step 3: Unify mock responses — have `/api/profiles` mock return `mockProfiles` too**

In `setup-mocks.ts`, update the `/api/profiles` mock to return `mockProfiles` (so both AgentConfigBar and ProfileList see the same data):

```typescript
  await page.route(/\/api\/profiles$/, (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockProfiles),
    });
  });
```

If `mockProfileSummaries` is now redundant (same shape as `mockProfiles`), remove it and update imports. If other tests rely on its distinct shape, keep both for now.

- [ ] **Step 4: Remove stale legacy mock objects from `mocks.ts`**

Remove these mock objects if they are no longer referenced after the profile reconciliation:
- `mockProfileCreateResponse`
- `mockProfileUpdateResponse`
- `mockProfileDetail`
- `mockProfileLoadResponse`

Search for usages first — if any are still imported by tests, leave them.

- [ ] **Step 5: Commit**

```bash
git add frontend/tests/helpers/setup-mocks.ts frontend/tests/fixtures/mocks.ts
git commit -m "test: update shared mocks — remove legacy /api/settings/profiles, unify profile shape"
```

### Task 8: Update `profile-ui.spec.ts`

**Files:**
- Modify: `frontend/tests/e2e/profile-ui.spec.ts`

- [ ] **Step 1: Remove legacy mock routes**

Remove all `/api/settings/profiles` route mocks from `setupProfileMocks()`. The `/api/profiles` mock is sufficient.

- [ ] **Step 2: Remove tests for deleted features**

Remove tests for:
- Load profile (any test using `handleLoadProfile` or "Load" button)
- Set default (any test clicking "Set Default")
- Duplicate profile
- "Currently Loaded" badge
- "Loaded" per-card badge (`hides "Load" for currently loaded profile` test)

- [ ] **Step 3: Update remaining tests**

Update rename and delete tests to mock `/api/profiles/{id}` instead of `/api/settings/profiles/{id}`:
- PUT for rename → `page.route(/\/api\/profiles\/\d+$/, ...)`
- DELETE → same pattern

- [ ] **Step 4: Run profile-ui tests**

Run: `cd frontend && npx playwright test tests/e2e/profile-ui.spec.ts`
Expected: All remaining tests PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/tests/e2e/profile-ui.spec.ts
git commit -m "test: update profile-ui E2E tests for reconciled profile API"
```

### Task 9: Update remaining E2E test files

**Files:**
- Modify: All E2E test files that mock `/api/settings/profiles`

These files all have similar changes: remove the `/api/settings/profiles` mock route (the `/api/profiles` mock from `setupMocks()` now handles both uses).

Files to update:
- `frontend/tests/e2e/chat-ui.spec.ts`
- `frontend/tests/e2e/export-ui.spec.ts`
- `frontend/tests/e2e/history-ui.spec.ts`
- `frontend/tests/e2e/deck-integrity.spec.ts`
- `frontend/tests/e2e/slide-styles-ui.spec.ts`
- `frontend/tests/e2e/slide-operations-ui.spec.ts`
- `frontend/tests/e2e/deck-prompts-ui.spec.ts`
- `frontend/tests/e2e/help-ui.spec.ts`
- `frontend/tests/e2e/save-points-versioning.spec.ts`
- `frontend/tests/slide-generator.spec.ts`
- `frontend/tests/user-guide/shared.ts`
- `frontend/tests/e2e/profile-integration.spec.ts`

- [ ] **Step 1: Remove `/api/settings/profiles` mocks from simple test files**

These files use `setupMocks()` from `setup-mocks.ts` but also add their own `/api/settings/profiles` mock. Remove the per-file legacy mock — the shared `setupMocks()` `/api/profiles` route now covers both:

| File | Lines to remove (approx) | Pattern |
|---|---|---|
| `chat-ui.spec.ts` | ~75-82 | `page.route(/\/api\/settings\/profiles$/, ...)` |
| `export-ui.spec.ts` | ~75-79 | `page.route(/\/api\/settings\/profiles$/, ...)` |
| `history-ui.spec.ts` | ~41-45 | `page.route('...api/settings/profiles', ...)` |
| `deck-integrity.spec.ts` | ~96-100 | `page.route(/\/api\/settings\/profiles$/, ...)` |
| `slide-operations-ui.spec.ts` | ~75-79 | `page.route('...api/settings/profiles', ...)` |
| `help-ui.spec.ts` | ~29-33 | `page.route('...api/settings/profiles', ...)` |
| `save-points-versioning.spec.ts` | ~90-94, ~984-988 | Two blocks, `page.route('...api/settings/profiles', ...)` |
| `slide-generator.spec.ts` | ~44-47 | `page.route(/\/api\/settings\/profiles$/, ...)` |
| `shared.ts` (user-guide) | ~185-193 | `page.route('**/api/settings/profiles', ...)` |

For each file: search for `settings/profiles`, delete the mock block, verify the `/api/profiles` mock is present (either from shared `setupMocks` or inline).

- [ ] **Step 2: Update `profile-integration.spec.ts`**

This file has extensive tests for the old profile creation flow. Specific changes:

- Remove all `/api/settings/profiles` route mocks (multiple blocks)
- Remove tests that call `page.getByRole('button', { name: 'Save Profile Info' })` (~lines 303, 345, 497) — these test the old wizard-based creation
- Remove tests for duplicate profile and set-default behavior
- Keep tests that navigate to `/profiles` and verify the list renders
- Keep tests that validate delete confirmation dialog
- Update any remaining mocks from `/api/settings/profiles/{id}` to `/api/profiles/{id}`

- [ ] **Step 3: Update `slide-styles-ui.spec.ts` profile-related tests**

Lines ~572-596 mock old profile routes for a "profile switching" test:
- Remove `page.route('...api/settings/profiles', ...)` (~line 572)
- Remove `page.route(/...api\/settings\/profiles\/\d+$/, ...)` (~line 580)
- Remove `page.route(/...api\/settings\/profiles\/\d+\/load/, ...)` (~line 592)
- If the test is testing profile loading behavior that no longer exists on the sidebar, remove the entire test block.

- [ ] **Step 4: Update `deck-prompts-ui.spec.ts` profile-related tests**

Lines ~433-497 mock old profile routes:
- Replace `page.route('...api/settings/profiles', ...)` (~lines 433, 493) with `/api/profiles` route
- Replace `page.route(/...api\/settings\/profiles\/\d+/, ...)` (~lines 436, 496) with `/api/profiles/\d+`
- If the test logic loads or switches profiles via the old flow, remove those assertions

- [ ] **Step 5: Run all frontend E2E tests**

Run: `cd frontend && npx playwright test`
Expected: All tests PASS (some may need further mock adjustments)

- [ ] **Step 6: Commit**

```bash
git add frontend/tests/
git commit -m "test: remove all legacy /api/settings/profiles mocks from E2E tests"
```

---

## Chunk 4: Final verification

### Task 10: Full test suite verification

- [ ] **Step 1: Run all backend tests**

Run: `pytest tests/unit/ -v`
Expected: All PASS

- [ ] **Step 2: Run all frontend E2E tests**

Run: `cd frontend && npx playwright test`
Expected: All PASS

- [ ] **Step 3: TypeScript compilation check**

Run: `cd frontend && npx tsc --noEmit`
Expected: Clean (no errors)

- [ ] **Step 4: Manual smoke test** (if running locally)

1. Start the app
2. Go to generator page → click "Load Profile" → should list profiles from `/api/profiles`
3. Go to sidebar "Agent Profiles" → should list the same profiles (no 404)
4. Rename a profile from the sidebar → should succeed
5. Delete a profile from the sidebar → should succeed
6. Save a profile from the generator → should succeed
7. Try saving the same config again → should get 409 error

- [ ] **Step 5: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix: address issues found during final verification"
```

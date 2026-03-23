# Default Slide Style Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users set a system-wide default slide style and a per-user default (localStorage), both managed from the Slide Styles settings page.

**Architecture:** Add `is_default` column to `SlideStyleLibrary`, a `POST .../set-default` endpoint, UI badges + buttons on the Slide Styles page, and a localStorage override in `AgentConfigContext`. Two-tier priority: user default > system default > fallback.

**Tech Stack:** Python/FastAPI, SQLAlchemy, PostgreSQL/SQLite, React/TypeScript, Playwright E2E

**Spec:** `docs/superpowers/specs/2026-03-23-default-slide-style-design.md`

---

### Task 1: Add `is_default` column to model + migration

**Files:**
- Modify: `src/database/models/slide_style_library.py:43` (add column after `updated_at`)
- Modify: `src/core/database.py:474` (add migration helper call)
- Create: migration helper function in `src/core/database.py` (after `_migrate_to_v0_2`)

- [ ] **Step 1: Add `is_default` column to the model**

In `src/database/models/slide_style_library.py`, after line 43 (`updated_at`), add:

```python
is_default = Column(Boolean, default=False, nullable=False)  # Which style is applied to new sessions by default
```

- [ ] **Step 2: Add the migration helper function**

In `src/core/database.py`, after the `_migrate_to_v0_2` function (around line 640), add:

```python
def _migrate_slide_style_default(conn, inspector, schema, _qual, is_sqlite):
    """Add is_default column to slide_style_library and seed the system style as default."""
    table_name = "slide_style_library"
    qualified_table = _qual(table_name)

    try:
        columns = {c["name"] for c in inspector.get_columns(table_name, schema=schema)}
    except Exception:
        return

    if "is_default" not in columns:
        logger.info(f"Migration: adding is_default column to {table_name}")
        conn.execute(text(
            f"ALTER TABLE {qualified_table} ADD COLUMN is_default BOOLEAN DEFAULT FALSE NOT NULL"
        ))

    # Only seed a default if none exists yet (first deploy only).
    # LIMIT 1 ensures exactly one row even if multiple is_system rows exist.
    if is_sqlite:
        conn.execute(text(f"""
            UPDATE {qualified_table} SET is_default = 1
            WHERE id = (
                SELECT id FROM {qualified_table}
                WHERE is_system = 1 AND is_active = 1
                LIMIT 1
            )
            AND NOT EXISTS (SELECT 1 FROM {qualified_table} WHERE is_default = 1)
        """))
    else:
        conn.execute(text(f"""
            UPDATE {qualified_table} SET is_default = TRUE
            WHERE id = (
                SELECT id FROM {qualified_table}
                WHERE is_system = TRUE AND is_active = TRUE
                LIMIT 1
            )
            AND NOT EXISTS (SELECT 1 FROM {qualified_table} WHERE is_default = TRUE)
        """))

    logger.info("Migration: slide_style_library is_default migration complete")
```

- [ ] **Step 3: Call the migration helper from `_run_migrations`**

In `src/core/database.py`, after the `_migrate_to_v0_2(...)` call (line 474), add:

```python
        _migrate_slide_style_default(conn, inspector, schema, _qual, is_sqlite)
```

- [ ] **Step 4: Update seeding**

In `src/core/init_default_profile.py`:

a) In `SYSTEM_SLIDE_STYLES` (line 225), add `"is_default": True` to the System Default entry:

```python
SYSTEM_SLIDE_STYLES = [
    {
        "name": "System Default",
        "description": "Protected system style. Use this as a template when creating your own custom styles.",
        "category": "System",
        "style_content": DEFAULT_SLIDE_STYLE,
        "is_system": True,
        "is_default": True,
    },
]
```

b) In `_seed_slide_styles()` (line 280), add `is_default` to the `SlideStyleLibrary(...)` constructor:

```python
        style = SlideStyleLibrary(
            name=style_data["name"],
            description=style_data["description"],
            category=style_data["category"],
            style_content=style_data["style_content"],
            is_active=True,
            is_system=style_data.get("is_system", False),
            is_default=style_data.get("is_default", False),
            created_by="system",
            updated_by="system",
        )
```

- [ ] **Step 5: Verify locally**

Run: `python -c "from src.core.database import init_db; init_db()"` (or start the backend) to confirm the migration runs without error.

- [ ] **Step 6: Commit**

```bash
git add src/database/models/slide_style_library.py src/core/database.py src/core/init_default_profile.py
git commit -m "feat: add is_default column to SlideStyleLibrary with migration + seeding"
```

---

### Task 2: Update `_get_default_style_id()` to use `is_default`

**Files:**
- Modify: `src/api/routes/chat.py:34-48`

- [ ] **Step 1: Update the query**

Replace the `_get_default_style_id` function (lines 34-48 of `src/api/routes/chat.py`) with:

```python
def _get_default_style_id() -> int | None:
    """Return the ID of the default slide style (is_default=True, is_active=True), or None."""
    from src.core.database import get_db_session
    from src.database.models import SlideStyleLibrary

    with get_db_session() as db:
        # Primary: explicit default
        style = (
            db.query(SlideStyleLibrary.id)
            .filter(
                SlideStyleLibrary.is_default == True,  # noqa: E712
                SlideStyleLibrary.is_active == True,  # noqa: E712
            )
            .first()
        )
        if style:
            return style.id

        # Fallback: system style (defensive, for mid-migration)
        style = (
            db.query(SlideStyleLibrary.id)
            .filter(
                SlideStyleLibrary.is_system == True,  # noqa: E712
                SlideStyleLibrary.is_active == True,  # noqa: E712
            )
            .first()
        )
        return style.id if style else None
```

- [ ] **Step 2: Commit**

```bash
git add src/api/routes/chat.py
git commit -m "feat: _get_default_style_id queries is_default with is_system fallback"
```

---

### Task 3: Add `set-default` endpoint + response schema + delete guard

**Files:**
- Modify: `src/api/routes/settings/slide_styles.py:49-61` (SlideStyleResponse)
- Modify: `src/api/routes/settings/slide_styles.py:100-113` (list construction)
- Modify: `src/api/routes/settings/slide_styles.py:154-167` (get construction)
- Modify: `src/api/routes/settings/slide_styles.py:235-248` (create construction)
- Modify: `src/api/routes/settings/slide_styles.py:336-349` (update construction)
- Modify: `src/api/routes/settings/slide_styles.py:389-393` (delete guard)
- Add: new `set_default` route function

- [ ] **Step 1: Add `is_default` to `SlideStyleResponse`**

In `src/api/routes/settings/slide_styles.py`, line 53 (after `is_system`), add:

```python
    is_default: bool  # Whether this is the system-wide default style
```

- [ ] **Step 2: Add `is_default` to all response construction sites**

In each `SlideStyleResponse(...)` call (list at line 100, get at line 154, create at line 235, update at line 336), add after `is_system=s.is_system,`:

```python
                    is_default=s.is_default,
```

There are 4 existing sites. The 5th (set-default) will be created in step 4.

- [ ] **Step 3: Add is_default guard to delete endpoint**

In `src/api/routes/settings/slide_styles.py`, after the `is_system` guard (line 393), add:

```python
        # Protect default style from deletion/deactivation
        if style.is_default:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete/deactivate the default style. Set another style as default first.",
            )
```

- [ ] **Step 4: Add the set-default endpoint**

At the end of `src/api/routes/settings/slide_styles.py` (after the delete function), add:

```python
@router.post("/{style_id}/set-default", response_model=SlideStyleResponse)
def set_default_slide_style(style_id: int):
    """Set a slide style as the system-wide default.

    Unsets the previous default in a single transaction.
    Idempotent: setting the already-default style returns 200.
    """
    try:
        with get_db_session() as db:
            style = db.query(SlideStyleLibrary).filter(
                SlideStyleLibrary.id == style_id,
            ).first()

            if not style:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Slide style {style_id} not found",
                )

            if not style.is_active:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot set an inactive style as default",
                )

            if not style.is_default:
                # Unset previous default
                db.query(SlideStyleLibrary).filter(
                    SlideStyleLibrary.is_default == True,  # noqa: E712
                ).update({"is_default": False})

                style.is_default = True
                db.commit()
                db.refresh(style)

            logger.info(f"Set default slide style: {style.name} (id={style.id})")

            return SlideStyleResponse(
                id=style.id,
                name=style.name,
                description=style.description,
                category=style.category,
                style_content=style.style_content,
                image_guidelines=style.image_guidelines,
                is_active=style.is_active,
                is_system=style.is_system,
                is_default=style.is_default,
                created_by=style.created_by,
                created_at=style.created_at.isoformat(),
                updated_by=style.updated_by,
                updated_at=style.updated_at.isoformat(),
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error setting default slide style {style_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to set default slide style",
        )
```

- [ ] **Step 5: Verify the backend starts**

Run: `python -m uvicorn src.api.main:app --host 0.0.0.0 --port 8000` and test:
- `curl http://localhost:8000/api/settings/slide-styles | python -m json.tool` — verify `is_default` field appears
- `curl -X POST http://localhost:8000/api/settings/slide-styles/1/set-default` — verify 200

- [ ] **Step 6: Commit**

```bash
git add src/api/routes/settings/slide_styles.py
git commit -m "feat: add set-default endpoint, is_default in responses, delete guard"
```

---

### Task 4: Frontend API client + TypeScript types

**Files:**
- Modify: `frontend/src/api/config.ts:129-142` (SlideStyle interface)
- Modify: `frontend/src/api/config.ts:365` (add new method after deleteSlideStyle)

- [ ] **Step 1: Add `is_default` to `SlideStyle` interface**

In `frontend/src/api/config.ts`, in the `SlideStyle` interface (after `is_system` on line ~133), add:

```typescript
  is_default: boolean
```

- [ ] **Step 2: Add `setDefaultSlideStyle` method**

In `frontend/src/api/config.ts`, after the `deleteSlideStyle` method (around line 365), add:

```typescript
  async setDefaultSlideStyle(styleId: number): Promise<SlideStyle> {
    const response = await fetch(`${API_BASE_URL}/api/settings/slide-styles/${styleId}/set-default`, {
      method: 'POST',
    })
    if (!response.ok) {
      const error = await response.json().catch(() => ({}))
      throw new Error(error.detail || 'Failed to set default slide style')
    }
    return response.json()
  },
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/config.ts
git commit -m "feat: add is_default to SlideStyle type + setDefaultSlideStyle API method"
```

---

### Task 5: Slide Styles page — system default badge + button

**Files:**
- Modify: `frontend/src/components/config/SlideStyleList.tsx:188-197` (badges area)
- Modify: `frontend/src/components/config/SlideStyleList.tsx:211-249` (actions area)

- [ ] **Step 1: Add "Default" badge**

In `frontend/src/components/config/SlideStyleList.tsx`, after the System badge (line 191), add:

```tsx
                        {style.is_default && (
                          <Badge className="text-xs bg-amber-500/10 text-amber-700 hover:bg-amber-500/20">
                            Default
                          </Badge>
                        )}
```

- [ ] **Step 2: Add "Set as default" button**

In the actions area (line 211), before the existing Preview button (line 212), add:

```tsx
                      {!style.is_default && style.is_active && (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-8 px-2 text-xs text-muted-foreground"
                          onClick={async () => {
                            setActionLoading(style.id);
                            try {
                              await configApi.setDefaultSlideStyle(style.id);
                              await loadStyles();
                            } catch (err) {
                              console.error('Failed to set default style:', err);
                            } finally {
                              setActionLoading(null);
                            }
                          }}
                          disabled={actionLoading === style.id}
                          aria-label="Set as default"
                        >
                          Set as default
                        </Button>
                      )}
```

- [ ] **Step 3: Verify in browser**

Navigate to the Slide Styles page, confirm:
- "Default" badge shows on the system style
- "Set as default" button appears on non-default styles
- Clicking it moves the badge

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/config/SlideStyleList.tsx
git commit -m "feat: add Default badge and Set as default button to Slide Styles page"
```

---

### Task 6: Slide Styles page — user default (localStorage) badge + button

**Files:**
- Modify: `frontend/src/components/config/SlideStyleList.tsx`

- [ ] **Step 1: Add localStorage state**

At the top of the component function in `SlideStyleList.tsx`, add state for the user default:

```typescript
  const [userDefaultStyleId, setUserDefaultStyleId] = useState<number | null>(() => {
    const stored = localStorage.getItem('userDefaultSlideStyleId');
    return stored ? Number(stored) : null;
  });
```

- [ ] **Step 2: Add lazy validation of stale ID**

After `loadStyles` resolves (in the existing `useEffect` that fetches styles), add validation:

```typescript
  // Clear stale user default if the style no longer exists in the active list
  useEffect(() => {
    if (userDefaultStyleId && styles.length > 0) {
      const exists = styles.some(s => s.id === userDefaultStyleId && s.is_active);
      if (!exists) {
        localStorage.removeItem('userDefaultSlideStyleId');
        setUserDefaultStyleId(null);
      }
    }
  }, [styles, userDefaultStyleId]);
```

- [ ] **Step 3: Add "My Default" badge**

After the "Default" badge added in Task 5, add:

```tsx
                        {style.id === userDefaultStyleId && (
                          <Badge className="text-xs bg-green-500/10 text-green-700 hover:bg-green-500/20">
                            My Default
                          </Badge>
                        )}
```

- [ ] **Step 4: Add "Set as my default" button**

After the "Set as default" button added in Task 5, add:

```tsx
                      {style.id !== userDefaultStyleId && style.is_active && (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-8 px-2 text-xs text-muted-foreground"
                          onClick={() => {
                            localStorage.setItem('userDefaultSlideStyleId', String(style.id));
                            setUserDefaultStyleId(style.id);
                          }}
                          aria-label="Set as my default"
                        >
                          My default
                        </Button>
                      )}
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/config/SlideStyleList.tsx
git commit -m "feat: add My Default badge + button with localStorage persistence"
```

---

### Task 7: AgentConfigContext — user default override in pre-session mode

**Files:**
- Modify: `frontend/src/contexts/AgentConfigContext.tsx:98-104`

- [ ] **Step 1: Add user default override**

In `frontend/src/contexts/AgentConfigContext.tsx`, replace the `.then()` callback (lines 98-104) with:

```typescript
    api.listProfiles()
      .then((profiles: ProfileSummary[]) => {
        const defaultProfile = profiles.find(p => p.is_default);
        if (defaultProfile?.agent_config) {
          const config = { ...defaultProfile.agent_config };
          // User default style overrides profile's style
          const userStyleId = localStorage.getItem('userDefaultSlideStyleId');
          if (userStyleId) {
            config.slide_style_id = Number(userStyleId);
          }
          setAgentConfig(config);
        }
      })
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/contexts/AgentConfigContext.tsx
git commit -m "feat: user default slide style override in pre-session AgentConfigContext"
```

---

### Task 8: Update integration test mock for `is_default`

**Files:**
- Modify: `frontend/tests/helpers/integration-helpers.ts`

- [ ] **Step 1: Update the mock's default style lookup**

In `frontend/tests/helpers/integration-helpers.ts`, in the `mockChatStream` function, the current code finds the system style with:

```typescript
const systemStyle = (stylesData.styles ?? []).find((s: Record<string, unknown>) => s.is_system);
```

Change to prefer `is_default`:

```typescript
const defaultStyle = (stylesData.styles ?? []).find((s: Record<string, unknown>) => s.is_default)
  ?? (stylesData.styles ?? []).find((s: Record<string, unknown>) => s.is_system);
const systemStyle = defaultStyle;
```

- [ ] **Step 2: Run existing agent-config integration tests**

Run: `./scripts/run_e2e_local.sh agent-config-integration`

Expected: All 13 tests pass.

- [ ] **Step 3: Commit**

```bash
git add frontend/tests/helpers/integration-helpers.ts
git commit -m "test: update integration mock to use is_default for default style lookup"
```

---

### Task 9: E2E test — set system default on Slide Styles page

**Files:**
- Modify: `frontend/tests/e2e/slide-styles-integration.spec.ts`

- [ ] **Step 1: Add test for set-default**

Add a new test to the existing `slide-styles-integration.spec.ts` file in an appropriate describe block:

```typescript
  test('set system default style', async ({ page, request }) => {
    // Create a second style
    const style2 = await createTestStyle(request, `Default Test ${Date.now()}`);

    try {
      await page.goto('/slide-styles');
      await page.waitForLoadState('networkidle');

      // Verify the system style has "Default" badge
      const systemCard = page.locator(`text=System Default`).first();
      await expect(systemCard.locator('..').locator('text=Default')).toBeVisible();

      // Click "Set as default" on the new style
      const style2Card = page.locator(`text=${style2.name}`).first();
      await style2Card.locator('..').locator('button', { hasText: 'Set as default' }).click();

      // Wait for refresh
      await page.waitForResponse(resp => resp.url().includes('/set-default') && resp.ok());
      await page.waitForTimeout(500);

      // Verify badge moved
      await expect(style2Card.locator('..').locator('text=Default')).toBeVisible();
    } finally {
      // Restore default to system style and clean up
      const styles = await configApi.listSlideStyles();
      const systemStyle = styles.styles.find(s => s.is_system);
      if (systemStyle) {
        await request.post(`${API_BASE}/settings/slide-styles/${systemStyle.id}/set-default`);
      }
      await cleanupStyle(request, style2.id);
    }
  });
```

Note: Adjust the test to match the exact selector patterns used in the existing `slide-styles-integration.spec.ts` file — check how other tests locate style cards and buttons.

- [ ] **Step 2: Run the test**

Run: `./scripts/run_e2e_local.sh slide-styles-integration`

Expected: New test passes along with all existing tests.

- [ ] **Step 3: Commit**

```bash
git add frontend/tests/e2e/slide-styles-integration.spec.ts
git commit -m "test: E2E test for set system default slide style"
```

---

### Task 10: Backend tests — set-default endpoint + delete guard + migration idempotency

**Files:**
- Create: `tests/unit/test_slide_style_default.py` (no existing slide style test file — tests live in `tests/unit/`)
- Reference: `tests/unit/test_migration.py` for migration test patterns

- [ ] **Step 1: Write tests**

Create `tests/unit/test_slide_style_default.py`. Tests to cover:

- `POST /set-default` sets the default, returns updated style with `is_default=True`
- `POST /set-default` unsets the previous default (only one `is_default=True` at a time)
- `POST /set-default` on already-default style returns 200 (idempotent)
- `POST /set-default` on inactive style returns 400
- `POST /set-default` on nonexistent style returns 404
- `DELETE` on default style returns 400
- `DELETE` (soft-delete) on default style returns 400
- Migration idempotency: calling `_migrate_slide_style_default` twice does not error or duplicate defaults

Follow the existing test patterns in `tests/unit/` — use the `TestClient` from FastAPI and the test database fixtures from `tests/conftest.py`.

- [ ] **Step 2: Run tests**

Run: `pytest tests/unit/test_slide_style_default.py -v`

Expected: All tests pass.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_slide_style_default.py
git commit -m "test: backend tests for set-default endpoint, delete guard, migration idempotency"
```

---

### Task 11: Frontend unit test — user default priority resolution

**Files:**
- Create: `frontend/tests/unit/agent-config-priority.test.ts` (or add to existing AgentConfigContext test file if one exists)

- [ ] **Step 1: Write tests**

Test the three-tier priority resolution logic:

- When `userDefaultSlideStyleId` is set in localStorage, it overrides the profile's `slide_style_id`
- When `userDefaultSlideStyleId` is not set, the profile's `slide_style_id` is used
- When neither is set, `slide_style_id` remains null (backend system default is the fallback)
- When `userDefaultSlideStyleId` points to a stale/invalid ID, it is not applied (falls through to profile default)

This can be a plain unit test of the resolution logic extracted into a helper function, or a React Testing Library test of AgentConfigContext with mocked API responses.

- [ ] **Step 2: Run tests**

Run: `cd frontend && npx vitest run tests/unit/agent-config-priority.test.ts`

Expected: All tests pass.

- [ ] **Step 3: Commit**

```bash
git add frontend/tests/unit/agent-config-priority.test.ts
git commit -m "test: frontend unit test for user default slide style priority resolution"
```

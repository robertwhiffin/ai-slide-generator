# Default Slide Style — Design Spec

**Date:** 2026-03-23
**Branch:** feature/profile-rebuild
**Status:** Approved design, pending implementation

## Purpose

Allow users to control which slide style is applied to new sessions. Two tiers:

1. **System default** — global, stored in DB. Applies to any user who hasn't set their own preference.
2. **User default** — per-user, stored in localStorage. Overrides the system default.

Both are managed from the Slide Styles settings page only (not from the AgentConfigBar dropdown).

## Data Layer

### Model change

Add `is_default` to `SlideStyleLibrary`:

```python
is_default = Column(Boolean, default=False, nullable=False)
```

This is distinct from `is_system` (which means "protected from edit/delete"). Any style — system or user-created, including `is_system` styles — can be the default. Exactly one style has `is_default=True` at any time, enforced by the API layer.

Editing a default style's content (name, style_content, etc.) via the update endpoint is allowed and has no side effects — no cache invalidation or notification to active sessions is needed.

### Migration

Create a dedicated helper function `_migrate_slide_style_default()` following the existing pattern (`_migrate_to_v0_2`, `_migrate_google_credentials_to_global`, etc.). Call it from `_run_migrations()` alongside the other helpers.

The function accepts `conn, inspector, schema, _qual, is_sqlite` parameters and uses `_qual("slide_style_library")` for schema-qualified table names:

```python
def _migrate_slide_style_default(conn, inspector, schema, _qual, is_sqlite):
    table_name = "slide_style_library"
    qualified_table = _qual(table_name)

    columns = {c["name"] for c in inspector.get_columns(table_name, schema=schema)}
    if "is_default" not in columns:
        conn.execute(text(
            f"ALTER TABLE {qualified_table} ADD COLUMN is_default BOOLEAN DEFAULT FALSE NOT NULL"
        ))

    # Only seed a default if none exists yet (first deploy only).
    # Use LIMIT 1 to guarantee exactly one row is updated even if
    # multiple rows have is_system=TRUE.
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
```

Idempotent: the column check prevents duplicate ADD COLUMN, the `NOT EXISTS` guard prevents overwriting an existing default on redeploy, and `LIMIT 1` ensures exactly one row is set even if multiple `is_system` rows exist.

### Seeding

In `init_default_profile.py`:
- Set `is_default=True` on the "System Default" entry in `SYSTEM_SLIDE_STYLES`
- Update `_seed_slide_styles()` to pass `is_default=style_data.get("is_default", False)` when constructing `SlideStyleLibrary(...)` objects — without this, the dict key would be silently ignored

### Default resolution

Update `_get_default_style_id()` in `src/api/routes/chat.py`:

- Query `is_default=True, is_active=True` instead of `is_system=True`
- Fallback to `is_system=True` if no default found (defensive, for mid-migration)

### Deletion / deactivation of the default style

Block both deletion AND deactivation of the default style. The delete endpoint currently supports soft-delete (setting `is_active=False`). Both paths return 400 with "Cannot delete/deactivate the default style. Set another style as default first."

Guard ordering when a style is both `is_system` and `is_default`: the existing `is_system` guard (403) runs first. The `is_default` guard (400) only fires for non-system default styles.

## API

### New endpoint

`POST /api/settings/slide-styles/{style_id}/set-default`

- Validates the style exists and `is_active=True`
- `is_system` styles are valid targets (they can be the default)
- In a single transaction: unset previous default, set new default
- Returns the updated style as `SlideStyleResponse` (this is the 5th construction site for the response schema)
- Idempotent: setting the already-default style returns 200 with no change

### Existing endpoints

- `GET /api/settings/slide-styles` — add `is_default: bool` to the `SlideStyleResponse` pydantic schema. Update all 5 construction sites where `SlideStyleResponse(...)` is built: list, get, create, update, and the new set-default endpoint. Each must pass `is_default=s.is_default`.
- `DELETE /api/settings/slide-styles/{style_id}` — reject with 400 if the style has `is_default=True` (after the existing `is_system` 403 guard).
- Create/Update — no changes. `is_default` is managed only through the dedicated endpoint. Editing a default style's content is allowed with no side effects.

## Frontend — System Default

### Slide Styles page (`SlideStyleList.tsx`)

- "Default" badge on the style where `is_default=true` (similar to existing "System" badge)
- "Set as default" button on each card (hidden when the style is already the default)
- Clicking calls `POST /api/settings/slide-styles/{id}/set-default`, then refreshes the list

### API client (`config.ts`)

- Add `is_default` to the `SlideStyle` TypeScript interface
- Add `setDefaultSlideStyle(styleId: number)` method

## Frontend — User Default (localStorage)

### Storage

`localStorage` key: `userDefaultSlideStyleId` — stores a style ID (number) or absent.

### AgentConfigContext (pre-session mode)

The override happens inside the existing `.then()` callback (line 98 of `AgentConfigContext.tsx`) where the default profile's config is loaded. After `setAgentConfig(defaultProfile.agent_config)`, read `userDefaultSlideStyleId` from localStorage and, if set, override `slide_style_id` in the same state update to avoid a double-render flicker:

```typescript
const userStyleId = localStorage.getItem('userDefaultSlideStyleId');
const config = defaultProfile.agent_config;
if (userStyleId) {
  config.slide_style_id = Number(userStyleId);
}
setAgentConfig(config);
```

Validation of stale IDs is deferred — not checked on mount. If the stored style ID no longer exists, the backend's `_validate_references()` in the PUT agent-config endpoint will reject it with a 422, and the `_get_default_style_id()` system default serves as the fallback during session creation. The Slide Styles page clears the localStorage key when it detects the stored ID isn't in the active list (lazy validation on page open, no extra API call on mount).

Priority: **user default > default profile's style > system default (backend fallback)**.

### Slide Styles page (`SlideStyleList.tsx`)

- "Set as my default" button on each card (separate from the system "Set as default")
- "My Default" badge on the style matching localStorage
- If user default matches system default, show both badges
- On page load, if `userDefaultSlideStyleId` points to a style not in the active list, clear it silently

## Testing

### Backend

- Unit tests for `POST /api/settings/slide-styles/{id}/set-default`: sets default, unsets previous, rejects inactive style, rejects nonexistent style, idempotent for already-default
- Test that deleting the default style is blocked with 400
- Test that deactivating the default style is blocked with 400
- Verify migration is idempotent

### Frontend E2E

- Add "set system default" test to existing `slide-styles-integration.spec.ts`: click button, verify badge moves

### Frontend unit test

- Test the priority resolution logic: user default overrides profile style, profile style overrides system default, stale user default falls through gracefully

### Existing tests

- `agent-config-integration.spec.ts` "new session gets default slide style" continues to pass since `_get_default_style_id()` queries `is_default=True` and the migration seeds it

## Out of Scope

- "Set as default" from the AgentConfigBar dropdown — deferred, settings page only for now
- Removing `is_system` flag — future work, `is_default` prepares for it
- Per-user server-side preferences table — localStorage is sufficient for now
- Dedicated `GET /api/settings/slide-styles/default` convenience endpoint — future optimization

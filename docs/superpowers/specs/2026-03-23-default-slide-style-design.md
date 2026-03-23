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

### Migration

In `_run_migrations()` in `src/core/database.py`, following the existing inspector-based pattern (not `IF NOT EXISTS` which is unsupported on older SQLite):

```python
# Check if is_default column exists using inspector
columns = [c["name"] for c in inspector.get_columns("slide_style_library")]
if "is_default" not in columns:
    op_sql = "ALTER TABLE slide_style_library ADD COLUMN is_default BOOLEAN DEFAULT FALSE NOT NULL"
    conn.execute(text(op_sql))

# Only seed a default if none exists yet (first deploy only)
conn.execute(text("""
    UPDATE slide_style_library SET is_default = TRUE
    WHERE is_system = TRUE
    AND NOT EXISTS (SELECT 1 FROM slide_style_library WHERE is_default = TRUE)
"""))
```

Idempotent: the column check prevents duplicate ADD COLUMN, and the `UPDATE` only runs when no default exists, so redeploys don't overwrite a user's choice.

### Seeding

In `init_default_profile.py`, set `is_default=True` on the "System Default" entry in `SYSTEM_SLIDE_STYLES`. New deployments get the default from `create_all()`.

### Default resolution

Update `_get_default_style_id()` in `src/api/routes/chat.py`:

- Query `is_default=True, is_active=True` instead of `is_system=True`
- Fallback to `is_system=True` if no default found (defensive, for mid-migration)

### Deletion / deactivation of the default style

Block deletion of the default style — same pattern as `profile_service.py` which blocks deletion of the default profile. The delete endpoint returns 400 with "Cannot delete the default style. Set another style as default first." The user must reassign the default before deleting.

## API

### New endpoint

`POST /api/settings/slide-styles/{style_id}/set-default`

- Validates the style exists and `is_active=True`
- `is_system` styles are valid targets (they can be the default)
- In a single transaction: unset previous default, set new default
- Returns the updated style
- Idempotent: setting the already-default style returns 200 with no change

### Existing endpoints

- `GET /api/settings/slide-styles` — add `is_default: bool` to the `SlideStyleResponse` pydantic schema. Also update all 4 construction sites where `SlideStyleResponse(...)` is built (list, get, create, update) to pass `is_default=s.is_default`.
- `DELETE /api/settings/slide-styles/{style_id}` — reject with 400 if the style has `is_default=True`.
- Create/Update — no changes. `is_default` is managed only through the dedicated endpoint.

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

On first mount with no stored `pendingAgentConfig`, after loading the default profile's config, check `userDefaultSlideStyleId` from localStorage. If set, validate that the ID exists in the active styles list (fetched from `/api/settings/slide-styles`). If the style no longer exists or is inactive, silently clear the localStorage key. Otherwise, override `slide_style_id`.

Priority: **user default > default profile's style > system default (backend fallback)**.

### Slide Styles page (`SlideStyleList.tsx`)

- "Set as my default" button on each card (separate from the system "Set as default")
- "My Default" badge on the style matching localStorage
- If user default matches system default, show both badges

## Testing

### Backend

- Unit tests for `POST /api/settings/slide-styles/{id}/set-default`: sets default, unsets previous, rejects inactive style, rejects nonexistent style, idempotent for already-default
- Test that deleting the default style is blocked with 400
- Verify migration is idempotent

### Frontend E2E

- Add "set system default" test to existing `slide-styles-integration.spec.ts`: click button, verify badge moves
- No E2E for localStorage user default (client-only state, simple read)

### Existing tests

- `agent-config-integration.spec.ts` "new session gets default slide style" continues to pass since `_get_default_style_id()` queries `is_default=True` and the migration seeds it

## Out of Scope

- "Set as default" from the AgentConfigBar dropdown — deferred, settings page only for now
- Removing `is_system` flag — future work, `is_default` prepares for it
- Per-user server-side preferences table — localStorage is sufficient for now
- Dedicated `GET /api/settings/slide-styles/default` convenience endpoint — future optimization

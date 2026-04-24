# System Default Slide Style — Admin Affordance

**Date:** 2026-04-23
**Status:** Design (awaiting user review)
**Related:** `docs/superpowers/specs/2026-04-22-tellr-mcp-server-design.md`

## 1. Problem

Tellr has two parallel "default slide style" mechanisms that can silently diverge:

- **Server side.** `slide_style_library.is_default` is a single global boolean column. The endpoint `POST /api/settings/slide_styles/{id}/set-default` atomically flips it. `get_default_slide_style_id()` reads it. The recent MCP `create_deck` fix relies on this path.
- **Client side.** The "Set as default" button on the user-facing slide style list writes only to `localStorage.userDefaultSlideStyleId`. It never calls the server endpoint. When the UI picks a default for a new deck, it prefers localStorage over the server value.

Consequence: no UI surface currently changes the DB value, so the server `is_default` row stays pinned to whatever was seeded at install time. The user's experience is "I set style X as my default," but the DB still points at whichever style the seeder happened to mark. MCP reads the DB, gets the seeded style, returns a deck styled differently than the one the user sees in the browser. The MCP fix looks broken from the user's perspective.

## 2. Guiding principle

**Something becomes a system-wide default if and only if it is organizationally meaningful for it to be consistent.**

Applied:

- **Slide style** — visual identity. Consistent across the org is the explicit goal (corporate branding). Gets a system default.
- **Deck prompt** — content scaffolding. Varies by workload, use case, individual working style. Stays per-user (localStorage).
- **Profile** — a bundle of tools + configuration. Personal working preference. Stays per-user (localStorage + server `is_default` already exists but is also dormant — out of scope here).

Only slide styles are changed by this design.

## 3. Target behavior

**System default (new).** Exactly one row in `slide_style_library` has `is_default=true`. Changeable only from the hidden `/admin` route. No authentication gating beyond the app's standard user auth ("security through obscurity" — the `/admin` route has no navigation link; a user has to know the URL). This is the corporate-branding default. MCP always uses this value.

**Per-user override (unchanged).** The existing "Set as default" button on the user-facing slide style list continues to write `localStorage.userDefaultSlideStyleId`. A logged-in user who has set a personal default sees their style on new decks. A user who has not sees the system default.

**First-run experience.** A brand-new user logs in, clicks "New Deck," and the deck opens with the system default applied — matching the Google-Slides "follows your corporate branding" expectation.

**MCP.** Always uses the system default; cannot see per-user localStorage. Accepted limitation; in-scope to revisit if per-user defaults ever move server-side.

## 4. Scope

**In scope:**
- New admin UI affordance at `/admin` → "Slide Style" tab → list of styles with "Set as system default" action.
- New frontend API client method `setSlideStyleSystemDefault(id)` calling the existing endpoint.

**Out of scope:**
- Changing deck prompt or profile default behavior.
- Server-side auth gating on `POST /api/settings/slide_styles/{id}/set-default`.
- Migrating per-user `localStorage.userDefaultSlideStyleId` entries to server-side storage.
- Any backend endpoint changes.
- Any MCP-side changes (the existing `get_default_slide_style_id()` lookup is already correct).

## 5. Files touched

| File | Change | Estimated size |
|---|---|---|
| `src/api/routes/settings/slide_styles.py` | Unchanged. `POST /{id}/set-default` already atomic. | 0 LOC |
| `src/api/mcp_server.py`, `src/core/settings_db.py` | Unchanged. | 0 LOC |
| `frontend/src/api/config.ts` | Add `setSlideStyleSystemDefault(id: number)` | ~5 LOC |
| `frontend/src/components/Admin/AdminSlideStyleDefault.tsx` | New. Lists slide styles, marks the `is_default=true` row with a badge, "Set as system default" button on others, confirmation toast on success/failure. | ~100 LOC |
| `frontend/src/components/Admin/AdminPage.tsx` | Add third tab entry and panel wiring. | ~15 LOC |
| `frontend/src/components/Admin/__tests__/AdminSlideStyleDefault.test.tsx` | New unit test for the component. | ~40 LOC |

Total: ~160 LOC, one new component, one new API method, one tab added to an existing page.

## 6. Component sketch

```tsx
// AdminSlideStyleDefault.tsx — shape only, not final code
const AdminSlideStyleDefault: React.FC = () => {
  const [styles, setStyles] = useState<SlideStyle[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [saving, setSaving] = useState<number | null>(null);  // id of style being set
  const { showToast } = useToast();

  const load = async () => { /* configApi.listSlideStyles() */ };
  useEffect(() => { load(); }, []);

  const handleSet = async (id: number) => {
    setSaving(id);
    try {
      await configApi.setSlideStyleSystemDefault(id);
      await load();
      showToast('System default slide style updated', 'success');
    } catch (e) {
      showToast(String(e), 'error');
    } finally {
      setSaving(null);
    }
  };

  // Render: list rows with name + "System default" badge on is_default,
  // "Set as system default" button otherwise. Disabled while saving.
};
```

Matches existing `config/SlideStyleList.tsx` visual language so users recognize the surface; only the action differs.

## 7. Data flow

**Admin sets system default:**
1. User navigates to `/admin` → selects "Slide Style" tab.
2. Component fetches `configApi.listSlideStyles()` → renders.
3. User clicks "Set as system default" on row *X*.
4. Frontend calls new `configApi.setSlideStyleSystemDefault(X)` → `POST /api/settings/slide-styles/{X}/set-default`.
5. Backend (existing logic): unsets previous `is_default` row, sets *X*.`is_default=true`, commits.
6. Frontend refreshes the list and shows the updated badge.

**Normal user creates a new deck (unchanged):**
1. `AgentConfigContext` resolves the default slide style via `resolveDefaultStyleId()`.
2. Priority: `localStorage.userDefaultSlideStyleId` > server `is_default` > server `is_system`.
3. Result populates `agent_config.slide_style_id` on the new session.

**MCP `create_deck` (unchanged; uses existing fix):**
1. Tool handler receives call with no `slide_style_id`.
2. `_create_deck_impl` calls `get_default_slide_style_id()` → reads DB `is_default=true`.
3. Resolved ID written to `agent_config.slide_style_id`.
4. `agent_factory` resolves the style content from the library by ID.

## 8. Error handling / edge cases

- **POST fails (network, 5xx, permission).** Toast surfaces the server error; list doesn't refresh. Same behavior the other admin-panel mutations already use.
- **No `is_default=true` row** (admin deleted or deactivated the current default). `get_default_slide_style_id()` already falls back to `is_system=true`, then to `None`. MCP treats `None` as "omit `slide_style_id`", and `agent_factory` uses the hardcoded `DEFAULT_SLIDE_STYLE` constant. Not a hard failure.
- **Inactive style selected as default.** The existing endpoint rejects this (`400 Cannot set an inactive style as default`). Admin UI does not show the "Set as system default" button on inactive rows.

## 9. Testing

- **Backend.** Existing `set_default_slide_style` tests cover the endpoint. No new backend tests.
- **Frontend unit.** New `AdminSlideStyleDefault.test.tsx`:
  - Renders the list from a mocked `listSlideStyles` response.
  - Clicking "Set as system default" calls `setSlideStyleSystemDefault` with the correct id.
  - After success, the list refetches and the badge moves to the new row.
  - Error path shows a toast and leaves the list unchanged.
- **Manual verification after deploy:**
  1. Visit `/admin`, switch to "Slide Style" tab, click "Set as system default" on a chosen style.
  2. Open a private browser window (no localStorage), log in, click "New Deck" → confirm the chosen style is applied to the new deck.
  3. Call MCP `create_deck` with no `slide_style_id` → confirm the returned deck uses the same style.
  4. In your normal browser (with a localStorage preference set), confirm the personal preference still takes precedence for browser-initiated decks.

## 10. Non-goals / deferred items

- **Admin role enforcement.** The endpoint remains open to any authenticated user. Acceptable for current scale.
- **Audit log of default changes.** Not tracked beyond the existing server log line in `set_default_slide_style`.
- **Per-user server-side default.** Not in this change — would be a significant lift (new table, migration, MCP lookup by caller identity). If later user research justifies it, revisit.
- **Deck prompt or profile defaults.** Left alone per the guiding principle.

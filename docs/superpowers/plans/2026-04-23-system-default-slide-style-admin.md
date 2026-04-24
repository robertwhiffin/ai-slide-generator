# Implementation Plan — System Default Slide Style Admin Affordance

**Date:** 2026-04-23
**Spec:** [2026-04-23-system-default-slide-style-admin.md](../specs/2026-04-23-system-default-slide-style-admin.md)
**Method:** Test-Driven Development (Red → Green → Refactor)
**Test framework:** Playwright E2E (the only frontend test tooling in this repo — no unit-test framework present).

## Summary

Add a new "Slide Style" tab to the existing `/admin` page that lets a caller pick which row in `slide_style_library` is the system default. Reuses the existing `POST /api/settings/slide-styles/{id}/set-default` endpoint. No backend changes. No MCP changes. Fully additive.

Total code footprint (≈ spec estimates):

- `frontend/src/api/config.ts` — one new client method (~5 LOC).
- `frontend/src/components/Admin/AdminSlideStyleDefault.tsx` — new file (~100 LOC).
- `frontend/src/components/Admin/AdminPage.tsx` — third tab (~15 LOC delta).
- `frontend/tests/fixtures/mocks.ts` — add `is_default` fields to existing `mockSlideStyles` (~3 LOC delta).
- `frontend/tests/e2e/admin-page.spec.ts` — new test cases (~80 LOC delta).

## Prerequisites

Before starting:

1. Confirm the existing `/admin` e2e tests still pass on the branch base:
   ```bash
   cd frontend && npx playwright test tests/e2e/admin-page.spec.ts
   ```
2. Confirm `is_default` is already on the `SlideStyle` TypeScript type (`frontend/src/api/config.ts`). If not, add it before the TDD cycles — it's a pure type addition, no runtime behavior.
3. Familiarise yourself with the patterns used by the existing "Feedback" and "Google Slides" tabs in `AdminPage.tsx`. The new tab must follow the same shape.

## Test data update (before Cycle 1)

The existing `mockSlideStyles` fixture in `frontend/tests/fixtures/mocks.ts` does not carry `is_default` fields. Add them so the new assertions can target specific rows:

- Style `id: 1` ("System Default"): `is_default: true`
- Style `id: 2` ("Corporate Theme"): `is_default: false`
- Style `id: 3` (inactive example, if present): `is_default: false`

This is a fixture-only change. No existing test asserts on `is_default`, so it cannot regress prior tests. Commit before the first TDD cycle so each cycle starts from a consistent state.

## TDD Cycles

Each cycle follows: **RED** (write test, run, watch fail) → **GREEN** (minimal code, run, watch pass) → **REFACTOR** (tidy only if needed, stay green).

Cycles are ordered to minimise rework — each builds on the previous and each test should fail *only* for the behavior it exercises, not because of missing plumbing from a later cycle.

---

### Cycle 1 — "Slide Style" tab appears on the admin page

**RED.** In `tests/e2e/admin-page.spec.ts`, add:

```ts
test('renders Slide Style tab alongside Feedback and Google Slides', async ({ page }) => {
  await page.goto('/admin');
  await expect(page.getByRole('tab', { name: 'Slide Style' })).toBeVisible();
});
```

Run: `npx playwright test tests/e2e/admin-page.spec.ts -g "Slide Style tab"` — must fail ("element not found").

**GREEN.** In `AdminPage.tsx`:

1. Extend the `TabId` type to include `'slide_style'`.
2. Add a third `<button role="tab">` with text "Slide Style" and the matching `onClick`/`aria-selected` pattern.
3. Add a third `<div role="tabpanel">` with `hidden={activeTab !== 'slide_style'}` containing a placeholder (e.g., `<div>TBD</div>`) — just enough to make the test pass. Real content comes in Cycle 2.

Run the test — must pass. Re-run the whole `admin-page.spec.ts` file — all four tests must pass.

**REFACTOR.** None needed yet.

---

### Cycle 2 — Slide Style tab renders the list of styles

**RED.** Add:

```ts
test('Slide Style tab renders each slide style name', async ({ page }) => {
  await page.goto('/admin');
  await page.getByRole('tab', { name: 'Slide Style' }).click();
  await expect(page.getByText('System Default')).toBeVisible();
  await expect(page.getByText('Corporate Theme')).toBeVisible();
});
```

Run — must fail (placeholder doesn't render names).

**GREEN.**

1. Create `frontend/src/components/Admin/AdminSlideStyleDefault.tsx`:
   - `useState` for `styles: SlideStyle[]` and `loading: boolean`.
   - `useEffect` on mount: `configApi.listSlideStyles()` → `setStyles(resp.styles)` → `setLoading(false)`.
   - Render: loading spinner while `loading`; otherwise a `<ul>` of style names (minimum markup to make the assertion pass — one `<li>` per row rendering `style.name`).
2. In `AdminPage.tsx`, replace the `<div>TBD</div>` placeholder with `<AdminSlideStyleDefault />`.

Run — must pass.

**REFACTOR.** If the markup grew verbose, extract a tiny `StyleRow` sub-component; otherwise leave it.

---

### Cycle 3 — "System default" badge on the `is_default=true` row

**RED.** Add:

```ts
test('Slide Style tab marks the is_default row with a "System default" badge', async ({ page }) => {
  await page.goto('/admin');
  await page.getByRole('tab', { name: 'Slide Style' }).click();
  // Row 1 ("System Default") is the is_default=true fixture row.
  const row = page.getByRole('listitem').filter({ hasText: 'System Default' });
  await expect(row.getByText('System default')).toBeVisible();
  // Row 2 ("Corporate Theme") must not have the badge.
  const otherRow = page.getByRole('listitem').filter({ hasText: 'Corporate Theme' });
  await expect(otherRow.getByText('System default')).toHaveCount(0);
});
```

Run — must fail (no badge rendered yet).

**GREEN.** In `AdminSlideStyleDefault.tsx`, add a conditional `<span className="badge">System default</span>` inside the row when `style.is_default === true`. Use whatever badge styling the codebase already uses elsewhere (search for an existing `Badge` component — if none, plain `<span>` + tailwind is fine).

Run — must pass.

**REFACTOR.** None expected.

---

### Cycle 4 — "Set as system default" button on non-default active rows

**RED.** Add:

```ts
test('Slide Style tab shows "Set as system default" on non-default active rows', async ({ page }) => {
  await page.goto('/admin');
  await page.getByRole('tab', { name: 'Slide Style' }).click();
  const defaultRow = page.getByRole('listitem').filter({ hasText: 'System Default' });
  const otherRow = page.getByRole('listitem').filter({ hasText: 'Corporate Theme' });
  // The default row should not offer the action.
  await expect(defaultRow.getByRole('button', { name: 'Set as system default' })).toHaveCount(0);
  // Another active, non-default row should.
  await expect(otherRow.getByRole('button', { name: 'Set as system default' })).toBeVisible();
});
```

Run — must fail (no button rendered yet).

**GREEN.** Extend the row rendering: when `style.is_active && !style.is_default`, render a `<button>` labelled "Set as system default". No click handler yet — just the markup. Run — must pass.

**REFACTOR.** None.

---

### Cycle 5 — Clicking the button calls the API and updates the badge

**RED.** Add:

```ts
test('Clicking Set as system default calls the endpoint and updates the badge', async ({ page }) => {
  // Intercept the set-default endpoint. Record the URL that was hit.
  let setDefaultUrl: string | null = null;
  await page.route('**/api/settings/slide-styles/*/set-default', async (route, req) => {
    setDefaultUrl = req.url();
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id: 2, name: 'Corporate Theme', is_default: true }) });
  });

  // After the POST, the list refetch should return the new state.
  // Update the list mock so the second call returns Corporate Theme as default.
  let listCallCount = 0;
  await page.route('**/api/settings/slide-styles', (route) => {
    listCallCount += 1;
    const styles = listCallCount === 1
      ? mockSlideStyles.styles // initial: System Default is default
      : mockSlideStyles.styles.map(s => ({ ...s, is_default: s.id === 2 }));
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ styles, total: styles.length }) });
  });

  await page.goto('/admin');
  await page.getByRole('tab', { name: 'Slide Style' }).click();
  const otherRow = page.getByRole('listitem').filter({ hasText: 'Corporate Theme' });
  await otherRow.getByRole('button', { name: 'Set as system default' }).click();

  // URL assertion — exact id is in the path.
  expect(setDefaultUrl).toContain('/api/settings/slide-styles/2/set-default');
  // Badge now on Corporate Theme.
  await expect(otherRow.getByText('System default')).toBeVisible();
  // Badge removed from System Default.
  const oldRow = page.getByRole('listitem').filter({ hasText: 'System Default' });
  await expect(oldRow.getByText('System default')).toHaveCount(0);
});
```

Run — must fail (no click handler, API client method doesn't exist).

**GREEN.**

1. Add `setSlideStyleSystemDefault(id: number)` to `frontend/src/api/config.ts` — one method posting to `${API_BASE}/slide-styles/${id}/set-default` and returning the updated style. Match the style of the existing `setDefaultProfile` method.
2. Wire the button's `onClick` in `AdminSlideStyleDefault.tsx`:
   ```tsx
   const handleSet = async (id: number) => {
     setSaving(id);
     try {
       await configApi.setSlideStyleSystemDefault(id);
       const resp = await configApi.listSlideStyles();
       setStyles(resp.styles);
     } catch (e) {
       // Cycle 6 adds toast handling
     } finally {
       setSaving(null);
     }
   };
   ```
3. Add `saving: number | null` state so the button can be disabled while in-flight. Wire a `disabled={saving === style.id}` prop.

Run — must pass.

**REFACTOR.** If the inline-fetch-after-POST pattern feels clunky, consider making `setSlideStyleSystemDefault` return the list directly — but only if it keeps the test green with no change.

---

### Cycle 6 — Error toast on failure

**RED.** Add:

```ts
test('Failed set-default call surfaces an error toast', async ({ page }) => {
  await page.route('**/api/settings/slide-styles/*/set-default', (route) => {
    route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'boom' }) });
  });
  await page.goto('/admin');
  await page.getByRole('tab', { name: 'Slide Style' }).click();
  await page.getByRole('listitem').filter({ hasText: 'Corporate Theme' })
    .getByRole('button', { name: 'Set as system default' }).click();
  // The existing codebase uses a toast component; match the assertion to whatever
  // data-testid or role the existing error toasts expose. Inspect one other admin
  // error path (e.g. Google Slides credential upload) to confirm the selector.
  await expect(page.getByText(/failed|error|boom/i)).toBeVisible();
});
```

Run — must fail (no toast wiring).

**GREEN.** In `AdminSlideStyleDefault.tsx`, pull in the toast utility the existing admin components use (search `components/Admin` or `contexts/ToastContext` for the pattern) and call `showToast(message, 'error')` in the `catch` branch of `handleSet`. Run — must pass.

**REFACTOR.** None.

---

### Cycle 7 — Inactive rows do not offer the button

**RED.** Ensure the `mockSlideStyles` fixture contains at least one `is_active: false` row (add one if necessary — this is a fixture tweak before the RED step). Then add:

```ts
test('Inactive slide styles do not show the Set as system default button', async ({ page }) => {
  await page.goto('/admin');
  await page.getByRole('tab', { name: 'Slide Style' }).click();
  const inactiveRow = page.getByRole('listitem').filter({ hasText: '<name-of-inactive-fixture>' });
  await expect(inactiveRow.getByRole('button', { name: 'Set as system default' })).toHaveCount(0);
});
```

Run — must fail if the current condition only checks `!is_default` but not `is_active`. If it already correctly guards on `is_active` from Cycle 4, this test will pass on RED — in that case note it and collapse the cycle (write the test and verify it passes to prevent regression).

**GREEN.** If the test failed, add the `is_active` guard to the button-render condition. Run — must pass.

---

### Final full-file run

```bash
cd frontend && npx playwright test tests/e2e/admin-page.spec.ts
```

All tests in the file must pass, including the pre-existing three. Also run the broader test suite once to ensure no cross-test pollution from the new mock routes:

```bash
cd frontend && npx playwright test
```

---

## Documentation updates

After the component work lands (between the last TDD cycle and the manual verification), walk through the docs and align wording with the new two-tier model. Keep the edits minimal — no new pages, just a few targeted tweaks.

Files to revisit:

**Technical docs:**

- **`docs/technical/mcp-server.md`** — The `slide_style_id` row in the `create_deck` input schema currently says "Omit for default." Clarify: "Omit to use the system default (settable at `/admin`); MCP cannot see per-user localStorage overrides."
- **`docs/technical/mcp-integration-guide.md`** — Cross-check any mention of slide style defaults and align with the MCP server doc's updated wording so they don't drift.
- **`docs/technical/frontend-overview.md`** — Add a short note that `/admin` now exposes a "Slide Style" tab for setting the system default, and briefly describe the two-tier resolution (localStorage → DB `is_default` → `is_system` fallback) so a future reader can understand why the frontend helper `resolveDefaultStyleId()` has three tiers.
- **`docs/technical/database-configuration.md`** — If it references `slide_style_library.is_default`, confirm the description matches the new behavior (one row system-wide, settable via `/admin`).

**User-facing docs:**

- **`docs/user-guide/05-creating-custom-styles.md`** — The primary place users learn about slide styles. Add a short section (one or two paragraphs) covering: (a) there is a system-wide "corporate" default that applies to every new deck out of the box, settable only at `/admin`; (b) the existing "Set as default" button on their own slide style list continues to let them set a personal default that overrides the corporate one for their browser only. Frame it the way the design's Google Slides analogy does — "new decks inherit the corporate look unless you've chosen otherwise for yourself."
- **`docs/user-guide/02-creating-profiles.md`** — If it describes slide style selection flow in terms that imply "the default is whatever your last choice was," update to reference the two-tier model briefly and cross-link to 05-creating-custom-styles.
- **`docs/user-guide/01-generating-slides.md`** — Scan for any mention of default styling and align if needed; likely nothing to change.
- **`docs/user-guide/README.md`** — If it has a table of contents entry or section overview touching styles, ensure nothing there conflicts with the new model.

What to write: one or two sentences per file. The goal is to leave no stale descriptions claiming there's no UI surface for changing the DB default, which is where the docs stand today. Do NOT rewrite these docs wholesale — scope is "fix the specific lines that would mislead a reader after this change ships."

Commit the docs update as its own commit (not bundled with component code) so a future `git log` reader can see "docs align with new admin affordance" as a discrete step.

## Post-Implementation Manual Verification (after deploy)

Per spec section 9:

1. Deploy tellr. Visit `/admin`, switch to "Slide Style" tab, click "Set as system default" on a chosen style. Confirm the badge moves.
2. Open a private browser window (no localStorage), log in, click "New Deck". Confirm the deck uses the chosen style.
3. Call the MCP `create_deck` with no `slide_style_id`. Confirm the returned deck uses the same style.
4. In your normal browser (with a localStorage preference already set), confirm the personal preference still takes precedence for browser-initiated decks.

## Git Strategy

One commit per TDD cycle is ideal but not mandatory — two commits is acceptable:

- Commit A — fixture + tab wiring (Cycles 1 + 2 + test-data update).
- Commit B — everything else (Cycles 3-7 + API method + component).
- Commit C — docs updates (see "Documentation updates" section).

Plus a final commit for the manual verification notes if any surprises emerge.

Push the branch; open a PR targeting `main` with the spec document linked in the description.

## Rollback

If the deploy goes sideways and the admin flow breaks, the change is purely additive — reverting the branch restores the previous behavior. The MCP `create_deck` fallback to `get_default_slide_style_id()` continues to read whatever DB row happens to be `is_default=True` either way.

## Out of scope — do not do in this plan

- No backend changes.
- No changes to the user-facing slide style list (`SlideStyleList.tsx`).
- No changes to MCP code.
- No changes to profile or deck prompt default handling.
- No server-side auth gating on the `set-default` endpoint.
- No migration of existing `localStorage.userDefaultSlideStyleId` entries.

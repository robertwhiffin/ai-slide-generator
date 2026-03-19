# Docusaurus Documentation Update — Design Spec

**Date:** 2026-03-19
**Branch:** feature/profile-rebuild
**Context:** The profile rebuild is fully implemented. Most doc text was updated during implementation, but the Docusaurus site config, sidebar coverage, screenshots, and a few text files remain stale.

---

## 1. Remove: API Reference Section

Remove the entire `docs/api/` directory (8 files) and all Docusaurus references. The API is internal (consumed only by the bundled React frontend) and the auto-generated Swagger UI at `/docs` on a running instance is the authoritative reference.

**Files to delete:**
- `docs/api/overview.md`
- `docs/api/settings.md`
- `docs/api/sessions.md`
- `docs/api/chat.md`
- `docs/api/slides.md`
- `docs/api/export.md`
- `docs/api/verification.md`
- `docs/api/openapi-schema.md`

**Config changes in `docs-site/docusaurus.config.js`:**
- Remove "API Reference" navbar item (lines 89-94)
- Remove "API Reference" footer link (lines 118-121)

**Config changes in `docs-site/sidebars.js`:**
- Remove entire `api` sidebar definition (lines 66-81)

**Replacement:** Add a one-line note in `docs/technical/backend-overview.md` at the top of the existing API surface section (which lists endpoint tables — keep those, they're useful for technical readers). Note should say: "For full endpoint details, request/response schemas, and interactive testing, see the Swagger UI at `/docs` on any running instance."

---

## 2. Fix: Sidebar Coverage

Several technical docs exist on disk but are missing from `sidebars.js`. Since we're already editing the sidebar to remove the API section, add the missing entries.

**Add to `technical` sidebar:**
- `technical/save-points-versioning`
- `technical/url-routing`
- `technical/image-upload`
- `technical/google-slides-integration`
- `technical/feedback-system`

**Do NOT add to sidebar:**
- `*-tests.md` files (7 files) — these are internal test documentation, not user/developer-facing. Leave them accessible via direct URL but not in nav.
- `docs/OPEN_ISSUES.md` — internal tracking, not sidebar material. No stale profile references found.

**Remove duplicate:**
- `docs/local-development.md` is nearly identical to `docs/getting-started/local-development.md` (one trivial line differs). Delete the root-level duplicate. Verify no other docs link to it; if they do, update the links.

---

## 3. Update: `docs/user-guide/README.md`

This file has two stale sections:

**Quick Start (lines 19-23):** Completely rewrite. Current text references "Click New Session" and "Check your profile — shown top-right; switch if needed." New text should reflect:
1. Open the app — land directly on the generator
2. Optionally add Genie spaces or other tools via the config bar
3. Enter a prompt describing your presentation
4. Click Send — session created automatically on first message
5. Refine through follow-up messages

**Guide table (line 10):** Update the "Creating Profiles" description from "Set up configuration profiles linking Genie rooms, styles, and prompts" to something like "Save and load session configurations as reusable profiles."

---

## 4. Verify: Already-Updated Docs

These files were updated during the profile rebuild implementation. Verify they're accurate — no rewrites expected, but check for:
- Stale profile/wizard terminology
- References to old UI elements (profile selector in header, profile creation wizard)
- Broken internal links (especially after API docs removal)

| File | What to verify |
|------|---------------|
| `docs/getting-started/quickstart.md` | Already references AgentConfigBar and pre-session mode. Confirm. |
| `docs/getting-started/how-it-works.md` | Already mentions prompt-only mode. Confirm no profile-centric language. |
| `docs/user-guide/01-generating-slides.md` | Already references AgentConfigBar and session-on-first-message. Confirm. |
| `docs/user-guide/02-creating-profiles.md` | Already rewritten for save-from-session/load-into-session. Confirm text. Screenshots are stale (handled in section 6). |
| `docs/user-guide/05-creating-custom-styles.md` | Unrelated to profiles. Quick scan for any cross-references to old profile concepts. |
| `docs/technical/profile-switch-genie-flow.md` | Already documents per-tool conversation IDs and `build_agent_for_request()`. Optional: change "Conversation IDs are reset" to "conversation_id fields are cleared; fresh conversations initialize on first Genie query." |
| `docs/technical/backend-overview.md` | Already references `agent_factory.py` and per-request builds. Verify conversation ID docs are accurate (per-tool in `agent_config.tools[]` vs legacy fallback). |

---

## 5. Update: `docs/technical/frontend-overview.md` — Provider Tree

Both `ProfileContext` and `AgentConfigContext` are active and complementary (not a naming error):

- **AgentConfigProvider** (wraps in `App.tsx`): Manages the active agent config (tools, style, prompt). Two modes: pre-session (localStorage) and active session (backend-synced). Used by AgentConfigBar, ChatPanel.
- **ProfileProvider** (wraps in `AppLayout.tsx`): Manages profile CRUD (list, create, rename, delete, duplicate, set default) and profile loading/selection. Used by ProfileList component on `/profiles` page.

The frontend-overview doc should document both providers with their distinct scopes and explain how they interact: ProfileContext manages profile metadata and selection; AgentConfigContext manages the actual tool/style/prompt configuration and session syncing. Users save configs as profiles via AgentConfigContext.saveAsProfile, and load profiles via AgentConfigContext.loadProfile.

**Placement:** Add as a new subsection under the existing context/provider documentation, expanding the entrypoint paragraph (line 10) that currently mentions only `AgentConfigProvider`. Include both providers in the provider tree diagram.

---

## 6. Rewrite: Playwright Screenshot Specs

This is the bulk of the remaining work. The user guide text is largely current, but screenshots are stale.

### `frontend/tests/user-guide/shared.ts` — VERIFY + MINOR FIXES
- Verify `goToGenerator()` still works: it navigates to `/`, clicks `button:has-text("New Deck")`, then waits for `/sessions/.../edit`. Since the landing page IS the generator in pre-session mode, decide based on screenshot intent: if capturing pre-session state (config bar with no session), the helper should navigate to `/` and stop (no "New Deck" click). If capturing an active session, the current flow is fine. Update the helper or create a variant as needed.
- Check legacy mock route `http://127.0.0.1:8000/api/settings/profiles` (line ~186) — this endpoint may be gone (replaced by `/api/profiles`). Remove if stale. Note: this legacy route pattern also exists in other E2E test files outside the user-guide specs (history-ui, chat-ui, etc.) — cleanup those separately if desired, but this spec scopes to user-guide specs only.
- Verify other mock response shapes match current API.

### `frontend/tests/user-guide/01-generating-slides.spec.ts` — UPDATE
- **Steps 03-04:** Delete. They try to find a profile button in the header (`page.locator('header').getByRole('button', { name: /Profile|Sales Analytics/i })`) which no longer exists. The AgentConfigBar is already captured in Step 02.
- **Step 02:** Verify `goToGenerator()` works with new landing page flow (see shared.ts note above).
- Remaining steps (landing, chat input, send, slides) should work — verify selectors.

### `frontend/tests/user-guide/02-creating-profiles.spec.ts` — FULL REWRITE
The entire spec captures a wizard-based profile creation flow that no longer exists (steps reference "Create New Profile" modal with 5 wizard steps). Replace with:
1. Generator view showing AgentConfigBar with configured tools
2. "Save as Profile" action triggered from AgentConfigBar
3. Save dialog with name/description fields
4. Profiles page showing saved profiles list
5. "Load Profile" action from AgentConfigBar
6. Profile selection and loading into session
7. Profile management on Profiles page (edit name, delete)

---

## 7. Verify: Footer Slug Resolution

The Docusaurus footer links to slugs that are derived from filenames with numeric prefixes:
- `/docs/user-guide/generating-slides` (from `01-generating-slides.md`)
- `/docs/user-guide/advanced-configuration` (from `03-advanced-configuration.md`)

These work because the sidebar already uses the unprefixed slugs (e.g., `user-guide/generating-slides`). But verify these resolve correctly after all changes. The `onBrokenLinks: 'throw'` build setting will catch failures, but flagging here for awareness.

---

## Implementation Order

1. **Remove API docs + fix Docusaurus config** — delete files, update navbar/sidebar/footer
2. **Fix sidebar coverage** — add missing technical docs, remove duplicate `docs/local-development.md`
3. **Update README Quick Start + guide table** — the only text file needing a real rewrite
4. **Verify already-updated docs** — quick scan of ~7 files for stale references
5. **Update frontend-overview.md** — document both providers with distinct roles
6. **Add Swagger UI note** — one line in backend-overview.md
7. **Update Playwright specs** — shared.ts fixes, delete steps 03-04 from generating-slides, full rewrite of creating-profiles
8. **Run Playwright** — regenerate all screenshots
9. **Build Docusaurus** — verify site builds cleanly, no broken links

---

## Out of Scope

- User guide sections 04-07 (feedback, styles, images, Google Slides — unaffected by profile rebuild)
- Technical docs unrelated to profile rebuild (streaming, concurrency, exports, etc.)
- New documentation for features not yet implemented (MCP tools)
- Merging/removing `ProfileContext.tsx` (both contexts are active and complementary — this is not dead code)
- Test documentation files (`*-tests.md`) — internal, not added to sidebar

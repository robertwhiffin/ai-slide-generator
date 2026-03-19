# Docusaurus Documentation Update — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update the Docusaurus documentation site to reflect the completed profile rebuild, remove stale API docs, fix sidebar coverage, update screenshots.

**Architecture:** Delete `docs/api/` (8 files), update Docusaurus config (navbar/sidebar/footer), fix text in 3 docs, verify 7 docs, rewrite 2 Playwright specs, regenerate screenshots, build site.

**Tech Stack:** Docusaurus 3.9.2, Playwright, React/TypeScript

---

## Chunk 1: Remove API Docs + Fix Docusaurus Config

### Task 1: Delete API doc files

**Files:**
- Delete: `docs/api/overview.md`
- Delete: `docs/api/settings.md`
- Delete: `docs/api/sessions.md`
- Delete: `docs/api/chat.md`
- Delete: `docs/api/slides.md`
- Delete: `docs/api/export.md`
- Delete: `docs/api/verification.md`
- Delete: `docs/api/openapi-schema.md`

- [ ] **Step 1: Delete the API directory**

```bash
rm -rf docs/api/
```

- [ ] **Step 2: Verify deletion**

```bash
ls docs/api/ 2>&1
```

Expected: `No such file or directory`

- [ ] **Step 3: Commit**

```bash
git add -A docs/api/
git commit -m "docs: remove API reference section — Swagger UI is authoritative"
```

---

### Task 2: Update Docusaurus config — remove API navbar item and footer link

**Files:**
- Modify: `docs-site/docusaurus.config.js`

- [ ] **Step 1: Remove API Reference navbar item**

In `docs-site/docusaurus.config.js`, remove this block from `themeConfig.navbar.items`:

```javascript
          {
            type: 'docSidebar',
            sidebarId: 'api',
            position: 'left',
            label: 'API Reference',
          },
```

- [ ] **Step 2: Remove API Reference footer link**

In the same file, remove this block from `themeConfig.footer.links[0].items` (the "Documentation" column):

```javascript
              {
                label: 'API Reference',
                to: '/docs/api/overview',
              },
```

- [ ] **Step 3: Commit**

```bash
git add docs-site/docusaurus.config.js
git commit -m "docs: remove API Reference from navbar and footer"
```

---

### Task 3: Update sidebars — remove API sidebar, add missing technical docs

**Files:**
- Modify: `docs-site/sidebars.js`

- [ ] **Step 1: Remove the `api` sidebar definition**

In `docs-site/sidebars.js`, delete the entire `api` key:

```javascript
  api: [
    {
      type: 'category',
      label: 'API Reference',
      items: [
        'api/overview',
        'api/sessions',
        'api/chat',
        'api/slides',
        'api/export',
        'api/verification',
        'api/settings',
        'api/openapi-schema',
      ],
    },
  ],
```

- [ ] **Step 2: Add missing technical docs to the `technical` sidebar**

Add these 5 entries to the end of the `technical` sidebar `items` array, after `'technical/profile-switch-genie-flow'`:

```javascript
        'technical/save-points-versioning',
        'technical/url-routing',
        'technical/image-upload',
        'technical/google-slides-integration',
        'technical/feedback-system',
```

- [ ] **Step 3: Commit**

```bash
git add docs-site/sidebars.js
git commit -m "docs: remove API sidebar, add 5 missing technical docs to sidebar"
```

---

### Task 4: Delete duplicate `docs/local-development.md`

**Files:**
- Delete: `docs/local-development.md`

- [ ] **Step 1: Check for any references to the root-level file**

```bash
# Search for links pointing to the root-level file (not getting-started/)
grep -r "local-development" docs/ --include="*.md" | grep -v "getting-started"
```

If any references are found, update them to point to `getting-started/local-development` before deleting.

- [ ] **Step 2: Delete the duplicate**

```bash
rm docs/local-development.md
```

- [ ] **Step 3: Commit**

```bash
git add docs/local-development.md
git commit -m "docs: remove duplicate local-development.md (canonical copy in getting-started/)"
```

---

### Task 5: Add Swagger UI note to backend-overview.md

**Files:**
- Modify: `docs/technical/backend-overview.md`

- [ ] **Step 1: Add note at the top of the API Surface section**

Insert the following line immediately after the `## API Surface (Contracts Shared with Frontend)` heading (line 41 of `docs/technical/backend-overview.md`), before the first table:

```markdown

> **Interactive API docs:** For full endpoint details, request/response schemas, and interactive testing, see the Swagger UI at `/docs` on any running instance.
```

- [ ] **Step 2: Commit**

```bash
git add docs/technical/backend-overview.md
git commit -m "docs: add Swagger UI reference in backend-overview"
```

---

## Chunk 2: Update Text Docs

### Task 6: Rewrite `docs/user-guide/README.md` Quick Start and guide table

**Files:**
- Modify: `docs/user-guide/README.md`

- [ ] **Step 1: Update guide table description for Creating Profiles**

Change line 10 from:

```markdown
| [Creating Profiles](./02-creating-profiles.md) | Set up configuration profiles linking Genie rooms, styles, and prompts |
```

To:

```markdown
| [Creating Profiles](./02-creating-profiles.md) | Save and load session configurations as reusable profiles |
```

- [ ] **Step 2: Rewrite Quick Start section**

Replace lines 17-23:

```markdown
## Quick Start

1. **Open the app** - Navigate to the application URL
2. **Start a session** - Click "New Session" in the navigation bar
3. **Check your profile** - The active profile is shown top-right; switch if needed
4. **Enter a prompt** - Describe the presentation you want to create
5. **Send** - Click Send and watch your slides generate
```

With:

```markdown
## Quick Start

1. **Open the app** — you land directly on the generator
2. **Add tools** (optional) — click "Add Tool" in the config bar to connect Genie spaces or other data sources
3. **Enter a prompt** — describe the presentation you want to create
4. **Click Send** — a session is created automatically and slides begin generating
5. **Refine** — send follow-up messages to edit, add, or restyle slides
```

- [ ] **Step 3: Commit**

```bash
git add docs/user-guide/README.md
git commit -m "docs: update user guide README Quick Start for new landing flow"
```

---

### Task 7: Update `docs/technical/frontend-overview.md` — Provider documentation

**Files:**
- Modify: `docs/technical/frontend-overview.md`

- [ ] **Step 1: Expand the entrypoint paragraph**

In `docs/technical/frontend-overview.md`, replace line 10:

```markdown
- **Entrypoint:** `src/main.tsx` wraps `<App />` in `<BrowserRouter>` and injects into `#root`. `src/App.tsx` wraps the tree in `AgentConfigProvider`, `SessionProvider`, `GenerationProvider`, `SelectionProvider`, `ToastProvider` and defines routes via React Router v7 — each route renders `AppLayout` with `initialView` and optional `viewOnly` props.
```

With:

```markdown
- **Entrypoint:** `src/main.tsx` wraps `<App />` in `<BrowserRouter>` and injects into `#root`. `src/App.tsx` wraps the tree in `AgentConfigProvider`, `SessionProvider`, `GenerationProvider`, `SelectionProvider`, `ToastProvider` and defines routes via React Router v7 — each route renders `AppLayout` (which adds `ProfileProvider`) with `initialView` and optional `viewOnly` props.
```

- [ ] **Step 2: Add provider documentation after the Generation Context section**

Insert the following after the Generation Context section (after line 107) and before "### 5. Version Check":

```markdown

### 4b. Agent Config Context (`src/contexts/AgentConfigContext.tsx`)

Manages the active agent configuration (tools, slide style, deck prompt). Operates in two modes:

- **Pre-session mode** (no `/sessions/:id/` in URL): Config stored in React state + localStorage. Persists across navigation until a session is created.
- **Active session mode**: Config loaded from backend on session change. Updates synced via `PUT /api/sessions/{id}/agent-config` with optimistic updates (reverts on failure).

```typescript
// Key operations
updateConfig(config)       // Replace full agent config
addTool(tool)              // Add a Genie space or MCP server
removeTool(tool)           // Remove a tool
setStyle(styleId)          // Set slide style
setDeckPrompt(promptId)    // Set deck prompt
saveAsProfile(name, desc)  // Save current config as a named profile (active session only)
loadProfile(profileId)     // Load a profile's config into current session
```

Used by: `AgentConfigBar`, `ChatPanel`.

### 4c. Profile Context (`src/contexts/ProfileContext.tsx`)

Manages profile CRUD operations and the profile list. Wraps inside `AppLayout` (not app-level) because it's only needed by the profile management page.

```typescript
// Key operations
reload()                   // Refresh profile list from backend
createProfile(data)        // Create new profile
updateProfile(id, data)    // Update profile metadata (name, description)
deleteProfile(id)          // Delete a profile
setDefaultProfile(id)      // Mark profile as default
loadProfile(id)            // Load profile and trigger hot-reload
```

Used by: `ProfileList` on the `/profiles` page.

**How they interact:** `AgentConfigContext` handles the active session's tool/style/prompt configuration. `ProfileContext` handles profile metadata (names, defaults, CRUD). Users save configs as profiles via `AgentConfigContext.saveAsProfile()` and browse/manage profiles via `ProfileContext`.
```

- [ ] **Step 3: Commit**

```bash
git add docs/technical/frontend-overview.md
git commit -m "docs: document AgentConfigContext and ProfileContext provider roles"
```

---

### Task 8: Verify already-updated docs for stale references

**Files:**
- Verify: `docs/getting-started/quickstart.md`
- Verify: `docs/getting-started/how-it-works.md`
- Verify: `docs/user-guide/01-generating-slides.md`
- Verify: `docs/user-guide/02-creating-profiles.md`
- Verify: `docs/user-guide/05-creating-custom-styles.md`
- Verify: `docs/technical/profile-switch-genie-flow.md`
- Verify: `docs/technical/backend-overview.md`

- [ ] **Step 1: Search for stale terminology across all docs**

```bash
grep -rn "profile creation wizard\|New Session.*button\|profile.*top-right\|singleton.*agent\|ProfileCreationWizard\|/api/overview\|/api/settings\|/api/sessions\|/api/chat\|/api/slides\|/api/export\|/api/verification" docs/ --include="*.md" | grep -v "superpowers/" | grep -v "api/"
```

Fix any matches found. Common fixes:
- Replace broken links to `docs/api/*` with a note about Swagger UI
- Replace "profile creation wizard" with "Save as Profile"
- Replace "singleton agent" with "per-request agent"

- [ ] **Step 2: Optional — improve profile-switch-genie-flow.md wording**

In `docs/technical/profile-switch-genie-flow.md`, if you find "Conversation IDs are reset", change to "conversation_id fields are cleared; fresh conversations initialize on first Genie query."

- [ ] **Step 3: Commit any fixes**

```bash
git add docs/
git commit -m "docs: fix stale references found during verification pass"
```

If no changes were needed, skip this commit.

---

## Chunk 3: Rewrite Playwright Screenshot Specs

### Task 9: Update `shared.ts` — remove legacy mock, add pre-session helper

**Files:**
- Modify: `frontend/tests/user-guide/shared.ts`

- [ ] **Step 1: Remove legacy profile mock route**

Delete lines 185-192 (the legacy `api/settings/profiles` route):

```typescript
  // Legacy profiles
  await page.route('http://127.0.0.1:8000/api/settings/profiles', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockProfiles)
    });
  });
```

- [ ] **Step 1b: Check if `mockProfiles` is still used elsewhere**

After removing the legacy route, `mockProfiles` (imported from `../fixtures/mocks`) may be unused in `shared.ts`. Check if it's referenced elsewhere in the file. If not, remove it from the destructured import at line 167 to prevent lint errors.

- [ ] **Step 2: Add a `goToPreSessionGenerator` helper**

Add after the existing `goToGenerator` function (after line 258):

```typescript
/**
 * Navigate to the pre-session generator (landing page, no session created).
 * Use this when you want to capture the config bar before a session exists.
 */
export async function goToPreSessionGenerator(page: Page): Promise<void> {
  await page.goto('/');
  await page.getByRole('textbox').waitFor({ state: 'visible', timeout: 10000 });
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/tests/user-guide/shared.ts
git commit -m "docs: update shared.ts — remove legacy mock, add pre-session helper"
```

---

### Task 10: Fix `01-generating-slides.spec.ts` — remove stale profile steps

**Files:**
- Modify: `frontend/tests/user-guide/01-generating-slides.spec.ts`

- [ ] **Step 1: Update the file header comment**

Replace lines 7-13:

```typescript
 * The workflow covers:
 * 1. Opening the app / logging in
 * 2. Navigating to the Generator page
 * 3. Selecting a profile
 * 4. Entering a prompt and generating slides
 * 5. Viewing and interacting with generated slides
```

With:

```typescript
 * The workflow covers:
 * 1. Opening the app (landing page is the generator)
 * 2. Navigating to an active session
 * 3. Entering a prompt and generating slides
 * 4. Viewing and interacting with generated slides
```

- [ ] **Step 2: Delete Steps 03-04 (profile selector)**

Delete lines 47-67 (Step 03: Profile Selector and Step 04: Open Profile Dropdown, including the Escape/close dropdown):

```typescript
    // Step 03: Profile Selector
    await capture.capture({
      step: '03',
      name: 'profile-selector',
      description: 'The current profile is shown in the header - click to change profiles',
      highlightSelector: '[data-testid="chat-panel"]',
    });

    // Step 04: Open Profile Dropdown (new UI: profile button may show profile name)
    await page.locator('header').getByRole('button', { name: /Profile|Sales Analytics/i }).click();
    // Wait for dropdown to appear
    await page.waitForTimeout(300);
    await capture.capture({
      step: '04',
      name: 'profile-dropdown',
      description: 'Select the profile that matches your data source and presentation style',
    });

    // Close dropdown by clicking elsewhere
    await page.keyboard.press('Escape');
    await page.waitForTimeout(200);
```

- [ ] **Step 3: Renumber remaining steps**

After deletion, renumber the captures sequentially. The mapping is:

| Old step | Old name | New step |
|----------|----------|----------|
| 05 | chat-input-empty | 03 |
| 06 | chat-input-with-prompt | 04 |
| 07 | send-button-enabled | 05 |
| 08 | slides-generated | 06 |
| 09 | slide-actions | 07 |
| 10 (second test) | empty-state | 08 |

For each capture call, update `step: '05'` → `step: '03'`, etc. Also update the corresponding comment lines (e.g., `// Step 05:` → `// Step 03:`).

- [ ] **Step 4: Run the spec to verify no selector failures**

```bash
cd frontend && npx playwright test user-guide/01-generating-slides.spec.ts --project=chromium 2>&1 | tail -20
```

Expected: Tests pass (screenshots may not show real slides since mocks don't return full chat response, but no selector errors).

- [ ] **Step 5: Commit**

```bash
git add frontend/tests/user-guide/01-generating-slides.spec.ts
git commit -m "docs: remove stale profile selector steps from generating-slides spec"
```

---

### Task 11: Rewrite `02-creating-profiles.spec.ts` — save-from-session flow

**Files:**
- Rewrite: `frontend/tests/user-guide/02-creating-profiles.spec.ts`

- [ ] **Step 1: Write the new spec**

Replace the entire file with:

```typescript
/**
 * User Guide: Creating Profiles
 *
 * This Playwright spec captures screenshots for the "Creating Profiles" workflow.
 * Run with: npx playwright test user-guide/02-creating-profiles.spec.ts
 *
 * The workflow covers:
 * 1. Viewing the AgentConfigBar with tools configured
 * 2. Saving a session config as a profile
 * 3. Browsing saved profiles on the Profiles page
 * 4. Loading a profile into a session
 */

import { test, expect } from '@playwright/test';
import {
  UserGuideCapture,
  setupUserGuideMocks,
  goToGenerator,
  goToPreSessionGenerator,
  goToProfiles
} from './shared';

test.describe('User Guide: Creating Profiles', () => {
  test('capture save-from-session workflow', async ({ page }) => {
    await setupUserGuideMocks(page);
    const capture = new UserGuideCapture(page, '02-creating-profiles');

    // Step 01: Show pre-session generator with config bar
    await goToPreSessionGenerator(page);
    await capture.capture({
      step: '01',
      name: 'pre-session-config-bar',
      description: 'The config bar shows your current tools, style, and prompt — configure before or during a session',
    });

    // Step 02: Navigate to active session to show AgentConfigBar in session mode
    await goToGenerator(page);
    await capture.capture({
      step: '02',
      name: 'session-config-bar',
      description: 'In an active session, the config bar syncs changes to the backend',
    });

    // Step 03: Highlight Save as Profile button
    await capture.capture({
      step: '03',
      name: 'save-as-profile-button',
      description: 'Click "Save as Profile" to save your current configuration as a reusable profile',
      highlightSelector: 'button:has-text("Save as Profile")',
    });

    // Step 04: Click Save as Profile to open dialog
    await page.getByRole('button', { name: 'Save as Profile' }).click();
    await page.waitForTimeout(500);
    await capture.capture({
      step: '04',
      name: 'save-profile-dialog',
      description: 'Enter a name and description for your profile',
    });

    // Step 05: Fill in profile name and description
    const nameInput = page.getByPlaceholder(/name/i).first();
    if (await nameInput.isVisible({ timeout: 2000 })) {
      await nameInput.fill('Quarterly Reports');
      const descInput = page.getByPlaceholder(/description/i).first();
      if (await descInput.isVisible()) {
        await descInput.fill('Sales data with executive summary template');
      }
      await capture.capture({
        step: '05',
        name: 'save-profile-filled',
        description: 'Give your profile a descriptive name — it captures the current tools, style, and prompt',
      });
    }

    // Close dialog
    await page.keyboard.press('Escape');
    await page.waitForTimeout(200);

    console.log('\n=== Generated Markdown for Save Profile Workflow ===\n');
    console.log(capture.generateMarkdown());
    console.log('\n=== End of Markdown ===\n');
  });

  test('capture load-profile workflow', async ({ page }) => {
    await setupUserGuideMocks(page);
    const capture = new UserGuideCapture(page, '02-creating-profiles');

    await goToGenerator(page);

    // Step 06: Highlight Load Profile button
    await capture.capture({
      step: '06',
      name: 'load-profile-button',
      description: 'Click "Load Profile" to apply a saved configuration to your session',
      highlightSelector: '[data-testid="load-profile-button"]',
    });

    // Step 07: Click Load Profile to open picker
    await page.getByTestId('load-profile-button').click();
    await page.waitForTimeout(500);
    await capture.capture({
      step: '07',
      name: 'load-profile-picker',
      description: 'Select from your saved profiles — the config is copied into your current session',
    });

    // Close picker
    await page.keyboard.press('Escape');
    await page.waitForTimeout(200);

    console.log('\n=== Generated Markdown for Load Profile Workflow ===\n');
    console.log(capture.generateMarkdown());
    console.log('\n=== End of Markdown ===\n');
  });

  test('capture profile management page', async ({ page }) => {
    await setupUserGuideMocks(page);
    const capture = new UserGuideCapture(page, '02-creating-profiles');

    // Step 08: Navigate to Profiles page
    await goToProfiles(page);
    await capture.capture({
      step: '08',
      name: 'profiles-page',
      description: 'The Profiles page lists all saved configurations',
    });

    // Step 09: Highlight a profile card
    const profileCard = page.locator('text=Sales Analytics').first();
    if (await profileCard.isVisible({ timeout: 2000 })) {
      await capture.capture({
        step: '09',
        name: 'profile-card',
        description: 'Click a profile to view its details — tools, style, and prompt',
        highlightSelector: 'text=Sales Analytics',
      });

      // Step 10: Click to view details
      await profileCard.click();
      await page.waitForTimeout(300);
      await capture.capture({
        step: '10',
        name: 'profile-details',
        description: 'View and edit profile name, description, or delete the profile',
      });
    }

    console.log('\n=== Generated Markdown for Profile Management ===\n');
    console.log(capture.generateMarkdown());
    console.log('\n=== End of Markdown ===\n');
  });
});
```

- [ ] **Step 2: Run the spec to verify**

```bash
cd frontend && npx playwright test user-guide/02-creating-profiles.spec.ts --project=chromium 2>&1 | tail -20
```

Expected: Tests pass. Some steps may not capture full UI (dialogs depend on exact component structure), but no hard failures on missing selectors.

- [ ] **Step 3: Commit**

```bash
git add frontend/tests/user-guide/02-creating-profiles.spec.ts
git commit -m "docs: rewrite creating-profiles spec for save-from-session flow"
```

---

## Chunk 4: Regenerate Screenshots + Build Site

### Task 12: Run all Playwright user-guide specs to regenerate screenshots

**Files:**
- Output: `docs/user-guide/images/01-generating-slides/*.png`
- Output: `docs/user-guide/images/02-creating-profiles/*.png`

- [ ] **Step 1: Start the dev server**

The Playwright config expects a Vite dev server at `http://localhost:3000` with API at `http://127.0.0.1:8000`. Start both if not already running:

```bash
# Terminal 1: Backend
cd /path/to/project && python -m uvicorn src.main:app --reload --port 8000

# Terminal 2: Frontend
cd /path/to/project/frontend && npm run dev
```

Or rely on the Playwright `webServer` config in `frontend/playwright.config.ts` if it handles startup.

- [ ] **Step 2: Run all user-guide specs**

```bash
cd frontend && npx playwright test user-guide/ --project=chromium
```

Expected: All specs pass. New screenshots written to `docs/user-guide/images/`.

- [ ] **Step 3: Review generated screenshots**

Manually check a few screenshots in `docs/user-guide/images/01-generating-slides/` and `docs/user-guide/images/02-creating-profiles/` to ensure they look correct.

- [ ] **Step 4: Commit new screenshots**

```bash
git add docs/user-guide/images/
git commit -m "docs: regenerate user guide screenshots"
```

---

### Task 13: Build Docusaurus site and verify

**Files:**
- Build output: `docs-site/build/`

- [ ] **Step 1: Install docs-site dependencies if needed**

```bash
cd docs-site && npm install
```

- [ ] **Step 2: Build the site**

```bash
cd docs-site && npm run build 2>&1
```

Expected: Build succeeds. The `onBrokenLinks: 'throw'` setting will catch any broken internal links (especially important after API docs removal).

- [ ] **Step 3: If build fails with broken links, fix them**

Common fixes:
- Any doc still linking to `/docs/api/*` → remove the link or replace with Swagger UI note
- Footer slug issues → verify the `to:` paths in `docusaurus.config.js` resolve correctly

- [ ] **Step 4: Commit any fixes**

```bash
git add .
git commit -m "docs: fix broken links found during Docusaurus build"
```

If no fixes needed, skip.

- [ ] **Step 5: Final verification — start dev server**

```bash
cd docs-site && npm start
```

Verify in browser:
- Navbar: no "API Reference" tab
- Footer: no "API Reference" link
- Technical sidebar: 5 new entries visible (save-points, url-routing, image-upload, google-slides, feedback)
- User Guide → README Quick Start reflects new flow
- Screenshots render in guide pages

# MCP Discoverability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the already-written MCP technical docs reachable from inside tellr (new MCP tab on `/help`, Overview bullet + quick link) and from the public docs-site sidebar, so a user who doesn't already know MCP exists can discover it without touching the GitHub repo.

**Architecture:** Purely additive frontend work plus two sidebar entries on the Docusaurus site. A new `MCPTab` component lives inside `HelpPage.tsx` following the existing single-file convention; it reads `window.location.origin` at render time to surface the user's actual MCP endpoint URL with a copy-to-clipboard button. All substantive setup content stays in the docs; the help surface is a discovery layer only.

**Tech Stack:** React 19, TypeScript, Tailwind (in-app). Playwright E2E (only frontend test framework in this repo). Docusaurus (docs site).

**Spec:** [`docs/superpowers/specs/2026-04-24-mcp-discoverability-design.md`](../specs/2026-04-24-mcp-discoverability-design.md)

---

## File Structure

| File | Role | Size |
|---|---|---|
| `frontend/src/constants/docs.ts` | Add two new `DOCS_URLS` entries pointing at the deployed MCP tech docs. | ~4 LOC delta |
| `frontend/src/components/Help/HelpPage.tsx` | Extend tab union with `'mcp'`, add `TabButton`, add `QuickLinkButton`, add one Overview bullet, define `MCPTab` in-file. | ~110 LOC delta |
| `docs-site/sidebars.js` | Append two page slugs to the `technical` category's `items` array. | ~2 LOC delta |
| `frontend/tests/e2e/help-ui.spec.ts` | New Playwright cases covering the MCP tab, Overview bullet, and Quick Link. | ~90 LOC delta |

Total: ~210 LOC across four files, purely additive. No backend or MCP code changes.

---

## Prerequisites

- [ ] **P1: Verify existing help-ui e2e tests pass on the branch base**

Run:

```bash
cd frontend && npx playwright test tests/e2e/help-ui.spec.ts --reporter=list
```

Expected: all existing `HelpNavigation`, `HelpTabs`, `QuickLinks` suites pass. If anything is red on a fresh checkout, stop and triage before continuing.

- [ ] **P2: Confirm `DOCS_BASE` in `frontend/src/constants/docs.ts`**

Read `frontend/src/constants/docs.ts`. Confirm `DOCS_BASE = 'https://robertwhiffin.github.io/ai-slide-generator/docs'` is present. If the base URL has moved, update the new entries in Task 1 to use the current base.

- [ ] **P3: Confirm `ToastContext` is available from `HelpPage.tsx`'s import path**

Run:

```bash
grep -l "useToast" frontend/src/contexts/ToastContext.tsx && echo ok
```

Expected: `ok`. The copy-button success/failure toast in Task 4 depends on `useToast` being the app-wide pattern; the Admin `AdminSlideStyleDefault` component imports it via `../../contexts/ToastContext` — the MCP tab uses the same path.

---

## Task 1: Add MCP doc URL constants

**Files:**
- Modify: `frontend/src/constants/docs.ts`

- [ ] **Step 1: Open the file and add two entries**

Edit `frontend/src/constants/docs.ts`. Inside the `DOCS_URLS` object, alongside the existing user-guide entries, add two technical-doc entries. Place them after `retrievingFeedback: userGuide('retrieving-feedback'),` so the block stays grouped.

```ts
const DOCS_BASE = 'https://robertwhiffin.github.io/ai-slide-generator/docs';

const userGuide = (slug: string) => `${DOCS_BASE}/user-guide/${slug}`;

export const DOCS_URLS = {
  home: 'https://robertwhiffin.github.io/ai-slide-generator/',

  generatingSlides: userGuide('generating-slides'),
  creatingProfiles: userGuide('creating-profiles'),
  advancedConfig: userGuide('advanced-configuration'),
  customStyles: userGuide('creating-custom-styles'),
  uploadingImages: userGuide('uploading-images'),
  exportingGoogleSlides: userGuide('exporting-to-google-slides'),
  retrievingFeedback: userGuide('retrieving-feedback'),

  // MCP (technical reference + integration guide)
  mcpServer: `${DOCS_BASE}/technical/mcp-server`,
  mcpIntegrationGuide: `${DOCS_BASE}/technical/mcp-integration-guide`,

  // … existing deep-link entries stay as-is …
} as const;
```

(Keep every other existing key untouched — only the two new lines are added.)

- [ ] **Step 2: Typecheck**

Run:

```bash
cd frontend && npx tsc -b
```

Expected: no output (clean).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/constants/docs.ts
git commit -m "feat(help): add DOCS_URLS entries for MCP server + integration guide"
```

---

## Task 2: Scaffold the MCP tab

Introduces the tab button and a placeholder panel so a Playwright assertion for "MCP tab in the tab strip" can turn green. Actual content lands in Task 3+.

**Files:**
- Modify: `frontend/src/components/Help/HelpPage.tsx`
- Modify: `frontend/tests/e2e/help-ui.spec.ts`

- [ ] **Step 1: Add the failing Playwright test**

Append to `frontend/tests/e2e/help-ui.spec.ts`, inside the existing `HelpTabs` describe block (or alongside it — whichever keeps the file's shape):

```ts
test('MCP tab renders in the tab strip', async ({ page }) => {
  await setupMocks(page);
  await goToHelp(page);
  await expect(page.getByRole('tab', { name: 'MCP' })).toBeVisible();
});
```

- [ ] **Step 2: Run it; expect fail**

Run:

```bash
cd frontend && npx playwright test tests/e2e/help-ui.spec.ts -g "MCP tab renders in the tab strip" --reporter=list
```

Expected: 1 failed. Error mentions `getByRole('tab', { name: 'MCP' })` not found.

- [ ] **Step 3: Extend the `HelpTab` union and wire the tab**

Edit `frontend/src/components/Help/HelpPage.tsx`. Three changes in this file:

**(a) Extend the `HelpTab` union:**

```tsx
type HelpTab = 'overview' | 'generator' | 'history' | 'profiles' | 'deck_prompts' | 'slide_styles' | 'images' | 'verification' | 'mcp';
```

**(b) Add the tab button.** Inside the tab-bar JSX (the `<div ... flex gap-2 mb-6 flex-wrap>`), after `<TabButton tab="images" label="Images" icon={FiImage} />`, add:

```tsx
<TabButton tab="mcp" label="MCP" icon={FiExternalLink} />
```

`FiExternalLink` is already imported at the top of the file — no new import needed.

**(c) Mount the panel.** The existing content area uses `{activeTab === 'x' && <XTab />}` conditional renders inside a single `<div className="bg-white rounded-lg shadow-sm …">`. After the `{activeTab === 'images' && <ImagesTab />}` line, add one more conditional:

```tsx
{activeTab === 'mcp' && <MCPTab />}
```

**(d) Add the `MCPTab` stub** at the bottom of the file, alongside the other tab components. Content comes in Task 3; the stub only needs to render something so the tab is mountable:

```tsx
const MCPTab: React.FC = () => <div>TBD</div>;
```

- [ ] **Step 4: Typecheck**

Run:

```bash
cd frontend && npx tsc -b
```

Expected: no output.

- [ ] **Step 5: Run the test; expect pass**

```bash
cd frontend && npx playwright test tests/e2e/help-ui.spec.ts --reporter=list
```

Expected: all existing help-ui tests + the new "MCP tab renders" test pass.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/Help/HelpPage.tsx frontend/tests/e2e/help-ui.spec.ts
git commit -m "feat(help): scaffold MCP tab in help page"
```

---

## Task 3: MCP tab — "What is MCP?" + "Who's this for?"

**Files:**
- Modify: `frontend/src/components/Help/HelpPage.tsx`
- Modify: `frontend/tests/e2e/help-ui.spec.ts`

- [ ] **Step 1: Add the failing test**

```ts
test('MCP tab shows What is MCP and Who is this for sections', async ({ page }) => {
  await setupMocks(page);
  await goToHelp(page);
  await page.getByRole('tab', { name: 'MCP' }).click();
  await expect(page.getByRole('heading', { name: 'What is MCP?' })).toBeVisible();
  await expect(page.getByRole('heading', { name: "Who's this for?" })).toBeVisible();
});
```

- [ ] **Step 2: Run it; expect fail**

```bash
cd frontend && npx playwright test tests/e2e/help-ui.spec.ts -g "What is MCP" --reporter=list
```

Expected: 1 failed (headings not found — placeholder renders TBD).

- [ ] **Step 3: Replace the stub with the two sections**

Replace the `MCPTab` stub in `HelpPage.tsx` with:

```tsx
const MCPTab: React.FC = () => (
  <div className="space-y-6">
    <section>
      <h2 className="text-lg font-semibold text-gray-800 mb-3">What is MCP?</h2>
      <p className="text-gray-600">
        The Model Context Protocol (MCP) exposes tellr's deck generator as a
        programmatic endpoint. Agents like Claude Code, Claude Desktop, and
        Cursor — and any HTTP-speaking client — can create, edit, and
        retrieve decks without the browser UI. Decks generated over MCP land
        in your tellr history exactly as if you'd made them interactively.
      </p>
    </section>

    <section>
      <h2 className="text-lg font-semibold text-gray-800 mb-3">Who's this for?</h2>
      <p className="text-gray-600">
        Developers and power users who want to automate deck creation — a CI
        job that drops a weekly briefing into Slack, an internal app that
        turns a CRM record into a pitch deck, an agent runtime that calls
        tellr as one tool in a wider workflow. If you only need interactive
        generation, stay on the main page.
      </p>
    </section>
  </div>
);
```

- [ ] **Step 4: Run the test; expect pass**

```bash
cd frontend && npx playwright test tests/e2e/help-ui.spec.ts --reporter=list
```

Expected: all tests pass including the new one.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Help/HelpPage.tsx frontend/tests/e2e/help-ui.spec.ts
git commit -m "feat(help): add What is MCP + Who's this for sections"
```

---

## Task 4: MCP tab — endpoint URL block + copy button

**Files:**
- Modify: `frontend/src/components/Help/HelpPage.tsx`
- Modify: `frontend/tests/e2e/help-ui.spec.ts`

- [ ] **Step 1: Add the failing tests**

```ts
test('MCP tab shows the live endpoint URL ending in /mcp/', async ({ page }) => {
  await setupMocks(page);
  await goToHelp(page);
  await page.getByRole('tab', { name: 'MCP' }).click();

  const endpointBlock = page.getByTestId('mcp-endpoint-url');
  await expect(endpointBlock).toBeVisible();
  await expect(endpointBlock).toContainText('/mcp/');
  // Resolves against Playwright's baseURL — substring match keeps the test
  // robust to baseURL changes.
});

test('MCP tab has a copy endpoint button', async ({ page }) => {
  await setupMocks(page);
  await goToHelp(page);
  await page.getByRole('tab', { name: 'MCP' }).click();
  await expect(
    page.getByRole('button', { name: /copy endpoint/i }),
  ).toBeVisible();
});
```

- [ ] **Step 2: Run them; expect fail**

```bash
cd frontend && npx playwright test tests/e2e/help-ui.spec.ts -g "MCP tab (shows the live|has a copy)" --reporter=list
```

Expected: 2 failed (`mcp-endpoint-url` testid not found, copy button not found).

- [ ] **Step 3: Import `useToast` at the top of `HelpPage.tsx`**

Add near the other imports (alphabetically if the file sorts imports, otherwise at the end of the existing import block):

```tsx
import { useToast } from '../../contexts/ToastContext';
```

- [ ] **Step 4: Add a third section inside `MCPTab`**

Change `MCPTab` so it calls `useToast` and renders the endpoint + copy button. Full new body:

```tsx
const MCPTab: React.FC = () => {
  const { showToast } = useToast();
  const mcpEndpoint = `${window.location.origin}/mcp/`;

  const copyEndpoint = async () => {
    try {
      await navigator.clipboard.writeText(mcpEndpoint);
      showToast('MCP endpoint copied to clipboard', 'success');
    } catch {
      showToast(
        `Unable to copy automatically — endpoint is ${mcpEndpoint}`,
        'error',
      );
    }
  };

  return (
    <div className="space-y-6">
      <section>
        <h2 className="text-lg font-semibold text-gray-800 mb-3">What is MCP?</h2>
        <p className="text-gray-600">
          The Model Context Protocol (MCP) exposes tellr's deck generator as a
          programmatic endpoint. Agents like Claude Code, Claude Desktop, and
          Cursor — and any HTTP-speaking client — can create, edit, and
          retrieve decks without the browser UI. Decks generated over MCP land
          in your tellr history exactly as if you'd made them interactively.
        </p>
      </section>

      <section>
        <h2 className="text-lg font-semibold text-gray-800 mb-3">Who's this for?</h2>
        <p className="text-gray-600">
          Developers and power users who want to automate deck creation — a CI
          job that drops a weekly briefing into Slack, an internal app that
          turns a CRM record into a pitch deck, an agent runtime that calls
          tellr as one tool in a wider workflow. If you only need interactive
          generation, stay on the main page.
        </p>
      </section>

      <section>
        <h2 className="text-lg font-semibold text-gray-800 mb-3">Your endpoint</h2>
        <div className="flex items-center gap-2 rounded bg-gray-50 border border-gray-200 p-3">
          <code
            data-testid="mcp-endpoint-url"
            className="text-sm font-mono flex-1 break-all"
          >
            {mcpEndpoint}
          </code>
          <button
            type="button"
            onClick={() => void copyEndpoint()}
            aria-label="Copy endpoint URL"
            className="shrink-0 text-xs font-medium text-blue-600 hover:text-blue-700 hover:underline"
          >
            Copy endpoint
          </button>
        </div>
        <p className="text-xs text-gray-500 mt-2">
          For production deployments behind a custom hostname, see the full
          guide for how to resolve the correct URL.
        </p>
      </section>
    </div>
  );
};
```

- [ ] **Step 5: Typecheck**

```bash
cd frontend && npx tsc -b
```

Expected: no output.

- [ ] **Step 6: Run the tests; expect pass**

```bash
cd frontend && npx playwright test tests/e2e/help-ui.spec.ts --reporter=list
```

Expected: all tests pass including the two new ones.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/Help/HelpPage.tsx frontend/tests/e2e/help-ui.spec.ts
git commit -m "feat(help): show MCP endpoint URL with copy button"
```

---

## Task 5: MCP tab — prerequisites list + DocLink footer

**Files:**
- Modify: `frontend/src/components/Help/HelpPage.tsx`
- Modify: `frontend/tests/e2e/help-ui.spec.ts`

- [ ] **Step 1: Add the failing tests**

```ts
test('MCP tab shows prerequisites', async ({ page }) => {
  await setupMocks(page);
  await goToHelp(page);
  await page.getByRole('tab', { name: 'MCP' }).click();
  await expect(page.getByRole('heading', { name: 'Prerequisites' })).toBeVisible();
  await expect(page.getByText(/Databricks user token/i)).toBeVisible();
});

test('MCP tab links to the integration guide', async ({ page }) => {
  await setupMocks(page);
  await goToHelp(page);
  await page.getByRole('tab', { name: 'MCP' }).click();

  const link = page.getByRole('link', { name: /MCP Integration Guide/i });
  await expect(link).toBeVisible();
  const href = await link.getAttribute('href');
  expect(href).toContain('/technical/mcp-integration-guide');
});
```

- [ ] **Step 2: Run them; expect fail**

```bash
cd frontend && npx playwright test tests/e2e/help-ui.spec.ts -g "(prerequisites|links to the integration)" --reporter=list
```

Expected: 2 failed.

- [ ] **Step 3: Add the Prerequisites section and DocLink footer**

Below the "Your endpoint" section inside `MCPTab`, add:

```tsx
      <section>
        <h2 className="text-lg font-semibold text-gray-800 mb-3">Prerequisites</h2>
        <ul className="list-disc list-inside text-gray-600 space-y-2">
          <li>A Databricks user token (OAuth U2M or PAT)</li>
          <li>
            An MCP-capable client: Claude Code, Claude Desktop, Cursor, or a
            raw HTTP library that speaks JSON-RPC 2.0
          </li>
        </ul>
      </section>

      <DocLink href={DOCS_URLS.mcpIntegrationGuide} label="MCP Integration Guide" />
```

`DocLink` is already defined at the bottom of `HelpPage.tsx` and `DOCS_URLS` is already imported. No new imports needed.

- [ ] **Step 4: Typecheck**

```bash
cd frontend && npx tsc -b
```

Expected: no output.

- [ ] **Step 5: Run the tests; expect pass**

```bash
cd frontend && npx playwright test tests/e2e/help-ui.spec.ts --reporter=list
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/Help/HelpPage.tsx frontend/tests/e2e/help-ui.spec.ts
git commit -m "feat(help): add MCP prerequisites list and integration-guide link"
```

---

## Task 6: Overview bullet for MCP

**Files:**
- Modify: `frontend/src/components/Help/HelpPage.tsx`
- Modify: `frontend/tests/e2e/help-ui.spec.ts`

- [ ] **Step 1: Add the failing test**

```ts
test('Overview tab shows MCP as a headline capability', async ({ page }) => {
  await setupMocks(page);
  await goToHelp(page);
  // Default tab is overview; no click needed.
  await expect(page.getByText(/Programmatic API via MCP/)).toBeVisible();
});
```

- [ ] **Step 2: Run it; expect fail**

```bash
cd frontend && npx playwright test tests/e2e/help-ui.spec.ts -g "MCP as a headline" --reporter=list
```

Expected: 1 failed.

- [ ] **Step 3: Add the bullet to `OverviewTab`**

Inside the `OverviewTab` component in `HelpPage.tsx`, in the first `<section>` (the "What is databricks tellr?" block), add a fourth `<li>` after the existing three:

```tsx
      <ul className="list-disc list-inside text-gray-600 space-y-2">
        <li>Creates presentation slides from natural language using AI</li>
        <li>Pulls data from Databricks Genie spaces for data-driven presentations</li>
        <li>Supports iterative editing through conversational interface</li>
        <li>Programmatic API via MCP — call tellr from agents, CI, or other apps</li>
      </ul>
```

- [ ] **Step 4: Run the test; expect pass**

```bash
cd frontend && npx playwright test tests/e2e/help-ui.spec.ts --reporter=list
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Help/HelpPage.tsx frontend/tests/e2e/help-ui.spec.ts
git commit -m "feat(help): surface MCP as a headline capability on Overview"
```

---

## Task 7: Overview Quick Link to the MCP tab

**Files:**
- Modify: `frontend/src/components/Help/HelpPage.tsx`
- Modify: `frontend/tests/e2e/help-ui.spec.ts`

- [ ] **Step 1: Add the failing test**

```ts
test('Overview Quick Link navigates to the MCP tab', async ({ page }) => {
  await setupMocks(page);
  await goToHelp(page);
  await page.getByRole('button', { name: /Learn about MCP/ }).click();
  // Clicking the quick link should activate the MCP panel.
  await expect(page.getByRole('heading', { name: 'What is MCP?' })).toBeVisible();
});
```

- [ ] **Step 2: Run it; expect fail**

```bash
cd frontend && npx playwright test tests/e2e/help-ui.spec.ts -g "Quick Link navigates to the MCP" --reporter=list
```

Expected: 1 failed (no button with "Learn about MCP").

- [ ] **Step 3: Add the Quick Link button**

Inside `OverviewTab`, in the "Navigation Quick Links" section, add a new `QuickLinkButton` entry at the end of the list (after the Images one):

```tsx
        <QuickLinkButton tab="images" label="Learn about Images →" />
        <QuickLinkButton tab="mcp" label="Learn about MCP →" />
      </div>
```

- [ ] **Step 4: Run the test; expect pass**

```bash
cd frontend && npx playwright test tests/e2e/help-ui.spec.ts --reporter=list
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Help/HelpPage.tsx frontend/tests/e2e/help-ui.spec.ts
git commit -m "feat(help): add MCP quick link on Overview tab"
```

---

## Task 8: Docs-site sidebar entries

Adds the two existing MCP markdown files to the Docusaurus "Technical Documentation" sidebar so they're reachable from the docs-site left nav.

**Files:**
- Modify: `docs-site/sidebars.js`

No Playwright coverage — Docusaurus owns its own sidebar rendering and testing. Verification is a local preview.

- [ ] **Step 1: Append the two slugs**

Edit `docs-site/sidebars.js`. Inside the `technical` sidebar's `items` array, append these two entries at the end of the list:

```js
        'technical/feedback-system',
        'technical/mcp-server',
        'technical/mcp-integration-guide',
      ],
    },
  ],
```

(The `'technical/feedback-system'` line is already there — just add the two new lines after it.)

- [ ] **Step 2: Preview the docs site locally**

Run:

```bash
cd docs-site && npm install --no-audit --no-fund && npm run start -- --no-open
```

Open `http://localhost:3000` in a browser. Navigate to the Technical Documentation section of the sidebar. Confirm both new items appear. Click each; confirm the page renders without a 404.

Kill the dev server with Ctrl+C when done.

- [ ] **Step 3: Commit**

```bash
git add docs-site/sidebars.js
git commit -m "docs(site): list MCP pages in technical sidebar"
```

---

## Task 9: Final full-file test run

- [ ] **Step 1: Run the full help-ui suite**

```bash
cd frontend && npx playwright test tests/e2e/help-ui.spec.ts --reporter=list
```

Expected: all pre-existing `HelpNavigation`, `HelpTabs`, `QuickLinks` tests still pass, plus the seven new MCP-related tests from Tasks 2-7.

- [ ] **Step 2: Run the broader e2e suite to catch cross-test pollution**

```bash
cd frontend && npx playwright test --reporter=list
```

Expected: no new failures compared to the branch base. If anything in `slide-styles-ui.spec.ts` or elsewhere regresses, triage before moving on — the mock routes added in Task 4-5 are test-local and should not leak, but confirm.

- [ ] **Step 3: Typecheck once more**

```bash
cd frontend && npx tsc -b
```

Expected: no output.

---

## Post-Implementation Manual Verification (after deploy)

1. Deploy tellr; visit `/help` in a fresh browser session (no localStorage tweaks).
2. On the Overview tab, confirm the "Programmatic API via MCP" bullet is present in "What is databricks tellr?" and that a "Learn about MCP →" quick link appears under Navigation Quick Links.
3. Click the MCP tab. Confirm the four sections render (What is MCP?, Who's this for?, Your endpoint, Prerequisites) and that the "MCP Integration Guide" link points to the deployed docs page.
4. Click "Copy endpoint". Confirm a success toast appears and that the clipboard contains `https://<your-tellr-app>/mcp/`.
5. Visit `robertwhiffin.github.io/ai-slide-generator/docs/technical/mcp-server`. Confirm the left-nav sidebar shows "mcp-server" and "mcp-integration-guide" under Technical Documentation and that both pages load.

---

## Documentation follow-up

None required. The two MCP markdown files already shipped with the feature work. This plan only surfaces them; it doesn't rewrite or extend them.

If during implementation you discover a doc inaccuracy — for example, the endpoint URL wording on `mcp-server.md` needs a sentence about what `window.location.origin` resolves to in local dev — capture it as a one-line note and address in a follow-up commit rather than expanding scope here.

---

## Git Strategy

One commit per task (already specified in each task's Step 5/6). Nine commits total:

- Task 1 (constants)
- Task 2 (tab scaffold)
- Task 3 (What is / Who is for)
- Task 4 (endpoint + copy)
- Task 5 (prerequisites + DocLink)
- Task 6 (Overview bullet)
- Task 7 (Overview Quick Link)
- Task 8 (docs-site sidebar)

(Task 9 is verification only — no commit.)

Rebase/squash before merge is fine if you prefer fewer commits on `main`; keep them atomic on the feature branch so review can walk them in order.

---

## Out of scope — do not do in this plan

- No backend changes.
- No MCP code changes.
- No changes to user-facing slide style, profile, or deck-prompt pages.
- No new MCP documentation — the technical reference and integration guide are already complete.
- No header/nav entry for MCP outside the help page.
- No per-deployment URL override — `window.location.origin` is authoritative for v1.

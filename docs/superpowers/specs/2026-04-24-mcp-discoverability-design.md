# MCP Discoverability: In-App Help Surface + Docs-Site Navigation

**Date:** 2026-04-24
**Status:** Design (awaiting user review)
**Related:** [2026-04-22-tellr-mcp-server-design.md](./2026-04-22-tellr-mcp-server-design.md), [2026-04-23-system-default-slide-style-admin.md](./2026-04-23-system-default-slide-style-admin.md)

## 1. Problem

Tellr's MCP endpoint ships with a full caller-facing technical reference (`docs/technical/mcp-server.md`) and a worked integration guide (`docs/technical/mcp-integration-guide.md`). Neither is reachable from the product itself:

- The in-app help page (`/help`) has tabs for every user-facing feature (Generator, Verification, History, Profiles, Deck Prompts, Slide Styles, Images). It has no mention of MCP anywhere — no tab, no Overview bullet, no deep link.
- The public docs site (`robertwhiffin.github.io/ai-slide-generator`) deploys the MCP markdown pages but does not list them in the Docusaurus sidebar (`docs-site/sidebars.js`). The pages exist at their URLs but the navigation tree does not surface them.

A user who likes tellr but doesn't already know MCP exists cannot find it. The only discovery path is the GitHub repo itself, which is the opposite of what good product docs should require.

## 2. Principle

**Docs are canonical. The in-app help is a discovery layer.**

The help page should tell a user *MCP exists, here's what it means in two paragraphs, here's your endpoint URL, here's the full guide* — and nothing more. All actionable setup instructions (auth recipes, client configs, troubleshooting) live in the docs. Duplication is disallowed so the two surfaces can't drift.

## 3. Target behavior

### 3.1 Overview tab (existing)

Add one bullet to the "What is databricks tellr?" list in `OverviewTab`:

> Programmatic API via MCP — call tellr from agents, CI, or other apps

The bullet is descriptive, not a link. Its purpose is to surface MCP as a headline capability so a user reading the Overview for the first time sees it alongside "pulls data from Genie" and "iterative editing."

A matching `QuickLinkButton` entry — *Learn about MCP →* — appears in the Overview tab's existing Navigation Quick Links row so the Overview bullet has a one-click path into the MCP tab.

### 3.2 New MCP tab

Appended to the tab strip in last position (after Images). Icon: `FiExternalLink` or a comparable Feather icon already in use (specific choice is cosmetic). Four sections inside:

1. **What is MCP?** — one paragraph, tellr-specific framing. The Model Context Protocol exposes tellr's deck generator as a programmatic endpoint; agents like Claude Code and any HTTP-speaking client can create, edit, and retrieve decks without the browser UI; resulting decks land in the user's history exactly as if they'd created them interactively.
2. **Who's this for?** — one paragraph distinguishing casual browser users from developer/agent callers. Explicitly says: if you only need interactive generation, stay on the main page.
3. **Your endpoint** — a code block showing `${window.location.origin}/mcp/` with a Copy button. One line of fine print pointing to the docs for custom-hostname deployments.
4. **Prerequisites** — two-bullet list: Databricks user token, MCP-capable client (Claude Code / Cursor / Claude Desktop / raw HTTP).

The tab ends with a `DocLink` footer (the existing pattern used by `SlideStylesTab` and `ImagesTab`) linking to `DOCS_URLS.mcpIntegrationGuide`.

### 3.3 Docs URL constants

`frontend/src/constants/docs.ts` gains two new entries:

```ts
mcpServer: `${DOCS_BASE}/technical/mcp-server`,
mcpIntegrationGuide: `${DOCS_BASE}/technical/mcp-integration-guide`,
```

The naming mirrors the file slugs so future readers can find the source markdown at a glance. `mcpServer` is currently unreferenced in component code — it's added proactively so that any future spot wanting to link to the protocol reference has a canonical constant instead of an ad-hoc URL.

### 3.4 Docs-site navigation

`docs-site/sidebars.js` — the `technical` sidebar appends two items:

```js
'technical/mcp-server',
'technical/mcp-integration-guide',
```

Flat entries in the existing "Technical Documentation" category. Two pages is not enough to justify a nested subcategory.

## 4. Scope

**In scope:**

- Overview tab: one new bullet + one new Quick Link button.
- New MCP tab with the four sections above.
- Two new `DOCS_URLS` entries.
- Two sidebar entries on the docs site.
- Playwright coverage of the new help surface (see §7).

**Out of scope:**

- Writing any new MCP documentation — the docs are complete.
- Backend or MCP code changes — none needed.
- Auth gating or per-user admin enforcement — this surface is informational.
- Showing the MCP endpoint on any page other than the help MCP tab.
- Teaching MCP on the help page (auth recipes, code snippets, troubleshooting all stay in the docs per §2).
- Adding "MCP" as a header nav item or toolbar button — discoverability via the help page is sufficient for v1.

## 5. Files touched

| File | Change | Estimated size |
|---|---|---|
| `frontend/src/constants/docs.ts` | Two new entries. | ~4 LOC |
| `frontend/src/components/Help/HelpPage.tsx` | `HelpTab` union gains `'mcp'`; new `TabButton`; new `QuickLinkButton` on Overview; new bullet on Overview "What is" list; new `MCPTab` component in-file (matches existing single-file convention). | ~110 LOC |
| `docs-site/sidebars.js` | Append two page slugs to the `technical` category's `items` array. | ~2 LOC |
| `frontend/tests/e2e/help-ui.spec.ts` | New Playwright cases covering the MCP tab and Overview bullet (see §7). | ~50 LOC |

Total: ~170 LOC across four files, purely additive.

## 6. Data flow

**At render time.** `MCPTab` reads `window.location.origin` directly (no props, no state, no fetch), concatenates `/mcp/`, and renders it in the code block. This is the same origin the browser used to load tellr, which in Databricks Apps production is the correct MCP endpoint host for external callers. In local development it yields `http://localhost:3000/mcp/` — which is the Vite proxy URL, not the backend — but the fine-print caveat and docs link cover that edge.

**Copy button.** `navigator.clipboard.writeText(mcpEndpoint)` with a `.then()` firing a success toast via the existing `useToast` hook. `.catch()` fires an error toast whose message includes the endpoint string so a user without clipboard access can select it from the toast (or from the code block itself, which remains visible).

**Overview bullet + Quick Link.** Static JSX. The Quick Link calls `setActiveTab('mcp')` using the existing callback prop on `OverviewTab`.

## 7. Testing

Playwright (the only frontend test framework in this repo). Extend `frontend/tests/e2e/help-ui.spec.ts`:

- **Overview bullet renders.** After `page.goto('/help')`, the text *Programmatic API via MCP* is visible in the Overview tab.
- **MCP tab appears in the tab strip.** `page.getByRole('tab', { name: 'MCP' })` is visible.
- **Clicking MCP shows its content.** After clicking the MCP tab, the *What is MCP?* heading is visible; the *Your endpoint* heading is visible; the endpoint code block contains `/mcp/` and the current origin.
- **Copy button is present.** `page.getByRole('button', { name: /copy/i })` inside the MCP panel is clickable. (Testing actual clipboard write is finicky across browsers; asserting clickability is sufficient.)
- **DocLink target.** The footer "MCP Integration Guide" link's `href` matches `DOCS_URLS.mcpIntegrationGuide`. Assert on the rendered attribute, not on the constant — keeps the test honest if the constant value changes.
- **Quick Link navigates into the MCP tab.** Clicking "Learn about MCP →" on the Overview tab activates the MCP panel.

The endpoint-string assertion uses substring matching (`toContain('/mcp/')`) so the test does not encode Playwright's `baseURL` and continues to work if it changes.

## 8. Non-goals / deferred items

- **Per-deployment URL override.** If an admin wants the help tab to advertise a canonical production URL different from `window.location.origin`, that's a future change (likely an env var the backend injects into the page). Not needed for v1.
- **Interactive MCP tester on the help page.** A button that issues a live `tools/list` against the endpoint and shows the result. Plausibly useful but pure v1.1 material and duplicates the smoke script's purpose.
- **Linking to the admin slide style default from the MCP tab.** Users who use MCP care about the system default (since MCP can't see their personal override). Consider a cross-link in a follow-up once both features are live.

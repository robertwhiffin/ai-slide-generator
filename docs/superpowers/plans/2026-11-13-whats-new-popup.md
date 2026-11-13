# "What's new in Tellr" popup and `release-tellr` skill — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. In this repo also load `executing-plans-tellr` (sabotage-verify every test, plan-vs-code pre-pass, `Models:` tiers). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Users see a "What's new in Tellr" popup listing each release's user-facing highlights. The wording is drafted from merged PRs and approved by the owner in the terminal at release time, by a new `release-tellr` skill. The publish workflow refuses a tag that has no notes file.

**Architecture:** One JSON notes file per release lives in `frontend/src/whatsNew/releases/` and is bundled by `import.meta.glob`. Pure functions (`releaseNotes.ts`) parse, order and diff the files. A `WhatsNewProvider`, nested inside the existing `TourProvider`, decides at page load whether to auto-open and records the last version dismissed in localStorage. A modal renders the list, and a sidebar footer button reopens it. A stdlib Python checker guards `publish.yml`. The skill is a Markdown process doc.

**Tech Stack:** React 19 + TypeScript + Vite + Tailwind, vitest + Testing Library, Playwright, Python 3 stdlib + pytest, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-11-13-whats-new-popup-design.md`

**Worktree setup:** the worktree is `.claude/worktrees/whats-new` on branch `feat/whats-new`. Before Task 1, run `uv sync --extra dev` in the worktree root and `npm ci` in `frontend/`.

## Global Constraints

- Notes directory: `frontend/src/whatsNew/releases/`, one file per release named `<version>.json`.
- Notes file shape: `{"version": "X.Y.Z", "date": "YYYY-MM-DD", "items": [{"title": "...", "body": "..."}]}`. The version must equal the file stem. `items: []` is valid and means "nothing user-facing". Titles have no trailing period, and the UI renders `**{title}.** {body}`.
- Only final versions (`^\d+\.\d+\.\d+$`) have notes. Ordering is numeric per component, so `0.5.10` > `0.5.9`.
- localStorage key `tellr-whats-new-last-seen` holds the last version dismissed. The existing key `tellr-app-tour-completed` is unchanged.
- "Newest release" comes from the bundled notes, never from the backend's `__version__`.
- Copy: title "What's new in Tellr"; subtitle "Highlights from each release"; badge "New"; button "Got it"; sidebar item "What's new"; month shown as e.g. "November 2026" (UTC).
- Auto-open delay is 800 ms, the same as the welcome guide.
- This PR adds **no** notes file. The 0.5.7 file is written by `release-tellr` in the 0.5.7 bump PR.
- Legacy deck mode is not touched.
- Python is run via `uv run` in the worktree, and frontend tests via `npx` in `frontend/`. Never `pip install`.

## Review Focus

1. **Esc while a generation is running and the popup is open.** Esc closes the popup only. The generation keeps going: `useEscapeToStop` skips while a `[role="dialog"]` exists, and the popup's handler calls `preventDefault()`. Pinned in Task 3.
2. **Garbage or old values in localStorage** (`"abc"`, `"0.5.7.dev3"`). These count as "seen nothing": the user sees every release, and nothing crashes. Pinned in Task 1 (`unseenVersions`) and Task 2.
3. **Version ordering across digit counts** (`0.5.10` vs `0.5.9`, `1.0.0` vs `0.99.0`). Newest is first, and badges land on the right releases. Pinned in Task 1.
4. **A brand-new user finishes the welcome guide in this session.** The What's new popup does not open afterwards, and does not open on the next load either. Pinned in Task 2 and in Task 4's E2E.
5. **The user starts the App Tour before the 800 ms timer fires.** The popup does not open over the tour, and the release stays unseen for the next load. Pinned in Task 2.

---

### Task 1: Release notes model and loader

**Models:** `test=opus impl=sonnet`

**Files:**
- Create: `frontend/src/whatsNew/releaseNotes.ts`. Pure: no `import.meta`, no browser APIs. Playwright imports it under Node.
- Create: `frontend/src/whatsNew/releases.ts`
- Create: `frontend/src/whatsNew/releases/README.md`
- Test: `frontend/src/whatsNew/releaseNotes.test.ts`, `frontend/src/whatsNew/releases.test.ts`

**Interfaces:**
- Produces (`releaseNotes.ts`):
  ```ts
  export const WHATS_NEW_STORAGE_KEY = 'tellr-whats-new-last-seen';
  export interface ReleaseNoteItem { title: string; body: string }
  export interface ReleaseNotes { version: string; date: string; items: ReleaseNoteItem[] }
  export function isReleaseVersion(v: string): boolean;                       // /^\d+\.\d+\.\d+$/
  export function compareVersions(a: string, b: string): number;              // <0, 0, >0; numeric per component
  export function parseReleaseNotes(raw: unknown, fileStem: string): ReleaseNotes; // throws Error whose message contains fileStem
  export function sortNewestFirst(releases: ReleaseNotes[]): ReleaseNotes[];  // returns a new array
  export function newestVersion(releases: ReleaseNotes[]): string | null;     // over ALL releases, empty ones included
  export function unseenVersions(releases: ReleaseNotes[], lastSeen: string | null): Set<string>;
  export function formatReleaseMonth(date: string): string;                   // '2026-11-14' -> 'November 2026', UTC
  ```
- Produces (`releases.ts`): `export const RELEASES: ReleaseNotes[]`. Every `./releases/*.json` from `import.meta.glob(..., { eager: true, import: 'default' })`, parsed with the file stem taken from the glob key, then `sortNewestFirst`.

- [ ] **Step 1: Write the failing tests** in `releaseNotes.test.ts`:
  - `parseReleaseNotes` returns the input unchanged for `{version:'0.5.7', date:'2026-11-14', items:[{title:'Images in chat', body:'Ask for an image of a monkey at a keyboard.'}]}` with stem `'0.5.7'`, and accepts `items: []`.
  - `parseReleaseNotes` throws `/0\.5\.7/` for each of: `null`; an array; version `'0.5.8'` with stem `'0.5.7'`; version `'0.5.7.dev1'` with stem `'0.5.7.dev1'` (assert `/0\.5\.7\.dev1/`); date `'14/11/2026'`; date `'2026-13-01'`; `items: 'x'`; an item with title `'   '`; an item with no `body`; an item with title `'Images in chat.'` (trailing period).
  - `compareVersions('0.5.10','0.5.9') > 0`, `compareVersions('1.0.0','0.99.0') > 0`, `compareVersions('0.5.7','0.5.7') === 0`, `compareVersions('0.5.6','0.5.7') < 0`.
  - `sortNewestFirst` on `[0.5.9, 0.5.10, 0.5.7]` gives `['0.5.10','0.5.9','0.5.7']` and leaves the input array's order unchanged.
  - `newestVersion([0.5.7 with items, 0.5.8 with items: []]) === '0.5.8'`, and `newestVersion([]) === null`.
  - `unseenVersions`, with releases `0.5.6`, `0.5.7` and `0.5.8` (all with items) plus `0.5.9` (empty):
    - `null` gives `{'0.5.6','0.5.7','0.5.8'}`;
    - `'0.5.7'` gives `{'0.5.8'}`;
    - `'0.5.9'` gives `{}`;
    - `'abc'` and `'0.5.7.dev3'` each give `{'0.5.6','0.5.7','0.5.8'}`.
  - `formatReleaseMonth('2026-11-14') === 'November 2026'`, and `formatReleaseMonth('2026-01-01') === 'January 2026'`. The second guards against a timezone shift into December 2025.

  In `releases.test.ts`:
  - every `RELEASES` entry has `isReleaseVersion(version)`;
  - `RELEASES` equals `sortNewestFirst(RELEASES)`;
  - `Object.keys(import.meta.glob('./releases/*.json')).length === RELEASES.length`.

- [ ] **Step 2: Run** `cd frontend && npx vitest run src/whatsNew`. Expected: FAIL, because the modules don't exist.
- [ ] **Step 3: Implement** `releaseNotes.ts` and `releases.ts` to the interfaces above.
  - Date validation must reject impossible dates. Round-trip through `Date.UTC`, so `2026-13-01` and `2026-02-30` are rejected.
  - `formatReleaseMonth` uses `toLocaleDateString('en-US', { month: 'long', year: 'numeric', timeZone: 'UTC' })`.
- [ ] **Step 4: Write `releases/README.md`.** One short page covering:
  - the file name and shape from Global Constraints;
  - the no-trailing-period rule and how a bullet renders;
  - that `items: []` means a release with nothing user-facing;
  - that files are written only by the `release-tellr` skill, after the owner approves the wording.
- [ ] **Step 5: Run** `cd frontend && npx vitest run src/whatsNew`. Expected: PASS. With zero notes files, `releases.test.ts` passes vacuously.
  - Sabotage check: add a temporary `releases/0.5.7.json` whose `version` is `"0.5.8"`. The test file should go red because `RELEASES` throws on import. Delete the temporary file.
- [ ] **Step 6: Commit** `feat(whats-new): release notes model and bundled loader`.

---

### Task 2: `WhatsNewProvider`, the open/seen state

**Models:** `test=opus impl=sonnet`

**Files:**
- Create: `frontend/src/contexts/WhatsNewContext.tsx`
- Test: `frontend/src/contexts/WhatsNewContext.test.tsx`

**Interfaces:**
- Consumes: from Task 1, `RELEASES`, `WHATS_NEW_STORAGE_KEY`, `newestVersion`, `unseenVersions`, `sortNewestFirst` and `ReleaseNotes`. From `frontend/src/contexts/TourContext.tsx`, `useTour()` → `{ hasCompletedTour, isTourActive, showWelcome }`.
- Produces:
  ```ts
  export function WhatsNewProvider(props: {
    children: React.ReactNode;
    releases?: ReleaseNotes[];   // default RELEASES; tests pass fixtures here
    autoOpenDelayMs?: number;    // default 800
  }): JSX.Element;               // must be rendered inside TourProvider
  export function useWhatsNew(): {
    isOpen: boolean;
    releases: ReleaseNotes[];    // newest first, ONLY releases with items
    unseen: Set<string>;         // unseenVersions(all releases, lastSeen)
    hasNotes: boolean;           // releases.length > 0
    open: () => void;
    close: () => void;           // lastSeen := newestVersion(all releases), in state + localStorage; isOpen := false
  };                             // throws outside the provider, like useTour
  ```

Behaviour the tests pin:
- `lastSeen` starts as the stored value, or `null`.
- **Auto-open is decided once, at mount.** If `hasCompletedTour` was already true at mount and `unseen` is non-empty, a timer fires after `autoOpenDelayMs`. When it fires, it opens the popup only if the tour is not active and the welcome guide is not showing. It reads the live tour values through a ref.
- When `hasCompletedTour` goes from false to true during this mount (welcome dismissed, or tour ended or skipped), `lastSeen` becomes `newestVersion(all releases)` and is written to storage. That transition never opens the popup.
- `close()` with no releases at all writes nothing.

- [ ] **Step 1: Write the failing tests.**
  - Setup:
    - Render `<TourProvider><WhatsNewProvider releases={…}>` plus a probe component. The probe shows `isOpen`, the sorted `unseen` list and `hasNotes`, and has buttons that call `open`, `close`, `useTour().dismissWelcome` and `useTour().startTour`.
    - Use `vi.useFakeTimers()`, and call `localStorage.clear()` in `beforeEach`.
    - Fixture releases: `R(v, n)` builds version `v` with `n` items.
  - Existing user with no record (`tellr-app-tour-completed='true'`, no key, `[R('0.5.7',2)]`): `isOpen` is false at 799 ms and true at 800 ms; `unseen` is `['0.5.7']`.
  - Up to date (key `'0.5.7'`): never opens after advancing 5000 ms.
  - Behind by several (key `'0.5.5'`, releases `0.5.5`, `0.5.6` and `0.5.7`, all with items): opens; `unseen` is `['0.5.6','0.5.7']`.
  - Only an empty release is newer (key `'0.5.7'`, `[R('0.5.7',1), R('0.5.8',0)]`): never opens.
  - `close()` records the newest release, empty ones included: with `[R('0.5.7',1), R('0.5.8',0)]` and no key, open then close. Storage key becomes `'0.5.8'`, `unseen` becomes `[]`, `isOpen` becomes false.
  - Brand-new user (no tour flag, no key, `[R('0.5.7',1)]`):
    - after 5000 ms, `isOpen` is false;
    - click "dismissWelcome": the storage key becomes `'0.5.7'`;
    - advance 5000 ms: `isOpen` is still false;
    - unmount and render fresh: it never opens.
  - Tour started before the delay (tour flag `'true'`, no key): click "startTour" at 500 ms, then advance to 2000 ms. `isOpen` is false, and the storage key is still absent.
  - Invalid stored value `'abc'`: behaves as no record and opens at 800 ms.
  - `open()` when up to date: `isOpen` becomes true and `unseen` is `[]`.
  - Only empty releases (`[R('0.5.7',0)]`): `hasNotes` is false.
  - `useWhatsNew()` outside the provider throws.
- [ ] **Step 2: Run** `cd frontend && npx vitest run src/contexts/WhatsNewContext.test.tsx`. Expected: FAIL (the module doesn't exist).
- [ ] **Step 3: Implement** `WhatsNewContext.tsx` to the interface and behaviour above. Mirror `TourContext.tsx`'s idioms (`createContext`, `useCallback`, the throwing hook).
- [ ] **Step 4: Run** the same command. Expected: PASS. Then run the full `npx vitest run`. Expected: no new failures.
- [ ] **Step 5: Commit** `feat(whats-new): provider decides auto-open and records the last release seen`.

---

### Task 3: The modal, the sidebar item and the app mount

**Models:** `test=opus impl=sonnet`

**Files:**
- Create: `frontend/src/components/WhatsNew/WhatsNewModal.tsx`
- Modify: `frontend/src/App.tsx:124-128`. Wrap `<AppRoutes /><AppTour /><WelcomeModal />` in `<WhatsNewProvider>` inside `<TourProvider>`, and add `<WhatsNewModal />` after `<WelcomeModal />`. `AppSidebar` renders inside `AppRoutes`, so the provider must sit above it.
- Modify: `frontend/src/components/Layout/app-sidebar.tsx`. In the footer `SidebarMenu`, add a `SidebarMenuItem` after "App Tour", rendered only when `hasNotes`. (Plan-time call: hide it while no release has notes, which is the state this PR ships in, rather than open an empty popup.) It holds `<SidebarMenuButton onClick={open}><Sparkles /><span>What's new</span></SidebarMenuButton>`, with `Sparkles` from `lucide-react`.
- Test: `frontend/src/components/WhatsNew/WhatsNewModal.test.tsx`
- Modify: `frontend/src/components/Layout/app-sidebar.test.tsx`. Add a module-level `vi.mock('@/contexts/WhatsNewContext', …)` returning a mutable `{ hasNotes, open }`, so the existing tests keep passing, plus the new tests below.

**Interfaces:**
- Consumes: `useWhatsNew()` (Task 2) and `formatReleaseMonth` (Task 1).
- Produces: `export function WhatsNewModal(): JSX.Element | null`.

Modal requirements:
- Look: follow `frontend/src/components/Tour/WelcomeModal.tsx`. The overlay is `fixed inset-0 z-[10001] … bg-black/40 backdrop-blur-sm`, inside a rounded white panel, sized `max-w-xl`.
- The panel has `role="dialog" aria-modal="true" aria-label="What's new in Tellr"`. The header carries the title and subtitle from Global Constraints and a ✕ button with `aria-label="Close"`.
- The body scrolls (`max-h-[60vh] overflow-y-auto`). Each release is a `<section aria-label="Tellr {version}">` holding:
  - the version, and the "New" badge when `unseen.has(version)`;
  - the month;
  - a `<ul>` of `<li><strong>{title}.</strong> {body}</li>`.
- Seen releases use quieter text, and a divider separates releases.
- The footer has a "Got it" primary button, which takes focus when the popup opens.
- Closing: "Got it", ✕, a backdrop click (the overlay only, not the panel), and Esc all call `close()`. Esc uses a window `keydown` listener while open that calls `e.preventDefault()`, copying `frontend/src/components/ConfirmDialog.tsx:38-49`.

- [ ] **Step 1: Write the failing tests.** In `WhatsNewModal.test.tsx`:
  - Setup: render the real providers with `releases = [R('0.5.6',1), R('0.5.7',2), R('0.5.8',0)]`, tour flag `'true'`, key `'0.5.6'` and `autoOpenDelayMs={0}`. `R` is a local helper like Task 2's. Here `0.5.7` has date `2026-11-14`, and its first item is `{title: 'Images in chat', body: 'Ask for an image of a monkey at a keyboard.'}`.
  - The dialog named "What's new in Tellr" shows sections `Tellr 0.5.7` then `Tellr 0.5.6`. There is no `Tellr 0.5.8` section. "New" appears inside `Tellr 0.5.7` only.
  - An item renders its title inside `<strong>` as "Images in chat." followed by its body. The month text is "November 2026" for date `2026-11-14`.
  - "Got it" has focus.
  - "Got it" removes the dialog and sets the storage key to `'0.5.8'`. Assert the same for ✕, for Esc on `document.body`, and for a click on the overlay. A click inside the panel leaves the dialog open.
  - **Review Focus 1:** also mount a probe calling `useEscapeToStop(true, onStop)` from `frontend/src/components/ChatPanel/useEscapeToStop.ts`. Esc closes the dialog, and `onStop` is not called.

  In `app-sidebar.test.tsx`:
  - with `hasNotes: true`, a "What's new" button is in the sidebar footer, and clicking it calls `open` once;
  - with `hasNotes: false`, there is no "What's new" text.
- [ ] **Step 2: Run** `cd frontend && npx vitest run src/components/WhatsNew src/components/Layout/app-sidebar.test.tsx`. Expected: FAIL.
- [ ] **Step 3: Implement** the modal, the sidebar item and the `App.tsx` mount.
- [ ] **Step 4: Run** the same command, then the full `npx vitest run` and `npm run build` (type-check plus bundle). Expected: all pass.
- [ ] **Step 5: Commit** `feat(whats-new): What's new popup and sidebar entry`.

---

### Task 4: E2E seeding and the `whats-new` spec

**Models:** `test=opus impl=sonnet`

**Files:**
- Create: `frontend/tests/helpers/whats-new.ts`
- Modify: `frontend/playwright.config.ts:21-27` (the global `storageState`)
- Modify: `frontend/tests/e2e/graph-release-admin-journey.spec.ts:126-133` and `frontend/tests/e2e/graph-release-conversation-journey.spec.ts` (around line 128), both of which hand-roll their own `storageState`
- Create: `frontend/tests/e2e/whats-new.spec.ts`
- Modify: `.github/workflows/test.yml`, adding `whats-new` to shard 3's `specs` (currently the shortest list)

**Interfaces:**
- Consumes: `compareVersions` and `WHATS_NEW_STORAGE_KEY` from `frontend/src/whatsNew/releaseNotes.ts`. That module is pure, and tests already import from `../../src/`.
- Produces (`tests/helpers/whats-new.ts`). Each function reads `frontend/src/whatsNew/releases/*.json` with `node:fs`:
  ```ts
  export function newestReleaseNotesVersion(): string | null;
  export function hasReleaseNotesWithItems(): boolean;
  export function whatsNewSeenStorage(): { name: string; value: string }[]; // [] when no notes; else [{ name: WHATS_NEW_STORAGE_KEY, value: newest }]
  ```

- [ ] **Step 1: Seed "seen everything" wherever the suite already seeds the tour flag.** Add `...whatsNewSeenStorage()` after the `tellr-app-tour-completed` entry in `playwright.config.ts` and in the two journey specs.
- [ ] **Step 2: Write `whats-new.spec.ts`.**
  - Use `test` and `expect` from `../fixtures/base-test` and `setupMocks` from `../helpers/setup-mocks`, as in `app-tour.spec.ts`.
  - At the top: `test.skip(!hasReleaseNotesWithItems(), 'no release notes bundled yet; first real run is on a release bump PR')`.
  - Read the newest notes file with `fs` to get its version and first item title.
  - Tests:
    - **Opens after an upgrade.** Context `localStorage` holds only `tellr-app-tour-completed=true`. After `goto('/')`, the dialog "What's new in Tellr" is visible. The section `Tellr <newest>` contains "New" and the first item's title.
    - **Dismissal survives a reload.** Same start. Click "Got it", reload, wait 1500 ms: the dialog count is 0.
    - **Reopen from the sidebar.** After dismissing, click the sidebar button "What's new". The dialog is visible with no "New" text.
    - **Brand-new user (Review Focus 4).** Empty `localStorage`. The welcome dialog ("Welcome to Tellr") is visible and What's new is not. Click "Get Started", reload, wait 1500 ms: the What's new dialog count is 0.
- [ ] **Step 3: Run** `cd frontend && npx playwright test tests/e2e/whats-new.spec.ts`. Expected: 4 skipped, because no notes are bundled.
- [ ] **Step 4: Prove the spec, and the seeding, against a real file.**
  - Create an **uncommitted** `frontend/src/whatsNew/releases/0.5.7.json` with two items.
  - Run the spec: 4 pass.
  - Sabotage: make `close()` skip the storage write. "Dismissal survives a reload" goes red. Revert.
  - With the sample file still present, run `npx playwright test tests/e2e/app-tour.spec.ts tests/e2e/help-ui.spec.ts`. Both pass, so the global seeding keeps the popup out of other specs.
  - Delete the sample file, and confirm `git status` shows no notes file.
- [ ] **Step 5: Add `whats-new` to shard 3** and run `uv run pytest tests/unit/test_e2e_matrix_covers_specs.py -q`. Expected: PASS.
- [ ] **Step 6: Commit** `test(whats-new): E2E spec, suite-wide seen seeding, shard entry`.

---

### Task 5: Publish guard

**Models:** `test=opus impl=haiku`

**Files:**
- Create: `scripts/check_release_notes.py` (stdlib only)
- Test: `tests/unit/test_check_release_notes.py`
- Modify: `.github/workflows/publish.yml`. In the `validate` job, after the "Extract and validate versions" step, add a step named "Check What's new notes" that runs `python3 scripts/check_release_notes.py "${{ steps.version.outputs.version }}"`.

**Interfaces:**
- Produces:
  ```python
  DEFAULT_NOTES_DIR: Path  # <repo root>/frontend/src/whatsNew/releases
  def check_release_notes(version: str, notes_dir: Path = DEFAULT_NOTES_DIR) -> list[str]: ...  # [] means OK
  def main(argv: list[str] | None = None) -> int: ...  # prints each problem to stderr; 1 if any, else 0
  ```
- Rules, the same as the TypeScript `parseReleaseNotes`:
  - `<version>.json` exists and is a JSON object;
  - `version` equals the argument;
  - `date` is a real `YYYY-MM-DD` date;
  - `items` is a list;
  - each item has non-empty string `title` (no trailing period) and `body`.

- [ ] **Step 1: Write the failing tests** (`tmp_path`, `from scripts.check_release_notes import check_release_notes, main`):
  - A valid file returns `[]`, and so does `items: []`.
  - Each of these returns one problem, and its message contains the named fragment:
    - missing file (`"0.5.7.json"`);
    - invalid JSON (`"JSON"`);
    - `version` `"0.5.8"` (`"0.5.8"`);
    - date `"2026-02-30"` (`"date"`);
    - an item without `body` (`"body"`);
    - title `"Images in chat."` (`"period"`).
  - `main(["0.5.7"])` with a patched default dir returns 1 for a missing file and 0 for a valid one.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_check_release_notes.py -q`. Expected: FAIL (import error).
- [ ] **Step 3: Implement** the script and add the workflow step.
- [ ] **Step 4: Run** the same command. Expected: PASS. Then run `python3 scripts/check_release_notes.py 0.0.0`. Expected: exit 1 with the missing-file message.
- [ ] **Step 5: Commit** `ci(publish): refuse a tag without a What's new notes file`.

---

### Task 6: `release-tellr` skill, PR template, `CLAUDE.md`

**Models:** `test=opus impl=opus`. Here "test" is the dry run in Step 4. The skill is a process artifact where a quiet mistake publishes to PyPI.

**Files:**
- Create: `.claude/skills/release-tellr/SKILL.md`. The frontmatter `name: release-tellr`, and a `description` that triggers on "cut a release", "new release", "release tellr", "publish to PyPI" and "bump the version". Follow `.claude/skills/deploy-tellr-dev/SKILL.md`'s shape.
- Create: `.github/pull_request_template.md`
- Modify: `CLAUDE.md`. Add a "Cutting a release" section after "Deploying dev builds" that points to the skill. Add a rule that every PR body includes a `## What's new` section in the template's format, or `None`.

**Skill content.** Spec Part 4, as concrete commands:
1. **Account and version.** `gh auth status`, and switch to `robertwhiffin` if the active account is EMU. The last final tag is the newest `v<X.Y.Z>` (ignore `ds-v1-checkpoint`). The proposed version is last + one patch. Confirm it with the owner.
2. **PRs since the last tag.** Run `git log --first-parent --format='%H %s' <last-tag>..origin/main`. Every subject `Merge pull request #N …` is a PR, read with `gh pr view N --json number,title,body`. List any other first-parent commit to the owner as "direct commit".
3. **Draft.** Use the PR's `## What's new` section if present (`None` means skip). Otherwise, judge from the title and body whether a Tellr user would notice the change. Bullets are written for users with no internal terms (fence, seal, SP, migration, PR numbers). Several PRs that make up one feature merge into one bullet.
4. **Approval in the terminal.** Print the popup preview exactly as users will read it (version, month, `**Title.** body` lines). Then print a "Left out" table (PR, title, one-line reason). Ask the owner to approve or edit, and repeat until they approve. Nothing is written before approval.
5. **Bump PR.** Work in a `release/v<version>` worktree.
   - Write `frontend/src/whatsNew/releases/<version>.json` (date = today, UTC).
   - Run `python3 scripts/check_release_notes.py <version>` and `cd frontend && npx vitest run src/whatsNew`.
   - Bump `version` in both `packages/databricks-tellr/pyproject.toml` and `packages/databricks-tellr-app/pyproject.toml`.
   - Commit, push, and open the PR. The body follows #367's shape: what the release adds by PR, the approved popup wording, and the after-deploy notes.
   - CI now runs the frontend suites, including the first real run of `whats-new.spec.ts`. Wait for green.
6. **Merge, tag, watch.** On the owner's go-ahead:
   - `gh pr merge <n> --merge --match-head-commit <full sha, typed literally>`;
   - `git fetch origin`;
   - `git tag -a v<version> -m v<version> <merge sha>`;
   - `git push origin v<version>`;
   - then `gh run watch` the `publish.yml` run, and quote its "Uploading" lines as the evidence.
7. **Stop.** List what the skill does not do: `tellr.update` on logfood/prod and the admin checks, any admin Adopt, and syncing the tag to `databricks-industry-solutions/databricks-tellr`.

Gotchas section, from the spec:
- the tag push alone publishes, with no approval gate;
- the `gh` account can flip to EMU;
- the pre-push hook takes ~3 min on both pushes;
- in worktree sessions, there is no `git`/`gh` inside `$(…)`;
- the PyPI JSON API may not answer from the laptop.

PR template: a `## Summary` section and a `## What's new` section. The latter has an HTML comment explaining that the text is shown to Tellr users in the in-app popup, with one bullet per user-facing change as `**Bold lead-in.** One sentence.`, or `None`.

- [ ] **Step 1: Write the three files.**
- [ ] **Step 2: Self-check the skill against the spec** (Part 4 and the gotchas). Every step must name its command, and nothing in it may push, tag or merge without an explicit owner go-ahead step.
- [ ] **Step 3: Commit** `docs(release): release-tellr skill, PR template, CLAUDE.md rules`.
- [ ] **Step 4: Dry run (the acceptance test).** Follow the skill's steps 1–4 against the real repo, for the PRs since `v0.5.6`, **writing nothing**. Hand the draft preview and the "Left out" table to the orchestrator, which shows them to the owner.
  - Expected: bullets covering image generation (#376), stopping a generation with Esc (#385) and MCP tools in Agent mode (#384).
  - Expected: internal-only PRs appear under "Left out" with reasons.
  - If the draft doesn't match, fix the skill's drafting rules and dry-run again.

---

## After the tasks

1. **Whole-branch review** on Opus, per `executing-plans-tellr` §7, including `tellr-code-review`.
2. **Owner browser check**, using a throwaway branch per the spec:
   - `git switch -c tmp/whats-new-preview feat/whats-new`, then add a sample `0.5.7.json` (the dry-run draft) and commit it;
   - push, `gh workflow run publish-dev.yml --ref tmp/whats-new-preview`, and deploy to a devloop instance via `deploy-tellr-dev`;
   - check with peers first (ListAgents) that the instance and the `.devN` counter are free;
   - never merge this branch; delete the branch and the instance afterwards.
3. **Open the PR from `feat/whats-new`.** Its own `## What's new` section is `None`: the popup ships without notes, and the first notes arrive with 0.5.7.

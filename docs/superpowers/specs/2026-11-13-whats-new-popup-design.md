# "What's new in Tellr" popup and the release skill — design

Date: 2026-11-13. Status: draft for owner approval.

## Intent

Users do not find out what each release gave them. 0.5.7 ships three things a user would want to
know about: image generation in chat, Esc to stop a generation, and MCP tools in Agent mode. Today
nothing in the app tells them.

This adds a "What's new in Tellr" popup that lists the user-facing highlights of each release.
The words come from the PRs merged into that release. They are drafted automatically at release
time, and the owner approves them in the terminal before the release goes out.

The release itself becomes a repo skill, `release-tellr`. The release procedure is not written
down in the repo today (it lives in the owner's agent memory notes), and the approval step needs a
home. So the skill owns the whole release, with the notes step built in.

## Goals

- On a user's first visit after an upgrade, a popup lists the highlights of every release they
  have not seen, newest first.
- Users can reopen it at any time and scroll back through every earlier release that has notes.
- The notes for each release are stored in the repo, one file per version.
- The wording is drafted from the merged PRs with no hand-writing needed, **including for 0.5.7**.
  #376, #384 and #385 were merged before any PR carried a "What's new" section, and the drafting
  must still work for them.
- The owner reviews and approves the wording in the terminal before any release is tagged.
- A release cannot be published without a notes file for its version.

## Non-goals

- Notes for releases before 0.5.7. The history starts at 0.5.7.
- Notes tailored per user, per role or per deployment. Everyone sees the same list. A bullet is
  not hidden from non-admins, or on a deployment where the feature is not switched on.
- Storing on the server what a user has seen. It lives in the browser, like the welcome guide.
- GitHub Releases. The repo has never used them, and this does not start.
- Changes to Legacy deck mode. Legacy is frozen. The popup is app-wide UI, not a deck feature.

## Anti-goals (it fails if…)

- A brand-new user gets the welcome guide and then the What's new popup straight after.
- Engineer-facing wording reaches users ("fence", "seal", "SP", PR numbers, CI changes).
- A release ships with wording the owner never saw.
- The popup gets in the way of the E2E suite or the user-guide screenshots.

## Part 1 — the popup

### What it looks like (owner chose layout "A: one scrolling list")

- A modal in the same visual style as `frontend/src/components/Tour/WelcomeModal.tsx`: rounded
  white panel, header with title and a close ✕, footer with one primary button.
- Title "What's new in Tellr". Subtitle "Highlights from each release".
- The body is one scrolling list, newest release first. Each release shows:
  - its version (e.g. `0.5.7`) and month (e.g. "November 2026");
  - a **New** badge if the user has not seen it yet;
  - its bullets. Each bullet has a short bold lead-in and then a sentence, e.g.
    **Stop a generation.** Press Esc to cancel mid-flow.
- Older releases follow below in the same list, in quieter styling, separated by a divider.
- Footer: a single "Got it" button.

The mockup the owner picked is at `~/tellr-loop/whats-new/.superpowers/brainstorm/*/content/popup-layout.html`
(option A).

### When it opens by itself

- **An existing user after an upgrade:** if the newest release in the notes is newer than the last
  version this browser dismissed, the popup opens by itself on load. It uses a short delay, like
  the welcome guide's 800 ms. Every release newer than the last dismissed one gets the **New**
  badge.
- **A user who has never dismissed a What's new popup but has completed the welcome guide**
  (everyone already on Tellr when this ships) counts as "seen nothing". They see the popup once,
  with every release badged New. Today that means just 0.5.7.
- **A brand-new user** (the welcome guide has not been completed) gets only the welcome guide.
  When they dismiss the welcome guide, or finish or skip the tour, they are marked as having seen
  everything up to the newest release. They then get the popup only after the next upgrade.
- **Never stacked:** it does not open while the welcome guide or the app tour is showing.
- **Empty releases:** a release whose notes have no bullets adds nothing to the list. If no
  release newer than the last dismissed one has bullets, nothing opens.
- **Closing:** "Got it", ✕, Esc and a backdrop click all count as dismissing. Each one records the
  newest release as seen.

### Reopening it

A "What's new" item in the sidebar footer opens the popup at any time. It sits next to the
existing "App Tour" button in `frontend/src/components/Layout/app-sidebar.tsx`, because both open
an overlay rather than a page. (During the conversation this was described as "next to Help".
The footer is my call, since Help is a page in the Configure list.) Opened this way it shows the
same list, with **New** badges only on releases not yet dismissed.

### Remembering what was seen

- localStorage, per browser, like `tellr-app-tour-completed` in
  `frontend/src/contexts/TourContext.tsx`. It stores the last version dismissed.
- Nothing goes to the server.
- A new browser, or cleared storage, has no tour flag either, so it follows the brand-new-user
  rule: the welcome guide only, then marked as caught up. (My call. It is the only reading that
  respects the "never stacked" anti-goal.)

### Where "newest release" comes from

From the newest notes file bundled into the frontend, **not** from the running app's version.
The backend's `__version__` is unreliable: `src/__init__.py` says `0.1.0` in shipped wheels, which
is a known bug. Dev builds such as `0.5.8.dev3` show the notes up to the newest release whose
file exists, which is the right behaviour.

Version ordering must be numeric per component, so that `0.5.10` sorts after `0.5.9`.

## Part 2 — the notes files

- One file per release version, in the frontend source so Vite bundles them into the build. One
  file per version keeps each release's wording in its own diff and gives the publish guard a
  single path to check.
- Each file holds the version, the release date, and an ordered list of bullets. Each bullet has a
  bold lead-in (`title`) and a sentence (`body`). An empty list is valid and means "nothing
  user-facing in this release".
- A unit test validates every notes file: the shape, the file name matching the version inside it,
  non-empty title and body, and no duplicate versions. Bump PRs now touch `frontend/**`, so the
  frontend suites run on them as well. That is intended: it is how a malformed notes file gets
  caught before the tag.

## Part 3 — writing the words down in PRs

- A new `.github/pull_request_template.md` with a `## What's new` section. Authors write the
  section in the same format as the popup (bold lead-in plus one sentence, written for Tellr
  users), or write "None" for CI, refactors and fixes nobody would notice.
- A line in `CLAUDE.md` telling agents to include the section in every PR body they write. Agent
  PRs are created with `gh pr create --body`, which ignores the template, so this line is what
  makes it happen in practice.
- The section is a strong hint, not a requirement. The release skill drafts wording for PRs that
  do not have it.

## Part 4 — the `release-tellr` skill

A new repo skill at `.claude/skills/release-tellr/`, alongside `deploy-tellr-dev`. It walks the
whole release. The notes step comes before the bump PR.

1. **Pick the version.** Default to the dev line's next patch (one patch above the highest final
   tag). Confirm it with the owner, who sometimes picks a minor bump instead (0.5.0, for example).
2. **Collect the PRs** merged to `main` since the last `v*` tag.
3. **Draft the wording.** For each PR:
   - if it has a `## What's new` section, use it (`None` means skip it);
   - otherwise read the title and description, decide whether a Tellr user would notice the
     change, and if so write a bullet in the popup format;
   - drop CI-only, refactor, test-only and invisible fixes;
   - merge several PRs into one bullet where they make up one feature for the user (e.g. #376
     plus its follow-ups).
4. **Ask for approval in the terminal.** Show the popup wording exactly as users will read it,
   then a list of every PR left out with a one-line reason, so the owner can see that nothing was
   missed. The owner approves or edits. Repeat until approved. Nothing is written before
   approval.
5. **Open the bump PR.** One PR that bumps `version` in both `packages/databricks-tellr/pyproject.toml`
   and `packages/databricks-tellr-app/pyproject.toml` and adds the approved notes file. The PR body
   keeps today's shape: what the release adds, by PR, plus after-deploy notes (migrations, Adopt
   steps, rollback limits).
6. **Merge, tag, watch.** After the owner's go-ahead, merge the PR. Then create an annotated tag
   `v<version>` (message `v<version>`) on the merge commit and push it, and watch the publish
   run through to the PyPI upload lines.

**The skill stops at the PyPI publish** (owner's decision). It ends by listing the after-publish
work that it does not do, so nobody assumes it was covered:

- `tellr.update` on logfood and prod, and the admin checks;
- any admin Adopt the release needs;
- syncing the tag to the internal `databricks-industry-solutions/databricks-tellr` repo.

The skill carries the known gotchas from past releases:

- The tag push alone publishes. The `pypi` environment has no approval rule, and a publish cannot
  be undone.
- The `gh` active account can flip to the EMU account. Pushes, merges and workflow runs need the
  personal `robertwhiffin` account.
- The global pre-push hook takes about 3 minutes on both the branch push and the tag push.
- In a worktree-isolated session, `git` and `gh` inside `$(…)` are refused, so pass full SHAs
  literally (e.g. to `gh pr merge --match-head-commit`).
- PyPI's JSON API may not answer from the laptop. The publish run's upload log lines are the
  evidence that the release published.

## Part 5 — the publish guard

`.github/workflows/publish.yml`'s `validate` job already checks that the tag matches both
pyprojects. It also has to fail when the notes file for the tag's version is missing or does not
parse. The skill makes skipping the step unlikely, and the guard makes it impossible.

## Rollout for 0.5.7

0.5.7 is the first release cut with `release-tellr`. The skill drafts from #376 (image
generation, with follow-ups), #384 (MCP tools in Agent mode) and #385 (stop a generation, merged
2026-11-13 as d7850cae). The owner's own phrasing, as the expected outcome:

- Native image generation in chat. Ask for things like "make an image that represents this slide"
  or "give me an image of a monkey at a keyboard".
- Chat cancellation. Hit Esc to cancel a generation mid-flow.
- MCP tool calling in Agent mode. Add any MCP from the Gateway to your slide agent.

This feature's own PR adds no notes file. The 0.5.7 file is written by the skill in the 0.5.7
bump PR, after approval.

## Testing constraints

- `frontend/playwright.config.ts` suppresses the welcome guide by seeding
  `tellr-app-tour-completed=true` in `storageState`. Under the rules above, that state looks like
  an existing user who has seen no notes, so the What's new popup **would open in every E2E test**
  and in the user-guide screenshot run. The global `storageState`, and the two specs that override
  it (`graph-release-admin-journey.spec.ts`, `graph-release-conversation-journey.spec.ts`), must
  also seed "seen up to the newest release". The newest version should come from the bundled
  notes, not a hard-coded value that goes stale.
- Unit tests cover the decision logic: brand-new, existing-with-no-record, behind by one, behind
  by several, up to date, empty releases, and version ordering.
- **This PR ships with no notes file**, so the popup has nothing real to show until the 0.5.7
  bump PR. My calls on testing it:
  - The popup takes its list of releases as an input. Component tests (vitest) pass in fixture
    releases and cover rendering, badges, dismissal and reopening. No test-only switch goes into
    production code, so fixture text can never reach users.
  - An E2E spec covers the popup opening after an "upgrade", dismissal sticking across a reload,
    and reopening from the sidebar. It reads the real bundled notes and skips while there are
    none. Its first real run is on the 0.5.7 bump PR (which touches `frontend/**`, so the E2E
    shards run), before the tag is pushed.
  - The owner's browser check before this PR merges uses a throwaway branch: this branch plus a
    sample 0.5.7 notes file, published as a `.devN` and deployed to a devloop instance. That
    branch is never merged.

## Left to the builder

- The exact file path, file format (JSON is the obvious choice) and loading mechanism for the
  notes files.
- The localStorage key name, and whether the What's new state lives in `TourContext` or its own
  context.
- The icon for the sidebar item and the exact styling, within the WelcomeModal look.
- How the skill finds merged PRs (merge commits versus `gh pr list --search`), as long as it
  lists every PR merged since the last tag.
- Whether the user-guide docs get a short mention of the sidebar item.

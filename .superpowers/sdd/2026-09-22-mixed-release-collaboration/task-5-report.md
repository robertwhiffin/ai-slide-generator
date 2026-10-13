# Task 5 report — accessible mixed-release warning UI and immutable Start-latest

**Status:** DONE_WITH_CONCERNS
**Base:** `a6bc952f39f786a47ee6d1a4bedb3a1799e6dc0a` (triple check clean before any edit:
empty `git status --porcelain`, empty `git diff HEAD`, empty `git diff --cached`)
**Commit:** `2ca0825fcc9b47648d349421c1145526efe471e0` on `plan/conversation-collaboration-262`
**Installs run:** none. No `npm install`, `npm ci`, `npx playwright install`, `pip install`,
`uv`, `uv run`, or `.venv`. No dev-database migration, alteration, drop or read-as-evidence.

## Gates

| gate | command | result |
| --- | --- | --- |
| frontend unit | `npm run test:unit` | 166 passed / 12 files, 0 failed |
| typecheck | `npm run typecheck` (`tsc -b`) | clean |
| new spec | `npx playwright test tests/e2e/mixed-release-collaboration.spec.ts --project=chromium --workers=1` | 5 passed |
| #261 adjacent spec | same, `conversation-graph-version.spec.ts` | 7 passed |
| e2e regression sweep | same, `session-loading` + `chat-ui` + `viewer-readonly` + `conversation-graph-version` | 44 passed |
| CI workflow guards | `pytest tests/unit/test_e2e_matrix_covers_specs.py test_ci_*.py test_agentic_layer_is_placed_and_gated.py` | 57 passed |

Port 3000 confirmed to have zero listeners before every Playwright invocation; all runs
`--project=chromium --workers=1`, one at a time. The frontend lane was held exclusively
throughout (C-23) — Vitest as well as Playwright.

The full `tests/unit` Python suite was **not** re-run: the only Python-visible change is one
line in the `e2e-tests` matrix of `.github/workflows/test.yml`, and all five test modules that
parse that file were run instead (57 passed). Slice 4A's 6-failure cause baseline is therefore
neither confirmed nor disturbed by this task; see Concerns.

## What was built

- `frontend/src/services/api.ts` — `CollaborationReleaseGroup`, `CollaborationHistory`,
  `api.getCollaborationHistory`. The client **narrows** the response to the four documented
  group keys rather than passing it through, so a later server-side widening cannot reach a
  consumer. On a non-ok response it throws one constant message, **never reads
  `response.json().detail`**, and **never retries** — the endpoint's byte-identical 404 for an
  unauthorized real id and a fabricated one stays indistinguishable client-side.
- `frontend/src/contexts/SessionContext.tsx` — `collaborationHistory` +
  `collaborationHistoryFailed`. The load starts before the slides fetch (so it is parallel,
  adding no serial round-trip) but deliberately does **not** block the commit; the commit
  handler is attached only on the committed path, and drops a landing when either the caller's
  `isCancelled` predicate or `api.getCurrentSessionId()` says the session has moved on. Both
  are pre-existing mechanisms — no new reducer, request-ID counter or pending-operation gate.
  `createNewSession` clears both fields; `switchSession` clears them in the same batch as the
  title/sessionId commit so an outgoing deck's rows never linger over a new conversation.
- `frontend/src/components/Conversation/MixedReleaseWarning.tsx` (new) — the warning
  (`role="status"`), the `Change provenance` disclosure (a real `<button>` with
  `aria-expanded`/`aria-controls`), the labelled rows, and the single generic unavailable
  state. Per **ruling F6** the component owns every display string: `Legacy (no graph release)`
  is rendered from `graph_version === null`, and no legacy row is ever called "active". The
  component is given **no** access to the conversation's own pinned version, so a row cannot
  borrow the root badge's release.
- `frontend/src/components/Layout/AppLayout.tsx` — rendered as a **sibling** of
  `GraphVersionStatus`, gated on `isSessionPersisted`.
- `frontend/src/components/Layout/deck-history.tsx` — comment only, recording why the deck
  list carries no indicator (see C-19 answer).
- `frontend/tests/helpers/setup-mocks.ts` — a default 200/empty collaboration-history route,
  registered after the `/api/sessions**` catch-all so LIFO ordering gives it precedence.
  Without it the catch-all's `else` answers 404 and every session-restoring spec would render
  the generic unavailable state. Measured blast radius after the change: 44 adjacent tests
  pass unchanged.
- `.github/workflows/test.yml` — `mixed-release-collaboration` added to the e2e matrix.
- Two new test files: `MixedReleaseWarning.test.tsx` (20 tests) and
  `frontend/tests/e2e/mixed-release-collaboration.spec.ts` (5 tests).

Note a design decision taken against a naive reading of the brief and disclosed here: an
earlier version awaited the history load **before** the session commit. It was correct on
privacy but it delayed the title, sessionId and pinned badge behind a provenance query, and it
broke #261's existing `restores returned graph versions` test by pushing the commit past that
test's `act()` flush. Fixing the test would have hidden a real latency regression, so the
design changed instead.

## Clause-to-mutation table

Every mutation below was applied to the working tree, measured, and restored from `cp` backups
enumerated with `git diff --name-only HEAD` (never `git checkout <commit> -- <paths>`).
Vitest mutations ran `npx vitest run src/components/Conversation`; E2E mutations ran the new
spec; the type mutation ran `npm run typecheck`; the CI mutation ran the guard module.

| brief clause | the test that claims it | the mutation that would RED it | measured result |
| --- | --- | --- | --- |
| two-version warning | Vitest `warns when one deck carries changes from two persisted Graph Versions`; E2E T1 | M1 `{history.mixed_release_warning && (` → `{false && (` | **RED** |
| no warning, same release | Vitest `shows no warning when every change is on the same release`; E2E T3 | M2 same guard → `{true && (` | **RED** |
| explicit legacy wording | Vitest `calls a null graph release Legacy and never active`; E2E T3 | M3 `LEGACY_RELEASE_LABEL` → `'Graph Version unknown'` | **RED** |
| never "active" for a legacy row (F6) | same two tests | M4 `LEGACY_RELEASE_LABEL` → `'Active (no graph release)'` | **RED** |
| visible fetch failure | Vitest `shows a visible failure state…` + `keeps the unavailable state generic`; E2E T4 | M5 `loadFailed` branch returns `null` | **RED** (2 tests) |
| …without badge erasure | E2E T4's badge assertion | M28 delete `<GraphVersionStatus/>` from AppLayout | **RED** (4 of 5 E2E) |
| accessible `role=status` | Vitest `warns…` via `getByRole('status')`; E2E T1 `toHaveAttribute('role','status')` | M6 remove `role="status"` | **RED** |
| focusable disclosure | Vitest `discloses provenance behind a focusable button…` (`tagName === 'BUTTON'`, `toHaveFocus`) | M7 `<button>` → `<span role="note">` | **RED** (5 tests) |
| labelled actor/release rows | Vitest same test; E2E T1 per-name `toHaveCount(1)` | M8 remove `aria-label` from the `<li>` | **RED** (4 tests) |
| rows use the returned release, not the root badge | Vitest `labels each row from its OWN returned release…`; E2E T1/T2 | M9 every row labelled with one deck-wide release | **RED** (3 tests) |
| " | " | M10 every row labelled with the root badge's version `1` | **RED** (3 tests) |
| no username / session id / UUID / principal in DOM or a11y tree | Vitest `lets no server-added field reach the DOM or the accessibility tree`; E2E T1 (`@`, UUID, session id) | M11 render `JSON.stringify(group)` into the row | **RED** |
| …nor in the client type | Vitest `declares no field beyond the documented safe set` (`never[]` guard) | M22 add `actor_session_id: string` to `CollaborationReleaseGroup` | **RED** at typecheck, on the guard's own line |
| …nor in the client's narrowing | Vitest `narrows the response to the four safe group fields` | M12 pass `payload.groups` through unnarrowed | **RED** |
| …nor in the request | Vitest `sends a bare authenticated GET carrying no identity of its own` | M13 add an `X-Actor-Session` header | **RED** |
| 404: do not branch on detail | Vitest `treats every denied response as one generic failure and never retries` | M14 throw `error.detail` | **RED** *(after re-aim — see below)* |
| 404: do not retry to probe existence | same test; E2E T4 `historyCalls === ['GET']` | M15 retry once on a non-ok response | **RED** |
| one generic unavailable state, no name/version disclosure | Vitest `keeps the unavailable state generic`; E2E T4 | M33 change `HISTORY_UNAVAILABLE_TEXT` | **RED** (2 tests) |
| mandated warning wording | Vitest `warns…` (literal) | M31 reword `MIXED_RELEASE_WARNING_TEXT` | **RED** *(after re-aim)* |
| mandated `Change provenance` disclosure wording | Vitest 4 tests (literal) | M32 `DISCLOSURE_LABEL` → `'Show details'` | **RED** (4 tests) *(after re-aim)* |
| context gets state, resets in `createNewSession` | Vitest `loads collaboration evidence… and clears it for a fresh session` | M16 drop the two resets from `createNewSession` | **RED** |
| loads on successful `switchSession` | same test | M17 never attach the landing handler | **RED** (2 tests) |
| honours the existing cancellation generation | Vitest `discards evidence for a switch superseded while its load was in flight` | M18 drop `if (isCancelled?.()) return;` from the landing guard | **RED** |
| no stale landing after a session change | Vitest `discards evidence that lands after the session has already changed` | M19 drop the `getCurrentSessionId()` check | **RED** |
| render only for persisted authorized sessions | Vitest `renders nothing for a session that is not persisted` | M20 remove the `isSessionPersisted` gate | **RED** |
| rendered beside the #261 badge at all | E2E T1–T5 | M29 delete `<MixedReleaseWarning/>` from AppLayout | **RED** (5 of 5) |
| Start latest creates a `graph_capable: true` session with a new id | E2E T2 | M24 `graphCapable: false` | **RED** |
| Start latest cannot PATCH/copy/repin the original | E2E T2 (`nonGetToOriginal === []`, recorded at the wire) | M25 add a PATCH to the original in `handleStartLatest` | **RED** |
| duplicate gets the active R2, source stays R1, client never asks for a release | E2E T5 | M26 `api.duplicateSession` sends `graph_version: 1` | **RED** |
| row names mutually distinct (hazard 1) | Vitest `keeps every row name distinct under substring matching`; E2E T1 per-name counts + bare-label count | M21 reduce the row label to the actor label alone | **RED** (4 tests) |
| no accessible name nested inside another (hazard 1) | Vitest `discloses provenance…` (literal); E2E T1 `getByRole('list', {name:'Contributor releases'})` | M27 `PROVENANCE_LIST_LABEL` → `'Change provenance details'`, which nests inside the disclosure's name | **RED** *(after re-aim)* |
| fixture cardinality joined, not free (hazard 3) | Vitest `keeps every row name distinct…` (`names.length === MIXED_HISTORY.groups.length`) | M30 narrow `MIXED_HISTORY` from 3 groups to 1 | **RED** (3 tests) |
| spec is collected by CI | `tests/unit/test_e2e_matrix_covers_specs.py` | M23 remove the matrix entry | **RED** |

**Blank count: 0.** Every clause the brief mandates has at least one measured RED. Two clauses
reached zero on the first attempt and were re-aimed; both attempts are reported below rather
than quietly replaced, and neither zero was a suite problem — both were defects in my own
tests.

### Mis-aimed attempt 1 — M14 first measured GREEN

`treats every denied response as one generic failure and never retries` used
`mockResolvedValue(new Response(...))`, which hands **the same Response instance** to every
call. Under M14 (a client that reads `error.detail`) the first call consumed the body and the
second call's `response.json()` threw into `.catch(() => ({}))`, falling back to the generic
message — and the test collected its message from that second call. The assertion was vacuous
under exactly the mutation it existed to catch. Re-aimed to `mockImplementation` returning a
**fresh** Response per call, collecting the message from the first (real) failure and asserting
`toHaveBeenCalledTimes(1)`. M14 and M15 then both RED. The reasoning is recorded in the test's
own comment so it is not "simplified" back.

### Mis-aimed attempt 2 — M27 measured GREEN in Vitest

The unit test imported the component's own `PROVENANCE_LIST_LABEL`, `DISCLOSURE_LABEL`,
`MIXED_RELEASE_WARNING_TEXT` and `HISTORY_UNAVAILABLE_TEXT`. Renaming
`PROVENANCE_LIST_LABEL` to `'Change provenance details'` — a string that **nests inside** the
disclosure's accessible name, i.e. precisely the strict-mode hazard this epic has paid for
twice — left all 20 unit tests green. Only the Playwright spec caught it, because the spec uses
literals. The same weakness made every mandated-wording clause unguarded at the unit level. All
four constants were replaced with literals in the test file, with a comment recording why; M27b,
M31, M32 and M33 then all RED. Finding worth keeping: **a test that imports the constant it
asserts is not a guard for that constant's value.**

## C-19 answer — did Task 5 need an inline summary on `get` or `contributor`?

**No.** The item closes.

`api.getCollaborationHistory` is the only call this task added, and it is issued in parallel
with the existing `api.getSlides` inside `switchSession`, so on the ordinary restore path
(`has_slide_deck: true`) it costs **zero extra serial round-trips** — it overlaps a fetch that
already had to happen. On a deckless restore it is one additional request after `getSession`,
which is the correct price for an authorization-scoped, deck-wide grouped projection: the data
is not a property of the requested session row, and putting it on `get` would make every
`getSession` caller pay for a grouped query none of them read.

Two related notes for the whole-branch review:

1. `contributor` likewise needed nothing: the contributor flow navigates to the new session,
   which restores through the same `switchSession` path and gets the history there.
2. The plan's Task 5 file list names `deck-history.tsx` — the **deck list** — as a second
   surface for the warning. That surface is genuinely blocked, not deferred by preference: it
   would need the `list` summary that C-19 upheld as deliberately not implemented, because
   bullet 3 of the same task forbids the N+1 a per-row fetch would be. I recorded the reason in
   a comment in `deck-history.tsx` rather than adding a per-row fetch. This is the AC5 concern
   below.

## Concerns

1. **AC5's "collaboration surfaces" is satisfied on one surface, not two.** Issue #262 AC5 is
   "Conversation and collaboration surfaces warn when one shared deck has writers on multiple
   Graph Versions." The conversation surface is implemented and tested. The second surface the
   plan named (`deck-history`, the deck list) is blocked by C-19 as above. The other candidate
   is the share dialog, which renders `DeckContributorsManager` from `AppLayout:1474` — I did
   **not** add a second instance there, for two reasons: the share dialog is an overlay that
   leaves the chat panel mounted, so two identical `Change provenance` accessible names would be
   on screen together, which is exactly the strict-mode collision hazard 1 warns about and which
   no disambiguating suffix avoids (any suffix makes one name a substring of the other under
   Playwright's case-insensitive substring matching); and `DeckContributorsManager.tsx` is
   outside my Files block. **The whole-branch review should confirm AC5 against verbatim issue
   text with this single-surface reading on the record**, or commission a second placement as a
   scoped task that owns the duplicate-name problem deliberately.
2. **Python baseline not re-measured.** I ran the five workflow-parsing modules (57 passed)
   rather than the full `tests/unit`, because the only Python-visible change is one matrix line.
   Slice 4A's residual (6 failed / 5325 passed / 110 skipped) is therefore unverified at this
   commit. If the whole-branch review wants a cause-based comparison it should re-measure there.
3. **`GraphVersionStatus.tsx` was not modified**, although the Files block permits it. The
   warning is a sibling rather than a child, which makes "no badge erasure" structural. The
   Files block permits modification; it does not require it.
4. **Deferred-landing race window is narrowed, not eliminated.** The landing guard checks
   `isCancelled` and `api.getCurrentSessionId()`. A restore of session A followed by a restore
   of A again (same id) while the first history load is in flight would let the first result land
   for the second restore. It is the same deck and the same authorization, so the rendered value
   is correct; noted so it is not rediscovered as a defect.
5. **Timestamp rendering is locale-dependent.** Row `<time>` text uses `toLocaleString()`, so no
   test asserts on it — the deterministic `dateTime` attribute carries the ISO value and the row's
   accessible name deliberately excludes the timestamp. If a future spec asserts displayed
   timestamp text it will be environment-sensitive.
6. **The `setup-mocks.ts` default is now load-bearing for other tickets' specs.** Any spec that
   restores a session and does not route `collaboration-history` relies on that default returning
   200/empty. It is documented in place, including the LIFO-ordering requirement.

---

# Task 5 — fix round 1 of 5

**Status:** DONE_WITH_CONCERNS
**Base:** `c5594a33be7d57d223a8c492ab214cc49c7d13df` (triple check clean before any edit)
**Commit:** `53126c8697977eb998819d65cf5eb06f2a85df18`
**Installs run:** none. Port 3000 confirmed to have zero listeners before each of the 5
Playwright invocations in this round, one at a time, `--project=chromium --workers=1`.
Frontend lane held exclusively. No dev-DB migrate/alter/drop/read. Restored from `cp`
backups enumerated with `git diff --name-only HEAD`; never `git checkout <commit> -- <paths>`.

| gate | result |
| --- | --- |
| `npm run test:unit` | 169 passed / 12 files (was 166; +3 new unit tests) |
| `npm run typecheck` | clean |
| new spec | 6 passed (was 5; +1 second-surface test) |
| adjacent regression (`mixed-release-collaboration` + `conversation-graph-version` + `session-loading` + `chat-ui` + `viewer-readonly`) | 50 passed |

## ITEM 1 — privacy guard now covers the region root's own attributes

`innerHTML` excludes the element's own attributes; `textContent` excludes all of them. The
unit guard used the former and the spec the latter, so a leak into `aria-label` on the
region root reached the accessibility tree as the region's **computed name** while both
guards stayed green. Fixed in three places:

- unit: `expect(region.outerHTML).not.toContain(needle)` for every needle, plus
  `.not.toMatch(UUID_PATTERN)` and `.not.toContain('@')` over `outerHTML`;
- unit: an accessibility-**tree** oracle rather than a markup one —
  `queryByLabelText(UUID_PATTERN)`, `queryByLabelText(/@/)` and `queryByTitle(UUID_PATTERN)`
  must all be absent. These compute over `aria-label`/`aria-labelledby`/`<label>`, so they
  fire for a leak that never appears as visible text;
- spec: both privacy assertions now read `locator.evaluate((el) => el.outerHTML)` instead of
  `textContent`, on both surfaces.

**Re-measured with the review's exact sabotage** (`aria-label="aa11bb22-…"` on the region
root — deliberately a *different* UUID from the test's needle, so the guard has to catch it
by pattern rather than by literal):

| probe | measured |
| --- | --- |
| `outerHTML_has_uuid` | **true** |
| `innerHTML_has_uuid` | **false** |
| `textContent_has_uuid` | **false** |
| `accessible_name_is_uuid` | **true** |

Marker confirmed on the executed path, byte-for-byte the shape the review reported. With the
marker confirmed: **N1 RED** in Vitest (`lets no server-added field reach the DOM or the
accessibility tree`) and **RED** in Playwright (2 tests — T1 and the new second-surface
test). And **N1b GREEN**: the same leak with the guard reverted to `innerHTML`/`textContent`
and the a11y oracles deleted passes, independently reproducing the review's finding and
proving the fix is load-bearing rather than cosmetic.

## ITEM 2 — AC5's second surface added, and the reasoning corrected

The review was right on all three counts and I have adopted the corrections rather than
re-arguing them.

- **Files block.** `MixedReleaseWarning` now renders in the Share Deck dialog **body**, which
  `AppLayout.tsx` owns. `DeckContributorsManager.tsx` is untouched. My earlier "outside my
  Files block" claim was simply wrong.
- **Distinct wording, not a suffix.** I had considered only suffixes. The two surfaces now use
  wholly distinct names — conversation `Change provenance` / `Contributor releases`,
  collaboration `Who changed this deck` / `Release history by contributor` — which escapes
  Playwright's default case-insensitive substring matching outright. Measured with the dialog
  open: each of the four names resolves to exactly 1 element under **default** matching, so
  neither `exact: true` nor scoping is needed for names.
- **The obstacle I had not named.** The conversation copy sits behind the overlay and cannot
  receive pointer events. The spec asserts that directly with
  `click({ trial: true, timeout: 2000 })` — a trial click runs the full actionability check
  without acting — and then interacts with the dialog copy through a **container-scoped**
  locator. Renaming was never the fix.
- I also hit the collision the review mentioned in passing: my fixture titles the session
  `Shared deck`, so `getByRole('button', { name: 'Share' })` matched the deck-title button
  too. The spec uses `exact: true` there.

Design decision taken and asserted: **only the conversation surface announces.** Its warning
can arrive asynchronously, so `role="status"` is correct there; the dialog copy is static
content the user just opened, and two simultaneous identical live regions would read the same
sentence twice. That also keeps `getByRole('status')` unambiguous while both placements are
mounted — asserted as `toHaveCount(1)` with the dialog open.

Coexistence is asserted rather than hidden: with the dialog open the spec pins
`getByTestId('mixed-release-warning-text')` at 2, `getByText(WARNING_TEXT)` at 2,
`getByTestId('mixed-release-disclosure')` at 2, and — once both disclosures are expanded —
`getByTestId('mixed-release-row')` at 6, with a comment recording that row vocabulary is
shared **by design** so nobody "fixes" the ambiguity by renaming rows per surface.

## Minor-1 and Minor-2

- **Minor-1.** `expect(names).toHaveLength(MIXED_HISTORY.groups.length)` and the spec's
  `toHaveCount(MIXED_HISTORY.groups.length)` could not fail — both sides shrink with the
  fixture. They are literal `3` now, and the "cannot silently shrink" comment moved onto the
  literal `toBe(2)` that actually earns it. The new `no surface's accessible name nests inside
  another's` test applies the same lesson up front: literal `toHaveLength(4)`.
- **Minor-2.** `MIXED_RELEASE_WARNING_TEXT`, `LEGACY_RELEASE_LABEL`, `HISTORY_UNAVAILABLE_TEXT`,
  `releaseLabel` and `groupRowLabel` are module-private now. Three exports remain, each with a
  real consumer: `MixedReleaseWarning`, `MixedReleaseWarningProps`, and
  `SURFACE_ACCESSIBLE_NAMES`. The last is exported deliberately for the pairwise-nesting guard,
  which asserts a **structural** property over the real set — and it still pins both disclosure
  labels by literal `toContain`, so C-24 is respected: the wording is never checked against an
  import of the constant that produces it.

## Extended clause-to-mutation table

| brief clause | the test that claims it | the mutation that would RED it | measured result |
| --- | --- | --- | --- |
| no identity reaches the region root's **attributes** or the a11y tree | Vitest `lets no server-added field reach the DOM or the accessibility tree` (outerHTML + `queryByLabelText`/`queryByTitle`); spec T1 + T6 outerHTML | N1 raw UUID into `aria-label` on the region root (the review's exact sabotage) | **RED** — Vitest 1 test, Playwright 2 tests, marker confirmed on the executed path first |
| …and the old text-only guard genuinely missed it | — (control) | N1b same leak, guard reverted to `innerHTML`/`textContent`, a11y oracles removed | **GREEN — reproduces the review's finding**, which is what makes the fix load-bearing |
| AC5's second surface exists | spec T6 `both AC5 surfaces stay independently addressable…` | N3 delete the collaboration placement from the dialog body | **RED** |
| second surface's wording is distinct, not suffixed | Vitest `no surface's accessible name nests inside another's`; spec T6 name counts | N4 `disclosureLabel` → `'Change provenance for this deck'` (a pure suffix) | **RED** both runners |
| second surface has its own scoping container | spec T6 container-scoped locators | N6 second surface reuses `mixed-release-warning` as its root test id | **RED** |
| one live region only, though the sentence appears twice | Vitest `announces on the conversation surface only…`; spec T6 `getByRole('status')` count | N5 `announce: true` on the collaboration surface | **RED** both runners |
| second surface carries the mandated warning + grouping | Vitest `gives AC5 second surface wholly distinct wording, not a suffix` | N7 render only the first group | **RED** both runners |
| literal row cardinality (Minor-1) | Vitest `keeps every row name distinct…` (`toHaveLength(3)`); spec T1 (`toHaveCount(3)`) | N2 narrow the fixture 3 groups → 1 | **RED** (4 unit tests) |
| — regression re-measurement after the surface refactor — | M1r, M2r, M3r, M4r, M6r, M10r, M11r, M20r, M27r, M31r, M32r, M33r re-aimed onto the new anchors | each as in the first round | **all 12 RED** |

**Blank count: 0**, unchanged. Every clause added this round has at least one measured RED.

### Mis-aimed attempt this round

**N1 and N1b first ANCHOR-FAILED.** My mutation anchor for the region root used six-space
indentation copied from the `loadFailed` branch, while the main return's root `<div>` is at
four. The script reported `anchor count 0` rather than silently patching nothing — but had the
anchor been merely *non-unique* instead of absent, a `replace(..., 1)` would have mutated the
wrong element and I would have measured a RED that proved something else. Re-aimed against the
exact source lines read back with `awk`, and only then trusted the result. This is the third
consecutive round on this task where the first aim was wrong; the anchor-count assertion in the
mutation harness is what caught it, and it is worth keeping in any future harness here.

## Concerns

1. **AC5 is now satisfied on both surfaces**, so concern 1 from the first round is closed. The
   design doc's finer split (C-26: conversation warns, collaboration groups) is honoured too —
   both surfaces group, and only the conversation one announces.
2. **Pre-existing failures, not mine, and confirmed by the review:**
   `slide-surface-fidelity.spec.ts:96`, `:122` and `:237` fail on this branch and that spec **is**
   in the CI matrix. The review proved they are pre-existing by neutralising all my frontend
   behaviours and observing identical failures. Carried to the whole-branch review.
3. **`setup-mocks.ts` blast radius is 18 specs, not the 4 I measured.** Of the 14 I had not
   measured, 13 fail: 10 across four specs already in `DELIBERATE_EXCLUSIONS` and excluded from
   CI, and 3 are the `slide-surface-fidelity` failures above. Risk to #264/#266 assessed low and
   structural. I did not re-measure that sweep this round; the figure is the reviewer's.
4. **Python baseline still not re-measured.** Nothing Python-visible changed in this round —
   `git diff --name-only HEAD` lists four frontend files only, and `.github/workflows/test.yml`
   is untouched since the first round — so the workflow guards were not re-run either.
5. **Row vocabulary is deliberately shared across surfaces**, so unscoped row locators are
   ambiguous once both disclosures are expanded. Asserted at 6 with a comment, but any future
   spec touching rows while the dialog is open must scope. Recorded rather than designed away,
   because per-surface row names would multiply the mandated vocabulary.
6. **Minors 3–5 remain open** as the coordinator recorded (cross-endpoint existence probing
   caught only at unit level; `has_legacy_evidence` typed but never read; the `aria-controls`
   assertion is self-consistency). Not addressed this round by instruction.

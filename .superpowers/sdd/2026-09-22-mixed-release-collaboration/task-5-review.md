# Task 5 independent review — accessible mixed-release warning UI and immutable Start-latest

**Reviewer:** independent (did not write this code).
**Range reviewed:** `a6bc952f39f786a47ee6d1a4bedb3a1799e6dc0a..2ca0825fcc9b47648d349421c1145526efe471e0`
— derived locally, one commit `2ca0825fc` ("feat: show mixed-release collaboration"), nine files,
1364 insertions / 1 deletion.
**Worktree:** `.worktrees/issue-262-plan`, branch `plan/conversation-collaboration-262`.
HEAD verified `2ca0825fcc9b47648d349421c1145526efe471e0`. Triple check clean before any edit
(empty `status --porcelain`, empty `diff HEAD`, empty `diff --cached`) and again after restore.

---

## VERDICT 1 — Spec compliance: **COMPLIANT on the brief, ONE GAP against the verbatim issue text**

Every clause of the brief's six bullets is implemented and has at least one measured RED, with two
qualifications recorded below. The gap is against issue #262 AC5's *surface count*, not against the
brief — the brief's Files block names `deck-history.tsx` but its bullets never mandate a second
warning placement. See the AC5 ruling.

### Clause by clause against the brief

| brief clause | verdict | evidence |
| --- | --- | --- |
| Extend types + `api.getCollaborationHistory` with Task 4 safe fields only | **COMPLIANT** | `api.ts:133-168` declares exactly the 4 group + 3 top-level fields; `api.ts:550-592` narrows the response key-by-key. I proved the compile-time guard has *independent* teeth (below). |
| Context gets collaboration state | **COMPLIANT** | `SessionContext.tsx:67-68`, exposed at `:253-254`. |
| resets in `createNewSession` | **COMPLIANT** | `SessionContext.tsx:91-92`. |
| loads on successful `switchSession` | **COMPLIANT** | `SessionContext.tsx:161-164` (start) + `:196-207` (landing, committed path only). |
| honours existing cancellation generation | **COMPLIANT** | `isCancelled?.()` at `:203`; no new generation counter introduced. |
| two-version warning | COMPLIANT | unit `warns when one deck carries…`; e2e T1. |
| no warning, same release | COMPLIANT | unit `shows no warning when every change is on the same release`; e2e T3. |
| explicit legacy wording, never "active" | COMPLIANT | `MixedReleaseWarning.tsx:28,50-52`; unit + e2e T3 both assert `not /active/i`. Ruling F6 honoured — the string is owned client-side and derived from `graph_version === null`. |
| visible fetch failure without badge erasure | COMPLIANT | `MixedReleaseWarning.tsx:112-122`; **I re-measured M28** — deleting `<GraphVersionStatus/>` REDs 4 of 5 e2e. |
| accessible `role=status` | COMPLIANT | `:115`, `:133`. Verified `GraphVersionStatus` carries no `role`, so `getByRole('status')` is unambiguous. |
| focusable disclosure | COMPLIANT | a real `<button>` with `aria-expanded`/`aria-controls` at `:137-146`. |
| labelled actor/release rows | COMPLIANT | `aria-label={groupRowLabel(group)}` at `:157`. |
| rows use returned `actor_label`/release, **not** the root badge | COMPLIANT | the component is given no `graphVersion` prop at all. **I re-measured the plan-mandated sabotage** (clause 6): forcing every row to the root badge's version REDs **3 unit + 3 e2e**. |
| no username / raw session id / UUID / principal in **DOM** | COMPLIANT | text leaks RED (measured). |
| …in the **accessibility tree** | **PARTIAL — see Important-1** | guarded for text and for descendant attributes, **blind to attributes on the warning's own root element**. Measured. |
| …in the **client type** | COMPLIANT | `never[]` guard; measured, and it fires alone under an *optional* added field. |
| …in the **request** | COMPLIANT | unit asserts `init === undefined` and an anchored URL. |
| 404: do not branch on detail | COMPLIANT | `api.ts:565-571` never reads the body on `!ok`. |
| 404: do not retry / probe existence | COMPLIANT | **my Sabotage B REDs it.** |
| one generic unavailable state | COMPLIANT | single `HISTORY_UNAVAILABLE_TEXT`; context stores a bare boolean, so no api-level message can reach the DOM at all. |
| Start-latest creates `graph_capable:true` + new id; cannot PATCH/copy/repin the original | COMPLIANT | e2e T2. **I re-measured M25** — a PATCH to the original REDs the wire-level `nonGetToOriginal === []`. |
| duplicate gets active R2, source stays R1 | COMPLIANT | e2e T5. |
| Playwright: opaque labels, legacy never "active", 404 generic | COMPLIANT | T1–T5, 5 passed at baseline. |
| gates per C-0 (`npm run test:unit`, `npm run typecheck`) | COMPLIANT | both re-run by me: 166 passed / 12 files; typecheck clean. |
| commit message `feat: show mixed-release collaboration` | COMPLIANT | verified. |
| C-19 binding follow-up answered explicitly | COMPLIANT | report answers **NO**; I verified the parallelism premise (below). |

---

## VERDICT 2 — Task quality: **APPROVED WITH FIXES**

The engineering is strong and unusually honest: two self-found zeros disclosed rather than
buried, one of them promoted to an epic-wide correction (C-24), immutability asserted at the wire
rather than from a `disabled` prop, a compile-time privacy guard that genuinely works, and a design
changed rather than a correctly-objecting test edited. Every claimed RED I re-measured reproduced
exactly.

Two things must be fixed before this is called done, neither of which is a shipped-behaviour defect:

1. **Important-1** — the accessibility-tree privacy assertion has a hole the brief explicitly
   mandates be closed.
2. **Important-2** — AC5 ships one of two surfaces, and the stated reason the second is impossible
   is **refuted by measurement**.

Disclosure earned credit for honesty on both; it did not earn immunity. Important-2 in particular
rests on a claim I tested and found false.

---

## YOUR NAMED JUDGEMENT CALL — the AC5 surface count

### 1. Is single-surface an AC5 gap? — **YES, but a narrow one, and the design doc constrains it**

Verbatim AC5 (fetched from the issue, not transcribed):
> "Conversation and collaboration surfaces warn when one shared deck has writers on multiple Graph Versions."

Two surfaces, plainly. One shipped. So on the issue text alone it is a gap.

But the design doc `docs/superpowers/specs/2026-09-21-agent-definition-workbench-design.md:254-261`
is much more specific than the AC, and it **splits the two obligations**:

> "…the **conversation surface** shows the actor's pinned version and **warns** participants when the
> shared deck has writers on more than one version. **History and audit views group this evidence by
> actor/release** rather than attributing a deck mutation to the root session's pin."

So in this system "collaboration surfaces" denotes the *sharing/collaboration* views —
`DeckContributorsManager` (the Share Deck dialog) and the history/audit views — and the design doc
assigns them **grouping**, not **warning**. §17.2 line 662 reinforces it in the singular:
"mixed-release contributor writes retain their distinct actor/release trace and show **the**
shared-deck version warning." And AC6 separately carries the grouping obligation
("History groups mixed-release evidence by actor and release").

**Ruling:** it is a gap against AC5's literal two-surface wording, and it should be closed, but it is
a *placement* gap of one small component — not a missing capability. The grouped evidence itself
(the `Change provenance` disclosure) is built, tested and correct; it is simply mounted in one place.
Nothing in the design doc is violated. I would not block the ticket on this; I would close it with
the scoped follow-on the controller proposed, before the whole-branch review.

### 2. Which surface closes it? — **the share dialog. Do NOT revisit C-19.**

The share dialog wins on three independent grounds:

- **It is the surface the design doc calls a collaboration surface.** `deck-history` is the deck
  *list*; the design doc's second clause about history views asks for *grouping*, which a
  per-row badge in a sidebar list does not provide.
- **It needs no backend change and no C-19 reopening.** The share dialog is already scoped to one
  deck (`sessionId`), so the existing single-deck endpoint answers it exactly. `deck-history` would
  need a new list-shaped summary — new backend surface, in slice 4A's otherwise-closed files, for a
  weaker result.
- **It is inside the author's own Files block.** This is the key correction to the author's
  reasoning: the second placement does **not** require touching `DeckContributorsManager.tsx` at
  all. The Share Deck dialog *body* is rendered by `AppLayout.tsx:1475-1499`, which the Files block
  explicitly permits. **I proved this by building it** — my probe edited only
  `AppLayout.tsx` and `MixedReleaseWarning.tsx`, both owned files. The "outside my Files block"
  objection is therefore mistaken.

On C-19: the controller's suspicion is well-founded — *a single grouped query over all listed roots
is not an N+1*, so bullet 3 would not have blocked a `list` summary, and C-19's premise as written is
too strong. **But that does not need resolving here**, because the right second surface never needed
the `list` summary. I recommend recording C-19's premise as imprecise (so it is not cited again as
settled reasoning) while leaving its *outcome* — the deferral — standing on its two surviving
grounds (`duplicate` is vacuous under C-5; no consumer exists).

### 3. Is the author's duplicate-name argument correct? — **NO. Measured and refuted.**

The claim: *"any suffix makes one name a substring of the other under Playwright's case-insensitive
substring matching"*, therefore no disambiguation is possible.

The premise about **coexistence is correct** — I verified it. The Share Deck dialog is an overlay
(`AppLayout.tsx:1477`, `fixed inset-0`) that leaves the chat panel mounted, so both placements are
visible simultaneously:

```
AC5PROBE dialog_open_and_both_placements_visible= true
```

The conclusion is **false**, on three counts, all measured:

**(a) A distinct wording — not a suffix — escapes substring matching entirely.** I built the second
placement with `disclosureLabel="Who changed this deck"` / `listLabel="Deck writers by release"`
and, with both placements live on screen at once, under Playwright's **default** case-insensitive
substring matching:

```
AC5PROBE change_provenance_count= 1 who_changed_count= 1
AC5PROBE dialog_disclosure_operated= true
AC5PROBE global_row_count= 1 scoped_row_count= 1
  1 passed (3.2s)
```

The author only ever considered *suffixes*. A different form of words was never tried.

**(b) `exact: true` rescues even a pure suffix.** Playwright's `getByRole` takes
`{ name, exact }`; `exact: true` is whole-string and case-sensitive:

```
AC5PROBE exact_true_count= 1
```

This is not exotic in this repo — **11 spec files already use `exact: true`**, including
`deck-prompts-ui.spec.ts:322` `getByRole('button', { name: 'Create Prompt', exact: true })`, which is
exactly the nested-name case.

**(c) Container-scoped locators resolve it too,** and the repo already does this, including against
this very overlay class: `slide-operations-ui.spec.ts:399`
`page.locator('.fixed').getByRole('button', { name: 'Delete' })`, and
`admin-page.spec.ts:247` `page.getByTestId('design-system-row-1').getByRole('button', { name: … })`.

An incidental finding from the same probe makes the point sharper: the **existing** app already has
colliding accessible names — `getByRole('button', { name: 'Share' })` resolves to 2 elements because
it also matches the deck-title button **"Shared deck"**. The codebase already lives with this class
of collision and already has the idioms to handle it.

The one obstacle that *is* real, and which the author did not name: the conversation's copy sits
behind the modal overlay, so its button is not *clickable* while the dialog is open (pointer events
intercepted). That is an overlay property, not a naming problem, and the fix is the ordinary one —
scope the dialog's assertions to the dialog container.

**Net:** the share dialog is **cheap** — roughly one extra `<MixedReleaseWarning>` element with
distinct wording plus two optional label props, entirely within owned files. The stated blocker does
not exist.

---

## FINDINGS

### Important-1 — the accessibility-tree privacy guard is blind to the warning's own root attributes
`frontend/src/components/Conversation/MixedReleaseWarning.test.tsx:262-286`
(and `frontend/tests/e2e/mixed-release-collaboration.spec.ts:184-188`)

The brief mandates asserting that no raw session id / UUID / principal reaches "DOM, **accessibility
tree**, client type or mock request". The unit guard reads
`region.textContent` and `region.innerHTML`; the e2e guard reads `textContent`. **`innerHTML` and
`textContent` both exclude the element's own attributes**, so an identifier placed in an attribute on
`<div data-testid="mixed-release-warning">` reaches the DOM *and* the accessibility tree while every
test stays green. This is my Sabotage A; see the measurement below.

No shipped code leaks anything here — the component is handed no identifier at all, and `api.ts`'s
narrowing plus the `never[]` type guard are the real defences and both have teeth. This is a
guard-strength defect, not a live leak, which is why it is Important rather than Critical.

Fix (one line each): assert `region.outerHTML` instead of `region.innerHTML` in the unit test, and
add an `outerHTML` (or accessible-name) assertion to e2e T1.

### Important-2 — AC5 ships one of two surfaces on a reason that measurement refutes
`frontend/src/components/Layout/AppLayout.tsx:1186-1199` (sole placement);
`frontend/src/components/Layout/deck-history.tsx:41-49` (the recorded reason)

Covered in full in the ruling above. The disclosure is honest and the comment in `deck-history.tsx`
is good practice, but the share-dialog rejection rests on a claim that is false as stated, and on a
Files-block objection that does not apply to the placement that actually works.

### Minor-1 — two residual fixture-sourced cardinality assertions (a weaker C-24 class)
`MixedReleaseWarning.test.tsx:236-237`, `mixed-release-collaboration.spec.ts:171`

```js
expect(names).toHaveLength(MIXED_HISTORY.groups.length);
expect(new Set(names).size).toBe(MIXED_HISTORY.groups.length);
```
Both sides come from the same fixture, so both shrink together and neither can fail. The comment
immediately above them — *"Cardinality joined to the fixture, so a narrowed fixture cannot silently
shrink this check to a vacuous pass"* — describes a property these two lines do not have.

What actually gives M30 its teeth is the **literal** on the next line,
`expect(new Set(MIXED_HISTORY.groups.map((g) => g.actor_label)).size).toBe(2)`, plus the literal row
names in the two sibling tests. I confirmed this by re-measuring M30: 3 tests RED, and the failure is
`AssertionError: expected 1 to be 2` — the literal, not the joined cardinality.

Risk: the misleading comment invites a future edit to delete the `toBe(2)` line as redundant, which
would make the silent-shrink hazard real. Fix the comment, or hard-code the expected count.

### Minor-2 — five constants and two functions are exported with no importer
`frontend/src/components/Conversation/MixedReleaseWarning.tsx:26-68`

After the C-24 fix, `MIXED_RELEASE_WARNING_TEXT`, `LEGACY_RELEASE_LABEL`, `DISCLOSURE_LABEL`,
`PROVENANCE_LIST_LABEL`, `HISTORY_UNAVAILABLE_TEXT`, `releaseLabel` and `groupRowLabel` have **zero
importers repo-wide** (swept `src/` and `tests/`). They are the residue of the pre-C-24 design and
are now an attractive nuisance: the cheapest way for a future test to "simplify" is to import them
again, reintroducing exactly what C-24 forbids. Un-export them, or add a one-line comment forbidding
test imports. (A second placement, per Important-2, would give two of them a legitimate importer.)

### Minor-3 — cross-endpoint existence probing is caught only at unit level
`mixed-release-collaboration.spec.ts:301` asserts `historyCalls === ['GET']`, which records the
*history* route only. My Sabotage B probed a **different** endpoint and e2e T4 stayed green; only the
unit test's `toHaveBeenCalledTimes(1)` caught it. Materially mitigated by architecture: the context
stores a bare boolean, so no api-level message can reach the DOM regardless. Worth knowing that the
unit call-count is the single guard for this class.

### Minor-4 — `has_legacy_evidence` is narrowed and typed but never read
`api.ts:166` / `MixedReleaseWarning.tsx`. Legacy is rendered purely from `graph_version === null`.
Equivalent under the shipped backend contract (the flag is true whenever a null-version group
exists), so not a defect — but if the backend ever reported legacy evidence *without* a
corresponding group, the UI would silently show nothing.

### Minor-5 — the `aria-controls` assertion is self-consistency, not requirement
`MixedReleaseWarning.test.tsx:184-187` takes its expected value from the rendered list's own `id`.
Since the component derives both from one `useId()`, it can only fail if the wiring is actively
broken. Legitimate as a wiring check; it is not evidence about the requirement.

### Pre-existing (NOT this commit) — 3 CI-visible e2e failures in `slide-surface-fidelity.spec.ts`
`:96`, `:122`, `:237`. This spec **is** in the e2e matrix (`.github/workflows/test.yml:736`), so these
would fail CI. I proved they are not Task 5's: with all three Task 5 frontend behaviours neutralized
(setup-mocks route, SessionContext load, AppLayout render) the identical 7 failures reproduce. Raised
for the whole-branch review, not against this task.

---

## SWEEPS

### Other vacuous mocks
Two `mockResolvedValue(new Response(...))` instances remain in the diff —
`MixedReleaseWarning.test.tsx:312` (`narrows the response…`) and `:352` (`sends a bare authenticated
GET…`). **Neither is currently vacuous**: each drives exactly one call, and neither reads a second
call's body. `narrows…` also pins `toHaveBeenCalledTimes(1)`, and under a retry the consumed body
would throw rather than silently fall back. The idiom is latent, not live. The re-aimed test at
`:378-410` correctly uses `mockImplementation` with a fresh `Response` per call and records why in a
comment.

Repo-wide sweep: the same idiom appears at `GraphVersionStatus.test.tsx:38,62,82` (pre-existing,
#261). All three are single-call and assert on the *request*, not a response body — not vacuous.

### Other implementation-sourced assertions (C-24 class)
**The C-24 fix is real and complete for constants.** `MixedReleaseWarning.test.tsx` imports only
`MixedReleaseWarning` and its props type; the four mandated strings are local literals at `:26-29`
with the reasoning at `:16-25`. The e2e spec uses literals throughout (`MIXED_ROW_NAMES:35-39`) and
keeps them separate from the fixture, so the two cross-check. Grep confirms no importer of any
component constant anywhere.

Residual instances, all weaker (fixture-sourced, not implementation-sourced) and all mitigated:
Minor-1 above, plus Minor-5. Nothing else in the diff sources its expected side from the
implementation.

---

## SABOTAGE RESULTS

### Sabotage A — leak a field the privacy contract forbids
**Aim:** the raw root session UUID into the accessibility tree, at the weakest point — an attribute
on the warning's **own root element**, which `innerHTML`/`textContent` cannot see. Threaded a
`sessionId` prop from `AppLayout.tsx` and rendered
`aria-label={`Collaboration on deck ${sessionId}`}` on `<div data-testid="mixed-release-warning">`.

**Result: GREEN — nothing RED. This is Important-1.**
```
=== UNIT ===
 Test Files  1 passed (1)
      Tests  20 passed (20)
=== TYPECHECK ===
> tsc -b            (clean)
=== E2E ===
  5 passed (6.3s)
```

**Marker proven on the executed path** (a zero is otherwise evidence of nothing) — dedicated probe
against the running app:
```
PROBE outerHTML_has_uuid=   true
PROBE innerHTML_has_uuid=   false
PROBE textContent_has_uuid= false
PROBE aria-label= Collaboration on deck 11111111-1111-4111-8111-111111111111
PROBE accName=    Collaboration on deck 11111111-1111-4111-8111-111111111111
```
The UUID is in the DOM and is the container's accessible name; both guards are structurally blind.

**Re-aimed to establish the boundary** — same UUID, same component, rendered as visible text:
**RED**, as it should be:
```
Error: expect(received).not.toMatch(expected)
Expected pattern: not /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i
Received string:  "Deck 11111111-1111-4111-8111-111111111111This shared deck has changes from multiple Graph Versions.Change provenance…"
  at tests/e2e/mixed-release-collaboration.spec.ts:186:26
  1 failed  4 passed
```
So the guard covers rendered text and descendant markup; it does not cover the root element's own
attributes.

### Sabotage B — make a 404 distinguishable
**Aim:** turn the byte-identical 404 into an existence oracle by **probing a second endpoint** that
does distinguish, then branching the message. In `api.ts`, on `status === 404`, fetch
`/api/sessions/{id}` and throw either *"This deck exists but its collaboration history is
restricted"* or *"No such deck"*. Deliberately distinct from the author's M14 (reading `detail`) and
M15 (retrying the same endpoint).

**Result: RED.**
```
 × api.getCollaborationHistory > treats every denied response as one generic failure and never retries
   → expected "fetch" to be called 1 times, but got 2 times
⎯⎯ Failed Tests 1 ⎯⎯
 FAIL src/components/Conversation/MixedReleaseWarning.test.tsx > api.getCollaborationHistory > treats every denied response as one generic failure and never retries
AssertionError: expected "fetch" to be called 1 times, but got 2 times
 Test Files  1 failed (1)
      Tests  1 failed | 19 passed (20)
```
**GREEN after restore:** `Tests 20 passed (20)`; e2e `5 passed`.

The guard has two independent teeth (the call count, and the single-message set). Coverage note in
Minor-3: e2e T4 stayed green under this mutation, so the unit call-count is the sole guard for
cross-endpoint probing.

---

## RE-MEASUREMENT OF THE AUTHOR'S CLAIMED REDs

All four load-bearing claims reproduced exactly.

| claim | verdict | measured |
| --- | --- | --- |
| **M28** delete `<GraphVersionStatus/>` REDs 4 of 5 e2e | **CONFIRMED** | `4 failed / 1 passed`. The survivor is T3 (legacy row), which makes no badge assertion — correct. Failure: `getByTestId('graph-version-status')` … `element(s) not found`. |
| **M22** add `actor_session_id` to the group type REDs `npm run typecheck` | **CONFIRMED, and stronger than claimed** | REDs on the guard's own line: `MixedReleaseWarning.test.tsx(437,11): error TS2322: Type '"actor_session_id"[]' is not assignable to type 'never[]'`. I then probed the harder case — an **optional** `actor_session_id?: string`, which leaves the fixture and the narrowing legal — and the `never[]` guard fires **alone**. It is a genuine compile-time privacy guard, not a side effect of the fixture. |
| **M30** narrow the shared fixture 3→1 groups REDs 3 tests | **CONFIRMED** | `Tests 3 failed | 17 passed`, `AssertionError: expected 1 to be 2`. Silent-shrink hazard closed — but by the literal, not by the "joined cardinality" the comment credits (Minor-1). |
| **M25** a PATCH to the original inside `handleStartLatest` REDs a **wire-level** assertion | **CONFIRMED** | REDs `expect(nonGetToOriginal).toEqual([])` at `:240` with `+ "PATCH http://127.0.0.1:8000/api/sessions/11111111-…"`. Immutability is asserted from recorded requests, not a `disabled` prop — hazard 2 properly honoured. |
| plan-mandated sabotage (clause 6): rows borrow the root badge's version | **CONFIRMED** | 3 unit RED + 3 e2e RED. |

**My own mis-aimed attempt, reported as required.** My first M25 used
`api.getCurrentSessionId()` *after* `api.createSession(...)`. `createSession` overwrites that module
global (`api.ts:492`, `currentSessionId = session.session_id`), so my PATCH went to the **new**
session and `recordNonGetTo(page, SESSION_A)` never saw it — **GREEN, a false zero from my own aim**.
Re-aimed to capture the original id *before* `createSession`; it then RED immediately. I also had a
vacuous first pass on the AC5 probe (asserting counts without proving the dialog had opened) and
rebuilt it with a hard `dialog_open_and_both_placements_visible` gate before any count.

---

## THE THREE CONTROLLER RULINGS — verified

1. **C-19 closed as NO — the parallelism claim is TRUE.** `SessionContext.tsx:161-164` *initiates*
   `api.getCollaborationHistory(newSessionId)` before `await api.getSlides(newSessionId)` at `:169`,
   so both are in flight concurrently on the `has_slide_deck: true` path: zero extra serial
   round-trips. The author in fact **undersold** it — because the landing is never awaited before the
   commit (`void collaborationLoad.then(...)` at `:196`), it adds zero latency to the commit on
   *every* path, including the deckless one, not just the ordinary restore. C-19's closure is sound.
   Separately, its *premise* is too strong (see the AC5 ruling); its outcome survives on other
   grounds.
2. **The design change is accepted and correctly shaped.** The landing is guarded by exactly the two
   stated pre-existing mechanisms — `isCancelled?.()` at `:203` and
   `api.getCurrentSessionId() !== newSessionId` at `:204` — and introduces **no** new reducer,
   request-ID counter or pending-operation gate (verified by reading the whole `switchSession`). The
   commit batch also clears the outgoing session's evidence (`:191-192`), so rows cannot linger
   across a switch. The `.catch` is attached at creation (`:164`), not at the consumer, so an
   abandoned restore cannot raise an unhandled rejection — the comment is accurate and I verified the
   placement. Concern 4's residual same-id race is real exactly as disclosed and is harmless (same
   deck, same authorization).
3. **`GraphVersionStatus.tsx` was not modified** — confirmed, 0 lines in the range diff. Sibling
   placement makes non-erasure structural, and M28's 4-of-5 RED gives it teeth. It also carries no
   `role`, which is why `getByRole('status')` resolves unambiguously to the new component.

---

## `setup-mocks.ts` ASSESSMENT

**Justification verified.** The `/api/sessions**` catch-all's final `else` really does
`route.fulfill({ status: 404 })`, so without the new default every session-restoring spec would have
rendered the generic unavailable state. **LIFO verified empirically**, not just asserted: the new
spec's own routes are registered after `setupMocks` and win — T4 receives its 404 and T1 its
populated body, which is only possible if the later registration takes precedence.

**Blast radius — the author's 44 is reproducible but the measurement was narrower than the exposure.**
I reproduced `44 passed` across the four specs named (`session-loading`, `chat-ui`,
`viewer-readonly`, `conversation-graph-version`). But **18 specs call `setupMocks` and restore a
session**, so 14 were unmeasured. I ran all 14.

- 8 specs / 67 passed + 6 failed, and 6 specs / 55 passed + 7 failed → **13 failures**, none caused
  by this commit:
  - **10** are in `share-link`, `routing`, `navigation`, `genie-detail-panel` — all four are in
    `tests/unit/test_e2e_matrix_covers_specs.py`'s `DELIBERATE_EXCLUSIONS` as **quarantined specs
    written against an older app shell**, deliberately excluded from CI. Known, documented, unrelated.
  - **3** are `slide-surface-fidelity.spec.ts:96/:122/:237`, which **is** in the CI matrix — raised
    above as pre-existing.
- Isolation proof, twice: removing only the new collaboration-history route reproduced the identical
  3 routing and 3 navigation/genie failures; neutralizing **all three** Task 5 frontend behaviours
  reproduced the identical 7 share-link + slide-surface-fidelity failures.

**Risk to #264/#266 is low and structural.** The new route's regex
`/\/api\/sessions\/[^/]+\/collaboration-history$/` can match nothing but collaboration-history URLs,
so it cannot shadow any other endpoint; and any spec needing a different body registers its own route
after `setupMocks` and wins by LIFO. `agent-definition-workbench.spec.ts` does not restore a session
and is not exposed. The residual fragility is the undocumented-by-Playwright LIFO ordering itself,
which the author *did* document in place.

---

## PYTHON RESIDUAL

**CONFIRMED UNCHANGED — the author's reasoning holds, and I measured it rather than accepting it.**

The author did not re-measure, reasoning that the only Python-visible change is one `e2e-tests`
matrix line in `.github/workflows/test.yml`. I ran the full suite at this commit:

```
6 failed, 5325 passed, 110 skipped, 135 warnings in 297.69s (0:04:57)
```

This is **byte-for-byte slice 4A's residual** (6 failed / 5325 passed / 110 skipped). The node set is
also identical, and I enumerate it in full since no prior artifact did:

```
FAILED tests/unit/test_deploy_autoscaling.py::TestGetOrCreateLakebase::test_returns_autoscaling_when_available
FAILED tests/unit/test_deploy_autoscaling.py::TestGetOrCreateLakebase::test_falls_back_when_autoscaling_creation_fails
FAILED tests/unit/test_style_exclusivity_chokepoint.py::TestModelDumpIsNotTheChokepoint::test_create_session_normalizes_a_raw_both_set_dict
FAILED tests/unit/test_style_exclusivity_chokepoint.py::TestModelDumpIsNotTheChokepoint::test_create_session_still_stores_a_single_authority_config_unchanged
FAILED tests/unit/test_style_exclusivity_chokepoint.py::TestModelDumpIsNotTheChokepoint::test_create_session_still_accepts_no_agent_config
FAILED tests/unit/test_style_exclusivity_persistence_boundary.py::TestEveryWriterIsNormalized::test_session_manager_create_session
```

This **corroborates correction C-21's re-classification**: `test_style_exclusivity_chokepoint.py` has
**three** nodes (the diverged-test-double class) and
`test_style_exclusivity_persistence_boundary.py` exactly **one** (the C-6/C-10 `no active Graph
Release` fixture class) — the split C-21 corrected the ledger to, not the inverted one. C-21 accounted
for four of the six; the remaining two are `test_deploy_autoscaling.py`, which belongs to neither
class. Useful for sizing the whole-branch sweep: it is **three** double-divergence sites, **one**
fixture site, **two** unrelated.

I also re-ran the five workflow-parsing modules the author used in place of the full suite:
`57 passed` — reproduced exactly. The matrix entry itself is correctly placed
(`.github/workflows/test.yml:726`, alphabetically between `inline-svg-records-export` and
`presentation-mode`, inside the `e2e-tests` job matrix), and
`tests/unit/test_e2e_matrix_covers_specs.py` is a real guard: it requires every
`frontend/tests/e2e/*.spec.ts` to be in the matrix or in `DELIBERATE_EXCLUSIONS` with a non-empty
reason, which is what gives the author's M23 (removing the matrix entry) its teeth.

Note on measurement conditions: C-22 honoured — no migration, alteration or drop of
`ai_slide_generator`, and it was not read as evidence. Incidental `RequestLog` inserts from
`TestClient` occurred, as C-22 accepts.

---

## CANNOT VERIFY

- **The Python residual's *cause* split** (C-21's classification) was not re-derived; I compared the
  failure set, not each traceback's root cause.
- **Whether the 13 pre-existing e2e failures predate the whole #262 branch.** I proved they are not
  caused by *this commit* (by neutralization at this HEAD); I did not check out an earlier commit.
- **Cross-lane interference.** I held the frontend lane exclusively and confirmed zero listeners on
  port 3000 before every Playwright invocation (all `--project=chromium --workers=1`, one at a time).
  I could not rule out another agent's Python activity during my pytest window; only my own pytest
  process was visible while I checked.
- **Real-browser assistive-technology behaviour.** The `role="status"` live-region *announcement* is
  asserted structurally (attribute present), not by a screen reader.
- **Timestamp rendering** (author's concern 5) is locale-dependent by design and no test asserts it;
  I did not test across locales.

---

## HYGIENE

- **No commits, no push, no PR, no merge, no subagents.** All writes inside this worktree only, with
  one exception I should flag: two scratch capture files went to `/tmp` (`/tmp/atrun.txt`) rather
  than the worktree. No repo file was affected.
- Every mutation restored from `cp` backups (`.review-backups/`), never
  `git checkout <commit> -- <paths>`. Drift enumerated with `git diff --name-only HEAD` after each
  restore, and each restored file re-verified by md5 against its pre-mutation hash.
- Two temporary probe specs (`zz-review-probe.spec.ts`, `zz-ac5-probe.spec.ts`) were created and
  deleted.
- No `npm install` / `npm ci` / `npx playwright install`; no `pip install` / `uv` / `.venv`.
- Per C-22: no migration, alteration or drop of `ai_slide_generator`, and it was not read as evidence.
- **Final state:** `git status --porcelain` empty, `git diff HEAD` empty, `git diff --cached` empty,
  HEAD still `2ca0825fcc9b47648d349421c1145526efe471e0`.

---
---

# Fix round 1 — scoped re-review

**Scope:** the four items I raised, plus new breakage in the fix diff only. The original task was
not re-reviewed.

**Range verified myself:** `c5594a33be7d57d223a8c492ab214cc49c7d13df..53126c8697977eb998819d65cf5eb06f2a85df18`
— four frontend files, 299 insertions / 46 deletions. `53126c869`'s parent really is `c5594a33b`;
all of `c5594a33b`, `53126c869` and round 1's `2ca0825fc` are ancestors of HEAD
`a99e7131a81987cd43c4e17c77a699c821141b88`. `c5594a33b` touches only two `.superpowers/` docs and
`a99e7131a` only eight, so **the fix commit is the sole frontend change since round 1** — confirmed by
`git diff --name-only 2ca0825fc..HEAD -- frontend/ .github/` returning exactly the four files.

**Baselines reproduced:** `npm run test:unit` **169 passed / 12 files** (was 166), `npm run typecheck`
clean, the new spec **6 passed** (was 5), adjacent set **50 passed**. All figures as reported.

**Per C-27, every mutation below asserted its anchor count and refused to patch on anything but the
expected number.** All twelve anchor assertions held at 1; no anchor ambiguity encountered.

## BOTTOM LINE

All four items **ADDRESSED**. Three of my corrections were adopted, one was sharpened beyond what I
asked, and **the fix introduces no behavioural breakage.** It does introduce three test-hygiene
Minors, all new and all measured — none blocking. The `role="status"` asymmetry is **CONFIRMED** as a
correct reading of C-26.

---

## ITEM 1 — Important-1, the accessibility-tree privacy guard: **ADDRESSED**

I re-ran my own round-1 sabotage against the fixed guard, which is the cleanest verdict available.

**Sabotage A3 — my exact round-1 leak shape** (`aria-label` on the non-failure root `<div>`), but with
a **fabricated UUID distinct from the test's `LEAKED_UUID` needle**, so the guard had to catch by
pattern rather than by literal:

```
--- UNIT ---
   × MixedReleaseWarning > lets no server-added field reach the DOM or the accessibility tree
     → expected '<div data-testid="mixed-release-warni…' not to match /[0-9a-f]{8}-[0-9a-f]{4}-…/i
      Tests  1 failed | 22 passed (23)

--- E2E ---
  ✘  1 … warns about two releases on one deck and discloses opaque provenance rows
  ✘  6 … both AC5 surfaces stay independently addressable with the Share dialog open
  2 failed / 4 passed
```
**1 Vitest + 2 Playwright RED** — the same leak measured GREEN across all 25 tests in round 1. The
`outerHTML` switch is the tooth, and it catches by pattern.

**The added accessibility-tree oracle is not decoration — it has INDEPENDENT teeth.** I probed the one
case `outerHTML` structurally cannot see: an `aria-labelledby` on the region root pointing at text
that lives **outside** the region, so the region's own markup never contains the UUID while its
computed accessible name *is* the UUID.

```
   × MixedReleaseWarning > lets no server-added field reach the DOM or the accessibility tree
     → expect(element).not.toBeInTheDocument()
```
That is `queryByLabelText(UUID_PATTERN)` firing, not the `outerHTML` assertion. This is genuinely
better than what I asked for: I asked for `outerHTML`; the author added a real a11y-tree oracle that
covers a leak class `outerHTML` misses.

**Residual → New-Minor-A.** The guard was upgraded on the *non-failure* branch only. The `loadFailed`
branch has its own separate root `<div>`, and the unit test for it
(`keeps the unavailable state generic`, `MixedReleaseWarning.test.tsx:165-167`) still reads
`region.innerHTML` and carries no UUID-pattern assertion at all. Measured: leaking a distinct UUID
into that branch's root attribute is **GREEN on all 23 unit tests** and RED only in e2e T4 (which
*was* upgraded to `outerHTML`).

```
--- UNIT (loadFailed branch root leak) ---
      Tests  23 passed (23)          ← unit blind
--- E2E ---
  ✘  4 … a denied history request becomes one generic unavailable state that discloses nothing
  1 failed / 5 passed                 ← e2e catches it
```
Coverage overall is intact, so this is not a reopening of Important-1. But it is the same
branch-asymmetry that made round 1's hole possible, in the faster feedback loop. Fix: change
`:167` to `outerHTML` and add the `UUID_PATTERN` / `queryByLabelText` pair to that test.

## ITEM 2 — Important-2, the second surface: **ADDRESSED**

- **Placed in the Share Deck dialog body**, `AppLayout.tsx:1490-1504`, rendered as the **first child**
  of the dialog body ahead of `DeckContributorsManager` — so it is the first thing in the dialog's
  reading order.
- **`DeckContributorsManager.tsx` untouched — 0 lines in the fix range.** My file-ownership
  correction is confirmed by construction: the whole second surface cost `AppLayout.tsx` +
  `MixedReleaseWarning.tsx`, both in the author's Files block, exactly as I measured in round 1.
- **Wholly distinct wording, not suffixes:** conversation `Change provenance` / `Contributor releases`;
  collaboration `Who changed this deck` / `Release history by contributor`.
- **Coexistence is asserted, not hidden.** T6 pins the ambiguity it creates —
  `mixed-release-warning-text` at 2, `getByText(WARNING_TEXT)` at 2, `mixed-release-disclosure` at 2,
  rows at 6 with both expanded — while every accessible *name* still resolves to exactly 1 under
  Playwright's default substring matching.
- **The obstacle I identified and the author had not named is now asserted directly**, via
  `click({ trial: true, timeout: 2000 })` on the conversation copy failing behind the overlay, with
  its expanded state proven to survive (reads unaffected). Dialog interactions go through a
  container-scoped locator.
- It also hit the `Shared deck` / `Share` collision I mentioned only in passing and used
  `exact: true`, with a comment explaining why.
- Good incidental design: `surface` is a **required** prop (`MixedReleaseWarning.tsx:137`), so a third
  placement cannot silently inherit a default vocabulary — typecheck forces the choice.

**C-26's named risk — does the shared row/testid vocabulary make an existing conversation-surface
assertion ambiguous while the dialog is open? Verified: NO, but only by circumstance.** I audited
every unscoped shared-testid locator in the spec:

- In T1–T5 each sits in a test that never opens the dialog, so each resolves to 1.
- In T6 every unscoped shared-testid locator is a deliberate **count** assertion (2, 2, 6), never a
  matcher that would violate strict mode.

**New-Minor-B.** The *inner* testids are not surface-scoped — both surfaces render
`mixed-release-warning-text`, `mixed-release-disclosure`, `mixed-release-provenance`,
`mixed-release-row` and `mixed-release-unavailable`; only the two **root** testids
(`mixed-release-warning` / `shared-deck-provenance`) disambiguate. T2, T3 and T5 use
`page.getByTestId('mixed-release-warning-text')` unscoped with `toBeVisible()` / `toHaveCount(0)`,
which are safe *only* because the dialog is shut there. I proved the hazard is real by swapping T6's
deliberate count for the same non-count matcher those tests use:

```
Error: strict mode violation: getByTestId('mixed-release-warning-text') resolved to 2 elements
```
The author documented the shared **row vocabulary** decision in a comment, but not that the inner
testids are shared across surfaces. Fix: surface-prefix the inner testids, or state the coupling at
the component so a future dialog-open test scopes by container.

## ITEM 3 — Minor-1, fixture-sourced cardinality: **ADDRESSED**

Both self-referential counts are now literal `3`, and the "cannot silently shrink" comment has moved
onto the literal `toBe(2)` that actually earns it. Verified the literal is now the tooth by re-running
the M30-equivalent (fixture 3→1):

```
   × keeps every row name distinct under substring matching
     → expected [ Array(1) ] to have a length of 3 but got 1     ← the literal firing
   × gives AC5 second surface wholly distinct wording, not a suffix
     → expected [ <li …(2)>…(2)</li> ] to have a length of 3 but got 1
      Tests  4 failed | 19 passed (23)
```
Four tests RED, up from three, and the failure is now the literal rather than the incidental
`toBe(2)`. The e2e equivalent at spec `:180` was given the same treatment. The new nesting test
applies the lesson up front with a literal `toHaveLength(4)`.

## ITEM 4 — Minor-2, dead exports, and C-24 at `SURFACE_ACCESSIBLE_NAMES`: **ADDRESSED**

Five constants and two functions un-exported (`MIXED_RELEASE_WARNING_TEXT`, `LEGACY_RELEASE_LABEL`,
`DISCLOSURE_LABEL`, `PROVENANCE_LIST_LABEL`, `HISTORY_UNAVAILABLE_TEXT`, `releaseLabel`,
`groupRowLabel`). Three exports remain — `MixedReleaseWarning`, `MixedReleaseWarningProps` and
`SURFACE_ACCESSIBLE_NAMES` — and typecheck stays clean, so the first two have real consumers.

**C-24 HOLDS at `SURFACE_ACCESSIBLE_NAMES`. Verified, not accepted.** The question is whether a guard
reading a set *from the implementation* can still catch a wording defect. All four names are pinned by
**local literals** in the test file: the two disclosure labels via `toContain(DISCLOSURE_LABEL)` /
`toContain(COLLABORATION_DISCLOSURE_LABEL)`, and — the part worth checking, since the coordinator only
mentioned the disclosure labels — **both list labels too**, via the literal
`getByRole('list', { name: PROVENANCE_LIST_LABEL })` and
`getByRole('list', { name: COLLABORATION_LIST_LABEL })` assertions, whose constants are local literals
at `:29` and `:33`. Nothing in the file takes an expected wording from the component.

Measured with a nesting rename (`collaboration.listLabel` → `'Contributor releases by date'`, which
contains `'Contributor releases'`) — **two independent teeth**:

```
   × gives AC5 second surface wholly distinct wording, not a suffix
     → Unable to find an accessible element with the role "list" and name "Release history by contributor"
   × no surface's accessible name nests inside another's
     → expected 'contributor releases by date' not to contain 'contributor releases'
      Tests  2 failed | 21 passed (23)
```

**New-Minor-C — the one residual, and it is exactly the creep the coordinator suspected.** The
structural guard's *subject* comes from the implementation, so it has a vacuity mode: if
`SURFACE_ACCESSIBLE_NAMES` ever stops deriving from `SURFACE_VOCABULARY`, the guard silently stops
covering the real vocabulary. Measured by decoupling the export to a hardcoded copy of the current
four names **while leaving the nesting rename in place**:

```
   × gives AC5 second surface wholly distinct wording, not a suffix      ← only the literal catches it
      Tests  1 failed | 22 passed (23)
```
The nesting guard went **green on a set that no longer reflected the real vocabulary, while the real
vocabulary did nest.** Defence in depth held — the literal test still caught the underlying defect —
so C-24 is not breached and this is a Minor. The robust fix removes the export entirely: render both
surfaces in the test and read the accessible names off the DOM, which makes the guard cover what is
actually rendered and retires Minor-2's last export.

---

## RULING — the `role="status"` asymmetry against my own C-26: **CONFIRMED**

N5 reproduces as claimed: adding `announce: true` to the collaboration surface REDs both runners —
1 Vitest (`announces on the conversation surface only` → `expect(element).not.toBeInTheDocument()`)
and 1 Playwright (T6 line 430, `getByRole('status')` expected 1).

**The implementation honours C-26 and does not narrow AC5 further.** The reasoning:

1. **AC5 requires the warning as *content*, and both surfaces deliver it.** `role="status"` is an
   *announcement mechanism*, not the warning. The identical mandated sentence is rendered on both
   surfaces and pinned at count 2 in T6. Nothing about AC5's "warn" is withheld from the second
   surface.
2. **The asymmetry is correct on independent a11y grounds, not just convenience.** A live region
   exists to announce content that *changes after render*. The conversation warning genuinely can
   arrive late — round 1 established the history load lands off the critical path
   (`void collaborationLoad.then(...)`), so `role="status"` is right there. The dialog copy is static
   at mount, deliberately opened by the user, and already present in context when it renders. Two
   simultaneous identical live regions announcing one sentence twice is a real defect, not a cosmetic
   one, and the code comment correctly leads with that reason and treats the
   `getByRole('status')`-stays-1 benefit as secondary.
3. **It matches the design doc's split precisely.** `2026-09-21-agent-definition-workbench-design.md:254-261`
   gives *grouping* to collaboration/history views and *warning* to the conversation surface; §17.2:662
   says "**the** shared-deck version warning", singular. Both surfaces carrying the grouped evidence
   and one announcing is that split implemented literally — which is the reading C-26 set out.

**Context worth recording, not a defect in this fix:** how much the second surface helps an
assistive-technology user is bounded by its host, not by `announce: false`. The Share Deck dialog is a
plain `<div className="fixed inset-0 …">` with an `<h2>` and no `role="dialog"`, no `aria-modal` and no
focus trap (`AppLayout.tsx:1476-1483`) — pre-existing, outside this fix's diff, and a whole-branch
a11y item. The new surface is at least placed first in the dialog's reading order, which is the right
call given that container.

---

## SPOT-CHECKS OF THE RE-AIMED FIRST-ROUND MUTATIONS

Given three consecutive rounds opening with a wrong aim, I re-measured two of the twelve myself —
deliberately the two whose anchors the refactor **moved**, since that is where a re-aim fails.

**M6 re-aimed** (`role="status"` is no longer a literal attribute but a conditional spread, and two
such spreads now exist — warning `<p>` and unavailable `<p>`; I targeted the warning one, anchor count
asserted at 1):
```
   × warns when one deck carries changes from two persisted Graph Versions
     → Unable to find an accessible element with the role "status"
   × announces on the conversation surface only, so one sentence is not announced twice
     → Unable to find an accessible element with the role "status"
      Tests  2 failed | 21 passed (23)
```

**M32 re-aimed** (the mandated disclosure wording moved from a module constant into
`SURFACE_VOCABULARY`):
```
⎯⎯ Failed Tests 7 ⎯⎯   (shows no warning…, calls a null graph release Legacy…,
   discloses provenance…, labels each row from its OWN returned release…,
   keeps every row name distinct…, and two more)
```
Both land on live anchors and RED. Combined with N1/N1b, N5, the M30-equivalent and the two C-24
mutations I ran, that is **eight** independently measured REDs plus **two** deliberate GREENs in this
round, all with asserted anchor counts. I did not hit a single anchor ambiguity, and I have no reason
to doubt the remaining ten re-aims.

On **C-27 itself**: the rule is right and the counterfactual is the real lesson —
`replace(..., 1)` on a merely *non-unique* anchor mutates the first match silently and yields a RED
that proves something else. An absent anchor is the benign failure; the ambiguous one is the dangerous
one. I applied C-27 throughout and it cost nothing.

---

## NEW BREAKAGE IN THE FIX DIFF

**None behavioural.** Unit 169/169, typecheck clean, new spec 6/6, adjacent set 50/50.

Blast radius of the second instance is structurally near-zero, which is worth stating because it is
not obvious: the collaboration surface renders only inside `showShareDialog && sessionId`, and
`MixedReleaseWarning` returns `null` when `history.groups.length === 0`. `setup-mocks.ts` defaults
collaboration-history to **200 with empty groups**, so in every other spec the dialog gets nothing at
all. Only `mixed-release-collaboration.spec.ts` references the mixed-release testids, and the only
other spec that opens the Share dialog is `share-link.spec.ts`, which is quarantined in
`DELIBERATE_EXCLUSIONS` and was already failing at a precondition in round 1. `test_e2e_matrix_covers_specs.py`
passes (4 passed) — no spec file was added, so the matrix guard is unaffected.

Three new Minors, all test-hygiene, all measured above: **New-Minor-A** (loadFailed branch root
unguarded at unit level), **New-Minor-B** (inner testids not surface-scoped; strict-mode violation
proven), **New-Minor-C** (structural nesting guard has a vacuity mode).

## PYTHON BASELINE — reasoning confirmed, not re-run

The claim holds and I verified it rather than accepting it. Everything changed since round 1's
reviewed commit is four frontend files plus eight `.superpowers/` docs; filtering that range for
`*.py`, `.github/`, `pyproject`, `conftest`, `requirements`, `*.yml`, `*.yaml` returns **nothing**, and
`.github/workflows/test.yml` is byte-identical to round 1 (`git diff --stat 2ca0825fc..HEAD --
.github/workflows/test.yml` empty). There is no Python-visible change, so the 6 / 5325 / 110 residual
I measured in round 1 stands unchanged. Re-running 5325 tests would have been waste.

## DEFERRED — open by instruction, not re-examined

- **Minor-3** (cross-endpoint existence probing caught only at unit level).
- **Minor-4** (`has_legacy_evidence` narrowed and typed but never read).
- **Minor-5** (the `aria-controls` assertion is self-consistency, not requirement).
- Carried to the whole-branch review: the three pre-existing `slide-surface-fidelity` CI failures, the
  18-spec `setup-mocks.ts` blast radius (the author reused my figure without re-measuring, which is
  correct — nothing in this diff touches `setup-mocks.ts`), and the Share dialog's missing
  `role="dialog"` / `aria-modal` / focus trap.

## HYGIENE

Twelve mutations applied and restored from `cp` backups (`.review2-backups/`), never
`git checkout <commit> -- <paths>`; every one asserted its anchor count per C-27. All four files
re-verified by md5 against their pre-mutation hashes after each restore. Drift enumerated with
`git diff --name-only HEAD`. No commits, no push, no PR, no merge, no subagents. All scratch kept
in-tree this round. Port 3000 confirmed at zero listeners before every Playwright invocation, all
`--project=chromium --workers=1`, one at a time. No installs; no migration, alteration or drop of
`ai_slide_generator`. HEAD `a99e7131a81987cd43c4e17c77a699c821141b88`.

**Final state, stated precisely:** all four reviewed source files are restored bit-for-bit (md5
verified against their pre-mutation hashes), `git diff --cached` is empty, and the ONLY entry in
`git status --porcelain` is ` M` on this review file itself — which is the required deliverable, and
which now shows as *modified* rather than *untracked* because `a99e7131a` force-tracked it. There is
no source drift.

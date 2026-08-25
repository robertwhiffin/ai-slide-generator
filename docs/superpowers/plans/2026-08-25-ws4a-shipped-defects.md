# ws4a — Shipped defects and CI hygiene

> **For agentic workers:** REQUIRED SUB-SKILLS: `superpowers:subagent-driven-development` **plus**
> `executing-plans-tellr`. **Read `2026-08-25-ws4-index.md` first** — this plan inherits its Global
> Conventions (environment, the cause-based baseline gate, the two rulings, execution requirements)
> and does not repeat them.

**Goal:** Fix three defects that are live on `main` today, and make CI actually run the 17 frontend
specs it currently ignores.

**Why this is its own PR:** nothing here touches the graph, the schemas, or any file ws4b–e need.
Every item stands on its own merits and would be worth doing even if workstream 4 were cancelled.
Landing it first also means every later PR's Playwright specs execute in CI instead of shipping
uncollected.

**Depends on:** nothing. **Blocks:** nothing (but see Task A4's note on the shared workflow file).

**Spec:** §L2a (the `merge_css` defect), §B5 (`duplicate_session`), §L8 (the stale docstrings), §C
(the CI matrix).

---

## What is broken, in one table

| # | Defect | Live symptom today | Verified |
|---|---|---|---|
| A1 | `merge_css` keeps only `qualified-rule` blocks (`src/utils/css_utils.py:28-34`) | **Every slide-replacement edit silently drops the deck's `@media`, `@keyframes` and `@supports` rules.** A branded deck loses its print rules and animations after one edit. `@font-face` survives only because `ensure_deck_token_css` re-emits it | Measured: `merge_css(css, css)` on a sheet carrying `:root`, `@font-face`, `section.slide`, `@media print`, `@keyframes` returns **only `:root` and `section.slide`** |
| A2 | `duplicate_session` builds `SessionSlideDeck(...)` without `deck_spec_json` (`session_manager.py:1014-1026`) | **`POST /sessions/{id}/duplicate` yields a deck whose spec is gone permanently, with no self-heal** | Verified: the constructor passes 11 fields; `deck_spec_json` is not among them |
| A3 | Two docstrings in `src/core/backfill_session_slides_startup.py` (`:4`, `:239`) still say the backfill runs "from its FastAPI lifespan" | Misleads any reader who trusts them — main moved migrations pre-fork into `run.py::init_database` (§L8). The code is correct; only the prose is stale | Verified both lines |
| A4 | The `e2e-tests` job is an explicit **23-entry allowlist** (`.github/workflows/test.yml`) against **32** specs in `frontend/tests/e2e/` plus **17** more outside it | **9 e2e specs never run in CI**, including `slide-viewer` — the only spec exercising the feedback drawer and findings. 17 further specs sit where the job's naming scheme cannot reach them | Measured: 23 matrix entries, 32 + 11 + 6 = 49 specs on disk |

**A1 is the one deliberate exception to ruling R2** (the new path does not change existing code). It
changes monolith edit-path behaviour on purpose, because it is a bug fix with a user-visible
symptom — not an accommodation for the graph. Recorded in the index for exactly this reason.

---

## Files

| File | Change |
|---|---|
| `src/utils/css_utils.py` | `parse_css_blocks()` added; `merge_css` rewritten to carry at-rules. `parse_css_rules`'s existing `{selector: declarations}` contract is **unchanged** |
| `src/api/services/session_manager.py` | `duplicate_session` carries `deck_spec_json`, on both the live-deck and `version_number` branches |
| `src/core/backfill_session_slides_startup.py` | Two docstrings |
| `.github/workflows/test.yml` | e2e matrix allowlist |
| `frontend/tests/**` | 17 specs relocated into `tests/e2e/` |
| `tests/unit/test_deck_css_at_rule_survival.py` | **new** |
| `tests/unit/test_duplicate_session_carries_spec.py` | **new** |
| `tests/unit/test_e2e_matrix_covers_specs.py` | **new** |

---

## Task A1 — `merge_css` must survive at-rules

**Contract.** `parse_css_rules(css) -> dict[str, str]` keeps its current behaviour and its current
tests. Two additions:

```python
@dataclass(frozen=True)
class CssBlock:
    key: str          # a qualified rule keys on its SELECTOR; an at-rule on its EXACT SERIALIZED TEXT
    text: str
    is_at_rule: bool

def parse_css_blocks(css_text: str | None) -> list[CssBlock]: ...
```

`merge_css(existing, replacement)` then merges over ordered blocks instead of a selector dict.

**The one design decision, and why it is not the obvious one.** Dedupe keys at-rules on their
**exact serialized block text**, not on `at_keyword`. Keying on the keyword would make a second
`@media` overwrite the first — a worse defect than the one being fixed. Keying on block text
satisfies both halves at once: at-rules survive, and N identical copies collapse to one (which ws4c's
CSS aggregation needs, because §M5 hands every builder the same full style block).

**Order is preserved** because CSS is order-sensitive: `@import` must come first and `@font-face`
should precede its consumers, so a merge that reshuffles at-rules can change rendering.

**Test intent** — `tests/unit/test_deck_css_at_rule_survival.py`. Write the **first** test against
the shipped path; a test written only against ws4c's future aggregator would ship green over the live
defect.

| Assertion | Why it earns its place |
|---|---|
| `SlideDeck.update_css` on a branded sheet preserves `@font-face`, `@media print`, `@keyframes`, `@supports` | **THE regression test**, on the shipped caller (`slide_deck.py:108` ← `chat_service.py:2631`) |
| A replacement still overrides a matching selector | Existing semantics must not regress — `tests/unit/test_css_utils.py` pins them too |
| `merge_css(sheet, sheet)` collapses identical at-rule blocks to one occurrence each | The dedupe half |
| Two **different** `@media` blocks both survive | The failure mode of a naive keyword-keyed fix |
| `@import` (prelude, no block — `rule.content is None`) survives | A fix assuming every at-rule has a block silently drops these |
| `@font-face` still precedes `@media print` in the output | Order sensitivity |

**Fixture.** One branded stylesheet carrying `:root` with two custom properties, `@font-face`,
`section.slide` referencing `var(--…)`, `@media print`, `@keyframes` and `@supports`. Reuse it across
every assertion so a failure names the block that was lost.

**Steps.** Write the tests → run and record the exact failure list (this failure *is* the shipped
defect; put it in `.PLAN-CORRECTIONS.md`) → implement → run both this file and
`tests/unit/test_css_utils.py` (the latter must pass **unchanged**; if a formatting assertion there
breaks, the fix changed qualified-rule output, which it must not) → sabotage → commit.

**Sabotage.** Replace `elif rule.type == "at-rule":` with `elif False:`, confirm the six at-rule
assertions go red, and `grep -n 'elif False'` to confirm the edit is on the executed path. Revert.

**Known trap for the corrections pre-pass.** The superseded plan asserted
`merge_css(".a { color: red; }", "not valid css {{{{") == ".a { color: red; }"` on the theory that
the parse fails and the original is returned. **tinycss2 parses that string successfully as a
qualified rule**, so the branch is never taken. Measured output:
`'.a {\ncolor: red;\n}\n\nnot valid css {\n{{{}}}\n}'`. Do not write that assertion; if you want to
cover the parse-failure path, find an input that actually fails to parse.

---

## Task A2 — `duplicate_session` must carry the deck spec

**Why only this column.** The duplicate creates **no `session_slides` rows**, so the new deck reads
through the `deck_json` blob fallback (`session_manager.py:1572`) — and `css`, `external_scripts`,
`head_meta` and `scripts` all live *inside* that blob. **`deck_spec_json` does not.** It is a sibling
column, deliberately, which is exactly why its loss was invisible.

**Two branches, two sources.**

| Branch | Reads its deck bytes from | So the spec comes from |
|---|---|---|
| live deck | `deck_owner.slide_deck` | `deck_owner.slide_deck.deck_spec_json` |
| `version_number is not None` (`:967-984`) | a `SlideDeckVersion` | **that version's** `deck_spec_json` snapshot |

Getting the second one wrong pairs a restored deck with a spec describing a different deck.

**A copy, not a trigger.** The duplicated spec is already correct for the HTML it carries, so
ws4d's `mark_dirty` must **not** fire here. This route is absent from §B1's trigger list, and that
absence was silence rather than a decision — which is what made this defect invisible. Say so in the
code comment.

**Test intent** — `tests/unit/test_duplicate_session_carries_spec.py`:

- duplicating a deck with a spec yields a duplicate whose spec is present and equal
- duplicating **from a version** carries that version's snapshot, not the live spec (set them
  different first, or the test cannot distinguish them)
- duplicating a specless deck does not raise
- the duplicate's `spec_dirty_at` is `NULL` — the copy fires no trigger

**Note for the executor:** `duplicate_session`'s signature is
`duplicate_session(source_session_id: str, created_by, …)` — it takes a **string**, not a session
object. A round-3 review finding caught a test passing the wrong thing.

---

## Task A3 — two stale docstrings

`src/core/backfill_session_slides_startup.py:4` says "from its FastAPI lifespan on every boot" and
`:239` says "Called from the FastAPI lifespan alongside `migrate_profiles`". Both are wrong since
main's `fix(startup): run migrations once pre-fork, never in the uvicorn workers` — the backfill runs
in `run.py::init_database`, pre-fork, and `SystemExit(1)`s on failure.

Prose only; no test. Fold into A2's commit rather than raising a commit for two comments.

**Do not "fix" anything else in that file.** The code is correct; only these two strings are stale.

---

## Task A4 — make the e2e matrix collect the specs it ignores

**The gap, measured.** 23 matrix entries; 32 specs in `frontend/tests/e2e/`; 11 more directly in
`frontend/tests/`; 6 in `frontend/tests/user-guide/` (49 total, matching the repo count).

**Nine e2e specs are absent from the matrix:** `admin-page`,
`design-system-brand-text-uncapped`, `genie-detail-panel`, `save-points-versioning`,
`session-config-isolation`, `slide-host-frame`, `slide-viewer`, `style-source-exclusivity`,
`template-viewer`. **`slide-viewer` is the one that matters most** — it is the only spec exercising
the feedback drawer and findings, which is ws4b's and ws4e's whole frontend surface.

**Two changes.**

1. **Relocate the 17 strays into `frontend/tests/e2e/`** so the job's naming scheme can reach them.
   Check each one's relative imports after moving; the `user-guide/` six may want their own matrix
   entries or a deliberate exclusion.
2. **Add every uncovered spec to the allowlist.** 23 + 9 + up to 17 relocated. **Do the arithmetic
   from what is on disk after the move, not from this document** — a round-3 finding caught the
   superseded plan off by one here, and an off-by-one leaves a spec uncovered *and* fails the guard
   test below.

**Guard test** — `tests/unit/test_e2e_matrix_covers_specs.py`. The matrix is an explicit allowlist,
so a new spec ships uncollected **by default**; this test makes that a visible failure.

| Assertion | Note |
|---|---|
| every `*.spec.ts` in `tests/e2e/` is in the matrix or in an explicit `DELIBERATE_EXCLUSIONS` dict with a non-empty reason | An empty reason is not allowed — that is how an exclusion becomes a silent gap |
| no `*.spec.ts` remains outside `tests/e2e/` where the naming scheme cannot see it | |
| `slide-viewer` specifically is in the matrix | Pins the named gap so a future re-drop is loud |

**The regex is a trap.** `r"^\s+- ([a-z0-9-]+)$"` against the whole workflow matches **34** items —
job names (`unit-tests`, `frontend-build`, `wheel-build`, `e2e-tests`), the branch `main`, and the
*integration* matrix. **Scope the search to the e2e matrix block** before applying it.

**A4 edits `.github/workflows/test.yml`, which ws4b also edits** (its `ConfigPrompts` seed step at
`:589`). If both are in flight, land A4 first and rebase; the two edits are in different blocks but a
conflict here fails all matrix jobs at seeding.

**Expect newly-collected specs to fail.** Nine specs have never run in CI. Any that fail are
**pre-existing defects this task surfaces, not defects it causes** — and that is the point. Triage
them: fix a genuine break, or add a `DELIBERATE_EXCLUSIONS` entry with a reason and a follow-up. Do
not weaken a spec to get the matrix green, and record the triage in the PR description so the
distinction survives review.

---

## Definition of done

- [ ] `tests/unit/test_deck_css_at_rule_survival.py`, `test_duplicate_session_carries_spec.py` and
      `test_e2e_matrix_covers_specs.py` all pass, and each has been sabotage-verified.
- [ ] `tests/unit/test_css_utils.py` passes **unchanged**.
- [ ] The export and preview suites pass — `test_html_to_pptx.py`,
      `test_google_slides_converter.py`, `test_preview_box_model_parity.py`, `test_export_csp.py`.
      A1 changes deck CSS on the edit path, and these are PRD §3's no-regression gate.
- [ ] `tests/integration/test_savepoint_e2e.py` passes — A2 touches the version branch.
- [ ] Full suite compared **by cause** to the index's baseline: no new cause, no change to the
      deploy-autoscaling cause, and no test that stopped existing.
- [ ] `npm run typecheck` clean (never `npx tsc --noEmit` — it checks zero files).
- [ ] The e2e job runs green on the widened matrix, with any newly-surfaced failure either fixed or
      excluded-with-a-reason and listed in the PR description.

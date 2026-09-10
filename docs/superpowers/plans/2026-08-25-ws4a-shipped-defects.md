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

| # | Defect | Status | Verified |
|---|---|---|---|
| A1 | `merge_css` drops at-rules because `parse_css_rules` discards them (`src/utils/css_utils.py:28-38`, merged at `:41`) | **Live defect on main:** Every slide-replacement edit silently drops the deck's `@media`, `@keyframes` and `@supports` rules. A branded deck loses its print rules and animations after one edit. `@font-face` survives only because `ensure_deck_token_css` re-emits it | Measured: `merge_css(css, css)` on a sheet carrying `:root`, `@font-face`, `section.slide`, `@media print`, `@keyframes` returns **only `:root` and `section.slide`** |
| A2 | `duplicate_session` builds `SessionSlideDeck(...)` without `deck_spec_json` (`session_manager.py:1014-1026`) | **Latent on main (PR1-only).** `deck_spec_json` does not exist on main yet; no writer touches it. The duplicate drops nothing today. Live the moment ws4b's writer persists a spec. | PR1-verified: constructor passes 11 fields; `deck_spec_json` was added in PR1; `duplicate_session` still omits it |
| A3 | Two docstrings in `src/core/backfill_session_slides_startup.py` (`:4`, `:239`) still say the backfill runs "from its FastAPI lifespan" | **Latent on main (PR1-only).** File does not exist on main; it was added in PR1. The code is correct; only the prose would be stale once the file exists. | PR1-verified: file exists on the branch at the stated line numbers |
| A4 | The `e2e-tests` job is an explicit **23-entry allowlist** (`.github/workflows/test.yml`) against **32** specs in `frontend/tests/e2e/` plus **17** more outside it. Matrix entry arithmetic is 23 (main matrix) vs 26 on branch. | **Spec coverage gap on main (and branch).** Main has 14 matrix entries collecting 18 specs; branch has 23 entries collecting 32 + 11 + 6 = 49 total specs. 9 branch specs absent from matrix; 17 strays outside `tests/e2e/`. | Measured on branch: 23 matrix entries at `:479-501`, 32 specs in `e2e/`, 11 in `frontend/tests/`, 6 in `user-guide/` |

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
    text: str         # for qualified rules, the declaration block with no newline normalization (preserve source formatting so golden files match); for at-rules, the complete block with its prelude and content
    is_at_rule: bool

def parse_css_blocks(css_text: str | None) -> list[CssBlock]: ...
```

`merge_css(existing, replacement)` then merges over ordered blocks instead of a selector dict.

**Override ordering:** When a replacement rule matches an existing selector (or an at-rule matches by key), the overridden rule stays in its **original position** in the block list (use `dict.update` semantics, not append). This preserves CSS order sensitivity — `@import` must stay first, and `@font-face` should precede its consumers.

**The one design decision, and why it is not the obvious one.** Dedupe keys at-rules on their
**exact serialized block text**, not on `at_keyword`. Keying on the keyword would make a second
`@media` overwrite the first — a worse defect than the one being fixed. Keying on block text
satisfies both halves at once: at-rules survive, and N identical copies collapse to one (which ws4c's
CSS aggregation needs, because §M5 hands every builder the same full style block).

**Order is preserved** because CSS is order-sensitive: `@import` must come first and `@font-face`
should precede its consumers, so a merge that reshuffles at-rules can change rendering.

**Known limit: dedupe is whitespace-sensitive.** `tinycss2.serialize` reproduces source formatting exactly, so two copies of the same `@media` block differing only in indentation will both survive. This is acceptable under §M5's rule (identical bytes to every builder), and any builder that reformats will hit it on the ws4c side. Worth one line in the DoD as a known constraint for ws4c.

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

**Emptiness guard:** The plan must state the behavior for empty inputs, since `test_css_utils.py:71-77` pins `merge_css(existing, "") == existing` (the early return must survive). A replacement consisting only of at-rules is also stripped by the current code, so the new version needs a guard: **"if not replacement_rules: return existing_css"** must remain in place. This matters downstream: **ws4b's** CSS aggregator (B3.3 — the aggregator is ws4b's per the index, not ws4c's) cannot dedupe by concatenating then merging with `""`; it must fold pairwise. **The design note "N identical copies collapse to one" is true only under a fold**, and that constraint should be stated since it affects ws4b's aggregation strategy. Note ws4c produces the style block and ws4b consumes it, so the fold constraint lands on the consumer.

**Fixture.** One branded stylesheet carrying `:root` with two custom properties, `@font-face`,
`section.slide` referencing `var(--…)`, `@media print`, `@keyframes` and `@supports`. Reuse it across
every assertion so a failure names the block that was lost.

**Steps.** Write the tests → run and record the exact failure list (this failure *is* the shipped
defect; put it in `.PLAN-CORRECTIONS.md`) → implement → run this file,
`tests/unit/test_css_utils.py` (must pass **unchanged**), `tests/integration/test_slide_replacement_flow.py` (golden-file constraint on `text` formatting and override ordering), and `tests/unit/test_deck_integrity.py::TestCSSMerging` (runs on `load_databricks_theme()` which contains `@media`, so its output changes after the fix) → sabotage → commit.

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
- the copy does not fire a `mark_dirty` trigger (no-op check: route is absent from §B1's trigger list)

**Note for the executor:** `duplicate_session`'s signature is
`duplicate_session(source_session_id: str, created_by, …)` — it takes a **string**, not a session
object. A round-3 review finding caught a test passing the wrong thing.

---

## Task A3 — two stale docstrings

`src/core/backfill_session_slides_startup.py:4` says "from its FastAPI lifespan on every boot" and
`:239` says "Called from the FastAPI lifespan alongside `migrate_profiles`". Both are wrong since
main's `fix(startup): run migrations once pre-fork, never in the uvicorn workers` — the backfill runs
in `packages/databricks-tellr-app/databricks_tellr_app/run.py::init_database`, pre-fork, and `SystemExit(1)`s on failure (wiring already pinned by `tests/unit/test_startup_migrations.py`).

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

1. **Relocate the 17 strays into `frontend/tests/e2e/`.** The six `user-guide/` specs are documentation screenshot generators (`frontend/tests/user-guide/shared.ts:19` writes to `docs/user-guide/images` via `path.join(__dirname, '..', '..', '..', 'docs', ...)` — depth 3). **Decide now:** 
   - **Option A (flatten+reason):** Move all six into `tests/e2e/`, which breaks the path (depth becomes 4). Update the path and add `DELIBERATE_EXCLUSIONS` with a reason stating they are documentation, not functional specs. 
   - **Option B (scope exemption):** Move the 11 non-user-guide strays into `tests/e2e/`, and leave user-guide where it is, adding an exemption to the guard's "no spec outside `tests/e2e/`" rule (same reason).
   
   **This plan chooses Option A (flatten).** Check each one's relative imports after moving; fix any paths.
   
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

**Job count and parallelism.** This change grows the e2e matrix from 23 to ~49 entries. Each entry is a full job: `npm ci`, `playwright install --with-deps chromium`, `pip install -e ".[dev]"`, Postgres service, DB seed, backend boot, and one spec at `--workers=1`. The matrix roughly doubles minutes and artifacts. This is an acceptable trade-off given the spec coverage gap (23 existing, 26 never run), but worth acknowledging. Consider adding `max-parallel` to the job config if you hit concurrent-job caps. The alternative — `--shard=i/N` over `tests/e2e/` — would dissolve both the allowlist and its guard; that option was rejected in favour of explicit matrix control.

**The regex is a trap.** `r"^\s+- ([a-z0-9-]+)$"` against the whole workflow matches **34** items —
job names (`unit-tests`, `frontend-build`, `wheel-build`, `e2e-tests`), the branch `main`, and the
*integration* matrix. **Scope the search to the e2e matrix block** before applying it. **Better: use a YAML parser.** `pyyaml` is already in `pyproject.toml:24`, so `yaml.safe_load(...)["jobs"]["e2e-tests"]["strategy"]["matrix"]["test"]` is exact and immune to formatting drift. Also anchor file paths with `Path(__file__).resolve().parents[2]` (the repo convention per `tests/unit/test_startup_migrations.py:16`), not a cwd-dependent relative path.

**Workflow file edits:** A4 edits `.github/workflows/test.yml` (this PR's matrix allowlist), which ws4e also edits (its layer-4 job near line 290). If both are in flight, coordinate the conflict; the two edits are in disjoint blocks. **Important: The `backend` filter (`.github/workflows/test.yml:35-38`) gates the `unit-tests` job to `src/**`, `tests/**`, `pyproject.toml`. Add `.github/workflows/test.yml` and `frontend/tests/**` to that filter**, else a PR editing only test.yml or adding frontend specs skips `unit-tests` entirely, and the guard test `test_e2e_matrix_covers_specs.py` never runs. The guard exists to catch spec-coverage gaps; a filter that makes it skip-able defeats its whole purpose.

**Expect newly-collected specs to fail.** 26 specs have never run in CI (9 absent from matrix, 17 relocated).
Any that fail are **pre-existing defects this task surfaces, not defects it causes** — and that is the point.
Triage them: fix a genuine break, or add a `DELIBERATE_EXCLUSIONS` entry with a reason and a follow-up. Do
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
- [ ] Relocation import verification: `cd frontend && npx playwright test --list` succeeds and loads all 49 relocated specs without unresolved-import errors (cheap gate that needs no server).
- [ ] The e2e job runs green on the widened matrix, with any newly-surfaced failure either fixed or
      excluded-with-a-reason and listed in the PR description.

# ws4a — ROUND 2 findings (VERBATIM). Loop stopped; these are UNFIXED and inherited.

Fresh reviewer, frozen prompt, no round-1 context. 15 findings on a 229-line document.
**Round 1 found 14. Round 2 found 15. No decay.**

Three classes, and the mix is the important part:
- **(a) Defects Wave 2's fix pass introduced or left half-done** — findings 5, 6, 12.
- **(b) Round 1 reviewer errors that Wave 2 faithfully applied** — findings 1, 7.
- **(c) Genuinely new** — findings 2, 3, 4, 8, 9, 10, 11, 13, 14, 15.

---

## 1. The A4 "Verified" cell is fabricated and self-contradictory (critical)

Claims *"Matrix entry arithmetic is 23 (main matrix) vs 26 on branch"* and *"Main has 14 matrix entries collecting 18 specs; branch has 23 entries collecting 32 + 11 + 6 = 49 total specs."*

Measured:
- `git diff origin/main...HEAD -- .github/workflows/test.yml` is **empty**. The workflow is byte-identical on main and the branch. Both have **23** matrix entries (yaml-parsed). There is no "23 vs 26", and main does not have 14.
- A matrix entry maps **1:1** to a spec: the run step is `npx playwright test tests/e2e/${{ matrix.test }}.spec.ts` (`.github/workflows/test.yml:754`). 23 entries collect **23** specs. "23 entries collecting … 49" is not a thing the job can do.
- Main: 31 e2e specs / 48 total → **8** absent from the matrix, not 9. Branch: 32 / 49; the single new spec is `frontend/tests/e2e/slide-viewer.spec.ts`.

This is the cell the executor is told to trust, in the task that warns *"a round-3 finding caught the superseded plan off by one here."* The `23`/`32`/`11`/`6`/`49`/`9-absent` figures elsewhere in A4 are all correct — only the cross-branch arithmetic is wrong. **ORIGIN: round 1's index reviewer supplied the 14/18/33 figures; Wave 1 wrote them in.**

## 2. The chosen at-rule dedupe key makes at-rules append-only (high)

Keying at-rules on **exact serialized block text** means an *edited* `@media print` is a different key → appended, old copy retained. `merge_css` is on a live user path (`chat_service.py:2631` → `slide_deck.py:108`), and `deck.css` is persisted and re-fed on the next edit. Consequences the plan never states:

- N edits touching an at-rule leave N copies. `deck.css` grows monotonically and ships in every knit, preview and export.
- "Remove this animation" can never remove a `@keyframes`. **At-rules become immortal.**

The plan rejects `at_keyword` keying (correctly) then presents text-keying as satisfying *"both halves at once"* — but never considers `(at_keyword, serialized_prelude)`, which satisfies **all six** of its own assertions (dedupe on `merge_css(sheet, sheet)`; two *different* `@media` both survive; `@import` survives; order preserved) **and** makes at-rules updatable. Its only cost is collapsing two byte-different `@media print` blocks within one sheet.

## 3. The "Emptiness guard" paragraph instructs the implementer to keep the bug (high)

> "A replacement consisting only of at-rules is also stripped by the current code, so the new version needs a guard: **`if not replacement_rules: return existing_css`** must remain in place."

Measured: today `merge_css(existing, "@media print { .a { color: red } }")` returns `existing` unchanged, because `parse_css_rules` yields `{}` and the early return fires. Keeping the guard keyed on `parse_css_rules`' output — what "must remain in place" literally says — leaves at-rule-only replacements silently dropped *after* the fix. The guard must key on `parse_css_blocks`' output, and the plan should say the behaviour **changes**. `test_css_utils.py:71-77` pins only the **empty-string** case, which a blocks-based guard also satisfies.

## 4. The `@import`-first invariant is not delivered by the stated algorithm (high)

> "the overridden rule stays in its **original position** … (use `dict.update` semantics, not append). This preserves CSS order sensitivity — `@import` must stay first"

`dict.update` preserves position only for keys that **already exist**; new keys append. A replacement introducing an `@import` (or `@charset`) that `existing` lacks lands **last**, which browsers ignore outright. Probed: tinycss2 parses both as at-rules with `content is None`, both serializing correctly, so both reach the output — in whatever position update semantics put them. Needs an explicit hoist, or the invariant downgraded to a known limit.

## 5. "Blocks: nothing" contradicts the index (high)

Header: *"**Depends on:** nothing. **Blocks:** nothing."* Index `:64` says "**Blocks ws4b.**" and `:76-78` explains why; ws4b's own text (`:801-803`) confirms `aggregate_deck_css` "Merges the blocks with ws4a's at-rule-preserving `merge_css`". A false "Blocks: nothing" in the header a reader skims first mis-sequences the workstream. **ORIGIN: Wave 1 fixed the index and not ws4a's header.**

## 6. The Goal line says "live on `main` today" — the index explicitly ordered this changed (high)

Index `:73-75`: *"Change all 'live on `main` today' references to 'live on the integration branch'."* Verified: `deck_spec_json` and `src/core/backfill_session_slides_startup.py` are PR1-only. The plan's own table 20 lines below gets this right for A2 and A3, so the Goal is an unfixed leftover contradicting the table. Only A1 is live on main. **ORIGIN: Wave 1 fixed the table and not the Goal.**

## 7. Both of the DoD's named safety nets guard something else (medium-high)

**A1's:** *"`tests/integration/test_slide_replacement_flow.py` (golden-file constraint on `text` formatting and override ordering)"*. That file has **no CSS assertion at all** — its only CSS line is `deck.update_css(result["replacement_css"])` at `:114`. **There is no golden file.** Repo-wide nothing pins `merge_css`'s exact output: `test_css_utils.py`'s assertions are all substring except the empty-replacement identity, and only three tests anywhere call `update_css` (`test_deck_integrity.py:372`, `:387`, and `:114`), none formatting-exact. So the `CssBlock.text` contract's entire justification is unfounded and a formatting change ships undetected. Either A1 owes a new exactness assertion or the constraint should be dropped. **ORIGIN: round 1's ws4a reviewer asserted the golden file; Wave 2 applied it.**

**A2's:** *"`tests/integration/test_savepoint_e2e.py` passes — A2 touches the version branch."* Its `test_duplicate_then_edit` (`:417`) calls `POST /api/slides/1/duplicate` — **slide** duplication. It never reaches `duplicate_session`. The file that does is `tests/unit/test_session_duplicate.py`, which already contains `test_duplicate_from_save_point_uses_version_snapshot` (`:255`) — the exact version-branch guard, with reusable fixtures. Omitted from Files, DoD and A2's test intent, so the executor scaffolds a new file and never learns the existing suite must stay green.

## 8. Option A's stated reason for flattening `user-guide/` is false (medium)

> "Move all six into `tests/e2e/`, which breaks the path (depth becomes 4)."

`frontend/tests/user-guide/shared.ts` is a **helper, not a spec**. Moving the six `*.spec.ts` files leaves its `path.join(__dirname,'..','..','..','docs',…)` at `:19` at depth 3 and still correct; the specs' `from './shared'` becomes `from '../user-guide/shared'`. The path breaks only if `shared.ts` also moves, which the plan neither states nor rules out. So the A-vs-B decision rests on a conditionally-true premise, and the plan picks the costlier branch.

Two unmentioned Option-A costs B avoids: the six specs write into `docs/user-guide/images`, so after the move `npx playwright test tests/e2e/` dirties the tree with regenerated PNGs; and the documented regeneration command `npx playwright test user-guide/` stops working, with no doc update in the Files table.

## 9. Matrix-size budget contradicts the plan's own Option A (medium)

Option A excludes the six user-guide specs via `DELIBERATE_EXCLUSIONS`, so the matrix is 23 + 9 + 11 = **43**, not the "~49" the parallelism section budgets. Also `retries: process.env.CI ? 2 : 0` (`frontend/playwright.config.ts:8`) means attempts, not jobs, drive cost — omitted from "roughly doubles minutes".

## 10. ws4a is the index-designated owner of the baseline artifact and doesn't create it (medium)

Index: *"**Baseline artifact:** Saved to `docs/superpowers/baselines/pr3_ws4_collected.log` **after ws4a merges**."* That directory does not exist. ws4a's Files table and DoD never mention it, so ws4b–e's "compare by cause to the index's baseline" has nothing to compare against.

## 11. `parse_css_blocks` is silent on comment and error nodes (medium)

Probed: `tinycss2.parse_stylesheet(css, skip_whitespace=True)` yields `type == 'comment'` nodes, and malformed input yields nodes too — `bad {{{` returns a `qualified-rule` serializing to `'bad {{{\n}}}'`, so *"`tinycss2.serialize` reproduces source formatting exactly"* has an exception. `CssBlock` has only `is_at_rule`, no third state. Current behaviour drops comments and error nodes; the contract should pin that, because it decides whether `_TOKEN_CSS_REEMIT_MARKER` (`design_system_templates.py:375-378`, "what a reviewer greps for") survives an edit. Today it does not.

## 12. Internal contradiction on the aggregator's owner, and review-voice text left in place (medium)

Line 76 says the dedupe *"ws4c's CSS aggregation needs"*; line 96 says *"**ws4b's** CSS aggregator … not ws4c's"*. Index `:65` and ws4b `:799-803` confirm ws4b; line 76 is an unfixed leftover.

Relatedly, the whole "Emptiness guard" paragraph is in **reviewer voice, not plan voice** — *"The plan must state the behavior…"*, *"that constraint should be stated"*, *"Worth one line in the DoD…"* — and the DoD does **not** carry the whitespace-sensitivity line it asks for. Unresolved review comments were pasted in rather than converted into instructions. **ORIGIN: Wave 2's fix pass.**

## 13. The workflow-conflict note is incomplete (medium-low)

ws4b's B1.3 (`:219-222`) adds a **`frontend-unit-tests`** job to `.github/workflows/test.yml`. **Three** of the five PRs touch that file, not two — and the index states the opposite explicitly ("not ws4a and ws4b"). Also ws4a's *second* workflow edit, the `backend` paths-filter, is at **`:36-39`**, not `:35-38`, and sits in the region every workflow-touching PR edits.

## 14. A2's rationale for scoping to one column is wrong, though the conclusion holds (medium-low)

> "`css`, `external_scripts`, `head_meta` and `scripts` all live *inside* that blob. **`deck_spec_json` does not.** It is a sibling column, deliberately"

PR1 added **four** sibling columns — `deck_spec_json`, `css`, `external_scripts_json`, `head_meta_json` (`session.py:271-299`; migration `database.py:1930-1961`), and `duplicate_session` drops all four. Being a sibling column is not the distinguishing property. The real distinction is that the other three are **also** inside `deck_json`, re-derived on the blob read path (`session_manager.py:1594`), and re-written to their columns on the first save (`:1366-1370`). The conclusion survives; the reason does not, and it hides that a fresh duplicate's `css`/`external_scripts_json`/`head_meta_json` columns are NULL until its first save. **Inherited verbatim from spec §B5, so the spec carries the same defect.**

## 15. Lower-severity

- **Four export suites in the DoD cannot be affected by A1.** `merge_css` has exactly one production caller chain; none of `test_html_to_pptx.py`, `test_google_slides_converter.py`, `test_preview_box_model_parity.py`, `test_export_csp.py` reaches it. Asserting a causal link dilutes the no-regression gate.
- **The backend-filter change couples e2e to backend unit tests.** `unit-tests` is gated on `backend` (`:85`) and `e2e-tests` requires its success-or-skip (`:471`). After adding `frontend/tests/**`, a frontend-spec-only PR now runs `unit-tests`, so a failing backend unit test blocks all 43 e2e jobs where it previously skipped. The change is right; the consequence is unstated.
- **A1's sabotage targets a source line the contract may not produce.** "Replace `elif rule.type == "at-rule":` with `elif False:`" presumes an `elif` chain, but only `parse_css_blocks(...) -> list[CssBlock]` is specified. Specify sabotage against **behaviour** (at-rules excluded from the block list).
- **DoD relocation gate is miscounted.** "`--list` … loads all 49 relocated specs" — only 17 are relocated, and `testDir: './tests'` already collects all 49 today, so the count cannot distinguish pass from fail. The "zero unresolved-import errors" half is the useful assertion.
- **"the one deliberate exception to ruling R2"** — R2 names two. Presumably means "the one in ws4a".
- **`.PLAN-CORRECTIONS.md` path unspecified.**
- **A1 table row cites "merged at `:41`"** — that's `def merge_css`; the merge is at `:70`.

## Verified correct — do NOT re-check

A1's measurement is exact. The "known trap" output is byte-exact. Every file:line anchor holds —
`css_utils.py:28-38`, `session_manager.py:967`/`:1014`/`:1572`, the 11-field constructor,
`backfill_session_slides_startup.py:4`/`:239`, `run.py::init_database` with `SystemExit(1)`,
`slide_deck.py:108` ← `chat_service.py:2631` as the sole caller, `test_css_utils.py:71-77`,
`test_startup_migrations.py:16`'s `parents[2]`, `pyproject.toml:24` pyyaml, `test.yml:479-501`,
`shared.ts:19` depth-3, 32/11/6 = 49. The nine absent specs are exactly the nine named.
`slide-viewer.spec.ts` is genuinely the only spec exercising the drawer and findings.
`yaml.safe_load(...)` works despite PyYAML parsing bare `on:` as `True`. `validate_css_syntax`
(`tests/validation/css_validator.py:45-54`) already counts at-rules, so `TestCSSMerging` will not
break on the fix. `tests/fixtures/css/databricks_theme.css` has two *different* `@media` blocks
(`:308`, `:329`), so its output does change. `duplicate_session` takes a string. `@import` parses
with `content is None`. `deck_json` is genuinely dual-written (`:1303`, `:1322`). Spec §L2a, §B5,
§L8 and §C all exist and say what the plan cites.

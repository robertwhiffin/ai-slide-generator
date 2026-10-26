# ws4a → ws4b handover

**Written 2026-09-11, on merging ws4a into `feat/langgraph-core`.** For the agent picking up **ws4b**
(`2026-08-25-ws4b-contracts-and-schema.md`). Read this *after* the three documents in §2, not instead
of them — it carries only what ws4a changed and what ws4a measured, both of which the plans predate.

---

## 1. Where things stand

- **ws4a is MERGED into `feat/langgraph-core`** at merge commit `a2dcae9e` (`--no-ff`, so the
  workstream keeps a boundary and stays revertable as a unit). Its 12 commits are `42312012..ce3e7876`.
- **Nothing is pushed.** `feat/langgraph-core` has no remote counterpart for this work, so **CI has
  never run any of it.** The decision was to merge the five workstreams locally and push the
  integration branch.
- The ws4a branch `feat/ws4a-shipped-defects` still exists as the record. Don't build on it; branch
  off **`feat/langgraph-core`**.
- The merge commit message carries ws4a's four Definition-of-Done obligations that would normally live
  in a PR description. **Read `git show a2dcae9e --no-patch`** — it is the authoritative record of the
  at-rule limits, the paths-filter coupling, and both triage decisions.

---

## 2. Read these first, in this order

1. **`.claude/skills/executing-plans-tellr/`** *and* **`superpowers:subagent-driven-development`** —
   both, per the repo's `CLAUDE.md`. Not optional.
2. **`ws4-START-HERE.md`**, then **`2026-08-25-ws4-index.md`** — the conventions ws4b inherits and
   deliberately does not repeat.
3. **Your plan, end to end, before writing anything.**
4. **Do the corrections pre-pass** into `docs/superpowers/plans/.ws4b-PLAN-CORRECTIONS.md` before
   Task 1, and point every dispatch at it. On ws4a it produced six real corrections, two of which
   changed what got written and two of which made the work *smaller*. It is not ceremony.

`docs/superpowers/plans/.ws4a-PLAN-CORRECTIONS.md` is committed — worth skimming for the house style
and for the A1 semantics section, which is a contract you consume.

---

## 3. The baseline — YOU MUST RE-DERIVE IT

`docs/superpowers/baselines/pr3_ws4_collected.log` now exists (ws4a created it; it needed a
`.gitignore` negation because `*.log` was silently swallowing the path — very likely why the directory
never existed before).

Current state, measured post-merge on the shared pyenv:

    3 failed, 4212 passed, 8 skipped     COLLECTED: 4223

Two causes, both pre-existing, both recorded with exact assertion strings in that file.

**ws4b adds four migrations and changes the ORM, so you fall squarely inside the file's own
re-derivation rule.** Re-measure and update Section 2 rather than comparing against a stale figure.

Two traps the file spells out and that are worth repeating:

- **Compare CAUSES, never counts.** A 13→13 collision once hid a real breakage here for seven tasks.
- The deploy-autoscaling cause raises **two DIFFERENT assertion strings**. Grepping for one silently
  misses the other.
- "No test stopped existing" cannot be checked by a count — N deletions plus N additions preserve it.
  Diff the test trees for removed `def test_` / `class Test` lines and for deleted files.

---

## 4. What ws4a changed that ws4b BINDS TO

### 4.1 `merge_css` — your B3.3 aggregator consumes this

`src/utils/css_utils.py` gained `CssBlock` and `parse_css_blocks()`, and `merge_css` now merges over an
ordered block list so at-rules survive. `parse_css_rules`'s `{selector: declarations}` contract is
**unchanged** and its tests pass untouched.

**The one that changes your implementation:** an empty replacement returns `existing_css` **early**, so
you **cannot** dedupe by concatenating every style block and merging the result with `""` — that call
never reaches the merge. **Fold pairwise.** "N identical copies collapse to one" is true only under
that fold.

The rest of the contract you inherit:

| Property | Value |
|---|---|
| At-rule dedupe key | `(lower_at_keyword, discriminator)` — **lowercased**, because CSS at-rule keywords are case-insensitive and the raw value lets `@MEDIA print` and `@media print` mint separate keys |
| Discriminator | serialized prelude when non-empty; serialized **CONTENT** when empty |
| Why the empty-prelude fallback is load-bearing | every `@font-face` serializes an empty prelude, so prelude-only keying collapses a multi-weight brand font to one weight — and `ensure_deck_token_css`'s guard is per-FAMILY, so it does not notice |
| Known limit | two at-rules sharing a keyword and a **non-empty** prelude collapse to one (later text, earlier position) |
| Known limit | an edited **empty-prelude** at-rule (`@font-face`, bare `@page`) **appends** rather than replaces |
| Hoisting | `@charset` then `@import` only. **`@namespace` and statement-form `@layer` are NOT hoisted** and would land last, where a browser ignores them. Documented, deliberate |
| Override position | an overridden rule keeps its **original** position (`dict.update` semantics), so `@font-face` still precedes its consumers |

**Do not change `merge_css`'s qualified-rule output formatting.**
`tests/integration/test_slide_replacement_flow.py::test_sequential_updates_exact_match` exact-matches
`SlideDeck.knit()` against the on-disk golden `tests/sample_htmls/final_html.html`, so the formatting is
pinned **transitively**. The plan's claim that nothing pins `merge_css`'s output is FALSE. If that test
fails, your change is wrong — **never regenerate the golden file.**

### 4.2 `session_manager.py` anchors have shifted — the measured table

A2 inserted 7 lines. The file went 2905 → 2912 lines. Measured by locating each old line's content in
the new file:

| Region | Shift |
|---|---|
| at or above `:967` | **+0** — `:194`, `:239`, `:709`, `:967` are all stable |
| `:1014` (the `SessionSlideDeck(` constructor itself) | **+6** |
| **everything below `:1014`** | **uniform +7** |

So the index's list of ws4b citations now resolves as: `:1303`→`1310`, `:1320`→`1327`,
`:1366`→`1373`, `:1403`→`1410`, `:1538-1564`→`1545-1571`, `:1549`→`1556`, `:1585`→`1592`,
`:1637-1650`→`1644-1657`, `:1793-1811`→`1800-1818`, `:1939-1951`→`1946-1958`, `:2240`→`2247`.
Also useful: `VERSION_LIMIT = 40` moved `:1859`→`:1866`.

**Re-grep anyway.** This table is a cross-check, not a substitute — your own edits will move lines
again, and a stale anchor is a silent misfile rather than an error.

Also note `duplicate_session` has **exactly ONE** `SessionSlideDeck(...)` constructor (now `:1020`),
shared by both branches — the plan's "two branches, two sources" describes where the *value* comes
from, not two constructors.

### 4.3 Two NEW guards that will fail your PR if you ignore them

These did not exist when your plan was written. **Both are in `tests/unit/`, so `unit-tests` runs them.**

- **`tests/unit/test_ci_collects_integration_tests.py`** — every `tests/integration/test_*.py` must be
  named in some CI job's `run` block, or listed in `DELIBERATE_EXCLUSIONS` with a **non-empty** reason.
  **If ws4b adds an integration test file, add it to a job or the guard fails.** It also fails on a
  file nested in a subdirectory, and on a file that is both excluded *and* still named in a job.
  (Your `tests/integration/conftest.py` is not `test_*.py`, so it is unaffected.)
- **`tests/unit/test_e2e_matrix_covers_specs.py`** — every `*.spec.ts` in `frontend/tests/e2e/` must be
  in the workflow's e2e matrix or excluded-with-a-reason; **no spec may sit outside `tests/e2e/`**, and
  none may be nested in a subdirectory. Both also fail if their discovery step finds **zero** files.

### 4.4 `.github/workflows/test.yml` has changed materially — re-read it

Your B1.3 adds a `frontend-unit-tests` job. Since your plan was written, this file gained:

- the e2e matrix widened then trimmed to **36** entries (13 specs in `DELIBERATE_EXCLUSIONS`)
- a new **`integration-general`** job naming the 10 previously-uncollected integration files
- `.github/workflows/test.yml` and `frontend/tests/**` added to the **`backend` paths filter**
- `timeout-minutes` on `integration-general` only

**Re-read the file; never resolve it by hunk.** Add your job in a region disjoint from the matrix block
and the paths filter. Note the coupling ws4a introduced: a frontend-tests-only PR now runs **all seven**
integration jobs, and a failing backend unit test blocks every e2e job where it previously skipped them.

---

## 5. Traps ws4a measured the hard way — do not re-learn these

- **`npm run typecheck` cannot see `frontend/tests/` at all.** `tsconfig.app.json` includes only `src`.
  The index already warns that `npx tsc --noEmit` checks zero files; this is the same trap one level
  down. For anything touching test files, the real gate is `npx playwright test --list` (assert on
  **errors**, not on a spec count).
- **An import gate and a type-checker prove NOTHING about a path built at runtime.** ws4a relocated 17
  specs, rewrote every import, passed `--list` and `tsc` — and still broke a spec that resolved a file
  via `new URL('../src/...', import.meta.url)`. It had silently disabled a security regression test. If
  you move a test file, grep separately for `import.meta.url`, `new URL`, `__dirname`, `readFileSync`,
  `path.join`, `path.resolve`, `fileURLToPath`.
- **`src/core/database.py` calls `load_dotenv()`, so your local `.env` leaks into test runs.** An
  explicit env var overrides it. ws4a measured "all ten integration files pass in 20s" with the real
  Databricks host in scope, and the CI env (a fake unreachable host) made four of them hang for
  minutes each — because under `ENVIRONMENT=test` the client construction *skips verification and
  succeeds*, so the identity provider picks WORKSPACE mode and the first SCIM call retries forever.
  **Measure anything touching a Databricks client with the CI env, not your `.env`.**
- **A coverage guard can pass vacuously.** Both of ws4a's guards initially passed when pointed at an
  empty directory — the worst possible failure for a coverage test. If you write a guard whose first
  step is discovery, assert the discovery found something, and sabotage-verify it against **both** a
  nonexistent path and a real-but-empty one; only the second proves you guarded the discovery.
- **`frontend/node_modules` may be stale.** `npm ci` (never `npm install`) installs what
  `package-lock.json` already pins, adds no dependency, and leaves the lockfile byte-clean — so the
  laptop-proxy-vs-npmjs lockfile hazard does not bite.
- **zsh does not word-split unquoted parameters.** Passing many spec paths via `$SPECS` sends them as
  ONE argument; Playwright then reports "No tests found", which reads exactly like a clean run. Use an
  array.
- **Verify every self-report.** Across ws4a, a scout "corrected" the plan with a value that was
  actually input-dependent (rejected on re-probe), an agent recommended a repo fix for what was a stale
  local `node_modules`, and a fix agent wrote "pass in CI" for results measured locally. Re-probe every
  external-state fact an agent volunteers.

---

## 6. What ws4a left open

- **CI has never run.** The widened matrix and the new integration job are verified **locally only**.
  The first push of `feat/langgraph-core` is the first real CI signal — and it will cover ws4a plus
  whatever else has merged by then, so attributing a CI-only failure gets harder the longer you wait.
- **7 quarantined specs** carry a greppable `FOLLOW-UP` marker in
  `tests/unit/test_e2e_matrix_covers_specs.py`. They predate the app-shell redesign and need
  re-authoring against `AppLayout`; **`slide-viewer` is NOT among them** — it is collected and green,
  which matters because it is the only spec covering the findings drawer your work surfaces.
- **No job except `integration-general` sets `timeout-minutes`.** Pre-existing repo-wide gap,
  deliberately out of ws4a's scope.
- **ws4b owns one behaviour change:** §E2 drops the `ConfigPrompts` prompt columns, so a stored custom
  `system_prompt` stops taking effect. Deliberate (§E1), but the release notes owe it a line.
- Ruling **R2** still binds: `src/services/agent.py`, `src/core/prompt_modules.py` and
  `src/services/design_system_compiler.py` are **never modified** — read and import freely, private
  names included. ws4a's `merge_css` fix was one of the two recorded exceptions across all five plans;
  the other is ws4c importing `UNTRUSTED_DATA_NOTICE`. Do not widen either.

---

## 7. Environment, in one place

- Interpreter: **`~/.pyenv/versions/3.11.0/bin/python`**. Prefix ad-hoc scripts with `PYTHONPATH=.`.
- **Never `pip install`** — shared pyenv site-packages; an install corrupts parallel agents' runs.
- The in-tree `.venv` carries the **pre-PR2** stack. Two facts these plans depend on are FALSE in it.
  Never reach for it; never delete it.
- **None of the five workstreams adds a dependency** except ws4b's frontend test runner. If a task
  thinks it needs one, stop and escalate.
- `packages/databricks-tellr-app/pyproject.toml` is what the Apps BUILD phase resolves — the repo-root
  dependency files are not on that path.

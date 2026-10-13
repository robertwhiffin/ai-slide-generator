# ws4a — round 1 findings (VERBATIM, do not paraphrase)

Reviewer verified every load-bearing claim against the code. **The measurements the plan reports are,
without exception, accurate** — including the character-exact `merge_css` outputs, the 11 constructor
fields, the 23/32/11/6/49 counts, the exact nine-spec gap set, and the 34-match regex. The problems are
in what the plan omits, in two contracts it under-specifies, and in a cross-PR independence claim that is
false.

**1. A4's guard test cannot fire on the PRs that cause the drift it exists to catch.**
`.github/workflows/test.yml:85` gates the `unit-tests` job on `needs.changes.outputs.backend == 'true'`,
and the `backend` filter (`:35-38`) is `src/**`, `tests/**`, `pyproject.toml`. A PR that adds one
Playwright spec under `frontend/tests/e2e/` and nothing else skips `unit-tests` entirely, so
`test_e2e_matrix_covers_specs.py` never runs. A PR that edits only `test.yml` (removing a matrix entry)
matches neither `backend` nor `frontend` — no guard, no e2e. The task's whole premise ("this test makes
that a visible failure") is defeated by the filter in the file it is editing. Fix inside A4: add
`.github/workflows/test.yml` and `frontend/tests/**` to the `backend` filter, or give the guard its own
ungated job.

**2. A1's `CssBlock` contract leaves undefined the two properties a golden-file test pins, and the DoD
omits that test.** `tests/integration/test_slide_replacement_flow.py:118` compares `deck.knit()` against
`tests/sample_htmls/final_html.html`. That fixture's `<style>` block is byte-for-byte `merge_css`'s
current reconstruction — `f"{selector} {{\n{declarations}\n}}"` joined by `\n\n`, first declaration
unindented and the rest carrying source indentation — while `update1.html` carries the fully-indented
source form. `normalize_html` is `soup.prettify()` plus whitespace-*only* node removal, so it does not
normalize text inside `<style>`. Two consequences:

- The plan says `key` is the selector for qualified rules and exact serialized text for at-rules, but
  never says what `text` is for a qualified rule. The obvious implementation, `tinycss2.serialize([rule])`,
  preserves source formatting (probed) and breaks this test.
- Override ordering is unspecified. Today `existing_rules.update(...)` keeps the overridden selector in
  its *original* position; appending instead also breaks the fixture.

The plan's stated safety net is illusory: "if a formatting assertion there breaks" — `tests/unit/test_css_utils.py`
has **no** formatting assertion. Every check is a substring `in result`, plus
`merge_css(existing, "") == existing`. Add to the DoD:
`tests/integration/test_slide_replacement_flow.py` and
`tests/unit/test_deck_integrity.py::TestCSSMerging` (the latter runs on `load_databricks_theme()`, which
contains `@media`, so its merged output changes after the fix).

**3. A2's fourth test assertion cannot be written in ws4a.** `spec_dirty_at` does not exist on `main` —
it is introduced by ws4b (`ws4b-contracts-and-schema.md:497`). The plan asserts "Depends on: nothing". An
executor will either write a test that errors on an unknown attribute, or reach for
`getattr(deck, "spec_dirty_at", None) is None`, which passes vacuously forever. Drop the assertion; the
no-trigger obligation belongs to ws4d, which owns `mark_dirty`.

**4. "Shares no file with b–e except the e2e workflow" is false, and A2 shifts anchors b–e depend on.**
ws4b's B3.2 edits the row-read `deck_dict` in `session_manager.py:1538-1564`, and cites `:1303`, `:1320`,
`:1356/:1366`, `:1403`, `:1793-1811`; ws4d cites `:2205-2212`, `:2222`, `:2240`, `:2772`; the index cites
`:1793` and `:1859`. Every one of those is below A2's insertions at `:1014-1026` and `:967-984`, so
landing A2 first silently invalidates them all by a few lines. Given how completely these five plans rest
on file:line anchors, this belongs in the sequencing note beside the A4 workflow warning, with an
instruction that each later plan's corrections pre-pass re-derives `session_manager.py` anchors.

**5. A4 undercounts the triage burden by 17.** "Expect newly-collected specs to fail. Nine specs have
never run in CI" contradicts the same document's own table. Checked with `git log -S` per name: none of
the 11 `frontend/tests/*.spec.ts` nor the 6 `user-guide/*` names has ever appeared in `test.yml`. So
**26** specs run in CI for the first time, not 9 — and the DoD requires them all green or
excluded-with-a-reason.

**6. The relocation has no verifier, and the one the DoD names is blind to it.**
`frontend/tsconfig.app.json` includes only `["src"]`; `tsconfig.node.json` only `vite.config.ts` and
`playwright.config.ts`. `frontend/tests/**` is not type-checked by anything, so `npm run typecheck`
cannot catch a missed `./helpers/x` → `../helpers/x` rewrite (the e2e convention is confirmed:
`../helpers/setup-mocks`, `../fixtures/mocks`, `../../src/services/domWalker`). Cheap gate to add:
`cd frontend && npx playwright test --list`, which loads all 49 specs and reports unresolved imports
without a server.

**7. The user-guide six are left undecided, and the plan's two halves conflict on them.** These are
documentation screenshot generators: `frontend/tests/user-guide/shared.ts:19` writes into
`docs/user-guide/images` via `path.join(__dirname, '..','..','..','docs',…)`. The guard's "no spec remains
outside `tests/e2e/`" forces a move; moving them as `tests/e2e/user-guide/` silently breaks that path
(depth 4, not 3), while flattening keeps it working by coincidence and puts screenshot generators into the
CI matrix. Decide it in the plan — flatten plus a `DELIBERATE_EXCLUSIONS` reason, or scope the "outside
e2e" assertion to exempt `user-guide/`.

**8. A4 roughly doubles the e2e job count with no acknowledgement of cost.** Each matrix entry is a full
job: `npm ci`, `playwright install --with-deps chromium`, `pip install -e ".[dev]"`, a Postgres service,
DB seed, backend boot, ~40 lines of debug `curl`s, then one spec at `--workers=1`, plus two artifact
uploads. 23 → ~49 doubles minutes and artifacts and exceeds typical concurrent-job caps. No
`max-parallel`, no estimate, and no mention of the alternative that dissolves both the allowlist and its
guard: `--shard=i/N` over `tests/e2e/`. State the choice explicitly.

**9. The regex-trap paragraph solves a problem a YAML parse removes.** `pyyaml` is already declared
(`pyproject.toml:24`), so `yaml.safe_load(...)["jobs"]["e2e-tests"]["strategy"]["matrix"]["test"]` is
exact and immune to window-size and formatting drift. Both regex measurements are correct as stated (34
whole-file matches, including `main`, `unit-tests`, `frontend-build`, `wheel-build`, `e2e-tests` and the
integration matrix; exactly 23 inside a 5000-char window from `e2e-tests:`) — the measurement is right,
the recommendation is the worse of two options. Also anchor file paths with
`Path(__file__).resolve().parents[2]`, the repo convention (`tests/unit/test_startup_migrations.py:16`,
`tests/unit/test_app_wheel_dependencies.py:30`); a relative `Path(".github/...")` is cwd-dependent.

**10. A2's "Live symptom today" is overstated.** Nothing on `main` writes `slide_deck.deck_spec_json`.
Its only touchers are `create_version`'s snapshot (`session_manager.py:1939-1951`) and `restore_version`'s
copy-back (`:2240`), both propagating a value no producer ever sets. Every deck's spec is already NULL, so
the duplicate drops nothing today. The fix is still right and cheap to land now, but the table's claim —
and the index's "every item is a defect live on `main` today" — holds for A1, not A2. Call it **latent**:
live the moment ws4b's deck-level writer persists a spec.

**11. A1 tests only one direction.** Every listed assertion is about at-rules already in the deck
surviving. Today an `@media` block *in the replacement* is also dropped, and a replacement consisting only
of at-rules is discarded wholesale by `if not replacement_rules: return existing_css`. The plan never
states the new emptiness guard. Note the constraint: `test_css_utils.py:71-77` pins
`merge_css(existing, "") == existing` verbatim, so the early return must survive — which means ws4c's
aggregator cannot dedupe by concatenating and passing `""`; it must fold pairwise. "N identical copies
collapse to one (which ws4c's CSS aggregation needs)" is true only under a fold, and the plan should say
so since it cites that as a design justification.

**12. The dedupe key is whitespace-sensitive.** `tinycss2.serialize` reproduces source formatting exactly
(probed), so two copies of the same `@media` differing only in indentation both survive. Acceptable under
§M5 (identical bytes to every builder), but it is the first thing ws4c hits if any builder reformats.
Worth one line as a known limit.

**13. Two smaller items.** There is no root `run.py`; A3 should give the path the index does —
`packages/databricks-tellr-app/databricks_tellr_app/run.py`. And A3's "prose only, no test" decision would
look visibly safe if it cited `tests/unit/test_startup_migrations.py`, which already pins the true wiring.

**14. The conflict note names the wrong sibling.** ws4b's `test.yml` edit is the seed step at `:589`, ~90
lines below the matrix. **ws4e** (its lines 17-19 and 290) states that every new Playwright spec it writes
must be added to the matrix in the same commit — ws4e edits the *same block* A4 edits. That is the real
conflict, and it is unmentioned.

## Verified correct — do NOT re-litigate

A1's measured `merge_css(sheet, sheet)` output and the "known trap" output (both character-exact); A2's 11
constructor fields, `:1014-1026` and `:967-984`, and that `SlideDeckVersion.deck_spec_json` exists
(`session.py:358`); A3's two docstrings at `:4` and `:239` plus the pre-fork/`SystemExit(1)` wiring; A4's
23 entries at `test.yml:479-501`, 32+11+6=49, the exact nine-name gap set, and that `slide-viewer.spec.ts`
is the only spec in the repo mentioning a drawer or findings; `test.yml:589` being the e2e seed step;
`npm run typecheck` = `tsc -b` against a `{"files":[],"references":[…]}` root; and that all four spec
sections cited (§L2a, §B5, §L8, §C) exist and say what the plan summarises.

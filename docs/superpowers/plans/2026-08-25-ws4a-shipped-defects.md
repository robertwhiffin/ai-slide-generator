# ws4a — Shipped defects and CI hygiene

> **For agentic workers:** REQUIRED SUB-SKILLS: `superpowers:subagent-driven-development` **plus**
> `executing-plans-tellr`. **Read `2026-08-25-ws4-index.md` first** — this plan inherits its Global
> Conventions (environment, the cause-based baseline gate, the two rulings, execution requirements)
> and does not repeat them.

**Goal:** Fix three defects — **A1 is a live defect on `main`; A2 and A3 exist only on the
integration branch**, because PR1 added the symbols they touch, and both are latent there until
ws4b's writer lands — and make CI collect 20 of the 26 specs it currently ignores, with the six it
still does not collect named and reasoned.

**Why this is its own PR:** nothing here touches the graph, the schemas, or any file ws4b–e need.
Every item stands on its own merits and would be worth doing even if workstream 4 were cancelled.
Landing it first also means every later PR's Playwright specs execute in CI instead of shipping
uncollected.

**Depends on:** nothing. **Blocks ws4b** — its B3.3 `aggregate_deck_css` requires A1's
at-rule-preserving `merge_css`, which exists on no other branch (index `:76-78`). Land this first.
Also see Task A4's note on the shared workflow file.

**Spec:** §L2a (the `merge_css` defect), §B5 (`duplicate_session`), §L8 (the stale docstrings), §C
(the CI matrix).

---

## What is broken, in one table

| # | Defect | Status | Verified |
|---|---|---|---|
| A1 | `merge_css` drops at-rules because `parse_css_rules` discards them (`src/utils/css_utils.py:28-38`; the merge itself is `existing_rules.update(replacement_rules)` at `:70` — `:41` is only the `def`) | **Live defect on main:** Every slide-replacement edit silently drops the deck's `@media`, `@keyframes` and `@supports` rules. A branded deck loses its print rules and animations after one edit. `@font-face` survives only because `ensure_deck_token_css` re-emits it | Measured: `merge_css(css, css)` on a sheet carrying `:root`, `@font-face`, `section.slide`, `@media print`, `@keyframes` returns **only `:root` and `section.slide`** |
| A2 | `duplicate_session` builds `SessionSlideDeck(...)` without `deck_spec_json` (`session_manager.py:1014-1026`) | **Latent on main (PR1-only).** `deck_spec_json` does not exist on main yet; no writer touches it. The duplicate drops nothing today. Live the moment ws4b's writer persists a spec. | PR1-verified: constructor passes 11 fields; `deck_spec_json` was added in PR1; `duplicate_session` still omits it |
| A3 | Two docstrings in `src/core/backfill_session_slides_startup.py` (`:4`, `:239`) still say the backfill runs "from its FastAPI lifespan" | **Latent on main (PR1-only).** File does not exist on main; it was added in PR1. The code is correct; only the prose would be stale once the file exists. | PR1-verified: file exists on the branch at the stated line numbers |
| A4 | The `e2e-tests` job is an explicit **23-entry allowlist** (`.github/workflows/test.yml:479-501`) against **32** specs in `frontend/tests/e2e/` plus **17** more outside it | **Spec coverage gap.** A matrix entry maps **1:1 to a spec** — the run step is `npx playwright test tests/e2e/${{ matrix.test }}.spec.ts` (`:751`) — so 23 entries collect exactly **23** of the 32 specs in `tests/e2e/`. **9** are absent from the matrix and **17** sit outside `tests/e2e/`, where no entry can name them: **26 specs have never run in CI.** | Measured on this branch by yaml-parsing the workflow (never by regex): **23** matrix entries; **32** specs in `e2e/`, **11** directly in `frontend/tests/`, **6** in `user-guide/` — **49** on disk. **Carry no main-vs-branch entry arithmetic in this plan.** An earlier round put "23 (main) vs 26 on branch" and "main has 14 entries collecting 18" in this one cell; those cannot both be true, neither was measured, and an entry cannot collect more than one spec |

**A1 is ws4a's one deliberate exception to ruling R2** (the new path does not change existing code).
R2 records two exceptions across the five plans — the other is ws4c importing
`UNTRUSTED_DATA_NOTICE` — so do not read this as licence to widen either. A1 changes monolith
edit-path behaviour on purpose, because it is a bug fix with a user-visible symptom — not an
accommodation for the graph. Recorded in the index for exactly this reason.

---

## Files

| File | Change |
|---|---|
| `src/utils/css_utils.py` | `parse_css_blocks()` added; `merge_css` rewritten to carry at-rules. `parse_css_rules`'s existing `{selector: declarations}` contract is **unchanged** |
| `src/api/services/session_manager.py` | `duplicate_session` carries `deck_spec_json`, on both the live-deck and `version_number` branches |
| `src/core/backfill_session_slides_startup.py` | Two docstrings |
| `.github/workflows/test.yml` | **two edits** — the e2e matrix allowlist (`:479-501`) and the `backend` paths filter (`:36-39`) |
| `frontend/tests/**` | 17 `*.spec.ts` relocated into `tests/e2e/`. **`tests/user-guide/shared.ts` does NOT move** — see A4 |
| `docs/user-guide/README.md` | `:33`'s documented regeneration command `npx playwright test user-guide/` no longer resolves after the move; repoint it |
| `tests/unit/test_deck_css_at_rule_survival.py` | **new** |
| `tests/unit/test_duplicate_session_carries_spec.py` | **new**. `tests/unit/test_session_duplicate.py` is the *existing* `duplicate_session` suite and must stay green — reuse its `_make_root_session`/`_add_deck` fixtures |
| `tests/unit/test_e2e_matrix_covers_specs.py` | **new** |
| `docs/superpowers/baselines/pr3_ws4_collected.log` | **new**, directory included — the index designates ws4a the owner of the by-cause baseline every later plan compares against |

---

## Task A1 — `merge_css` must survive at-rules

**Contract.** `parse_css_rules(css) -> dict[str, str]` keeps its current behaviour and its current
tests. Two additions:

```python
@dataclass(frozen=True)
class CssBlock:
    key: str | tuple[str, str]   # qualified rule: its SELECTOR. at-rule: (at_keyword, discriminator)
    text: str         # qualified rule: the declaration block, serialized, no newline normalization.
                      # at-rule: the complete block, its prelude and its content
    is_at_rule: bool

def parse_css_blocks(css_text: str | None) -> list[CssBlock]: ...
```

An at-rule's key is `(at_keyword, discriminator)`, where the discriminator is
`tinycss2.serialize(rule.prelude).strip()` when that is **non-empty** and
`tinycss2.serialize(rule.content)` when it is not. Measured preludes: `("media", "print")`,
`("keyframes", "acme-fade")`, `("supports", "(display: grid)")`, `("import", 'url("brand.css")')`.
`@font-face` and a bare `@page` serialize an **empty** prelude, so they key on their content —
see the empty-prelude note below, which is load-bearing, not a footnote.

**Only two node kinds become blocks.** `tinycss2.parse_stylesheet(css, skip_whitespace=True)` also
yields `comment` nodes, and it yields a node for malformed input rather than raising — measured,
`bad {{{` comes back as a `qualified-rule` serializing to `'bad {{{\n}}}'`. `parse_css_blocks`
handles `qualified-rule` and `at-rule` and **drops everything else, which is what the current code
does**; do not add a third `CssBlock` state to carry comments. Two consequences the executor must
not treat as accidents: `_TOKEN_CSS_REEMIT_MARKER` (`design_system_templates.py:375-378`, "what a
reviewer greps for") does **not** survive an edit today and still does not after the fix; and
"serialize reproduces source formatting" holds for well-formed input only — a degenerate rule is
re-serialized, not echoed.

`merge_css(existing, replacement)` then merges over ordered blocks instead of a selector dict.

**Override ordering:** When a replacement rule matches an existing selector (or an at-rule matches by key), the overridden rule stays in its **original position** in the block list (use `dict.update` semantics, not append), so `@font-face` still precedes its consumers.

**`dict.update` alone does NOT deliver "`@import` first", so hoist explicitly.** Update semantics hold position only for keys that already exist; a **new** key appends. A replacement that introduces an `@import` (or `@charset`) the existing sheet lacks therefore lands **last**, where a browser ignores it outright — and both parse as at-rules with `content is None`, so both do reach the output. After merging, stable-partition the block list into `@charset`, then `@import`, then everything else, preserving relative order within each group. Three lines, deterministic, and it makes the invariant true instead of aspirational.

**The one design decision, and why it is neither of the obvious ones.** Dedupe keys at-rules on
**`(at_keyword, serialized_prelude)`**. Keying on `at_keyword` alone would make a second `@media`
overwrite the first — a worse defect than the one being fixed. Keying on the **exact serialized
block text** (this plan's earlier choice, **reversed 2026-09-10**) survives that test but makes
at-rules **append-only**, and that is fatal on a live path: `merge_css` runs from
`chat_service.py:2631` → `slide_deck.py:108`, its output is persisted (`session_manager.py:1366`)
and re-fed as `existing_css` on the next edit, so an *edited* `@media print` mints a new key,
appends, and the old copy is retained — `deck.css` grows monotonically and ships in every knit,
preview and export. Sharper still: `merge_css` deletes nothing by omission, so a qualified rule can
at least be neutralised by overriding its selector, while a text-keyed at-rule cannot be overridden
at all — **`@keyframes` becomes immortal** and "remove this animation" is unexpressible. Prelude
keying satisfies every assertion in the table below *and* makes at-rules updatable, because an
edited `@media print` keeps its key and replaces. N identical copies still collapse to one, which
**ws4b's** aggregator needs, because §M5 hands every builder the same full style block.

**Order is preserved** because CSS is order-sensitive: `@import` must come first (that is what the
hoist above is for) and `@font-face` should precede its consumers, so a merge that reshuffles
at-rules can change rendering.

**Known limit: two at-rules sharing a keyword and a non-empty prelude collapse to one.** Two
byte-different `@media print` blocks in one sheet are legal CSS; after the merge one survives — the
later block's text at the earlier block's position, which is what building a dict from an ordered
list does. Accept it: a sheet carrying two `@media print` blocks is already ambiguous, and the
survivor is the block the cascade would have applied anyway. Prelude whitespace is not part of the
key (`@media  print` and `@media print` key identically); whitespace *inside* a prelude is
(`(min-width:40em)` != `(min-width: 40em)`).

**The empty-prelude fallback is required, not a refinement.** Measured: every `@font-face`
serializes an empty prelude, and `_font_assets_section`
(`src/services/design_system_compiler.py:2295`) instructs the model to emit **one `@font-face` per
font file**, explicitly uncapped. Keying those on the prelude alone collapses a three-weight brand
font to **one** weight, and `ensure_deck_token_css` does **not** catch it: its guard is per-FAMILY,
not per-block — `token_families <= _font_face_families(deck)`
(`src/services/design_system_templates.py:406-411`). One surviving `@font-face` for the family
satisfies the check, so the token stylesheet is never re-emitted and the lost weights never return.
**That would be a regression against today's behaviour**, where dropping every `@font-face` empties
the deck's family set, the guard fails, and the backstop restores all of them; bold and italic would
silently degrade to browser-synthesised faux styling with no exception and no failing test. Keying
empty-prelude at-rules on their **content** preserves every weight. Its only cost is that an
*edited* `@font-face` appends rather than replaces — acceptable, because `@font-face` blocks are
machine-emitted from a deterministic sorted asset list, and changing a brand font recompiles the
whole stylesheet rather than editing one block. Carry both limits into the DoD, because ws4b's
aggregator inherits them.

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
| **Three `@font-face` weights of one family all survive `merge_css(sheet, sheet)`** | The empty-prelude fallback. Prelude-only keying collapses them to one, and `ensure_deck_token_css`'s per-family guard does not notice — so this assertion is the only thing standing between the fix and a silent font regression |
| An **edited** `@media print` replaces the existing one — one copy out, not two | The append-only failure the reversed text key would have shipped, on the path that re-feeds `deck.css` |
| A replacement introducing an `@import` the existing sheet lacks lands **before every qualified rule** | The hoist. `dict.update` puts a new key last, where a browser ignores it |
| A declaration block's internal whitespace and inline comment survive **verbatim** in the merged output | The only thing that makes `CssBlock.text`'s formatting contract enforceable — measured, nothing in the repo pins `merge_css`'s output text today |
| A top-level comment (use `_TOKEN_CSS_REEMIT_MARKER`'s literal text) does **not** survive the merge | Pins today's behaviour deliberately, so a future change to it is a decision and not a surprise |

**Emptiness guard — keep the early return, move its condition to `parse_css_blocks`.** Write
`if not replacement_blocks: return existing_css`. Keying the guard on `parse_css_rules`' output
instead would preserve half the bug: measured, today
`merge_css(existing, "@media print { .a { color: red } }")` returns `existing` untouched because
`parse_css_rules` yields `{}` and the early return fires, so an at-rule-only replacement would still
be silently dropped **after** the fix. `test_css_utils.py:71-77` pins only the empty-**string** case
and a blocks-keyed guard satisfies it unchanged; at-rule-only replacements now merge, which is a
deliberate behaviour change and belongs in the commit message.

**What the guard costs ws4b.** Because an empty replacement returns early, ws4b's CSS aggregator
(B3.3) cannot dedupe by concatenating every style block and merging the result with `""` — that
call never reaches the merge. It must **fold pairwise**, and "N identical copies collapse to one" is
true only under that fold. ws4c produces the style block and ws4b consumes it, so the constraint
lands on the consumer.

**Fixture.** One branded stylesheet carrying an `@import`, `:root` with two custom properties,
`@font-face`, `section.slide` referencing `var(--…)`, **two `@media` blocks with different preludes**
(`print` and `(max-width: 1200px)`, as `tests/fixtures/css/databricks_theme.css:308`/`:329` really
have), `@keyframes` and `@supports`. Every assertion in the table needs one of those blocks, so the
fixture must carry all of them; reuse it throughout so a failure names the block that was lost.

**Steps.** Write the tests → run and record the exact failure list (this failure *is* the shipped
defect; put it in `docs/superpowers/plans/.ws4a-PLAN-CORRECTIONS.md`, this plan's corrections file)
→ implement → run this file, `tests/unit/test_css_utils.py` (must pass **unchanged**),
`tests/integration/test_slide_replacement_flow.py` (it drives `update_css` at `:114`, but it makes
**no CSS assertion and there is no golden file** — measured, repo-wide nothing pins `merge_css`'s
exact output, which is why the verbatim-declaration assertion above exists; run it as a flow gate,
not as a formatting gate), and `tests/unit/test_deck_integrity.py::TestCSSMerging` (runs on
`load_databricks_theme()`, which carries two *different* `@media` blocks, so its output changes
after the fix) → sabotage → commit.

**Sabotage the behaviour, not a line this plan never specified.** Make `parse_css_blocks` return
only its qualified rules — at-rules excluded from the block list — confirm the at-rule assertions go
red, and confirm the sabotage sits on the executed path before reverting. The contract specifies only
`parse_css_blocks(...) -> list[CssBlock]`, so an instruction phrased against an `elif rule.type ==
"at-rule":` chain can miss a target that was never required to exist, and a sabotage that misses
looks identical to a test that cannot fail.

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
`head_meta` and `scripts` are all **also** inside that blob, re-derived on the blob read path
(`:1585-1594`) and re-written to their columns on the deck's first save (`:1366-1370`).
**`deck_spec_json` has no copy inside `deck_json`**, so nothing restores it. Being a sibling column
is *not* the distinguishing property: PR1 added four of them together — `deck_spec_json` (`:276`),
`css` (`:280`), `external_scripts_json` (`:288`), `head_meta_json` (`:299`) in
`src/database/models/session.py` — and `duplicate_session` omits all four. The other three heal on
first save; this one does not, which is exactly why its loss was invisible. **Do not "fix" the other
three here** — but know that a fresh duplicate's `css`/`external_scripts_json`/`head_meta_json`
columns read NULL until that first save, so a test asserting them non-NULL on a fresh copy is
asserting a false claim.

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

**The existing suite is `tests/unit/test_session_duplicate.py`, and it must stay green.** It is the
only file that reaches `duplicate_session`, it already pins the version branch with
`test_duplicate_from_save_point_uses_version_snapshot` (`:255`), and its `db`/`session_manager`
fixtures plus `_make_root_session`/`_add_deck` helpers are what the new file should build on. Read it
before scaffolding: a second set of hand-rolled fixtures is how the version-branch assertion above
ends up weaker than the one already in the repo.

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
   - **Option A (flatten+reason):** Move the six `*.spec.ts` into `tests/e2e/` and add `DELIBERATE_EXCLUSIONS` entries with a reason stating they are documentation, not functional specs.
   - **Option B (scope exemption):** Move the 11 non-user-guide strays into `tests/e2e/`, and leave user-guide where it is, adding an exemption to the guard's "no spec outside `tests/e2e/`" rule (same reason).

   **This plan chooses Option A (flatten).** Check each one's relative imports after moving; fix any paths.

   **`shared.ts` does not move, and its path does not change.** It is a helper, not a spec, so the guard's `*.spec.ts` scope never sees it: leaving it at `frontend/tests/user-guide/shared.ts` keeps `DOCS_IMAGE_BASE` (`:19`) at depth 3 and still correct. **Do not "update the path"** — the depth only breaks if `shared.ts` moves too, so editing it is how the screenshots start writing outside `docs/user-guide/images`. What does change is each spec's `from './shared'`, which becomes `from '../user-guide/shared'`.

   **Two costs Option A carries that Option B does not.** The six specs write PNGs into `docs/user-guide/images`, so once they sit in `tests/e2e/` a plain `npx playwright test tests/e2e/` dirties the working tree with regenerated screenshots — the `DELIBERATE_EXCLUSIONS` entries keep them out of CI but not out of a local full-directory run. And `docs/user-guide/README.md:33` documents `npx playwright test user-guide/ --project=chromium` as the regeneration command; that path stops resolving, so repoint it in the same commit (it is in the Files table).
   
2. **Add every uncovered spec to the allowlist.** Under Option A that is 23 existing + 9 absent + 11
   relocated non-user-guide = **43 entries**, with the six user-guide specs present in `tests/e2e/`
   but excluded by name. **Do the arithmetic from what is on disk after the move, not from this
   document** — a round-3 finding caught the superseded plan off by one here, and an off-by-one
   leaves a spec uncovered *and* fails the guard test below.

**Guard test** — `tests/unit/test_e2e_matrix_covers_specs.py`. The matrix is an explicit allowlist,
so a new spec ships uncollected **by default**; this test makes that a visible failure.

| Assertion | Note |
|---|---|
| every `*.spec.ts` in `tests/e2e/` is in the matrix or in an explicit `DELIBERATE_EXCLUSIONS` dict with a non-empty reason | An empty reason is not allowed — that is how an exclusion becomes a silent gap |
| no `*.spec.ts` remains outside `tests/e2e/` where the naming scheme cannot see it | Scoped to `*.spec.ts`, so `tests/user-guide/shared.ts` staying where it is does not trip it |
| `slide-viewer` specifically is in the matrix | Pins the named gap so a future re-drop is loud |

**Job count and parallelism.** This change grows the e2e matrix from 23 to **43** entries — not 49, because Option A excludes the six user-guide generators. Each entry is a full job: `npm ci`, `playwright install --with-deps chromium`, `pip install -e ".[dev]"`, Postgres service, DB seed, backend boot, and one spec at `--workers=1`. Budget by **attempts, not entries**: `retries: process.env.CI ? 2 : 0` (`frontend/playwright.config.ts:7`) means a flaky spec costs up to three runs inside its job, so "roughly doubles minutes" is the floor, not the estimate. This is an acceptable trade-off given the coverage gap (23 collected today, 26 never run), but worth acknowledging. Consider adding `max-parallel` to the job config if you hit concurrent-job caps. The alternative — `--shard=i/N` over `tests/e2e/` — would dissolve both the allowlist and its guard; that option was rejected in favour of explicit matrix control.

**The regex is a trap.** `r"^\s+- ([a-z0-9-]+)$"` against the whole workflow matches **34** items —
job names (`unit-tests`, `frontend-build`, `wheel-build`, `e2e-tests`), the branch `main`, and the
*integration* matrix. **Scope the search to the e2e matrix block** before applying it. **Better: use a YAML parser.** `pyyaml` is already in `pyproject.toml:24`, so `yaml.safe_load(...)["jobs"]["e2e-tests"]["strategy"]["matrix"]["test"]` is exact and immune to formatting drift. Also anchor file paths with `Path(__file__).resolve().parents[2]` (the repo convention per `tests/unit/test_startup_migrations.py:16`), not a cwd-dependent relative path.

**Workflow file edits — three of the five PRs touch this file, not two.** A4 edits `.github/workflows/test.yml` in **two** places (the matrix allowlist at `:479-501` and the `backend` paths filter); ws4b's B1.3 adds a `frontend-unit-tests` job; ws4e adds its layer-4 job near line 290. Coordinate all three: the matrix block and the two new jobs are in disjoint regions, but **the paths-filter block is the region every workflow-touching PR reaches**, so whoever lands second re-reads it rather than resolving by hunk.

**Important: the `backend` filter is at `:36-39`** (`:35-38` is the `filters: |` line plus two of the three globs) and gates the `unit-tests` job to `src/**`, `tests/**`, `pyproject.toml`. **Add `.github/workflows/test.yml` and `frontend/tests/**` to that filter**, else a PR editing only test.yml or adding frontend specs skips `unit-tests` entirely, and the guard test `test_e2e_matrix_covers_specs.py` never runs. The guard exists to catch spec-coverage gaps; a filter that makes it skip-able defeats its whole purpose. **Record the coupling this creates in the PR description:** `unit-tests` is gated on `backend` (`:85`) and `e2e-tests` requires it to have succeeded *or skipped* (`:471`), so after the change a frontend-spec-only PR runs `unit-tests` and one failing backend unit test blocks all 43 e2e jobs where it previously skipped them. That is the intended trade, but it should not arrive as a surprise.

**Expect newly-collected specs to fail.** 26 specs have never run in CI (9 absent from the matrix, 17
outside `tests/e2e/`); **20 of them start running here** (9 + the 11 relocated non-user-guide strays).
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
      These are PRD §3's no-regression gate and run on every PR in this set. **A1 cannot reach them**
      — `merge_css` has one production caller chain and none of these four imports it, directly or
      transitively — so a failure here is not an A1 regression and must be triaged as its own cause.
- [ ] `tests/unit/test_session_duplicate.py` passes **unchanged** — it is the only suite that reaches
      `duplicate_session`, and `:255` already pins the version branch A2 edits.
      (`tests/integration/test_savepoint_e2e.py` is *not* that safety net: its
      `test_duplicate_then_edit` at `:417` posts to `/api/slides/1/duplicate` — **slide**
      duplication — and never enters `duplicate_session`.)
- [ ] The at-rule dedupe's limits are recorded in the PR description for ws4b to inherit: two
      at-rules sharing a keyword and a **non-empty** prelude collapse to one; **empty-prelude
      at-rules (`@font-face`, bare `@page`) key on their content instead**, so an edited one appends
      rather than replaces; and the aggregator must fold pairwise, because an empty replacement
      returns early.
- [ ] Full suite compared **by cause** to the index's baseline: no new cause, no change to the
      deploy-autoscaling cause, and no test that stopped existing.
- [ ] **That baseline log is committed by this PR**, at `docs/superpowers/baselines/pr3_ws4_collected.log`
      (create the directory — it does not exist). The index makes ws4a its owner, and ws4b–e's
      "compare by cause to the index's baseline" has nothing to compare against until it lands.
      Record the cause list and the collected count, not a pass/fail number.
- [ ] `npm run typecheck` clean (never `npx tsc --noEmit` — it checks zero files).
- [ ] Relocation import verification: `cd frontend && npx playwright test --list` exits 0 with **zero
      unresolved-import errors** (cheap gate, needs no server). Assert on the errors, not on a count:
      `testDir: './tests'` (`playwright.config.ts:4`) already collects all 49 specs today, and only 17
      move, so a spec total cannot distinguish pass from fail.
- [ ] The e2e job runs green on the widened **43-entry** matrix, with any newly-surfaced failure either
      fixed or excluded-with-a-reason and listed in the PR description.

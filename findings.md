# Round 8 findings

Branch `ty/authz-optionc-e2e`, fresh worktree off tip `ad00745`. One commit per item.
Round 7's findings are preserved below, unedited.

Baselines captured BEFORE any edit, in this worktree:

| Gate | Baseline @ `ad00745` |
|---|---|
| `pytest tests/unit -q` | **2495 passed, 11 skipped** |
| `ruff check src tests` | **2176 errors** |
| `mypy src` | **551 errors in 84 files** |
| `COMPILER_VERSION` | **13** |

Frozen-invariant hashes at baseline (re-verified after every item):
`src/api/routes/_authz.py` = `afa344e8…e034647`,
`services/pptx-emit-huashu/preprocess.mjs` = `eec02c0c…8906a1`.

Environment: **PostgreSQL 14.22 (Homebrew)** live on `127.0.0.1:5432`, block_size
8192 — the same version codex used, so Item 3's live matrix was really run.

---

## R8 Item 1 — B1: the NAME HEURISTIC was the defect, not its pattern list

**Status: FIXED.** Commit `005abbc`.

### RED first — all ten of codex's rows, reproduced verbatim

Against `ad00745`, before any edit:

```
=== UNDER-inclusive (real font sizes, printed as SPACING) ===
  'fs–body'   / 16px   owns=False   norm='fs–body'      <- en dash survived normalization
  'fs．body'   / 16px   owns=False   norm='fs．body'      <- fullwidth period survived
  'fs‐body'   / 16px   owns=False   norm='fs‐body'      <- unicode hyphen survived
  'fs-body'   / 2cap   owns=False
  'fs-body'   / 0      owns=False
  'fs-body'   / small  owns=False
  'fs-body'   / large  owns=False
=== OVER-inclusive (NOT font sizes, but owned) ===
  'text-indent'                / 2em   owns=True
  'text-decoration-thickness'  / 2px   owns=True
  'text-gap'                   / 8px   owns=True
```

New spec `tests/unit/test_design_system_compiler.py`, class
`TestFontSizeOwnershipStemIsAWholeSegment`: **11 failed, 3 passed** before the fix.
The eviction codex measured is pinned as its own case and failed with
`'text-indent' is not a font size but holds the font-size heading`.

After the fix, all ten invert:

```
UNDER-inclusive: all 7 owns=True      OVER-inclusive: all 3 owns=False
```

### Which structural option, and why

**Option (a) — prefer the manifest's declared `kind` — was evaluated and REJECTED
on evidence.** It is the most appealing option on its face, and it does not work
here:

1. **There is no declared kind left to read.** `design_system_token` carries exactly
   `(group, name, value)` (`src/database/models/design_system.py:281-283`) and the
   importer writes `DesignSystemToken(group=, name=, value=)`
   (`src/services/design_system_service.py:712`). The manifest `kind` is mapped
   through `_KIND_TO_GROUP` and collapsed into `group` at import time, before the
   compiler ever runs.
2. **Where kind IS visible, it is WRONG for exactly these tokens.** A real Claude
   Design manifest declares
   `{"name": "--fs-12", "value": "12px", "kind": "spacing"}`
   (`tests/unit/conftest_design_system.py:112-115`). Preferring the declared kind
   would file the type ramp as spacing **by contract** — re-creating the v7
   small-titles defect as designed behaviour rather than closing it. The compiler
   has documented this manifest bug since v4.

So **(b) + (c)**: keep the name fallback, make both axes structural.

**(b) Name.** Separators are decided by **Unicode category** (`Pd`/`Pc`/`Po` plus
whitespace) via `_is_name_separator`, not a hand-listed ASCII class — hand-listing
code points is the same losing move one level down, and would leave the next
separator (em dash, ideographic full stop, non-breaking hyphen) broken. `Lo`/`So`/`Sm`
are not punctuation, so CJK, Cyrillic and emoji are preserved and `fs-サイズ-24` still
cannot collapse onto `fs-24` (pinned). The stem is a **whole segment**, never a
prefix: `_TYPE_SIZE_STEMS = ("fs", "font-size", "text-size", "type-scale")`.

**(c) Value.** Added `cap`/`rcap`, a bare `0`, and `small`/`large`. Still rejects
negative lengths, colours and malformed `calc()`.

### Two deliberate omissions from the suggested stem list

Both because the stem would be **ambiguous**, not merely awkward:

* **`size`** is in the suggested list but cannot be a stem: `size-gap: 8px` is an
  explicitly named frozen control, and a bare `size` segment does not say *what* is
  being sized. Verified: with `size` as a stem, `size-gap` becomes owned.
* **bare `text`** had to go. `text-gap` (codex: must not be owned) and
  `text-🎨-body` (round 7: was owned) are the **same shape** — `text` plus one
  word — so no whole-segment rule can own one and reject the other. The suggested
  list itself says `text-size`, not `text`.

**Consequence, stated plainly:** two existing fixtures were restated onto the
`text-size-*` spelling (`text-🎨-body` → `text-size-🎨-body` in
`_HOSTILE_NAMED_RAMP`; `text-percent` → `text-size-percent`). Those two tokens are
no longer *owned* under the bare-`text` spelling. Neither is dropped — both remain
in the artifact under their declared group — so the cost is a label, whereas the
prefix match's cost was evicting genuine spacing tokens *and* handing a non-size the
font-size heading. The collision is pinned by
`test_bare_text_is_not_a_stem_but_text_size_is` so it cannot be silently undone.

### COMPILER_VERSION

**13 → 14.** Compiled output changes in both directions, so persisted v13 rows hold
both mislabelings and must recompile.

### Gates

| Gate | Before | After | Net-new |
|---|---|---|---|
| `pytest tests/unit` | 2495 passed, 11 skipped | **2510 passed, 11 skipped** | +15, 0 failures |
| `ruff check src tests` | 2176 | 2176 | **0** |
| `mypy src` | 551 in 84 files | 551 in 84 files | **0** |

Zero tests disappeared. Frozen hashes for `_authz.py` and `preprocess.mjs` unchanged.
All 14 `test_authz_*.py` spec files pass (246 passed, 5 skipped under `-k authz`).
Goldens unregenerated; `git status` showed only the two intended files.

Frontend: **no frontend file was touched, so tsc/eslint were not run.**

---

# Round 7 findings

Branch `ty/authz-optionc-e2e`, worktree off tip `aaca44c`. One commit per item.

Environment note: a real **PostgreSQL 14.22 (Homebrew)** was reachable on
`127.0.0.1:5432`, so Item 1's mandatory live-Postgres matrix was actually run. No
Docker in this environment; none was needed.

---

## Item 1 — migration was non-idempotent and could hard-fail startup (CRITICAL)

**Status: FIXED.** Commit: see `git log` for `fix(database): stop the brand-text
column migrations from fighting each other`.

### RED first, on real PostgreSQL

New spec: `tests/unit/test_brand_text_migration_postgres.py` (5 tests).
Before the fix, 4 of 5 failed. Verbatim failures:

```
E  AssertionError: after migration run 1 these brand-text columns are NOT unbounded TEXT:
   {('design_system_token', 'group'): 255, ('design_system_token', 'name'): 255}
   -- test_fresh_database_stays_text_across_repeated_migration_runs

E  AssertionError: after migration run 2 these brand-text columns are NOT unbounded TEXT:
   {('design_system_token', 'group'): 255, ('design_system_token', 'name'): 255}
   -- test_legacy_narrow_database_converges_to_text_and_stays[legacy-50-100]

E  AssertionError: after migration run 2 these brand-text columns are NOT unbounded TEXT:
   {('design_system_token', 'group'): 255, ('design_system_token', 'name'): 255}
   -- test_legacy_narrow_database_converges_to_text_and_stays[legacy-255-255]
```

This reproduces codex's oscillation exactly: a **fresh `create_all` database was
NARROWED** on run 1, and the legacy databases **flipped back to 255** on run 2.

The killer case failed with the production boot failure, traced to the exact line:

```
src/core/database.py:537: in _run_migrations
    _migrate_widen_token_name(conn, inspector, schema, _qual, is_sqlite)
src/core/database.py:707: in _migrate_widen_token_name
E  [SQL: ALTER TABLE "design_system_token" ALTER COLUMN name TYPE VARCHAR(255)]
E  psycopg2.errors.StringDataRightTruncation: value too long for type character varying(255)
```

The whole migration runs inside a single `engine.begin()` transaction, so this
escaping error aborts every migration after it — a boot failure on a database
holding legitimate long brand tokens.

### Fix (structural)

(a) `_migrate_widen_token_name` / `_migrate_widen_token_group` are **retired to
no-ops**. Their target (`VARCHAR(255)`) is strictly narrower than the `TEXT` the
superseding migration produces, so there is no state from which they are an
improvement — a widener whose target is now `Text` must never fire. They are kept
as documented no-ops (not deleted) so the history stays discoverable in code and
in log archaeology; their call sites are replaced by a comment explaining why.

(b) `_migrate_uncap_brand_text_columns` now reflects with a **fresh inspector per
column** instead of the shared one threaded through `_run_migrations`. The shared
inspector caches reflection, which is why the uncap step used to *skip* the two
columns the widener had just narrowed. Deciding on a live read makes it converge
to `TEXT` from any starting state (varchar(50)/(100)/(255)/text) and be a true
fixpoint.

(c) The per-column `SAVEPOINT` is already inside a `try/except` that logs and
continues, so one problem column cannot abort the run. This is now **asserted**
rather than assumed.

### GREEN + non-tautology proof

All 5 pass on live Postgres. The containment test is proven non-vacuous: with the
`try/except` temporarily removed, it fails (`NotSupportedError`), while the other
four still pass — so it is specifically the containment it measures.

### CI gating

The module is marked `pytest.mark.postgres` (marker registered in
`pyproject.toml`) and **skips itself at module level** when no PostgreSQL answers:

```
$ TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:59999/nope pytest ...
1 skipped in 0.05s
```

So CI without Postgres is unaffected. Point `TELLR_TEST_POSTGRES_URL` at a
throwaway server to run it. Each test creates and drops its own uniquely-named
database; verified 0 leftover `tellr_migr_%` databases after a full run.

### Gates

| Gate | Before | After | Net-new |
|---|---|---|---|
| `pytest tests/unit` | 2466 passed, 11 skipped | 2471 passed, 11 skipped | +5 (the new spec), 0 failures |
| `ruff check src tests` | 2176 | 2176 | **0** |
| `mypy src` | 551 in 84 files | 551 in 84 files | **0** |

No test disappeared. The two pre-existing SQLite widener specs
(`tests/unit/test_design_system_import.py::test_widen_helper_is_a_noop_on_sqlite`
and `::test_widen_group_helper_is_a_noop_on_sqlite`) still pass — they assert the
no-op-on-SQLite contract, which retirement preserves and strengthens (now a no-op
on every dialect).

---

## Item 2 — B1: font-size ownership was wrong in BOTH directions

**Status: FIXED.** Spec: `tests/unit/test_design_system_compiler.py`, new class
`TestFontSizeOwnershipIsDecidedOnTheVisibleToken` (11 tests).

### RED first — all seven of codex's rows reproduced verbatim

Probing `_is_font_size_token` on the committed tip:

```
dotted-fs      'fs.body'            '16px'                   font=False   <- FALSE NEGATIVE
snake          'font_size_body'     '16px'                   font=False   <- FALSE NEGATIVE
camel          'fontSizeBody'       '16px'                   font=False   <- FALSE NEGATIVE
dotted         'font.size.body'     '16px'                   font=False   <- FALSE NEGATIVE
var-ref        'fs-var'             'var(--x)'               font=False   <- FALSE NEGATIVE
invalid-negative   'fs-neg'     '-8px'                   font=True        <- FALSE POSITIVE
invalid-function   'fs-calc'    'calc(not css at all)'   font=True        <- FALSE POSITIVE
```

And the U+001F ordering case — one string, two answers:

```
raw name        'fs\x1f-body'
ownership(raw)  False  <- classification runs BEFORE sanitization -> filed as SPACING
emitted name    'fs-body' -> visible token is 'fs-body'
ownership(safe) True   <- what the VISIBLE token would decide
```

9 of 11 tests failed RED; the two controls passed from the start.

### Fix

* **Name normalization** (`_normalized_token_name`): sanitize, split camelCase
  humps, collapse separator runs to a single `-`. So `fs.body` / `font_size_body` /
  `fontSizeBody` / `font.size.body` all reach `_TYPE_SIZE_NAME_RE` in a form it
  recognizes. The separator class is `[-_./\\:|\s]+` and deliberately **not**
  `[^0-9A-Za-z]` — see the regression note below.
* **Value grammar**: added a `var(--…)` arm (indirecting the scale through a custom
  property is the commonest way a DS references its own tokens); removed the leading
  `[+-]?` (there is no negative font size); and `calc()`/`clamp()`/`min()`/`max()`
  now require their contents to hold at least one length/percentage or custom
  property, so `calc(not css at all)` is no longer claimed.
* **Ordering**: ownership is decided on the **sanitized** name, so the string that
  decides is the string that emits.
* The **px-only ramp for band math is unchanged** — a non-px value still contributes
  no numeric band (codex's endorsed call), asserted directly.

### A real regression I caught and fixed mid-flight

My first normalization used `[^0-9A-Za-z]+`, which erased CJK/emoji: `fs-サイズ-24`
normalized to `fs-24` and collided with another rung of the same ramp. Corrected to
punctuation/whitespace only — normalization must unify separator conventions, never
erase script. Verified: `'fs-サイズ-24'` normalizes to itself, as does
`'text-🎨-body'`.

### One pre-existing assertion changed — with its stronger-successor argument

`TestEveryTokenNameIsKept::test_type_scale_region_emits_numbers_and_no_token_name`
asserted `"24px" in region` for section/upper-mid. That assertion **encoded the very
defect under repair**. Proof from the pristine tree:

```
BASELINE ramp: {64.0: 'fs-xxx…', 24.0: 'fs-サイズ-24', 18.0: 'text-🎨-body', 12.0: 'fs-12'}
BASELINE owns font-size/heading-xl: False
```

The fixture ships a 40px rung named `font-size/heading-xl`; the slash meant it was
not recognized as a font size, so **40px was missing from the ramp entirely** and
24px became upper-mid by default. With separators unified the ramp is complete
(12/18/24/40/64) and 40px is the correct upper-mid. The assertion is now `"40px" in
region` — strictly stronger, because it is made over the ramp the fixture always
described rather than the truncated one the defect produced. Nothing was dropped:
all five tokens still emit.

### Gates

| Gate | Before | After | Net-new |
|---|---|---|---|
| `pytest tests/unit` | 2473 passed, 11 skipped | 2484 passed, 11 skipped | +11 (new class), 0 failures |
| `ruff check src tests` | 2176 | 2176 | **0** |
| `mypy src` | 551 in 84 files | 551 in 84 files | **0** |

Test-name diff against the round-7 baseline junit: **0 disappeared**, 18 added.

---

## Item 3 — B3: `model_dump()` was not the choke point

**Status: FIXED.** Spec: `tests/unit/test_style_exclusivity_chokepoint.py`, new class
`TestModelDumpIsNotTheChokepoint` (8 tests).

### RED first — codex's five bypass rows + the exclude_none assertion

On the committed tip:

```
model_dump()            ['design_system_id']                 <- the only path that worked
model_dump_json()       slide_style_id":7 present -> True    <- BYPASS
dict(model)             ['slide_style_id', 'design_system_id'] <- BYPASS
raw attrs               7 3                                  <- BYPASS
exclude_none=True keys  ['design_system_id','slide_style_id','tools']
                        slide_style_id present? True value: None   <- CONTRACT VIOLATION
```

`SessionManager.create_session` (`session_manager.py:109-154`) took an
`agent_config` **raw dict** and assigned it straight onto the ORM row — a real,
reachable bypass, confirmed by a test that captures the row it adds.

4 of 8 tests failed RED (the 4 real defects); the 4 controls passed.

### Fix

* The `model_dump` override is replaced by a **`@model_serializer(mode="wrap")`**.
  Overriding one method only covers callers who choose it; pydantic v2's
  `model_dump_json` serializes through its Rust core and never calls a python
  override. A model serializer is what `model_dump`, `model_dump_json` **and nested
  serialization** all funnel through — the last of which the old override never
  reached at all.
* **`exclude_none` regression**: the slide style is now *removed* from the dump when
  `exclude_none=True` and nulled otherwise, so the option's contract holds.
* **`create_session`** normalizes its raw dict via a new
  `normalize_agent_config_dict`, which applies no policy of its own — it parses to
  the model and serializes back, so whatever the model enforces the dict inherits.
  It fails soft (an unparseable dict is stored as supplied, with a warning) so a
  normalizer cannot turn a previously-working create into a 500.
* **Not** a per-call-site normalization: one helper, used at the one raw-dict
  persister, deriving its rule from the model.

### The one row I did NOT "fix", deliberately, with the boundary asserted

`dict(model)` still shows both ids. It invokes no serializer — it is attribute
iteration, the same act as reading `config.slide_style_id`, which the PUT ordering
**requires** to keep working: `_validate_references` must see a dangling design
system *before* exclusivity is applied, or a user holding a dead pin plus a real
slide style ends up with neither. So the model must be able to hold both
transiently. Rather than paper over it, the spec asserts the boundary explicitly
(`test_dict_of_model_is_raw_attribute_access_and_is_not_a_persist_path`) and pins the
two tests that protect the ordering. Raw ORM assignment and bulk update are the same
category; the reachable one (`create_session`) is fixed where it persists.

### Semantics re-proven unchanged

```
model_dump / model_dump_json / exclude_none / sanitize_for_persist /
normalize_dict / in-place helper / nested dump / nested json
   -> all ['design_system_id']            (DS-WINS)
ds-only    -> ['design_system_id']        (untouched)
style-only -> ['slide_style_id']          (untouched)
both-set constructs fine                  (NOT a 422; legacy rows still HEAL)
```

All 81 tests across `test_style_exclusivity_chokepoint.py`,
`test_agent_config_schema.py`, `test_agent_config_routes.py` and
`test_chat_style_exclusivity.py` pass, so the application paths codex confirmed
(agent PUT, agent-patch-legacy, all three chat branches, profile-create,
duplicate-session, MCP create, sanitize_agent_config_for_persist) still hold.

### Gates

| Gate | Before | After | Net-new |
|---|---|---|---|
| `pytest tests/unit` | 2484 passed, 11 skipped | 2492 passed, 11 skipped | +8, 0 failures |
| `ruff check src tests` | 2176 | 2176 | **0** |
| `mypy src` | 551 in 84 files | 551 in 84 files | **0** |

0 tests disappeared against the round-7 baseline junit.

# ws4b — round 1 findings (VERBATIM, do not paraphrase)

Reviewer spot-checked ~60 `file:line` claims; the great majority are exact (including `_get_prompt_content`
really being 237 lines, `:250-263` really cutting mid-`return {`, the six test files really carrying
41/40/17/14/12/8 = 132 references, and `Send(timeout=)` raising the quoted `ValueError` on 1.2.10). The
failures cluster in three places: **fixtures that cannot be built as specified**, **a declared dependency
that is false**, and **frozen contracts whose existing consumers were never checked**.

## 1. BLOCKING — B1.7's sqlite engine fixtures are impossible as specified

> "`sqlite_engine_with_decks` … Throwaway sqlite with the deck tables built **by the real migration
> helper**, not `create_all`" and "Build the sqlite engines with the real `_migrate_*` helpers, never
> `create_all()`."

No `_migrate_*` helper in `src/core/database.py` creates any deck table. `grep 'CREATE TABLE'` over the
whole migration chain returns exactly one hit (`:1586`, the sqlite oauth-token recreate).
`_migrate_row_per_slide_schema`'s own docstring says it:

> "Note: session_slides table itself is created by Base.metadata.create_all() from the Task 1 ORM model
> (SessionSlide). This helper only handles the ALTER path for columns that create_all() will never add to
> already-existing tables in a live DB."

Worse, every column check is guarded `if decks_cols and "…" not in decks_cols:` — with no table present the
helper *silently does nothing*, so the fixture yields an engine with zero tables and no error.
`sqlite_engine_with_prompts` has the same problem (`config_prompts` is ORM-only). Every task from B2 onward
depends on these. The real fix for the PR1 defect being cited is a *separate* migration test against a
pre-migration table shape, not a create_all-free fixture.

## 2. BLOCKING — Part 2's "all ORM models → created by `create_all`" premise is unstated and probably false, and it contradicts B2.1's sabotage step

`create_all` only sees models registered on `Base.metadata` at `init_db()` time, which happens through the
single line `import src.database.models` in `src/core/database.py::init_db`.
`src/database/models/__init__.py` imports each model module explicitly (note `SessionSlide` is registered
only as an import side-effect of `session.py`, never exported). The plan puts the new models in
`src/core/checkpointer.py` and `src/services/deck_review_store.py` and **never says they must be
registered** — so by default `create_all` will *not* create `graph_checkpoints`,
`graph_checkpoint_writes` or `deck_reviews`.

That leaves two mutually exclusive statements:

- Part 2: "their `_migrate_*` helpers always short-circuit in production. **This is accepted**", and
- B2.1: "disable `_migrate_graph_checkpoints`' body and confirm the fixture and every test using it go red
  with 'no such table'. **If they stay green the fixture is building tables from the ORM — fix the
  fixture, not the test.**"

Exactly one can be true. As written, an agent that registers the models correctly will then be instructed
to "fix" a fixture that is behaving correctly. Pick one, and state the registration requirement either way.

## 3. BLOCKING — "Depends on: nothing (ws4a is parallel)" is false

B3.3's contract is "Merges the blocks with **ws4a's at-rule-preserving `merge_css`**", and its test intent
asserts "at-rules survive". Neither `parse_css_blocks` nor the rewritten `merge_css` exists on main.
Measured against the current `src/utils/css_utils.py`:

```
merge_css('@media (max-width:600px){.a{color:red}} .b{color:blue}', '.b{color:green}')
→ '.b {\ncolor:green\n}'
```

The `@media` block is destroyed, because `parse_css_rules` keeps only `rule.type == 'qualified-rule'`
(`:29`). B1.2's e2e rewrite is also ws4a-dependent — `slide-viewer` is confirmed absent from the matrix
list in `.github/workflows/test.yml` (`:479-501`). ws4b should declare `Depends on: ws4a` or scope
B3.3/B1.2 accordingly.

## 4. HIGH — B1.1 freezes the verdict shape without checking its existing consumer; the current UI throws

`get_slide_deck` puts `verification_data.get(content_hash)` straight into `slide["verification"]`
(`session_manager.py:1532`), which the frontend types as `VerificationResult`
(`frontend/src/types/slide.ts:8`). That interface requires `score`, `rating`, `explanation`, `issues`,
`duration_ms`, **`error: boolean`**. `VerificationBadge.tsx:117` returns null only for a falsy value, then
dereferences `.rating` (`:119`) and:

```tsx
{verificationResult.issues.length > 0 && (      // :201
```

A `{content_hash: {"tellr_review": {…}}}` verdict is truthy, so the badge renders grey
(`getRatingColor(undefined)` falls to the default) and **throws `TypeError: Cannot read properties of
undefined (reading 'length')`** the moment the user opens the details popup.

Two related problems: (a) B1.2 builds a conformance test for `finding.ts` but none for `verification.ts`,
which is the seam that actually breaks; (b) the rule "**no level carries `error`**" is stricter than the
repo mechanism requires — `is_placeholder_record` checks `verdict.get("error") is True`, so `error: false`
is safe — and it directly conflicts with `VerificationResult.error` being a required field.

Related over-claim: "makes a healthy slide read as a failed placeholder in **the release query, the
deck-review trigger and the UI badge**" — `is_placeholder_record` currently has **zero production
callers** (only `test_slide_writer.py` and `test_slide_writer_field_coherence.py`), and the badge doesn't
use it. The constraint is still right for ws4c/d; the present-tense framing isn't.

## 5. HIGH — `SlideVerdict`'s `"placeholder"` value is undetectable by the mechanism that detects placeholders

`commit_placeholder` writes `{content_hash: {"error": True, "message": …}}`, and its docstring names
`is_placeholder_record()` as "the supported way to detect it". B1.1 both puts `"placeholder"` in
`SlideVerdict` (so `build_verification_record(verdict="placeholder")` is legal) and asserts
`is_placeholder_record(build_verification_record(...))` is **False** with "no level carries `error`". So a
graph-written placeholder verdict is invisible to the release-order and deck-review-trigger code ws4c/d
will build on it. Resolve here: either drop the literal (placeholders only ever come from
`commit_placeholder`) or special-case it in `build_verification_record`.

## 6. HIGH — `make_finding_id(criterion, subject_hash)` collides on multiplicity

§K9's stability requirement is well argued and correct. Multiplicity is never mentioned. Two `overflow`
findings on one slide, or two `arc_gap` findings on one digest, produce **the same `id`**.
`FeedbackDrawer` uses it as `key={f.id}` and `data-testid={`finding-${f.id}`}` (`:125-126`), all three
callbacks are `(findingId) => …`, and `markSeen` folds ids into a `Set` (`seenState.ts:41`). Since these
ids are declared frozen, the composite needs a third component (ordinal or message digest) decided in this
PR.

## 7. HIGH — B2.4's test-side inventory is right about its six files and wrong about the surface

The six named files check out exactly (41/40/17/14/12/8). But at least six more Python test files hold real
references the R1 triage never sees, and several fail hard:

| File | Lines | Why it breaks |
|---|---|---|
| `tests/unit/config/test_models.py` | `89-90, 96, 139-140, 152` | Constructs `ConfigPrompts(system_prompt=…, slide_editing_instructions=…)` and asserts round-trip |
| `tests/unit/test_unset_agent_config_is_sql_null.py` | `129-130, 207-208` | Asserts the `agent_config` blob **stores** both keys — directly contradicts B2.5's strip |
| `tests/unit/test_settings_db.py` | `71-72, 102` | Asserts `"system_prompt" in settings.prompts`, the exact key B2.4 removes at `settings_db.py:386-387` |
| `tests/unit/config/test_services.py` | `173, 177, 290` | Profile-service update with `system_prompt` |
| `tests/unit/test_config_loader.py` | `150-151` | `required = ["system_prompt"]`, against `config_loader.py:130` |
| `tests/unit/test_default_config_integration.py` | `25` | `mock_settings.prompts` carries both |

Under the "no new cause" gate these are new causes. (False positives already checked so you needn't:
`html_to_pptx.py`, `html_to_google_slides.py`, `prompt_modules.py`, `design_system_compiler.py`,
`design_system.py`, `tests/conftest.py:146` are unrelated local names. The ~45 frontend `tests/` hits are
harmless — `frontend/tests/` is not type-checked, and they're Playwright route mocks where extra JSON keys
are ignored.)

## 8. MEDIUM-HIGH — B2.5's placement window already contains two writers of the keys it strips

> "wired into `run.py::init_database` after `init_db()` and before `seed_defaults()`"

That window is precisely where `migrate_profiles(get_session_local())` / `backfill_sessions(...)` run
(immediately after `init_db()`), followed by `backfill_unmigrated_decks`. And
`build_agent_config_from_profile` (`src/core/migrate_profiles_to_agent_config.py:51-56`) **unconditionally
emits both keys** into the blob. A strip placed early in that window is undone on the same boot. State the
ordering explicitly (strip last in the window), or make B2.4's edit to `migrate_profiles_to_agent_config.py`
a hard prerequisite of B2.5.

## 9. MEDIUM-HIGH — B3.2 names one blob fallback; there are two, and the new writer lands on the one it misses

The legacy path branches at `if deck.deck_json:` (`session_manager.py:1585`). When `deck_json` is falsy it
falls through to `# Legacy: return basic info without slides array` at **`:1637-1650`** — a dict with no
`slides`, no `css`, no `head_meta`, and nowhere for `deck_spec`. That is exactly the state B3.1's
pre-fan-out write creates on a brand-new session: deck row created, `deck_json` never assigned, zero rows.
So §7.1's spec view still has no data path in the one state the new writer produces, and B3.2's own
assertion ("a specless deck reports `deck_spec: None` rather than omitting the key") is violated by the
branch the plan doesn't name.

## 10. MEDIUM — B1.3 states a behaviour change with no test and no sabotage

The second row of B1.3's table — `unseenSlideIndices` (`SlideViewer.tsx:201-205`) and `hasUnseen` (`:525`)
ignoring `status === 'fixed'` — has no coverage. The only unit file named is `FeedbackDrawer.test.tsx`, and
the existing e2e `unseen indicator appears then clears once slide 1 is viewed` (`slide-viewer.spec.ts:324-337`)
still passes regardless, because `f2` stays open. It ships untested.

## 11. MEDIUM — B1.3's vitest contract collides with `tsc -b`, which the DoD requires clean

`tsconfig.app.json` is `include: ["src"]` with `types: ["vite/client"]` (the `paths` block really is
`:20-22`, and `frontend/src/components/ui` doesn't exist while `frontend/src/ui/` holds ten components, so
trap 1 is correct). Putting tests at `src/**/*.test.{ts,tsx}` therefore lands them *inside* the typechecked
project with no `vitest/globals` and no `@testing-library/jest-dom` matcher types, under
`noUnusedLocals`/`noUnusedParameters`. `vitest.config.ts` also falls outside both projects
(`tsconfig.node.json` includes only `vite.config.ts` and `playwright.config.ts`). The tsconfig decision
belongs in this contract.

## 12. MEDIUM — B2.2 contradicts itself on whether the digest is stored, and skips deck-owner resolution

"unique on `(deck_id, deck_digest)`" and then "**The digest is computed on read, never stored**". The intent
is presumably "not denormalised onto `session_slide_decks`", but read literally an implementer drops the
column carrying the unique key. Separately, `save_deck_review(session_id, …)` / `get_deck_review(session_id, …)`
take a session id against a table keyed on `deck_id`; the plan gives the `_get_deck_owner_session` rule only
in B3.1, so a contributor's deck review keys off the wrong deck.

## 13. MEDIUM — `Finding.slide_index` goes stale on reorder and nothing re-stamps it

Findings persist inside the content-hash-keyed record, which §F3 has travelling with its slide.
`findings_from_record(record, content_hash)` takes no position argument, so it must read `slide_index` back
from the payload. The drawer filters `f.slideIndex === currentIndex`, so after a reorder carried-over
findings attach to the wrong slide — the exact defect the per-row content-hash design exists to prevent.
Either drop the field and derive position on read, or name the re-stamper.

## 14. MEDIUM-LOW — B1.2's stated contract is thinner than B1.1's schema

"mirrors `Finding` field-for-field … and adds `FindingStatus`" understates it: current `SlideFinding` is
`{id, slideIndex, category, message, seen}`, so the mirror needs **three** new fields (`criterion`,
`objective`, `status`). Likewise the fixture guidance assigns a criterion only to `f3`; `f1` (design) and
`f2` (content) need theirs too. Worth stating that `frontend/tests/` is **not** type-checked, so nothing
catches a drifted fixture.

## 15. LOW — ambiguous bare filenames

`requests.py`, `responses.py` and `types.py` are cited without paths, and `src/api/schemas/requests.py` /
`src/api/schemas/responses.py` both exist alongside the `settings/` ones the line numbers actually match.
Also `databricks_client.py` is `src/core/`, not `src/services/`, and `database.py` is `src/core/database.py`.

## 16. LOW — count and range slips

- "**three of the four**" migrations no-op should be **two** by the plan's own enumeration — the
  dirty-marker `ALTER`s and the `DROP` are not create_all-shadowed.
- "five frontend consumers read `slideDeck.external_scripts`" — it's ten files (`PresentationMode`,
  `ThumbnailRibbon`, `SlideViewer`, `VisualEditorPanel`, `SlideTile`, `pdf_client`, `pptx_client`,
  `slideDocument`, `domWalker`, `screenshotCapture`). Strengthens the argument.
- `agent.py`'s legacy branch runs **620-675**, not 620-640.
- `encryption.py`'s NOTE is `:46-54`; `:44` is `_KEY_FILE`.
- `save_slide_deck` has **one** `deck.css` assignment (`:1366`), not "both assignments".
- `FeedbackDrawer`'s action block is `:135-160`; `:128` closes the `<li>`.

## 17. LOW — `SCHEMA_VERSION = 1` is dead

Declared in the B1.1 contract, then never used — no test asserts it, nothing writes it into a record. Either
wire it into `build_verification_record` so a future shape change is detectable, or drop it.

## 18. LOW — B2.5 doesn't name the `DROP COLUMN` dialect precedent

In-repo precedent worth pointing at: `src/core/database.py:1852-1870` wraps the sqlite `DROP COLUMN` in
try/except with "SQLite version may not support DROP COLUMN", and
`_migrate_drop_profile_id_from_oauth_tokens` (`:1566`) does a full table recreate.

## 19. LOW — cited lines leave dead parameters behind

`config_service.py:69-75` is the assignment block, but the retired kwargs are declared at `:29-30` with
docstring at `:41-42`. Same shape at `scripts/init_database.py`: the `ConfigPrompts(` call is `:218` but the
values are computed at `:209-216`.

## 20. LOW — B3.1's "title also updates the session row" duplicates existing code

`SessionManager.update_session` already sets both `session.title` and `session.slide_deck.title`
(`session_manager.py:908-911`). The plan explicitly forbids a second implementation for
`_get_deck_owner_session` but is silent here — and note `update_session` uses the *requesting* session's
deck, which is `None` for a contributor.

## 21. LOW — B2.1's inventory annotations are misleading in two spots

`delete_thread` is annotated "already on the base class" inside a list headed "implement these" —
`BaseCheckpointSaver.delete_thread` raises `NotImplementedError` on 4.1.1, so it must be implemented. And
"everything else has a working base-class default" is false for `prune`, `copy_thread` and
`delete_for_runs`, which also raise. Note `get_next_version` **does** have a working integer default
despite containing a `raise NotImplementedError` — verified a minimal saver omitting it runs a graph fine,
so don't add it to the implement list.

## Verified correct — do NOT re-check

`FeedbackDrawer.tsx:13`; `is_placeholder_record` at `slide_repository.py:41-61`; `get_verification_map` at
`session_manager.py:1793-1811`; `VERSION_LIMIT = 40` at `:1859`; `_get_deck_owner_session` at `:709` taking
a `UserSession`; every `save_slide_deck` anchor (`:1303/1309-1314/1320/1321/1356/1366/1403`) and the
`html_content` positional; `deck_spec_json`'s only two touchers (`:1939-1951`, `:2240`); `database.py:411`
before `:414`, reassign at `:584`; `search_path` at `:239/:259`; `provide_token` at `:305-312` and
`TOKEN_REFRESH_INTERVAL_SECONDS = 50*60`; `get_session_local()` returning a `sessionmaker`;
`slide_hash.py:44` and the wrong docstring example at `:69-72`; `_get_prompt_content` at 237 lines with the
`:250-263` mid-`return` trap; all seven `ConfigPrompts(...)` insert sites including `clone_profile` at
`:490`; `test.yml:589` inside a `fail-fast: false` matrix; `PromptsConfig`/`ProfileDetail` dead;
`migrate_profiles_to_agent_config.py:15,17,44-45,51-52,54,76-77` as pairs; all four frontend anchor sets;
`routes/sessions.py:233`; `export.py:84`; `knit()`'s `if self.css:` guard at `:454`;
`ensure_deck_token_css`'s prepend + marker + props/`@font-face`-only scope; `COMPILER_VERSION = 20`;
`databricks_client.py:492/:511-515/:536`; `user_context.py:21-23`; `types.py:64-70/:139-156`;
`session.py:135`; `profile.py:31`; zero `*.test.tsx` and five Playwright `test*` scripts;
`tsconfig.app.json:20-22`; `tests/unit/conftest.py` absent; langgraph 1.2.10 / langgraph-checkpoint 4.1.1
signatures; `JsonPlusSerializer` round-tripping `{0: None, "a": {1,2}}`; `Send(timeout=)` raising the quoted
`ValueError`; all four export/preview DoD suites exist; `package-lock.json` at zero artifactory hits.

# ws4b — Contracts, schema and deck-level persistence

> **For agentic workers:** REQUIRED SUB-SKILLS: `superpowers:subagent-driven-development` **plus**
> `executing-plans-tellr`. **Read `2026-08-25-ws4-index.md` first** — this plan inherits its Global
> Conventions (environment, the cause-based baseline gate, rulings R1/R2, the verified runtime facts,
> execution requirements) and does not repeat them.

**Goal:** Freeze every contract the graph binds to, land all four schema changes in one migration
pass, prove the checkpointer against real Lakebase, and build the deck-level write/read path — all
without a graph and without a model in the loop.

**Why this is its own PR:** §A1 is the organising insight. A skill's prompt *prose* is metadata; its
output *schema* is a contract, and the graph binds to it in four places at once — the reducers key
off it, `foreman_router` reads its fields, `finding.ts` mirrors it, the conformance tests parse it. A
schema change after ws4c starts ripples through all four plus the frontend types. So the contracts
land, and get reviewed, **before** any code binds to them.

**Depends on:** nothing (ws4a is parallel). **Blocks:** ws4c, ws4d, ws4e.

**The rule that makes this PR worth separating:** once merged, **a later PR that wants a schema field
which does not exist escalates back here — it never edits locally.** Three of the review loop's
blocking findings were exactly that violation.

**Spec:** §A1, §A2, §F1–§F4, §E2, §L3, §K4, §K7–§K9, §H1a, §H1b, §L2, §L2a, §L8, §M3, §G3, §C.

---

## Part 1 — Contracts

### B1.1 The canonical finding schema and criteria registry

**Contract** — `src/domain/finding.py`. Pure Pydantic; no DB, no framework imports.

```python
SCHEMA_VERSION = 1
VERDICT_KEY = "tellr_review"          # findings nest one level deeper than is_placeholder_record scans

FindingCategory = Literal["content", "design", "narrative"]     # CLOSED
FindingStatus   = Literal["open", "fixed"]
FindingLevel    = Literal["slide", "deck"]
SlideVerdict    = Literal["clean", "fixed", "surfaced", "placeholder"]

class FindingCriterion(BaseModel):
    name: str; category: FindingCategory; level: FindingLevel
    objective: bool          # PREDICATE: could a fixer handle this. NOT a state.
    description: str

CRITERIA: dict[str, FindingCriterion]

class Finding(BaseModel):
    id: str; slide_index: int          # -1 for deck-level
    category: FindingCategory; criterion: str; message: str
    objective: bool                    # predicate
    status: FindingStatus = "open"      # STATE: did a fixer handle it (§F2 branches on this)
    seen: bool = False                 # initial value only; lifecycle owned client-side

def make_finding_id(criterion: str, subject_hash: str) -> str
class SlideReviewOutput(BaseModel)     # slide_index, verdict, findings + objective/subjective splits
class DeckReviewOutput(BaseModel)      # findings
def build_verification_record(*, content_hash, findings, verdict) -> dict
def findings_from_record(record, content_hash) -> list[Finding]
```

**Three hard constraints, each with a measured defect behind it.** These are the reason this file is
canonical rather than convenient.

1. **`category` is a closed union** consumed by an exhaustive `Record<SlideFinding['category'], string>`
   at `FeedbackDrawer.tsx:13`. A fourth value **fails to compile**. So every criterion must map into
   the three — which is why §A2's criteria list is schema-relevant, not stylistic.
2. **`error` is reserved anywhere inside a verification record.** `is_placeholder_record`
   (`slide_repository.py:41-61`) returns True when the record's top level **or any verdict value
   inside it** has `error is True`. A finding payload using `error` makes a healthy slide read as a
   failed placeholder in the release query, the deck-review trigger and the UI badge. Hence
   `VERDICT_KEY`.
3. **A verdict stays inside the `{content_hash: verdict}` shape.** `get_verification_map`
   (`session_manager.py:1793-1811`) flattens every row's record into one dict that feeds
   `create_version`, so anything keyed otherwise is persisted into save points and silently lost.

**§A2's initial criteria — few, sharply defined, objective-heavy**, because PRD §14 names review
fatigue as a live risk and PRD §3 wants most defects fixed before the user sees them.

| Criterion | Category | Level | Objective | Note |
|---|---|---|---|---|
| `overflow` | design | slide | yes | Judge against `_SLIDE_FRAME_CONSTRAINTS`' numbers (§L5/§L7), never numbers the reviewer invents |
| `contrast_failure` | design | slide | yes | |
| `rogue_colour` | design | slide | yes | Outside the *resolved* contract — compiled artifact tokens, or the resolved style on the legacy branch |
| `distorted_image` | design | slide | yes | |
| `source_contradiction` | content | slide | yes | Only assertable against `resolved_data`; a figure with no cited source is not this finding |
| `brief_not_delivered` | content | slide | **no** | Exactly one subjective slide criterion, so the drawer's actionable path is exercised by real data rather than only fixtures |
| `arc_gap` | narrative | deck | no | |
| `cross_slide_repetition` | narrative | deck | no | |
| `missing_conclusion` | narrative | deck | no | |

**§K9's id rule, which is why this had to be settled here and not deferred.** Seen-state is persisted
client-side in `localStorage` keyed `(deckKey, finding.id)` (`SlideViewer/seenState.ts`), and two
requirements pull opposite ways: ids that are *not* stable make every carried-over finding re-highlight
as unseen each turn (PRD §14's fatigue failure), while ids that are *unconditionally* stable make a
finding legitimately re-raised after an edit read as already-seen. **A `(criterion, subject_hash)`
composite satisfies both** — stable while the slide is unchanged, different once it is edited.
`subject_hash` is the slide's `compute_slide_hash` for a slide finding, the deck digest for a deck one.

**Test intent** — `tests/unit/test_finding_schema.py`:

| Assertion | Why |
|---|---|
| every criterion's category is one of the three | Widening breaks the TS compile |
| slide criteria are objective-heavy; deck criteria are all narrative and subjective | §A2's posture, and §F3/§F4's grain split |
| an id is stable for the same `(criterion, hash)` and **changes** when the hash changes | Both halves of §K9 — one without the other is the bug |
| a `Finding` with an unknown criterion is rejected; one whose category contradicts the registry is rejected | The registry is the authority |
| `objective` and `status` are independent | The superseded plan's `auto_fixable` conflated predicate and state, which made §F2 unimplementable |
| `is_placeholder_record(build_verification_record(...))` is **False**, and no level carries `error` | Constraint 2 |
| the record's only top-level key is the content hash | Constraint 3 |
| findings round-trip through the record | |
| PR1's placeholder shape still reads as a placeholder | The other direction — don't break what works |

**Sabotage both constraint tests.** Put `error: True` where the helper can see it and confirm red;
add a criterion with a fourth category and confirm red (pydantic may reject it at import, which is a
*stronger* guard — record which mechanism caught it). Confirm each sabotage landed on the executed
path before believing the guard is real.

**Do NOT write `test_every_criterion_maps_into_the_closed_union` as a loop over `CRITERIA`
asserting membership.** `FindingCriterion.category` is already typed `FindingCategory`, so pydantic
rejects a fourth value at construction and the test is a tautology. The real risk is the **TS union
drifting from the Python**, and B1.2's `test_category_label_record_is_exhaustive_over_the_union` is
what covers it. (Round-3 finding 25.)

---

### B1.2 Mirror the schema into `finding.ts`, with a conformance test

**Contract** — `frontend/src/types/finding.ts` mirrors `Finding` field-for-field in camelCase, and
adds `FindingStatus`. `DrawerCallbacks` is unchanged.

**Why a conformance test rather than trust:** there is no runtime bridge between the two, which is
exactly why they had already drifted — the backend produced `{category, severity, description,
auto_fixable}` while the frontend declared `{id, slideIndex, category, message, seen}`. §7.1 names
this seam explicitly.

**Test intent** — `tests/unit/test_finding_conformance.py`, which *parses the TypeScript*:

- every backend field has a camelCase mirror, and `finding.ts` declares no field the backend lacks
- the `FindingCategory` union equals the categories in `CRITERIA` equals exactly the three
- the `FindingStatus` union is exactly `open | fixed`
- `CATEGORY_LABEL`'s keys are exhaustive over the union (`FeedbackDrawer.tsx:13`) — **this is the
  test that matters**, per finding 25 above
- a real `Finding.model_dump()` maps to the exact camelCase dict the frontend will read

**Sabotage:** rename `message` → `description` in the mirror only and confirm red. A conformance test
that survives a rename is the entire defect.

**Fixture and e2e consequences — the part that is easy to miss.**
`frontend/tests/fixtures/findings.ts` exports **`mockFindings`** with **three** entries: `f1`/`f2` on
`slideIndex: 1` and **`f3` on `slideIndex: 3`**. All three need the new fields, and one must carry
`status: 'fixed'` so the read-only branch has coverage. **Keep the ids** — about ten assertions in
`frontend/tests/e2e/slide-viewer.spec.ts:314-359` key on them, and after ws4a that spec runs in CI.

Two specific breakages to handle rather than discover:

- `slide-viewer.spec.ts:353-360` is `'Apply and Discuss buttons are present on each finding'` — note
  **no Dismiss**, contrary to what an earlier draft claimed. Rewrite it to assert the branch:
  `f1` (fixed) renders read-only with no action buttons and a "Fixed" marker; `f2` (open) renders all
  three.
- `slide-viewer.spec.ts:341-352` (`dismiss removes a finding from the drawer`) clicks
  `finding-dismiss-f1`, which **will not render** once `f1` is `status: 'fixed'`. **Repoint it to
  `f2`**, which stays open and actionable. This test is currently untouched by the change and would
  break silently.
- The spec uses `openDeck(page)` + `thumbClick(page, 'ribbon-thumb-1')`. There is no
  `openDrawerOnSlide` helper — an earlier draft invented one.
- `f3` carries `criterion: 'arc_gap'`, a **deck**-level criterion, on `slideIndex: 3`. That is fine
  for a drawer *layout* fixture but contradicts the grain-routing rule, so say so in a comment — and
  do not let it become the basis of a deck-level assertion.

---

### B1.3 Frontend unit-test runner, and the drawer's `status` branch

There is no FE unit runner today: all five `test*` scripts in `frontend/package.json` are Playwright
variants and there are zero `*.test.tsx` files. §F2's read-only branch is a component concern badly
served by E2E, so the runner lands here rather than as a follow-up.

**Contract:** `vitest` + `@testing-library/react` + `jsdom`, a `test:unit` script, `vitest.config.ts`,
`src/test/setup.ts`. The five Playwright scripts are untouched, and vitest's `include` is
`src/**/*.test.{ts,tsx}` with `tests/**` excluded so it never collects a Playwright spec.

**Two traps, both measured.**

1. **The `@/ui` alias must resolve to `frontend/src/ui/`**, not `./src/components/ui` — the latter is
   empty. `tsconfig.app.json:20-22` declares only `"@/*": ["./src/*"]`, so an aliases block claiming
   to "mirror tsconfig" and adding a second entry is already diverging. A wrong `@/ui` currently
   works only by accident, because Vite matches the earlier `'@'` entry first, and breaks on any
   reordering. (Round-3 finding 27.)
2. **The npm registry lockfile rule.** Your laptop resolves npm through the Databricks proxy; CI
   resolves through public npmjs. After `npm install`, rewrite the lockfile's `resolved` URLs to
   `registry.npmjs.org` before committing, and confirm zero `artifactory` hits. This repo has been
   bitten by it.

**Behaviour changes** — §F2's two halves plus the interaction that neither implies on its own:

| Change | Site | Why |
|---|---|---|
| suppress Apply/Dismiss/Discuss when `status === 'fixed'`; add a "Fixed" marker | `FeedbackDrawer.tsx`, replacing the unconditional action block at `:128-160` | §F2: an auto-fixed finding is **reported** (PRD §3 wants what was fixed visible) but not **actionable** |
| `unseenSlideIndices` and `hasUnseen` both ignore `status === 'fixed'` | `SlideViewer.tsx:201-205` and `:525` | Otherwise the unseen badge nags about work already done — the exact fatigue symptom §F2's read-only presentation exists to avoid. §F1 lists this as the third settled field |

**Test intent** — `FeedbackDrawer.test.tsx`: an open finding renders all three actions; a fixed
finding renders none and is labelled; the two render correctly when mixed. **Sabotage** by replacing
the status gate with `true &&`, confirm red, and grep to confirm the edit landed.

---

### B1.4 Deck spec models

**Contract** — `src/domain/deck_spec.py`. Pure Pydantic; **no DB imports** (`src/domain/` has none
today, and persistence belongs to B3.1).

```python
class DesignContractRef(BaseModel):     # WHICH brand, never the compiled content
    design_system_id: int | None; template_id: int | None; slide_style_id: int | None
class ResolvedFigure(BaseModel):  key: str; value: str; source: str
class ResolvedData(BaseModel):    synthesis: str; figures: list[ResolvedFigure]; gaps: list[str]
class SlideSpec(BaseModel):
    position: int; purpose: str; content_brief: str; assumes: str; hands_off: str
    data_references: list[str]; template_section_index: int | None
class DeckSpec(BaseModel):
    audience: str; purpose: str; argument: str; call_to_action: str
    narrative_arc: list[str]; design_contract: DesignContractRef
    resolved_data: ResolvedData; slides: list[SlideSpec]
    def slide_at(self, position: int) -> SlideSpec | None
    def to_json(self) -> str
    @classmethod
    def from_json(cls, raw: str | None) -> DeckSpec | None    # never raises
```

**Four invariants the validators must enforce, each with a reason:**

- **`design_contract` stores a reference, never content (§L3).** `compiled_style_content`'s currency
  is an **exact** `COMPILER_VERSION` match, so a snapshot in the spec is stale the moment the version
  moves and the spec would silently drive builds from a superseded artifact. §4.1's "+ image
  guidelines" needs no field either: `image_guidelines` is a column on `slide_style_library` resolved
  only on the legacy branch, so `slide_style_id` *is* the reference.
- **A design system and a slide style are mutually exclusive** (§L1, enforced in three places
  downstream). Reject both-set.
- **`template_id` requires a `design_system_id`** — a template belongs to one.
- **`template_section_index` is an INDEX, never markup** (§M3). Brand bytes never pass through a
  model, and a spec carrying layout bytes would also go stale against its template.

**`slide_at` looks up BY position, never by list index** — `SlideSpec` carries an explicit `position`,
and the two diverge after a delete or a partial multi-target rebuild, at which point indexing by list
position silently briefs a builder for the wrong slide.

**`from_json` returns `None` rather than raising.** A deck may legitimately have no spec (pre-cutover
decks, MCP-built decks) and a hand-edited column may not parse; spec §4.3 has the architect back-fill
an absent spec, which it cannot do if the read raised.

**Review criteria are NOT a spec field** (§4.2). If the architect authored the standard it is judged
against, review independence would be nominal. Assert their absence — `review_criteria`, `criteria`,
`rubric`, `quality_bar` — so a later "helpful" addition fails a test.

**Test intent:** the four validator rejections; `slide_at` by position with a gap in the sequence;
positions unique; JSON round-trip lossless; `from_json` tolerates `None`, `""`, malformed JSON and a
partial object; criteria absent.

---

### B1.5 The five remaining skill output schemas

B1.1 covered `build_reviewer`, `fix_reviewer` and `deck_reviewer` (they share
`SlideReviewOutput`/`DeckReviewOutput`). This covers the rest plus the registry.

**Contract** — `src/domain/skill_io.py`:

```python
ArchitectIntent = Literal["discuss", "ask_data", "build", "edit", "confirm_design_contract"]
class DataRequest(BaseModel):    metric, time_bound, grouping, units, tool_preferences
class ArchitectOutput(BaseModel): intent, message, deck_spec?, data_request?,
                                  target_positions, proposed_design_contract?
class AnalystOutput(BaseModel):   outcome: Literal["success","missing_data","no_tool"], synthesis,
                                  sources, gap, tried_tools, reason
class BuilderOutput(BaseModel):   position, html, scripts: str
class FixerOutput(BuilderOutput): changed: bool, change_summary
OUTPUT_SCHEMAS: dict[str, type[BaseModel]]      # exactly the seven skill names
```

**The load-bearing validators:**

| Validator | Why it is not decoration |
|---|---|
| `intent='build'` requires `deck_spec`; `ask_data` requires `data_request`; `edit` requires `target_positions`; `confirm_design_contract` requires `proposed_design_contract` | Each intent's payload is what the router acts on. `confirm_design_contract` holds its proposal **outside** `deck_spec` on purpose, so nothing restyles before the user answers (§4.6/§M1) |
| `outcome='success'` requires **both** `synthesis` and `sources` | "Single source → pass through, do not re-summarise" and "synthesis only engages with 2+ sources" are both uncheckable without the source list |
| `outcome` is a closed union | Spec §5.2.2's three outcomes are the testable contract |
| `BuilderOutput.html` must contain **no `<style>` element** | Spec §5.2.3: deck-level CSS has a single writer, and n builders each emitting `<style>` would collide on shared deck state |
| `scripts` is `str`, not dict | Matches `src/domain/slide.py`'s JavaScript-source-text field |

**`scripts` is `str` everywhere — pick it once, here.** ws4d declares a `scripts` field on
`StreamEvent` too; it must be the same type. An earlier draft had `str` in one place and
`Optional[str]` in the other, and wrote a near-unfalsifiable test to paper over it
(`assert … in (str, "Optional[str]", type(None))`, where the string literal can never match an
annotation object). (Round-3 finding 26.)

**Test intent:** all seven names present and each a `BaseModel`; each validator's rejection; the
architect's discuss turn needs no deck spec (PRD §4.1: a substantive shaping conversation with zero
slides); a builder emitting `<style>` is rejected; `scripts`' annotation is exactly `str`.

---

### B1.6 CI schema smoke tests (§G3)

**Contract:** one realistic canned payload per skill under `tests/fixtures/skill_payloads/<skill>.json`,
and `tests/unit/test_skill_schema_smoke.py` asserting, for each of the seven: the payload file exists,
it parses against its schema, the schema emits JSON Schema (it is shipped to the model as a
structured-output contract), and it round-trips.

**Why realistic and not minimal:** a payload trimmed to required fields lets an optional field's type
rot undetected.

**This is the gate that stops a prompt edit breaking its own output schema and shipping green** — the
"test that cannot fail" class this project has paid for twice. **Sabotage it:** rename a field in one
payload and confirm that skill's parse test goes red.

---

### B1.7 Shared test fixtures

**This is the largest single dependency in the PR and it currently exists nowhere.**
`tests/unit/conftest.py` does not exist — only `tests/conftest.py`,
`tests/unit/conftest_design_system.py` and `tests/unit/conftest_images.py`. Everything from B2
onwards depends on these, so they are built here, first, with contracts stated.

**Contract — one table, and the methods are part of it.** A fixture whose methods are undeclared is
a fixture the next task guesses at; round-3 finding 13 caught ~20 such methods and three fixtures used
but never declared.

| Fixture | Exposes | Purpose |
|---|---|---|
| `sqlite_engine_with_decks` | a bound engine | Throwaway sqlite with the deck tables built **by the real migration helper**, not `create_all` |
| `sqlite_engine_with_prompts` | a bound engine | Same, with `config_prompts` |
| `deck_fixture` | `session_id`, `deck_row()`, `prune_all_versions()` | One `SessionSlideDeck`; prune deletes every `SlideDeckVersion` for it |
| `deck_with_three_rows` | `session_id`, `rows()`, `row_snapshot()`, `deck_row()`, `deck_json()`, `version()`, `session_row()`, `deck_row_for(sid)`, `set_raw_deck_spec_json(s)`, `get_slide_deck()`, `duplicate(version_number=None)`, `create_version()`, `version_count()` | The workhorse. `row_snapshot()` must capture enough to prove **no row changed** |
| `deck_with_spec` | the above plus `set_spec_audience(str)` | Carries a parsed deck spec |
| `deck_with_spec_but_no_rows` | `get_slide_deck()` | Forces the `deck_json` blob-fallback read path |
| `deck_with_verdicts` | `verdict_for_html_at(pos)` | Keyed by content hash, so a verdict can be followed across a reorder |
| `deck_with_marker` | `set_marker(age_seconds=, author=)`, `set_claim(age_seconds=)`, `deck_row()`, `restore_latest_version()`, `restore_version(n)` | The dirty marker's clock is injected, never slept on |
| `partial_deck` | `land(positions=[…])`, `placehold(position=)`, `session_id` | Drives release-order assertions |
| `released_deck` | `session_id` | A deck with a committed ascending prefix |
| `stub_writer` | `written_positions`, `written`, `placeheld` | Monkeypatches `SlideWriter`, recording `(position, html)` **in call order** — order is the assertion in ws4c/d |
| `contributor_session` | `contributor_session_id`, `owner_deck_row()` | Contributor writes must reach the deck owner |
| `contributor_session_with_spec` | `get_slide_deck_as_contributor()` | §7.5: spec visibility equals deck visibility |
| `session_with_messages(user_msgs, assistant_messages=None)` | returns a session id; `session_messages(sid)` helper | ws4d's engine-mode resolution reads the earliest `role='user'` row |
| `empty_session`, `mcp_created_session` | session ids | The no-message and non-chat cases |
| `session_with_spec_and_messages` | `session_id` | Context clearing keeps the spec |
| `session_and_profile_with_legacy_blobs` | `session_local`, `reload_blobs()` | B2.5's JSON-key migration |
| `session_with_garbage_blob` | `session_local` | See the trap below |
| `as_user(username)` | context manager | Stamps identity for `modified_by` / permission assertions |
| `other_user` | context manager | A different principal, for permission denials |
| `fake_queue` | `.items` | ws4d asserts the emitter queues the **object**, not a string |

**Fixture engines must call `create_all()` after `init_db()` to populate deck tables.** The `_migrate_*`
helpers for `graph_checkpoints`, `graph_checkpoint_writes`, and `deck_reviews` assume their tables already
exist (they perform `ALTER` and `DROP` operations only, never `CREATE TABLE`). In production this is safe
because `create_all()` runs at `database.py:411` before `_run_migrations` at `:414`. In test fixtures:
- Call `init_db(engine)` to load the ORM and apply migrations (which no-op on empty tables)
- Ensure the new models are **registered on `Base.metadata`** — a missing import of the model module means `create_all()` skips those tables
- Call `create_all(bind=engine)` to materialize the deck-level tables, then `_run_migrations(conn)`
- Verify the fixture produces non-empty `engine.table_names()` or fail loudly rather than silently

**This matters because:** a fixture that yields an engine with zero tables and no error is exactly the
measured PR1 defect where an idempotency test stayed green with the migration disabled. Guard with an
explicit assertion.

**Trap for `session_with_garbage_blob`.** `agent_config` is a `NormalizedAgentConfig` (JSON) column,
so decoding happens in the type's **result processor during the query**, outside any `try` in the
consuming function. A genuinely unparseable blob raises before a guard in the caller can see it. So
either make the fixture produce something that survives decode but fails downstream, or drop the
"skipped not raised" assertion as unreachable and say which. (Round-3 finding 29.)

---

## Part 2 — Schema: four migrations in one pass, and the checkpointer

**Where migrations run:** the chain reached from `run.py::init_database`, **pre-fork**, via
`init_db()`. Each step `raise SystemExit(1)` on failure, so an app that reaches RUNNING is proof the
migration applied (§L8).

**Order, and the two facts that constrain it:**

1. **`create_all(bind=engine)` runs at `database.py:411`, BEFORE `_run_migrations` at `:414`.** So
   `graph_checkpoints`, `graph_checkpoint_writes` and `deck_reviews` — all ORM models — are created by
   `create_all`, and their `_migrate_*` helpers always short-circuit in production. **This is accepted**
   (repo precedent: `_migrate_design_system_tables`' own docstring says the same), and the helpers
   still earn their place for sqlite test paths and for explicitness. **But do not write ordering
   rhetoric that claims otherwise** — "X must run first or nothing works" is false for three of the
   four. (Round-3 finding 22.)
2. **`_run_migrations` ends with `_reassign_new_objects_to_shared_owner(conn, is_sqlite)`**
   (`database.py:584`), whose comment reads *"Runs LAST so every object created above … is re-homed
   onto the shared owner."* Appending after it leaves the raw `CREATE INDEX` statements in the new
   helpers owned by the app's service principal for that boot. **Place the four steps BEFORE the
   reassign**, and state that as the reason. (Round-3 finding 12.)

Within that placement the four are ordered: checkpointer tables → `deck_reviews` → dirty marker →
`ConfigPrompts` drop **last**, and only after B2.4 has stopped every writer.

### B2.1 The checkpointer

**Contract** — `src/core/checkpointer.py`: `SqlAlchemyCheckpointSaver(BaseCheckpointSaver)` plus
`get_checkpointer()` returning a **process-wide** instance. Tables `graph_checkpoints` and
`graph_checkpoint_writes`, keyed `(thread_id, checkpoint_ns, checkpoint_id[, task_id, idx])`.

**Why custom rather than `langgraph-checkpoint-postgres`** — this is a correctness requirement, not a
preference. `PostgresSaver(conn: Conn, …)` holds a live psycopg connection. Lakebase's OAuth token
reaches connections **only** through `provide_token`, a SQLAlchemy `do_connect` listener on the
**engine** (`database.py:303-312`), refreshed on a 50-minute timer against a 1-hour expiry. A saver
holding a raw connection never traverses that listener, so its writes begin failing about an hour
into every deployment — **in production only, and invisibly to any test that mocks the database.**

**Verified surface on `langgraph-checkpoint` 4.1.1** — implement these; everything else has a working
base-class default:

```
get_tuple(config) -> CheckpointTuple | None
list(config, *, filter=None, before=None, limit=None) -> Iterator[CheckpointTuple]
put(config, checkpoint, metadata, new_versions) -> RunnableConfig
put_writes(config, writes: Sequence[tuple[str, Any]], task_id, task_path="") -> None
delete_thread(thread_id) -> None        # already on the base class — ws4d uses it for context clearing
CheckpointTuple = (config, checkpoint, metadata, parent_config, pending_writes)
JsonPlusSerializer().dumps_typed(obj) -> (type: str, bytes);  loads_typed((type, bytes)) -> Any
```

Note this inventory is the subset the compiled graph uses; `prune`, `copy_thread`,
`delete_for_runs`, `get_delta_channel_history`, `with_allowlist` and the `a*` methods also exist and
are deliberately left to the base class.

**Three traps, all measured.**

1. **`get_session_local()` returns a `sessionmaker`, not a `Session`.** `with sessionmaker() as s`
   raises `TypeError: 'sessionmaker' object does not support the context manager protocol`. The
   session-opening helper must call it **twice**. A fixture that injects an explicit factory hides
   this, which is how it survived review once.
2. **Do NOT schema-qualify the raw SQL.** `database.py:239,259` append
   `options=-csearch_path%3D{schema}` to the **connection URL**, so every pooled connection carries
   it — and `src/core/encryption.py:44-54` is an explicit in-repo NOTE relying on exactly that, with
   deliberately unqualified raw SQL "because this module must also run against SQLite (unit tests —
   no schemas)". **Follow `encryption.py`.** Unconditional qualification also breaks every sqlite
   unit test, and there is no `LAKEBASE_SCHEMA` symbol to import — `database.py` only reads
   `os.getenv("LAKEBASE_SCHEMA", "app_data")` locally. (Round-3 finding 1.)
3. **Sync only.** `BaseCheckpointSaver`'s async methods raise `NotImplementedError`, and the whole
   generation path is sync end to end. Never `astream`. Consequence, recorded in the module docstring
   because it decides ws4c's stall design: **`Send(timeout=)` is unusable** — it raises
   `ValueError: Node timeouts are only supported for async nodes…`.

**Test intent** — `tests/unit/test_checkpointer.py`, **against a real sqlite engine, never a mock.**
Mocking is precisely what would hide the failure mode this design exists to avoid.

- `put` → `get_tuple` round-trips, including a `set`, an **int-keyed dict** and a `None` value — the
  shapes `GraphState` actually stores, which a naive `json.dumps` would not survive
- `get_tuple` with no `checkpoint_id` returns the latest; with one, returns that one
- `list` is newest-first and honours `limit`; `parent_config` links successive checkpoints
- `put_writes` replays as `pending_writes`; threads are isolated; `delete_thread` clears both tables
- `get_checkpointer()` is process-wide (one shared saver — a per-session saver would open a
  connection per session against a `pool_size=80` engine)
- invoking a compiled graph **without** `thread_id` raises `ValueError`, and a compiled graph
  **resumes** from this saver across two invokes

Plus a `@pytest.mark.live` Lakebase test asserting a write lands on an engine-issued connection.
**The real proof of the token path is not a test** — it is an app that stays up past the 50-minute
refresh with graph traffic on it, which belongs to ws4e's release gate.

**Sabotage the migration, not just the saver:** disable `_migrate_graph_checkpoints`' body and
confirm the fixture and every test using it go red with "no such table". If they stay green the
fixture is building tables from the ORM — fix the fixture, not the test.

### B2.2 `deck_reviews` and the deck digest

**Contract** — `src/services/deck_review_store.py`: `compute_deck_digest(list[str]) -> str`,
`save_deck_review(session_id, digest, findings, author)`, `get_deck_review(session_id, digest)`. Model
`DeckReview` on `deck_reviews`, unique on `(deck_id, deck_digest)`.

**Content-addressed, not SCD2 and not the version counter (§F4).** An SCD2 pair records *when* a
review was current; every consumer needs *which deck state it judged*, and those come apart the moment
a user edits and reverts. Three consequences, all simplifications:

- **Restore needs no handling at all** — there is no "current" row to go stale. Contrast
  `deck_spec_json`, which *did* need snapshot-and-copy-back precisely because it is keyed by deck.
- **The save-point cap cannot break it.** `VERSION_LIMIT = 40` prunes the oldest version; anything
  FK'd to `slide_deck_versions` would orphan or cascade away the history this table exists to keep.
  FK the **deck** only, and assert that in a test.
- **Reorder correctly invalidates**, because a deck review judges the arc and a reorder is exactly
  what changes it. This is the **opposite** of the per-slide rule (§F3), where a record travels with
  its slide. Both are correct; say so.

**The digest is computed on read, never stored** — a denormalised column could drift from the rows it
summarises, and the read path already loads every row.

**Trap.** `compute_slide_hash` normalises case and collapses whitespace **runs**, but does **not**
remove inter-token whitespace: `src/utils/slide_hash.py:44` is `' '.join(html.split())`. So
`"<DIV CLASS='slide'>  a  </DIV>"` and `"<div class='slide'>a</div>"` produce **different** digests.
Do not assert they match. (`slide_hash.py:69-72`'s own docstring example is wrong, which is what
misled an earlier draft — record it in `.PLAN-CORRECTIONS.md`.) Assert the normalisation that *does*
hold: case, and runs of whitespace between tokens.

**Test intent:** digest stable for identical ordered content; **changes on reorder**; save/get
round-trips; edit-then-revert finds the earlier verdict; re-saving the same digest updates rather than
duplicating; no FK to `slide_deck_versions`; a review survives pruning every version.
**Sabotage:** `sorted()` the per-slide hashes before joining and confirm the reorder test goes red.

### B2.3 The dirty-marker columns

**Contract:** three columns on `session_slide_decks` — `spec_dirty_at`, `spec_dirty_by`,
`spec_dirty_claimed_at`, all nullable — plus a partial index on `spec_dirty_at IS NOT NULL` (Postgres
only).

**Why three, and why here (§K7/§K8).** §B2 says the marker "lives in the database" and wants a lease,
but nominates no table. A column trio on `session_slide_decks` is right because the marker never needs
to outlive the deck row. The **third** column is the identity decision: a sweeper tick has no request,
so `get_current_user()` returns `None` (`user_context.py:21-23`) and `get_user_client()` **fails
closed** in production (`databricks_client.py:492`, raised at `:536`; `:511-515` records that
SDR-4437 HIGH-6 removed the SP fallback outside non-prod). Recording the marker's author gives the arc
review's write a real `modified_by`, PRD §8.1 a real user to attribute cost to, and a permission
provenance that was already checked on that human's route — with no new identity concept and no
stored credential.

**Not deck presentation state**, so deliberately absent from `get_slide_deck`'s dict. Assert that.

**Test intent:** the three columns exist and are nullable with the right types; the migration is
idempotent across two runs; `spec_dirty` appears nowhere in `get_slide_deck`'s source.

### B2.4 Stop every writer and reader of the retired prompt columns

**Two physical storages, and one drop cannot retire both.**

| Storage | Where | Retired by |
|---|---|---|
| Real columns | `ConfigPrompts.system_prompt` / `.slide_editing_instructions`, `Column(Text, nullable=False)` (`prompts.py:39-40`) | B2.5's `_migrate_*` |
| JSON keys in `agent_config` | `AgentConfig.system_prompt` / `.slide_editing_instructions` (`agent_config.py:97-98`, validator `:100-105`), persisted through `Column(NormalizedAgentConfig, …)` on **both** `UserSession` (`session.py:135`) and `ConfigProfile` (`profile.py:31`) | B2.5's data migration |

**`NormalizedAgentConfig` needs NO change.** It inspects only `slide_style_id` and `design_system_id`
(`types.py:139-156`) and passes every other byte through, and its docstring says why (`:64-70`):
routing each blob through `AgentConfig` is **lossy in both directions** — the model ignores unknown
keys so a newer writer's value is destroyed, and it fills in every default so a lean `{"tools": []}`
inflates. A bind hook stripping prompt keys would be exactly that generalisation.

**Seven `ConfigPrompts(...)` insert sites, and two are not importable modules:**
`init_default_profile.py:408`, `profile_service.py:204`, `:409`, **`:490` (`clone_profile` — copies
from the *source* profile, so its lines look different; do not pattern-match past it)**,
`scripts/init_database.py:218`, **`scripts/run_e2e_local.sh:160`** and
**`.github/workflows/test.yml:589`**. The last two are inline Python, so no grep of `src/` finds them
and no type checker will either — and `test.yml:589` is the `e2e-tests` job's seed step, which every
matrix entry runs, so missing it **fails all matrix jobs at seeding before a single spec executes**.

**Plus two read sites that fail independently of insert ordering:** `settings_db.py:386-387` reads
both ORM attributes into `AppSettings`; `config_service.py:69-75` **assigns** both columns behind
`PUT /agent-config`.

**Plus `src/database/models/prompts.py:39-40` itself** — the ORM declarations. Removing them is
sequenced **before** B2.5's drop, because otherwise every `db.query(ConfigPrompts)` emits
`SELECT config_prompts.system_prompt` against a dropped column: `UndefinedColumn` on Postgres, and
`create_all()` will **not** re-add it (it only creates missing *tables*), so the breakage is permanent.
(Round-3 finding 7 — this file was in neither the file table nor the site list.)

**Plus the rest:** `agent_config.py:97-98` + validator; `requests.py:35-36`, `:133-134`, `:136-141`;
`responses.py:53-54` (`PromptsConfig` — **dead schema**: referenced only by `ProfileDetail`, which no
route declares as a `response_model`; update or delete, nothing breaks either way);
`defaults.py:41`, `:150`; `config_loader.py:130`; `validator.py:39`;
`migrate_profiles_to_agent_config.py:15,17,44-45,51-52,54,76-77` (**each line is a pair** — an earlier
draft cited only the `system_prompt` half); `agent_factory.py:250-268`; `agent.py:250-252,617,624-625`;
`frontend/src/types/agentConfig.ts:82-83,135-136`;
`frontend/src/contexts/AgentConfigContext.tsx:124-125,1137-1138` (**two** sites);
`frontend/src/api/config.ts:83,92`; `frontend/src/components/config/ProfileList.tsx:34,59` (a **third**
"has custom config" site).

**Two traps on the runtime consumers.**

- **`agent_factory._get_prompt_content` is 237 lines returning `dict[str, Optional[str]]`**, signature
  `(config: AgentConfig, mode: str = "generate")`, and it carries the entire design-system /
  pinned-template / type-scale pipeline (§L). **Edit only the override branch at `:250-268`** — `:250-263`
  cuts mid-`return {`. Keep the name and signature: six suites pin it and ws4c repoints them.
- **`agent.py:617,624-625` read the ASSEMBLED prompt dict**, not the retired `AgentConfig` field, so
  "replace each read with the default" would break the monolith's prompt assembly. The real consequence
  to record: once the override branch goes, `pre_assembled` is always `True` and `agent.py`'s legacy
  concatenation branch (`620-640`) becomes unreachable dead code. (Round-3 finding 7.)

**Ruling R1 applies to the tests.** Six files carry ~132 references:
`test_agent_factory.py` (41), `test_prompt_precedence_fixes.py` (40), `test_design_system_compiler.py`
(17), `test_ds_generation_state_matrix.py` (14), `test_migration.py` (12),
`test_agent_config_schema.py` (8). **Triage per test:**

| The test asserts… | Action |
|---|---|
| that a custom prompt **overrides** the default, that the field round-trips, or validator behaviour on it | **DELETE** — the functionality is gone, there is nothing to repoint at |
| design-system resolution, tool gating, prompt precedence or template pinning, merely *constructing* an `AgentConfig` with the retired kwarg incidentally | **KEEP**, dropping the kwarg. §L6 requires this behaviour survive |

`test_agent_factory.py` is the clearest split: its 41 references include both
`test_custom_system_prompt_overrides_default` (delete) and the `_get_prompt_content` / `_build_tools`
assertions §L6 names as the regression harness (keep; ws4c repoints them). **Name every deletion in
its commit**, with the behaviour removed, and record the new collected count beside the cause list.

**Inventory real custom values before removing anything.** §E2 requires they be visible rather than
silently discarded. A one-off script over `ConfigPrompts` rows and both `agent_config` blobs, reporting
anything not equal to a default. **If it reports anything, stop and escalate** — §E1's premise ("editing
these is highly unlikely in practice") is what makes the breaking change acceptable.

**Verify the CI seed step by running it**, not by reading it. Extract the inline Python from
`run_e2e_local.sh:160` and `test.yml:589` and execute each against a throwaway sqlite database. No
local pytest run would tell you.

### B2.5 Drop the columns, and migrate the stored blobs

**Contract:** `_migrate_drop_config_prompt_columns` issues `ALTER TABLE config_prompts DROP COLUMN`
for both, idempotently; `src/core/strip_retired_prompt_keys.py` removes the two keys from every stored
`agent_config` blob and is wired into `run.py::init_database` after `init_db()` and before
`seed_defaults()`, in its own `try` that `raise SystemExit(1)`.

**The implementation lives under `src/`, and the CLI (if any) imports *from* it.** The app wheel ships
`src/` but **not** `scripts/`, so a startup step written as `from scripts.… import …` raises
`ModuleNotFoundError` at boot in production while working perfectly locally — a measured PR1 near-miss.

**The data migration is surgical by design**, for the same reason `NormalizedAgentConfig` refuses to
generalise: it edits two keys and copies every other byte. Idempotent (a second boot returns 0), and a
blob that will not parse is logged and skipped, never raised — one bad row must not abort startup.
(See B1.7's trap on whether that last case is reachable at all.)

**Test intent:** columns gone after the migration and the migration idempotent; **profile creation
still works after the drop** (the ordering hazard, asserted); stored blobs lose the keys; **every other
byte preserved, and a lean blob does not inflate**; idempotent; the whole four-migration chain applied
twice against a fresh sqlite file leaves all four in place.

**Verify against real Lakebase on a devloop fork.** Deploy per `.claude/skills/deploy-tellr-dev/` and
confirm the app reaches **RUNNING** — each step is `SystemExit(1)` on failure, so RUNNING is proof all
four applied.

---

## Part 3 — Deck-level persistence

### B3.1 The deck-level-columns-only writer

**Contract** — `src/api/services/deck_level_writer.py`:

```python
def write_deck_level_columns(session_id, *, title=_UNSET, css=_UNSET, external_scripts=_UNSET,
                             head_meta=_UNSET, scripts_content=_UNSET, deck_spec=_UNSET,
                             slide_count=_UNSET, html_content=_UNSET,
                             modified_by=None, expected_version=None) -> dict
def read_deck_spec(session_id) -> dict | None
```

**A sentinel, not `None` defaults.** Two writes per turn means the second must not erase what the
first persisted, so "not supplied" and "explicitly null" must differ. An interface stating `=None`
defaults and an implementation using a sentinel is a contradiction an implementer will resolve the
wrong way — state the sentinel here and only here.

**Why a new writer rather than `save_slide_deck` (§H1a).** That method has exactly two behaviours and
neither is a deck-level-only write:

- **`deck_dict=None`** → `deck.css` is *never assigned* (both assignments are inside `if deck_dict:`,
  `session_manager.py:1356`/`:1366`) and it sets `deck.deck_json = None` (`:1303`, `:1320`).
- **`deck_dict={…}`** → it upserts every slide in `deck_dict["slides"]` and then runs
  `_prune_slide_rows_beyond(db, deck_owner.id, len(slides))` (`:1403`), hard-deleting every row at
  `position >= len(slides)`. A **pre-fan-out** call carries a shorter list than the live row count, so
  it would **truncate the live deck mid-turn** — and the read path serves rows whenever any exist.

It also takes `html_content` as a **required positional**, which the graph has not knitted at fan-out
time. Reuse `save_slide_deck`'s **locking shape** (`:1309-1314` check, `:1321` bump) but not its
dual-write body.

**It must handle the no-row case.** The pre-fan-out write is the **first** deck write of a brand-new
session, when no `SessionSlideDeck` exists. `save_slide_deck` has an `else: deck = SessionSlideDeck(...)`
branch; this writer needs the equivalent, or every graph turn on a new session raises. (Round-3
finding 8.)

**Resolving the deck owner:** the lookup already exists as
`SessionManager._get_deck_owner_session(db, session: UserSession)` (`session_manager.py:709`, ~20 call
sites) — note it takes a **`UserSession` object, not a session_id string**, so a `session_id` caller
needs the session lookup first. Do not write a second implementation.

**The eight columns, split across two writes (§H1b, §L2). Nothing self-heals.**

| Column | Which write | If never written |
|---|---|---|
| `title` | pre-fan-out | untitled deck **and** untitled session row |
| `css` | both (B3.3 aggregates for the second) | unstyled deck — the §H defect. `knit()` guards with `if self.css:` so an empty value emits **nothing** |
| `external_scripts_json` | pre-fan-out | **Chart.js missing from every export.** Does **not** self-heal: `_ensure_default_external_scripts` runs only when something builds a `SlideDeck` domain object, and nothing on the export or preview path does — `export.py:84` reads the raw dict, and five frontend consumers read `slideDeck.external_scripts`. Failure is **silent**: no exception, blank charts |
| `head_meta_json` | pre-fan-out | custom viewport and every other `<meta>` reverts to `knit()`'s default |
| `scripts_content` | pre-fan-out | deck-level JS lost from the row-read path |
| `deck_spec_json` | pre-fan-out | **the spec is never persisted** — §7.1's view has no data and turn *n+1*'s architect starts blind. The pre-fan-out trigger *is* "the architect committed the spec" |
| `slide_count` | post-commit | **the session list renders `0 slides`** (`routes/sessions.py:233` — a *column*, not derived) |
| `html_content` | post-commit | raw-HTML debug view empty |

**§K4 — what deterministic CSS the pre-fan-out write persists: the pinned template's `token_css` plus
its own `<style>` block.** Forced, not preferred: §H1's stated reason for writing before the fan-out is
that an incrementally-released slide renders **styled**. Persist nothing up front and every released
slide is unstyled until the post-commit write, which destroys that payoff. On an unpinned or legacy
deck there is nothing deterministic, and `css` is left to the post-commit aggregation.

**Test intent:** it **touches no `session_slides` row** (the reason it exists — snapshot before and
after); it does **not** null `deck_json`; version bumps exactly once per call and the optimistic lock
rejects a stale write; `html_content` is optional; **omitted columns are left alone rather than
nulled** across two calls; all eight are written between the two; `title` also updates the session
row; a contributor session writes to the **owner**; **it creates the deck row when none exists**;
`read_deck_spec` round-trips, returns `None` when absent, and returns `None` for an unparseable column.

**Sabotage:** make the writer delegate to `save_slide_deck(deck_dict={"slides": []})` — the plausible
wrong implementation §H1a exists to rule out — and confirm the no-row-touched test goes red.

### B3.2 Serve the deck spec through the read path

`deck_spec_json` is the only deck-level column with a **reader** gap as well as a writer gap: today its
only touchers are `create_version`'s snapshot (`:1939-1951`) and `restore_version`'s copy-back
(`:2240`), and the row-read `deck_dict` (`:1538-1564`) emits no deck spec at all. So §7.1's spec view
has no data path.

**Contract:** add a parsed `deck_spec` key to **both** read paths — the row-read `deck_dict` and the
blob fallback at `:1572`, since a pre-cutover deck with no rows reaches the latter. Parse with a helper
that never raises, alongside `_read_head_meta`.

**Test intent:** the key is present and parsed; a specless deck reports `deck_spec: None` rather than
omitting the key (a missing key and a null are different things to a frontend); the blob-fallback path
exposes it; a contributor sees the owner's spec (§7.5); and **adding this key changes no other key** —
PRD §10.2's parity guarantee means the export chain and every `html_content` consumer depend on that
dict's exact shape. Run the export and preview suites, not just the new test.

### B3.3 Aggregate the deck's CSS and run the token backstop

**Contract** — `src/services/deck_css_aggregator.py`:
`aggregate_deck_css(existing_css, emitted_style_blocks, token_css) -> str`. Merges the blocks with
ws4a's at-rule-preserving `merge_css`, then runs `ensure_deck_token_css`.

**§L2a's unassigned owner.** `deck.css` is populated today by exactly two monolith-path mechanisms —
`SlideDeck.from_html_string`'s `<style>` walk (`slide_deck.py:193-198`) and `update_css` → `merge_css`
(`:108`, from `chat_service.py:2631`). The graph calls neither; `SlideWriter` writes per-row `html`
only. Without this step a graph deck reaches `ensure_deck_token_css` with an empty `deck.css`, and that
backstop restores only **custom properties and `@font-face` families** — so it returns the token
stylesheet alone and the deck knits with **no layout CSS**, the exact §H defect by a different route.

**Runs at the post-commit write, not before the fan-out**, because the backstop compares **emitted**
deck CSS against the token stylesheet and so cannot run before builders have emitted anything.

**Where the blocks come from — the constraint that makes this coherent.** `BuilderOutput` **forbids**
a builder emitting `<style>` (B1.5), so the blocks are **not** builder output. They are the
**template's** style block: §M5 pairs each extracted section with the template's full block, so a
15-slide pinned deck yields up to 15 identical copies and the aggregator's job is to collapse them.
ws4c owns producing them; this task owns consuming them. **If ws4c concludes one pinned template needs
no per-slide accumulation at all, this function's dedupe premise weakens and its test must change with
it** — flag that rather than leaving a test asserting a path nothing reaches.

**CSS travels whole and is never pruned** (§M5): the backstop covers only custom properties and
`@font-face` families, so a pruner's mistakes land outside the safety net.

**Test intent:** N identical blocks collapse to one occurrence each; at-rules survive; the backstop
**prepends** when a token is undefined (so deck CSS stays later in the cascade and anything the model
authored still wins) and leaves a genuinely compliant deck untouched; the pipeline is **semantically**
idempotent — assert the invariant (every token defined exactly once, every at-rule present), **not
byte equality**, because the backstop prepends a CSS *comment* marker that `parse_css_blocks` drops on
the next pass; no `token_css` means no backstop and no crash; a failing backstop never blocks the save.

**Fixture trap:** a "compliant" deck fixture must define **every** custom property `token_css`
declares, or the backstop legitimately prepends and the test fails for the wrong reason. And count
occurrences carefully — a fixture that both defines and `var()`-references a token contains it twice.
(Round-3 findings 6 and 7.)

---

## Definition of done

- [ ] Every contract in Part 1 has a passing test suite, and every guard has been **sabotage-verified**
      with the sabotage confirmed on the executed path.
- [ ] `npm run typecheck` clean; `npm run test:unit` green; the lockfile has zero `artifactory` hits.
- [ ] The four-migration chain applies twice against a fresh sqlite database with all four effects
      present, and reaches **RUNNING** on a devloop Lakebase fork.
- [ ] The checkpointer's live test passes against Lakebase, and a compiled graph resumes across two
      invokes.
- [ ] Profile creation works after the column drop; the CI seed step was **executed**, not read.
- [ ] Export and preview parity suites pass — `test_html_to_pptx.py`,
      `test_google_slides_converter.py`, `test_preview_box_model_parity.py`, `test_export_csp.py`.
- [ ] Full suite compared **by cause** to the index's baseline: no new cause, no change to the
      deploy-autoscaling cause. **Every deleted test named in its commit**, with the new collected
      count recorded beside the cause list.
- [ ] The seven output schemas, `finding.ts`, the deck-spec models and the fixture contracts are
      **frozen**. A later PR wanting a field escalates here; it does not edit locally.

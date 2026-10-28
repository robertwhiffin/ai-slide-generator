# Architect Edit Operations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. In this repo also load `executing-plans-tellr` (`.claude/skills/executing-plans-tellr/`).

**Goal:** an `edit` turn can apply any combination of insert, update, delete, replace and move in one message. The architect lists them as an ordered `operations` list, and the code applies them deterministically instead of re-aligning a rewritten `deck_spec`.

**Architecture:**
- A new pure domain module (`src/domain/slide_operations.py`) turns the persisted slides plus an operations list into a composed slide list, a row layout and a rebuild set, or into a list of problems.
- `ArchitectOutput` gains optional `operations` and `deck_changes`.
- `architect_node` takes an "operations path" when they are present. It lays the rows out in one transaction through a generalised `SlideWriter.apply_slide_layout`, and builds only inserted, updated and replaced slides.
- A planning refusal gets one model retry with the exact problems. The architect's message is said only once the plan has landed. A refusal is replayed to the architect as a system note.

**Tech Stack:** Python 3.11, Pydantic v2, LangGraph, SQLAlchemy (SQLite in unit tests, Postgres in CI), pytest, the `evals/` MLflow harness.

**Spec:** `docs/superpowers/specs/2026-10-28-architect-edit-operations-design.md`. Read it first; this plan argues from it.

## Global Constraints

- Python env: the per-worktree uv `.venv`. Run everything as `uv run …` from the worktree root. Never `pip install`.
- `SlideSpec` and `DeckSpec` must not change. The schema digests of every role except the architect must stay byte-identical.
- `ArchitectOutput` changes are additive only: new fields are optional with defaults, and nothing is removed or renamed (`_HISTORICAL_DIGESTS` rule).
- All positions in `operations` are `SlideSpec.position` values of the **persisted** (pre-message) spec. `after_position = -1` means "at the start".
- A slide can be the subject (`position`) of at most one operation.
- Replace keeps the subject's row for its **first** slide (update + inserts).
- At most **one** retry per turn (two architect calls).
- Eval spend for the whole change is capped at **USD 20**.
- Commits end with `Co-authored-by: Isaac <no-reply@databricks.com>`.
- Do not touch the frontend (spec §11).

## Review Focus

1. **The production shape:** replace slide 5 of a 16-slide deck with seven slides in one edit. It must apply in one turn, with 22 slides, old slides 6–16 byte-identical at 12–22, and positions 4..10 built. → Task 4 `test_production_replace_five_with_seven_applies_in_one_turn`.
2. **Insert after a slide deleted in the same message:** the new slide lands in the gap and nothing is refused. → Task 1 `test_insert_after_deleted_slide_fills_its_gap`.
3. **The deck changes under the planner** (a panel edit while the architect thinks): `SlideRowsChangedError`, no retry, the "deck changed" refusal, nothing written. → Task 4 `test_rows_changed_mid_plan_refuses_without_retry`.
4. **A moved hand-edited slide** keeps its HTML, scripts, authorship, verification record and spec fragment, and is not rebuilt. → Task 3 `test_moved_row_keeps_whole_row` and Task 4 `test_move_only_edit_builds_nothing_and_reviews_deck`.
5. **The retry's answer is a `discuss`:** its message is said, nothing changes, and the first answer's message is never shown. → Task 5 `test_retry_answer_can_be_discuss`.

---

## File Structure

| File | Role |
|---|---|
| `src/domain/slide_operations.py` (new) | `SlideContent`, `SlideOperation`, `DeckChanges`, `OperationProblem`, `OperationProblems`, `OperationsResult`, `apply_operations`, `compose_edit_spec`, `problem_sentence`. Pure; no DB. |
| `src/domain/skill_io.py` | `ArchitectOutput.operations`, `.deck_changes`, relaxed edit validator. |
| `src/services/agent_schema_registry.py` + pins | Re-pinned architect v1/v2 digests, old ones moved to `_HISTORICAL_DIGESTS`. |
| `src/api/services/session_manager.py` | `_lay_out_slide_rows` (general layout primitive); `_splice_slide_rows` delegates to it. |
| `src/api/services/slide_repository.py` | `SlideWriter.apply_slide_layout`; `insert_pending_slides` delegates to it. |
| `src/services/graph/nodes.py` | The operations path, the retry, the deferred message, the refusal metadata, and the `_conversation` system note. |
| `evals/harness/scorers.py`, `evals/harness/…` | Operations answers normalised and scored with production semantics. |
| `evals/packs/architect/cases{,_heldout}/` | Four new cases per split. |
| `evals/configs/architect/edit-ops.{md,yaml}` | The prompt candidate(s). |
| `src/core/skills/architect.py`, `src/services/agent_definition_manifest_v1.py` | The promoted prompt. |
| `docs/technical/backend-overview.md`, `CONTEXT.md`, `evals/README.md` | Docs. |

---

## Before Task 1

- **Baseline:** on the base commit, run `uv run pytest tests/unit -q -p no:randomly`. Record every failing node id **and its cause** in the ledger (`~/tellr-loop/edit-ops/LEDGER.md`). Later regression checks diff causes, not counts (executing-plans-tellr §3).
- **Plan-vs-code pre-pass** (executing-plans-tellr §2): write `~/tellr-loop/edit-ops/PLAN-CORRECTIONS.md` and point every dispatch at it.

---

### Task 1: The operations domain module

**Models:** test=opus impl=sonnet

**Files:**
- Create: `src/domain/slide_operations.py`
- Test: `tests/unit/test_slide_operations.py`

**Interfaces:**
- Consumes: `src.domain.deck_spec.SlideSpec`, `DeckSpec`, `DesignContractRef`, `ResolvedData`.
- Produces (exact):

```python
class SlideContent(BaseModel):   # SlideSpec's fields minus position, same types/defaults
    purpose: str; content_brief: str; assumes: str; hands_off: str
    data_references: list[str]
    slide_type: Optional[str] = None
    template_section_index: Optional[int] = None
    def to_slide_spec(self, position: int) -> SlideSpec: ...
    @classmethod
    def from_slide_spec(cls, slide: SlideSpec) -> "SlideContent": ...

OperationKind = Literal["insert", "update", "delete", "replace", "move"]
class SlideOperation(BaseModel):   # flat, NO validators (per-op rules live in apply_operations)
    op: OperationKind
    position: Optional[int] = None
    after_position: Optional[int] = None
    slides: Optional[list[SlideContent]] = None

class DeckChanges(BaseModel):      # every field Optional, default None, NO validators
    title, audience, purpose, argument, call_to_action: Optional[str]
    narrative_arc: Optional[list[str]]
    design_contract: Optional[DesignContractRef]
    resolved_data: Optional[ResolvedData]

@dataclass(frozen=True)
class OperationProblem:
    code: str                      # one of PROBLEM_CODES
    positions: tuple[int, ...]     # persisted positions involved (may be empty)
    detail: str                    # model-facing sentence, in positions

@dataclass(frozen=True)
class OperationProblems:
    problems: tuple[OperationProblem, ...]

@dataclass(frozen=True)
class OperationsResult:
    slides: tuple[SlideSpec, ...]          # composed, re-stamped 0..m-1
    layout: tuple[Optional[int], ...]      # per new index: persisted position whose row lands here, or None
    rebuild: tuple[int, ...]               # ascending new indices: inserted, updated, replaced
    deleted: tuple[int, ...]               # ascending persisted positions
    moved: tuple[int, ...]                 # ascending persisted positions

PROBLEM_CODES = ("unknown_slide", "slide_targeted_twice", "missing_slides",
                 "update_needs_one_slide", "missing_position", "missing_after_position",
                 "move_after_itself", "move_loop", "deck_emptied", "nothing_to_do",
                 "invalid_deck_changes")

def apply_operations(current: Sequence[SlideSpec],
                     operations: Sequence[SlideOperation]) -> OperationsResult | OperationProblems
def compose_edit_spec(prior: DeckSpec, result: OperationsResult,
                      changes: Optional[DeckChanges]) -> DeckSpec | OperationProblems
def problem_sentence(problem: OperationProblem, slide_numbers: Mapping[int, int],
                     slide_count: int) -> str
```

The rules are in spec §2 and §3:
- `current` is read in position order, and positions may be gapped.
- An empty `operations` list returns `nothing_to_do`. The node only calls this module when `operations is not None`, or when `deck_changes` is set, in which case it passes `[]`. `compose_edit_spec` reports `nothing_to_do` only when the ops are empty and `changes` sets nothing.
- `slides` on delete or move is ignored.
- Every problem is collected in one pass. Never raise.

The composed order is fixed by spec §2. One algorithm that satisfies it:
- Keep `followers[anchor]` lists, where the anchor is `START` or a position. Insert items and moved slides are appended to them in op order.
- Emit `followers[START]`, then walk the current slides in order, skipping moved slides.
- For each slot, emit its own content (nothing if deleted, all of its replacement slides if replaced), then expand `followers[slot]` recursively. A moved slide is emitted as a slot.
- A moved slide that is never emitted means a `move_loop`.

`compose_edit_spec`:
- It returns `prior.model_copy(update={...set DeckChanges fields..., "slides": list(result.slides)})`, then re-validates it with `DeckSpec.model_validate(...model_dump())`.
- A `ValidationError` becomes `OperationProblems((OperationProblem("invalid_deck_changes", (), <first error msg>),))`.

`problem_sentence` builds user-facing sentences, using 1-indexed numbers from `slide_numbers` (position → slide number of the pre-message deck). These sentences are fixed copy:

| code | sentence |
|---|---|
| unknown_slide | `there is no slide {n} — the deck has {count} slides` (n = position+1 when the position is not numbered) |
| slide_targeted_twice | `slide {n} was changed in more than one way` |
| missing_slides | `the new slides for slide {n} had no content` (or `…at the start of the deck…` for -1) |
| update_needs_one_slide | `the change to slide {n} described {k} slides instead of one` |
| missing_position | `one change did not say which slide it was for` |
| missing_after_position | `one change did not say where its slides go` |
| move_after_itself | `slide {n} cannot be moved after itself` |
| move_loop | `the moves of slides {a}, {b} go round in a circle` (sorted numbers, joined ", ") |
| deck_emptied | `it would have left the deck with no slides` |
| nothing_to_do | `it did not list any change to make` |
| invalid_deck_changes | `the deck-level changes were not valid ({detail})` |

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_slide_operations.py`. Build decks with a local `deck(n)` helper that returns `SlideSpec`s whose `purpose` is `f"s{p}"`, plus `content(name)` for `SlideContent`. Assert on the composed `purpose` sequence, `layout`, `rebuild`, `deleted` and `moved`. Never assert on counts alone. The tests:
  - `test_update_rebuilds_in_place`: 4 slides, update 2 gives purposes `[s0,s1,X,s3]`, layout `(0,1,2,3)`, rebuild `(2,)`.
  - `test_replace_is_update_plus_inserts`: 16 slides, replace 4 with `[A..G]` gives 22 slides. Index 4 = A with layout[4] = 4, indices 5..10 = B..G with layout None, indices 11..21 = s5..s15 with layout 5..15, rebuild `(4,5,6,7,8,9,10)`.
  - `test_insert_at_start_and_after`: insert after -1 `[A]`, insert after 1 `[B,C]` gives `[A,s0,s1,B,C,s2]`, rebuild `(0,3,4)`.
  - `test_delete_rebuilds_nothing`: delete 1 of 4 gives `[s0,s2,s3]`, layout `(0,2,3)`, rebuild `()`, deleted `(1,)`.
  - `test_move_rebuilds_nothing`: move 3 after 0 gives `[s0,s3,s1,s2]`, layout `(0,3,1,2)`, rebuild `()`, moved `(3,)`. Move 0 after -1 is a no-op order.
  - `test_insert_after_deleted_slide_fills_its_gap`: delete 2, insert after 2 `[N]` on 4 slides gives `[s0,s1,N,s3]`.
  - `test_anchor_follows_moved_slide`: move 1 after 3, insert after 1 `[N]` gives `[s0,s2,s3,s1,N]`.
  - `test_followers_keep_list_order`: insert after 0 `[A]`, move 3 after 0, insert after 0 `[B]` gives `[s0,A,s3,B,s1,s2]`.
  - `test_insert_after_replaced_goes_after_all_replacements`: replace 1 with `[X,Y]`, insert after 1 `[N]` gives `[s0,X,Y,N,s2]`.
  - `test_mixed_owner_example`: on 8 slides, delete 3, update 4, replace 5 with `[A,B,C]`, insert after 4 `[N]` gives `[s0,s1,s2,U4,N,A,B,C,s6,s7]`, rebuild `(3,4,5,6,7)`, deleted `(3,)`.
  - `test_gapped_positions`: current positions `(0,2,5)`, delete 2 gives layout `(0,5)`, and the slides are re-stamped `0,1`.
  - Problems, one test each, asserting the exact `code` and `positions`: unknown position (29), unknown after_position, -2 after_position, duplicate subject (update 2 + delete 2), insert with `slides=None`, replace with `[]`, update with 2 slides, delete with no position, move with no after_position, move 2 after 2, a move loop (1 after 2, 2 after 1), delete every slide (`deck_emptied`), and `[]` (`nothing_to_do`).
  - `test_all_problems_collected_in_one_pass`: three distinct problems in one list returns all three, in op order.
  - `test_slides_on_delete_or_move_are_ignored`.
  - `test_never_mutates_inputs`.
  - `test_compose_applies_only_set_deck_changes`: title and narrative_arc are set, every other field equals prior, and slides = result.slides.
  - `test_compose_invalid_deck_changes`: `DeckChanges(title="  ")` gives `invalid_deck_changes`, because DeckSpec's H1 title validator fails on the composed spec.
  - `test_compose_nothing_to_do` (empty ops result, `changes=None`).
  - `test_problem_sentences` checks every row of the table above, verbatim, with `slide_numbers={0:1,…}`.
  - `test_slide_content_mirrors_slide_spec`: `set(SlideContent.model_fields) == set(SlideSpec.model_fields) - {"position"}`, and each field's annotation and default are equal.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_slide_operations.py -q`. Expected: FAIL, because the module does not exist.
- [ ] **Step 3: Implement** `src/domain/slide_operations.py` with exactly the interfaces above. Write a module docstring that states spec §2's placement rules.
- [ ] **Step 4: Run** the same command. Expected: all pass. Then `uv run pytest tests/unit -q -k "deck_spec or slide_alignment"`: still green.
- [ ] **Step 5: Commit** `feat(domain): slide operations for architect edits`.

---

### Task 2: `ArchitectOutput` gains `operations` / `deck_changes`; re-pin the architect contract

**Models:** test=opus impl=opus

**Files:**
- Modify: `src/domain/skill_io.py` (`ArchitectOutput`)
- Modify: `src/services/agent_schema_registry.py` (`_V1_DIGESTS["architect"]`, `_V2_DIGESTS["architect"]`, `_HISTORICAL_DIGESTS`)
- Modify: `src/services/agent_definition_manifest_v1.py`. Edit only the architect `schema_contract.digest` values, and only through JSON-aware rewriting.
- Modify, the pins the recon found:
  - `tests/unit/test_agent_schema_registry.py` (EXPECTED_V1/V2 and the other architect digest literals);
  - `tests/unit/test_architect_edit_prompt.py` (`HEAD_ARCHITECT_CONTENT_HASH`, `HEAD_ARCHITECT_HASH_WITHOUT_PROMPT`, `HEAD_V1/V2_SCHEMA_DIGESTS`);
  - `tests/unit/test_retained_bundle_ledger.py`;
  - `tests/unit/test_graph_definition_manifest.py` (`PACKAGED_V1_CONTENT_HASHES` and the architect digest asserts);
  - `tests/unit/test_packaged_release_loader.py`;
  - `tests/unit/test_graph_configuration_draft.py`;
  - `tests/unit/test_agent_runtime.py`;
  - `tests/unit/test_persisted_agent_runtime.py`.

  Run `grep -rn "9704af4e\|39ed9e91" tests src` to find them all.
- Test: `tests/unit/test_architect_output_operations.py`

**Interfaces:**
- Consumes: Task 1's `SlideOperation`, `DeckChanges`.
- Produces:
  - `ArchitectOutput.operations: Optional[List[SlideOperation]] = None`
  - `ArchitectOutput.deck_changes: Optional[DeckChanges] = None`
  - The edit rule in `_intent_payload_consistency` becomes: `intent == "edit"` requires `target_positions` non-empty **or** `operations is not None` **or** `deck_changes is not None`. The error message names all three. Other rules are unchanged.

Notes for the implementer:
- `AgentSchemaRegistry()` raises `SchemaContractMaterialChangedError` at import, with the calculated digest in its message. Use that to read the new v1/v2 values.
- Move the current `9704af4e…` (v1) and `39ed9e91…` (v2) into `_HISTORICAL_DIGESTS`, after the existing two architect rows. This is the commit 5653f3ec precedent.
- After re-pinning the manifest digest, the architect content hash changes. Compute it with `definition_content_hash` and update the pins.

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_architect_output_operations.py`:
  - `test_edit_with_operations_needs_no_targets`: `ArchitectOutput(intent="edit", message="m", operations=[SlideOperation(op="delete", position=1)])` validates, with `target_positions == []`.
  - `test_edit_with_only_deck_changes_validates`.
  - `test_edit_with_nothing_still_rejected`: a `ValidationError` whose message contains `target_positions`, `operations` and `deck_changes`.
  - `test_old_shape_still_valid`: today's `edit` with a `deck_spec` and targets, and today's `build`, both validate unchanged.
  - `test_operations_in_json_schema`: `ArchitectOutput.model_json_schema()` has the `operations` and `deck_changes` properties, and neither is in `required`.
  - `test_historical_architect_digests_resolve`: for each of `9704af4e…` (v1) and `39ed9e91…` (v2), `HISTORICAL_SCHEMA_CONTRACT_BUNDLES[("architect", v, d)].canonical_model is ArchitectOutput`.
  - `test_other_roles_digests_unchanged`: the six non-architect v1/v2 literals equal today's values, copied into the test.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_architect_output_operations.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the two fields and the validator change. Then re-pin the registry, the history and the manifest digest, and update every pin listed above.
- [ ] **Step 4: Run** `uv run pytest tests/unit -q -p no:randomly`. Expected: green, except the baseline causes recorded before Task 1 (see "Before Task 1"). Compare causes, not counts.
- [ ] **Step 5: Commit** `feat(architect): operations and deck_changes on ArchitectOutput; re-pin contract`.

---

### Task 3: The general row-layout writer

**Models:** test=opus impl=sonnet

**Files:**
- Modify: `src/api/services/session_manager.py`. Add `_lay_out_slide_rows`, and re-express `_splice_slide_rows` through it.
- Modify: `src/api/services/slide_repository.py`. Add `SlideWriter.apply_slide_layout`, and make `insert_pending_slides` delegate to it.
- Test: `tests/unit/test_apply_slide_layout.py`, plus `tests/integration/test_apply_slide_layout_postgres.py`, which is CI-only and follows `tests/unit/test_insert_pending_slides_postgres.py`'s marker/skip pattern.

**Interfaces:**
- Consumes: nothing from earlier tasks. The layout is plain data.
- Produces:

```python
# session_manager.py
def _lay_out_slide_rows(db: Session, owner_id: int, old_rows: List[SessionSlide],
                        layout: Sequence[Optional[int]],
                        new_slides: Mapping[int, Tuple[Dict[str, Any], Dict[str, Any]]]) -> None
#   layout[i] = INDEX into old_rows (position order) whose row lands at new index i, or None.
#   new_slides keys == exactly the None indices.  An old index appears at most once; absent = deleted.
#   Snapshots/attributions before any write; _rewrite_slide_rows with the exact map,
#   now_dt=None, author_fallback=None; prune beyond len(layout).  ValueError before any write
#   on a malformed layout.
# _splice_slide_rows(db, owner_id, old_rows, new_slides) == _lay_out_slide_rows with the
#   in-order layout (old rows in order around the new indices).

# slide_repository.py
def apply_slide_layout(self, session_id: str, layout: Sequence[Optional[int]], *,
                       deck_spec: str, expected_rows: Sequence[Tuple[Optional[str], str]],
                       created_by: Optional[str], mutation: DeckMutationContext) -> List[str]
#   layout[i] = INDEX into the current rows (position order) or None (pending placeholder).
#   Same transaction/guards as insert_pending_slides: expected_rows re-read check
#   (SlideRowsChangedError), DeckSpec.from_json(deck_spec) valid with len(slides) == len(layout)
#   when rows exist, deck_spec_json written, version bumped, last_activity touched, ONE mutation
#   event.  Row-less deck: layout must be all None; spec/version/event only.
#   mutation.operation must equal layout_mutation_operation(layout, len(rows)) and object_type "deck".
#   Returns new slide_ids in ascending new-index order.

def layout_mutation_operation(layout: Sequence[Optional[int]], old_count: int) -> str
#   "insert_slide" if every old index is present in order and >=1 None;
#   "delete_slide" if no None, kept indices ascending, and some missing;
#   "reorder_slides" if no None, all present, not in order;
#   "save_deck_slides" otherwise (mixed).  Identity layout -> ValueError (nothing to write).
```

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_apply_slide_layout.py`. Use the same oracle style as `tests/unit/test_insert_pending_slides.py`:
  - Rows are found by a marker in their own HTML.
  - Every column except `position`/`id` is compared.
  - Seed rich rows: non-NULL scripts, authorship, timestamps, a two-hash verification record and a spec fragment.
  - The JSON columns are compared parsed.
  - "Nothing changed" is a whole-database snapshot, including `version` and the mutation-event count.

  The tests:
  - `test_moved_row_keeps_whole_row`: layout `(0,3,1,2)`. Each row's full content sits at its new index, and `modified_at` is unchanged.
  - `test_deleted_row_is_gone`: layout `(0,2,3)` leaves 3 rows, and the row at old index 1 is absent from the table.
  - `test_mixed_layout`: layout `(0,None,3,None,1)` on 4 rows. Two pending placeholders carry fresh slide_ids and `created_by`, old row 2 is gone, and the other rows are whole.
  - `test_replace_shape`: layout `(0,1,2,3,4,None,…,None,5,…,15)`, the production shape on 16 rows.
  - `test_expected_rows_mismatch_writes_nothing` (`SlideRowsChangedError`, snapshot unchanged).
  - `test_spec_count_mismatch_writes_nothing` (`ValueError`).
  - `test_malformed_layouts`: a duplicate old index, an out-of-range index, and the identity layout each raise `ValueError` with nothing written.
  - `test_wrong_mutation_operation_refused`.
  - `test_one_mutation_event_and_version_bump`.
  - `test_insert_pending_slides_unchanged`: today's `test_insert_pending_slides.py` stays green untouched. Run it in Step 4.
  - `test_layout_mutation_operation`: the four classifications plus identity → `ValueError`.

  Write the Postgres twin of `test_mixed_layout` and `test_expected_rows_mismatch_writes_nothing`.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_apply_slide_layout.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** `_lay_out_slide_rows`, re-express `_splice_slide_rows`, then add `apply_slide_layout` and `layout_mutation_operation`, and delegate `insert_pending_slides`. Keep its signature and its `insert_slide` operation check.
- [ ] **Step 4: Run** `uv run pytest tests/unit/test_apply_slide_layout.py tests/unit/test_insert_pending_slides.py tests/unit/test_slide_writer.py tests/unit/test_slide_writer_field_coherence.py -q` and `uv run pytest tests/unit -q -k "insert_slide or save_slide_deck or restore"`. Expected: green. If local Postgres is up (`pg_ctl` per memory), also run `uv run pytest tests/integration/test_apply_slide_layout_postgres.py tests/unit/test_insert_pending_slides_postgres.py -q`.
- [ ] **Step 5: Commit** `feat(slides): general row-layout writer for graph edits`.

---

### Task 4: The operations path in `architect_node`

**Models:** test=opus impl=opus

**Files:**
- Modify: `src/services/graph/nodes.py` (`architect_node`, `_untouched_blank_positions`)
- Test: `tests/unit/test_architect_edit_operations.py` (uses `tests/unit/conftest_graph.py`'s `graph_env`, `make_spec` and `SkillStub`)

**Interfaces:**
- Consumes: Task 1 (`apply_operations`, `compose_edit_spec`, `OperationProblems`, `problem_sentence`), Task 2 (`ArchitectOutput.operations/deck_changes`), and Task 3 (`SlideWriter.apply_slide_layout`, `layout_mutation_operation`).
- Produces, for Task 5:
  - `_plan_operations_edit(state, out, prior_spec, committed_rows, brand, slide_payload) -> _EditPlan | OperationProblems`. It is pure apart from the brand resolution read: no emit, no write.
  - `_EditPlan(spec: DeckSpec, layout: tuple, rebuild: tuple, references_map: Dict[int, int])`, a dataclass.
  - `_apply_edit_plan(state, plan, committed_rows, updates) -> Optional[Dict[str, str]]`, which writes the rows and returns a degrade dict or `None`.

Behaviour (spec §4):
- **When the path runs:** `intent == "edit"`, not `describe_only`, `prior_spec` is present, and the persisted-spec guards pass, with `out.operations is not None or out.deck_changes is not None`.
- **Planning:**
  - Pass `out.operations or []` to `apply_operations`.
  - `compose_edit_spec`, then `complete_index_only_bindings`/`invalid_slide_bindings` on the composed spec. A binding error becomes an `OperationProblem("invalid_slide_type_binding", (), msg)`.
  - Re-resolve the brand if `deck_changes.design_contract` changes the ids, which is today's rule on `spec.design_contract`.
- **Problems** (Task 4 only; Task 5 adds the retry): degrade with code `edit_operations_rejected`. The user sentence is `"I couldn't apply that edit, so nothing in the deck has changed: " + "; ".join(problem_sentence(...)) + "."`, and `error_state["message"]` is the joined `detail`s.
- **Rows:**
  - If `layout` is not the identity over the committed rows, call `apply_slide_layout`. `expected_rows` comes from `committed_rows`, the mutation operation is `layout_mutation_operation(layout, len(committed_rows))`, and `deck_spec` is the composed spec's JSON.
  - `layout` from Task 1 holds persisted positions. Map them to row indices through `committed_rows`' order, since rows and spec positions are guaranteed equal by `_persisted_spec_describes_these_rows`.
  - `SlideRowsChangedError` degrades with `insert_rows_changed` and today's sentence, and any other exception with `insert_rows_failed`. Reuse today's two degrade dicts, renamed only in their constant names if extracted.
- **Targets:** `updates["target_positions"] = list(rebuild)`, with the untouched-blank rule (spec §4):
  - `untouched` = blank composed indices not in `rebuild`;
  - `_drop_untouched_blanks` applies to the design-contract and deck-level lists;
  - references are mapped through `layout` (persisted position → composed index) before being passed.
- **Logging:** log `operations_targets_disagree` (WARNING) when the model's `target_positions` differ from `rebuild`.
- **Ignored fields:** `operations`/`deck_changes` on a non-edit intent are ignored with an INFO `operations_ignored` log. A describe-only turn ignores them too and keeps today's `deck_spec` handling.
- **Then** the existing `classify_spec_change` / deck-level re-review / pre-fan-out write runs unchanged on the composed spec.
- **No operations:** an edit without `operations`/`deck_changes` takes today's path byte-for-byte.

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_architect_edit_operations.py`. Seed rich rows (marker HTML, scripts, a verification record). Each test runs `architect_node(env.state())` with `env.skills.set("architect", ArchitectOutput(...))`, then asserts `updates`, every row by marker, and `env.messages()`:
  - `test_production_replace_five_with_seven_applies_in_one_turn`: 16 rows/spec, `replace` 4 with seven slides. `target_positions == [4..10]`, there are 22 rows, the rows at 11..21 are byte-identical to old 5..15, the row at 4 is old row 4 (same slide_id), the rows at 5..10 are pending placeholders, and the persisted `deck_spec` has 22 slides with the new purposes at 4..10.
  - `test_delete_only_edit_builds_nothing_and_reviews_deck`: `target_positions == []`, the row is gone, and the others are whole. Then run `foreman_router` on the node's state merged with `updates` and assert it returns `"deck_reviewer"`.
  - `test_move_only_edit_builds_nothing_and_reviews_deck`: the moved row's HTML is byte-identical at its new index, and `target_positions == []`.
  - `test_update_only_edit_writes_no_layout`: version bumped only by the deck-level write (one bump), rows untouched, targets `[2]`.
  - `test_mixed_owner_example`: the Task 1 example on a seeded deck, with targets equal to that `rebuild`.
  - `test_deck_changes_only_reruns_deck_level_review`: `deck_changes(audience=…)`, `operations=None`. `rereview_committed_slides` is reached (stub `review_out`), and the deck-level notice is said.
  - `test_design_contract_change_rebuilds_all_but_untouched_blanks`: a blank entry at a position no op touched is not in `target_positions`.
  - `test_operations_problems_degrade_with_named_sentence`: replace position 29 on 22 slides. `error_state.code == "edit_operations_rejected"`, the message contains `there is no slide 30 — the deck has 22 slides`, and nothing is written (whole-DB snapshot).
  - `test_binding_error_in_operations_degrades`.
  - `test_rows_changed_mid_plan_refuses_without_retry`: monkeypatch `SlideWriter.apply_slide_layout` to raise `SlideRowsChangedError`. `insert_rows_changed`, nothing written. Task 5 will assert exactly one architect call.
  - `test_operations_ignored_on_build_and_describe_only`.
  - `test_old_path_unchanged_without_operations`: one of today's insert tests' outputs (a grown `deck_spec`, no operations) gives the same `updates`.
  - `test_model_targets_disagree_logged`.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_architect_edit_operations.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the path as two helpers, `_plan_operations_edit` and `_apply_edit_plan`, called from `architect_node`. Keep today's path intact for edits without operations.
- [ ] **Step 4: Run** `uv run pytest tests/unit/test_architect_edit_operations.py tests/unit/test_architect_insert_slide.py tests/unit/test_architect_blank_slides.py tests/unit/test_graph_nodes.py -q`, then the whole unit suite against the baseline causes. Expected: green or baseline causes only.
- [ ] **Step 5: Commit** `feat(graph): architect applies edit operations`.

---

### Task 5: One retry, the deferred message and the refusal note

**Models:** test=opus impl=opus

**Files:**
- Modify: `src/services/graph/nodes.py` (`architect_node`, `_degrade_edit`, `_say`, `_conversation`)
- Test: `tests/unit/test_architect_edit_retry.py`; update the existing tests that assert message order (find them with `grep -rn "Editing slide\|Building your deck" tests/unit`).

**Interfaces:**
- Consumes: Task 4's helpers.
- Produces:
  - `_say(state, message, *, message_type="llm_response", metadata: Optional[Dict[str, Any]] = None)`.
  - `REFUSAL_METADATA_KEY = "architect_refusal"`, with payload `{"code": str, "problems": [{"code","positions","detail"}]}`.
  - `RETRYABLE_EDIT_CODES = frozenset({"edit_operations_rejected", "invalid_slide_type_binding", "edit_insert_ambiguous", "edit_spec_moves_slides", "edit_spec_positions_changed"})`.

Behaviour (spec §5 and §7):
- **The retry loop:**
  - There are at most two model calls. After the first answer, run every planning check, which has no side effects.
  - If a retryable degrade results, call `get_agent_runtime().run("architect", …)` again with `payload | {"rejected_edit": {"your_previous_answer": out.model_dump(include={"intent","operations","deck_changes","target_positions"}, mode="json"), "problems": [...]}}`. Today's alignment refusals become problems with `code = f"alignment_{exc.code}"`, `detail = exc.detail` and `positions = ()`.
  - The second answer is handled from the top: intent dispatch, `confirm_design_contract` augmentation, and every check.
  - If the second answer degrades too, degrade with the second answer's problems. For a non-operations refusal, today's code and sentence are used.
  - These never retry: `edit_without_spec`, `spec_positions_stale`, `edit_without_revised_spec`, `insert_rows_changed`, `insert_rows_failed`, and write failures.
- **The deferred message:**
  - For `build` and `edit`, the model's message is emitted and `_say`'d only after every check and the row layout have succeeded, and before `classify_spec_change`.
  - `discuss`, `ask_data` and `confirm_design_contract` keep the immediate emit.
  - On any degrade, only the refusal is said.
- **The refusal row:** `_degrade_edit` saves its sentence with `metadata={REFUSAL_METADATA_KEY: {...}}`.
- **The system note:** `_conversation` appends, right after such an assistant turn, `{"role": "system", "content": "The edit above was NOT applied; nothing in the deck changed. It was rejected because: " + "; ".join(problem details or the code) + "."}`. Rows without the key are replayed exactly as today.

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_architect_edit_retry.py`. Use a `SkillStub` handler that returns answer A on the first call and answer B when `"rejected_edit" in payload`:
  - `test_bad_operations_then_good_retry_applies`:
    - two architect calls;
    - the second payload's `rejected_edit.problems[0].code == "unknown_slide"`;
    - the second payload's `your_previous_answer.operations` equals A's;
    - the rows reflect B;
    - exactly one assistant message is saved, and it is B's message. A's message is in neither the emitted events nor `env.messages()`.
  - `test_two_bad_answers_refuse_with_second_problems`: two calls, `edit_operations_rejected`, and the user sentence names B's problem.
  - `test_retry_answer_can_be_discuss`: B is `discuss`. Its message is said, nothing is written, and `error_state is None`.
  - `test_alignment_refusal_on_old_path_retries`: A is a grown `deck_spec` that is ambiguous (the production shape), and B is the same request as operations. B is applied, and `rejected_edit.problems[0].code == "alignment_ambiguous"`.
  - `test_non_retryable_refusals_call_once`: `spec_positions_stale`, and `SlideRowsChangedError` from the layout writer. One call each.
  - `test_build_message_said_only_after_checks`: a build whose binding fails twice. The only saved message is the binding refusal.
  - `test_message_precedes_deck_level_notice`: on a deck-level edit, the saved messages are [model message, deck-level notice], in that order.
  - `test_refusal_row_carries_metadata`.
  - `test_conversation_replays_refusal_with_system_note`: the turn after a refusal sees `[…, {"role":"assistant", content: refusal}, {"role":"system", content starts "The edit above was NOT applied"}, {"role":"user", …}]`.
  - `test_conversation_unchanged_for_plain_rows`.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_architect_edit_retry.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.** Restructure `architect_node` as `attempt → plan (no side effects) → maybe retry → say → write`. Keep every existing comment that still applies, and move each one with its code.
- [ ] **Step 4: Run** the Task 4 command plus `tests/unit/test_architect_edit_retry.py`, `tests/integration/test_architect_reply_is_persisted.py`, and the full unit suite against the baseline causes. Update tests that pinned the old "message before refusal" order to the new order, and note each such test in the commit message.
- [ ] **Step 5: Commit** `feat(graph): one architect retry on a refused edit; message after the plan lands`.

---

### Task 6: Eval harness scores operations answers; four new cases per split

**Models:** test=opus impl=opus

**Files:**
- Modify: `evals/harness/scorers.py`. Add `_operations_score`, and route edit outputs carrying `operations`/`deck_changes` to it for every edit case.
- Modify: whatever builds the judge input (find it from `scorers.py` / `mlflow_run.py`). An operations answer is normalised to its composed form before the judge sees it: `deck_spec = compose_edit_spec(...)`, `target_positions = list(rebuild)`. Existing references and calibrations then stay comparable.
- Create, under `evals/packs/architect/cases/` and `cases_heldout/`, each with `case.yaml`, `payload.json`, `reference.json` and `calibration.json`, built from the split's existing fixture deck (copy `add_slide_and_revise`'s payload as the base):
  - `delete_slide`
  - `move_slide`
  - `replace_slide_expand` (the production shape: "Replace slide N with these M slides …")
  - `mixed_operations` ("delete slide a, change slide b's title to …, expand the bullets on slide c into three slides")
- Test: `tests/unit/test_eval_operations_scorer.py`, plus the existing `tests/unit/test_eval_*` scorer tests.

**Interfaces:**
- Consumes: Task 1 (`apply_operations`, `compose_edit_spec`) and Task 2.
- Produces:
  - `case.yaml` `expect` may carry `layout: [int|null, …]` (persisted positions, `null` = new), in addition to `intent`, `positions` and `inserted`.
  - `_operations_score(output, expect, current, reference) -> (bool, str)`. It passes only when all of these hold:
    - the intent is `edit`;
    - there are no problems;
    - the composed spec is valid;
    - `rebuild == expect.positions`;
    - the None indices of `layout` equal `expect.get("inserted", [])`;
    - `layout == expect.layout` when given;
    - every slide at a non-rebuilt index equals the current deck's slide at its persisted position, field for field;
    - `DECK_LEVEL_FIELDS` and the design contract equal the reference's (composed).

- [ ] **Step 1: Write the failing tests:**
  - `test_operations_answer_scored_by_production_semantics`: a pass, then each failure mode (wrong rebuild, wrong layout, a problem, a changed untouched slide, a deck-level drift), each with a rationale naming the cause.
  - `test_existing_insert_cases_pass_with_operations_answers`: for every existing `add_slide_*`/`edit_*` case on both splits, the hand-written operations equivalent of its reference passes `_operations_score` with the case's own `expect`. Write the equivalents as a table in the test.
  - `test_spec_answers_still_use_alignment_scorer`.
  - `test_judge_input_is_composed`.
  - `test_new_case_references_pass_and_calibrations_fail`: every new case's `reference.json` passes the deterministic scorer, and `calibration.json` `should_fail` fails it.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_eval_operations_scorer.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the scorer, the normalisation and the eight case directories. Each `reference.json` is an `ArchitectOutput` dump with `operations`, and its `message` follows spec §7. Each `calibration.json` is a plausible wrong answer: the production failure for `replace_slide_expand`, a full-spec grown deck that `align_slides` refuses, and for the others a wrong anchor or a dropped slide.
- [ ] **Step 4: Run** `uv run pytest tests/unit -q -k "eval"` and `uv run python -m evals.run_eval --agent architect --dry-run` if the CLI supports it; otherwise rely on `test_new_case_references_pass_and_calibrations_fail`. Expected: green.
- [ ] **Step 5: Commit** `feat(evals): score architect operations answers; delete/move/replace/mixed cases`.

---

### Task 7: The prompt, measured, then promoted

**Models:** test=opus impl=opus

**Files:**
- Create: `evals/configs/architect/edit-ops.md`, which is the current `INSTRUCTIONS` with the EDITING and SLIDE NUMBERS blocks rewritten per spec §8, with no trailing newline. Also `edit-ops.yaml` (`agent_key: architect`, `name: edit-ops`, `base: v1`, `prompt_file: edit-ops.md`).
- Modify (after measurement): `src/core/skills/architect.py` `INSTRUCTIONS` = the finalist text; `src/services/agent_definition_manifest_v1.py` and the `PACKAGED_V1_CONTENT_HASHES` pins via `uv run python -m evals.harness.promote --config architect=evals/configs/architect/<finalist>.yaml --run-id architect=<run>`.
- Modify: `tests/unit/test_architect_edit_prompt.py`:
  - `EDITING_RULE_PHRASES`/`EDITING_GUARD_PHRASES` become the new rules' phrases: operations, replace, delete, move, -1, deck_changes and `rejected_edit`;
  - drop "removing or reordering slides is not an edit" and the discuss path phrase;
  - add `test_prompt_no_longer_refuses_delete_or_reorder`.
  - Check `tests/unit/test_rc12_architect_asks_add_or_replace.py` against the new text.
- Modify: `evals/README.md`, adding the measured table (the format of the existing tables: run id, config, split, cases, repeats, rows, pass rate, judge errors, tokens, ≈USD).

**Interfaces:**
- Consumes: Tasks 1–6.
- Produces: the promoted v1 manifest architect prompt, which equals `INSTRUCTIONS`.

The prompt must state, in plain words, everything in spec §8 and the §2 table and placement rules.

**Spend plan (cap USD 20 total; ≈ USD 0.18/row):**
1. Calibrate the judge on the four new cases, both splits: `uv run python -m evals.run_eval --agent architect --calibrate --cases delete_slide,move_slide,replace_slide_expand,mixed_operations` and `--split heldout`.
2. Screen each candidate on the four new cases with `--repeats 3`, about USD 2.2 per candidate.
3. Run the finalist on all train cases with `--repeats 3` (about USD 10) and on held-out with `--repeats 1` (about USD 3.5).

Stop if the running estimate would pass USD 20. Up to three candidates.

**Acceptance bar** (spec §9):
- every existing case's train pass rate is at least its recorded `v1-baseline` rate;
- each new case passes at least 2 of 3 on train and 1 of 1 on held-out, decided by the deterministic scorer;
- the judge's calibration is recorded.

If the bar is missed after three candidates, promote the best and record the gap in `evals/README.md` and the PR.

- [ ] **Step 1:** Write the phrase-pin test changes (red against today's `INSTRUCTIONS`) and run `uv run pytest tests/unit/test_architect_edit_prompt.py -q`. Expected: FAIL.
- [ ] **Step 2:** Write `edit-ops.md`/`.yaml`. Check the Databricks auth the harness needs (see `evals/README.md`'s setup section), then run calibration and the screen.
- [ ] **Step 3:** Iterate up to two more candidates (`edit-ops-b`, `edit-ops-c`) only on failures the screen shows. Then run the finalist runs.
- [ ] **Step 4:** Copy the finalist into `INSTRUCTIONS` and run `promote`. Then `uv run pytest tests/unit -q` against the baseline causes, then `uv run pytest tests/unit/test_architect_edit_prompt.py tests/unit/test_graph_definition_manifest.py tests/unit/test_packaged_release_loader.py -q`. Expected: green.
- [ ] **Step 5:** Record the measured table and spend in `evals/README.md`. Commit `feat(architect): edit-operations prompt (measured, promoted)`.

---

### Task 8: Docs

**Models:** test=sonnet impl=sonnet

**Files:**
- Modify: `docs/technical/backend-overview.md`. Rewrite the "Adding a slide (#314)" section as "Editing the deck's slides", covering:
  - the operations and their placement rules;
  - the operations path vs the spec path;
  - the retry and its non-retryable codes;
  - the deferred message and the refusal note;
  - `apply_slide_layout` and the mutation operation mapping;
  - the rollout rule (new prompt only on publish; node code everywhere);
  - the two UI limits.
- Modify: `CONTEXT.md`. Add *operation*, *replace*, *move* and *rejected edit*, in the file's existing glossary style.
- Modify: the spec §9 line "existing references are converted to operations". It becomes "existing references stay; operations answers are composed before the judge sees them (Task 6)". Note it as a plan-time call.

- [ ] **Step 1:** Write the docs.
- [ ] **Step 2:** Run `uv run pytest tests/unit -q -k "docs or context"`. Some repos pin doc anchors; expected: green.
- [ ] **Step 3: Commit** `docs: architect edit operations`.

---

## After the tasks

1. **Whole-branch review (Opus, always; executing-plans-tellr §7).** Ask for:
   - a writer-by-writer table for `_lay_out_slide_rows`, `_splice_slide_rows`, `insert_pending_slides`, `apply_slide_layout`, `save_slide_deck`, `restore_version` and `SessionManager.insert_slide`;
   - a rollback-guarantee ruling (nothing written on any refusal or retry);
   - a merge/no-merge verdict.
2. **Dev deploy:** follow the `deploy-tellr-dev` skill to a **new** devloop instance, `edit-ops`. A fresh instance seeds the promoted manifest. Re-run the production transcript's request on a 16-slide deck. Check it applies in one turn, that delete and move work, and that the deck refetch shows the final order.
3. **PR:** push as the personal gh account, then `gh pr create`. The body states:
   - the rollout rule (existing installs must publish the new architect prompt);
   - the measured eval table;
   - the "calls made without the owner" list;
   - the two UI limits.

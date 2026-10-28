# Architect edit operations — design

**Date:** 2026-10-28
**Status:** approved in conversation with the repo owner. Review-check decisions are recorded under "Calls made without the owner".
**Supersedes:** the edit half of #314's D1 (how an edit says which slides are new). #314's row shift and its guards stay.

## Why

A production user asked the architect to replace slide 5 of a 16-slide deck with seven slides: one overview slide plus six stage slides. The architect produced the right plan twice, and the code refused it both times with "I could not tell which of the existing slides I was changing and where the new slide goes…". The user only got the change by splitting it into two edits.

The cause is structural, not the model:

- Today an edit returns the whole revised `deck_spec`. `architect_node` then reconstructs what changed with `align_slides` (`src/domain/slide_alignment.py`).
- When a slide is rewritten and new slides land next to it, every pairing ties, so the alignment refuses with `ambiguous`. The #314 plan recorded this as a known risk: "Ambiguity refusals annoy users… No eval case measures it". "Replace slide N with M slides", "expand slide N", "split slide N" and "add a slide after N and rewrite N" are always refused, whatever the model returns.
- Deleting and reordering are not supported at all. A shorter spec is refused by the position guard. The prompt tells the model to answer `discuss`.
- Removing that prompt line on a staging instance changed nothing, because the refusals happen in code after the model has answered.

Three things made it look like the model was misbehaving:

1. The model's message ("Slide 5 is now…") is shown and saved before the plan is checked, so the refusal arrives after a success claim.
2. The refusal is saved as an `llm_response`. On the next turn the architect reads it as its own words, with no reason attached, so it apologises and resends the same plan.
3. The refusal sentence's advice does not fit a replace request.

## Goals

- One chat message can ask for any combination of edits, and the turn applies them together as one change. The edits are: **insert**, **update** and **delete**, plus **replace** ("slide N becomes these M slides") and **move**. Example: "delete slide 4, add a slide after 5 about X, expand the three bullets on 6 into three slides".
- No refusal for a well-formed combination.
- A slide the edit does not touch keeps its HTML, hand edits, identity and records, and is not rebuilt. Only its number may change.
- A moved slide is a database change. Its HTML is not regenerated and it is not rebuilt. Its spec entry moves with it.
- When the architect's list is wrong, the architect is told exactly what is wrong and gets one automatic retry. Only then is the user refused, with a sentence that names the problem.
- What the user is told matches what happened.

## Non-goals

- A tool loop where the architect calls one tool at a time and sees each result. The owner decided on **one model answer listing every operation**, as today: one call per turn.
- Changing how a new deck is built (`build` intent).
- Changing the describe-only arc-review sweeper (`spec_sync.run_arc_review`). It keeps re-describing the deck through a full `deck_spec`.
- Changing the slide panel's own insert, delete, duplicate and reorder routes.
- Moving conversations that are pinned to an older graph release onto the new prompt.

## Anti-goals (a failure even if it "works")

- Rebuilding a slide that was only moved, or not touched at all.
- Applying part of a list. The whole list lands, or nothing does.
- Telling the user an edit is done before it has been applied.
- Guessing which slide an operation meant.

## Decisions made with the owner

1. **One answer with an ordered list of operations.** The architect does not run a tool loop. The code checks the whole list against the current deck and applies it as one change.
2. **The operations:** insert, update, delete, replace and move. Replace is a convenience operation, so the model does not have to break "expand/split slide N" down itself. Move is a pure database change.
3. **Slide numbers count from the deck before the message,** which is what the user was looking at. The architect already gets `slide_numbering` and `slide_references` resolved against that deck.
4. **Move and delete rebuild nothing.** The rows and the spec are rewritten, no HTML is regenerated, and the per-slide build and review are skipped for those slides. Deck review always runs over the whole deck after an edit that changed it.
5. **A bad list:** one automatic retry, in which the architect sees the exact problems. Then a refusal that names them. Nothing is applied unless the whole list checks out.
6. **A refused turn is recorded** so that the architect reads the reason next turn as a system note, not as its own words.
7. **The architect's message waits** until the plan has been checked and applied.
8. **Deck-level changes** (title, audience, purpose, argument, call to action, narrative arc) can come with the list when the user asks for them. They re-review every slide as today. A design-system or slide-style change still goes through `confirm_design_contract` first.
9. **Build and describe-only are unchanged.**
10. **Rollout:** this ships as a new architect prompt and output field. Conversations pinned to an older release keep today's prompt. New eval cases cover delete, move, replace and mixed requests, including the production "replace slide 5 with 7" message.
11. One save point per message: the whole list is one deck version and one undo. Graph turns already get exactly one save point per turn from `chat_service`, so this holds without new work.

## Design

### 1. What the architect returns

`ArchitectOutput` (`src/domain/skill_io.py`) gains two **optional** fields. Nothing is removed or renamed.

```python
class SlideContent(BaseModel):
    """A SlideSpec without its position: what one slide must say and how it binds."""
    purpose: str
    content_brief: str
    assumes: str
    hands_off: str
    data_references: list[str]
    slide_type: Optional[str] = None
    template_section_index: Optional[int] = None

class SlideOperation(BaseModel):
    op: Literal["insert", "update", "delete", "replace", "move"]
    position: Optional[int] = None        # the slide acted on (update/delete/replace/move)
    after_position: Optional[int] = None  # insert/move: goes after this slide; -1 = before the first slide
    slides: Optional[list[SlideContent]] = None  # insert (>=1), update (exactly 1), replace (>=1)

class DeckChanges(BaseModel):
    """Deck-level fields this edit changes; an unset field is unchanged."""
    title: Optional[str] = None
    audience: Optional[str] = None
    purpose: Optional[str] = None
    argument: Optional[str] = None
    call_to_action: Optional[str] = None
    narrative_arc: Optional[list[str]] = None
    design_contract: Optional[DesignContractRef] = None
    resolved_data: Optional[ResolvedData] = None

# on ArchitectOutput
operations: Optional[list[SlideOperation]] = None
deck_changes: Optional[DeckChanges] = None
```

- `SlideOperation` is **flat**, with the per-op rules checked in the domain module (§3), not in pydantic. A pydantic error fails the whole turn with a runtime error and gives the model no retry. A problem found by the domain check is retryable.
- Every `position` and `after_position` is a `SlideSpec.position` of the **current** deck. The model reads them off `slide_numbering`/`slide_references`, exactly as it reads `target_positions` today.
- `ArchitectOutput`'s validator today requires a non-empty `target_positions` on an edit. It becomes: an edit needs a non-empty `target_positions` **or** a non-empty `operations`. A delete- or move-only edit builds nothing and has no targets.
- `SlideSpec` and `DeckSpec` do not change. `SlideContent` duplicates `SlideSpec`'s fields minus `position`, and a test pins that the two stay in step.

### 2. What the operations mean

All positions refer to the deck as it was before the message.

| op | needs | meaning |
|---|---|---|
| `update` | `position`, `slides` = 1 | Slide `position` gets this spec and is rebuilt in place. It keeps its row. |
| `replace` | `position`, `slides` ≥ 1 | Slide `position` becomes these slides. The first takes over the old slide's row and is rebuilt. The rest are new slides directly after it. |
| `insert` | `after_position`, `slides` ≥ 1 | New slides after slide `after_position` (`-1` = at the start), in list order. |
| `delete` | `position` | The slide and its spec entry are removed. Nothing is rebuilt. |
| `move` | `position`, `after_position` | The slide moves to directly after `after_position` (`-1` = to the start). Not rebuilt, and its spec entry is unchanged. |

**Placement rules.** These are deterministic, so nothing is guessed:

- A slide can be the subject (`position`) of **at most one** operation. A replace is one operation.
- Anything placed "after slide *a*" (inserted slides and moved slides) goes directly after *a*'s own content, in the order the operations appear in the list. *a*'s own content means *a* itself, or all of its replacement slides.
- "After slide *a*" follows *a* if *a* is moved, and fills *a*'s gap if *a* is deleted.
- A slide cannot be moved after itself, and moves cannot form a loop.

The composed deck is: the slides placed at the start, then each current slide in order. A slide that is moved away is skipped where it was and appears where it was placed. Each slide's own content (unchanged, updated, replaced, or nothing if deleted) is followed by whatever was placed after it, recursively. The result is re-stamped to positions `0..m-1`.

### 3. The domain module: `src/domain/slide_operations.py` (new, pure)

`apply_operations(current: Sequence[SlideSpec], operations: Sequence[SlideOperation]) -> OperationsResult | OperationProblems`

- **`OperationsResult`:**
  - `slides`: the composed `SlideSpec` list, re-stamped `0..m-1`.
  - `layout`: one entry per new index, holding either the current position whose row lands there, or `None` for a new slide.
  - `rebuild`: the new indices to build, which are inserted, updated and replaced slides.
  - `deleted`: the current positions removed.
  - `moved`: the current positions moved.
- **`OperationProblems`:** a list of problems. Each one has a stable `code`, the positions involved, and a plain sentence the architect can act on. Codes:
  - `unknown_slide`: a `position` or `after_position` is not in the current deck.
  - `slide_targeted_twice`
  - `missing_slides`: insert or replace with no `slides`.
  - `update_needs_one_slide`
  - `missing_position`
  - `missing_after_position`
  - `move_after_itself`
  - `move_loop`
  - `deck_emptied`: the result has no slides.
  - `nothing_to_do`: no operations and no deck changes.
- Every problem is collected in one pass, so one retry can fix them all.
- It never raises on bad input and reads no database.
- `slides` on a `delete` or `move` is ignored, not refused.

### 4. `architect_node` on an edit

Node order for an edit that carries `operations` (the "operations path"):

1. The same up-front guards as today:
   - `edit_without_spec`;
   - `spec_positions_stale`, the persisted spec must still describe the committed rows;
   - describe-only handling.
2. `apply_operations(prior_spec.slides, out.operations)`. Problems mean a retry (§5).
3. Compose the new spec: the persisted spec, plus `deck_changes` fields that are set, plus the composed slides. Then run today's `complete_index_only_bindings` and `invalid_slide_bindings`. A binding error is a retryable problem too, reported against the op that introduced the slide. The DeckSpec validators (non-empty title, design-contract rules) are checked here, and a violation is a retryable problem.
4. **Lay out the rows** in one transaction with `SlideWriter.apply_slide_layout`, which generalises today's `insert_pending_slides` (§6). This happens before any builder is dispatched and before `classify_spec_change`, as for an insert today.
5. **Say the architect's message** (§7), then `classify_spec_change`:
   - `design_contract`: every position is rebuilt, as today.
   - `deck_level`: today's serial re-review of every committed slide, rebuilding the failing ones plus `rebuild`.
   - `none`: `target_positions = rebuild`.
6. Pre-fan-out deck-level write, as today.

`target_positions` is always the derived `rebuild` set (in the canonical numbering). The model's own `target_positions` is ignored on this path, and a difference is logged, as on today's insert path. An empty `rebuild` (delete/move only) routes the foreman straight to deck review. `_covered_positions` returns `[]`, so `all_positions_committed` is true. That is existing behaviour.

**An edit without `operations`** goes through today's path, unchanged: alignment, position guard, insert shift. This covers:

- sessions pinned to an older release, whose prompt never mentions operations;
- the describe-only sweeper;
- a model that ignores the new prompt.

With the new prompt, an edit that returns only a `deck_spec` still works if alignment can read it. If alignment refuses, the refusal gets the same single retry (§5), and the problem tells the model to list the changes as operations.

`describe_only` turns ignore `operations` entirely. They re-describe the deck through `deck_spec` exactly as today, and they dispatch nothing.

**`operations` and `deck_changes` on any other intent** (`build`, `discuss`, `ask_data`, `confirm_design_contract`) are ignored, with an INFO log. A build still uses its `deck_spec`, and only an `edit` takes the operations path.

**Blank slides keep today's rule (#314 N1, #337), now decided on the composed deck.**

- A blank entry (`is_blank_slide_spec`) at composed index *i* is *untouched* when *i* is not in `rebuild`, meaning no insert, update or replace produced it.
- Untouched blanks are dropped by `_drop_untouched_blanks` from all three build lists, exactly as today: the targets (empty by construction), the design-contract rebuild-all, and the deck-level rebuild set.
- The "named but not described" notice still fires when the user's message named a blank slide that no operation touched. `slide_references` count the pre-message deck, so a named position is mapped through `layout` to its composed index first.
- On this path the helper takes `rebuild` and the composed slides instead of an alignment.

### 5. One retry

Some refusals are **retryable planning refusals**:

- operations problems;
- binding errors;
- DeckSpec validation problems;
- today's `edit_insert_ambiguous`, `edit_spec_moves_slides` and `edit_spec_positions_changed`.

On one of these, the node calls the architect **once more** with the same payload plus:

```json
"rejected_edit": {
  "your_previous_answer": { "intent": "...", "operations": [...], "deck_changes": {...}, "target_positions": [...] },
  "problems": [ { "code": "unknown_slide", "positions": [29], "detail": "position 29 is not in the deck; positions run 0..21" } ]
}
```

- The second answer is handled exactly like a first answer, and it may be a different intent, such as a `discuss` question to the user. If it is refused again, the turn degrades with a user-facing sentence built from the problems, in 1-indexed slide numbers ("Slide 30 doesn't exist — the deck has 22 slides").
- These do **not** retry, because the model cannot fix them: `edit_without_spec`, `spec_positions_stale`, `insert_rows_changed` (the deck changed under the planner), and write failures.
- At most one retry per turn, so at most two architect calls. The retry runs before anything is said or written.

### 6. The row writer: `SlideWriter.apply_slide_layout`

This generalises `insert_pending_slides`. Today's insert is the special case of a layout with old rows in order and `None` entries for the new slides.

`apply_slide_layout(session_id, layout, *, deck_spec, expected_rows, created_by, mutation)`:

- `layout[i]` is the current position whose row lands at new index `i`, or `None` for a new pending slide. A current position can appear at most once, and an absent one is deleted.
- In one `get_db_session()` transaction:
  1. Re-read the rows and require `[(slide_id, content_hash)] == expected_rows`, else `SlideRowsChangedError` (as today).
  2. Snapshot and attribute every old row before any write.
  3. Lay out the deck with the exact old-row map through `_rewrite_slide_rows` (no attribution heuristic, `now_dt=None`, `author_fallback=None`). Open a pending placeholder for each `None`.
  4. Prune the rows beyond the new count. That is how a deleted row goes.
  5. Write `deck_spec_json`, bump `version`, and touch `last_activity`.
  6. Record one mutation event.
- `_splice_slide_rows` becomes the in-order special case of the general layout primitive, so the slide panel's manual `SessionManager.insert_slide` keeps sharing the one shift primitive.
- A moved or untouched row keeps its `slide_id`, HTML, scripts, authorship, timestamps, verification record and spec fragment.
- An updated or replaced row keeps its identity until its builder overwrites the HTML, as an edited slide does today.
- If the layout is the identity (an update-only edit), nothing shifts and no write happens here. Builders overwrite in place, as today.

### 7. What the user sees

- **The architect's message is said** (emitted and saved) only after the plan has passed every check and the rows have been laid out, just before the deck-level re-review notice. This applies to `build` and `edit` on both paths. `discuss`, `ask_data` and `confirm_design_contract` still say their message straight away. On a refusal, only the refusal is said, and the model's own message is never shown.
- **A refusal row** is still saved as an `llm_response`, so the UI shows it as today. Its `metadata` carries `{"architect_refusal": {"code": ..., "problems": [...]}}`. `_conversation` replays such a row as the assistant turn, followed by `{"role": "system", "content": "The edit above was NOT applied; nothing in the deck changed. It was rejected because: …"}`. The architect then knows next turn that a check rejected the plan, and why. `_say` gains an optional `metadata` argument.
- **The message wording** (prompt): the message says what the edit will do. New slides are referred to by their number in the revised deck, and deleted slides by the number they had.

### 8. The prompt

This rewrites the EDITING and SLIDE NUMBERS blocks of `src/core/skills/architect.py` `INSTRUCTIONS`:

- An edit returns `operations`, plus `deck_changes` when the user asked for a deck-level change. It no longer returns the whole `deck_spec`. The operations table and placement rules from §2 go in, in plain words.
- "Removing or reordering slides is not an edit" is removed. Deleting and moving are edits.
- "Expand", "split" and "replace slide N with…" map to `replace`. "Rebuild slide N" with no content change is an `update` with the slide's current content.
- `target_positions` is not needed on an edit that has `operations`.
- The meaning of `rejected_edit` in the payload: fix every listed problem and answer again.
- A short line keeps the describe-only behaviour: when asked to re-describe what is there, return the full `deck_spec`.
- The design-contract confirmation rule stays. A confirmed contract is committed through `deck_changes.design_contract` on an edit, or `deck_spec` on a build.

### 9. Evals

`evals/packs/architect`:

- **New cases on both splits:**
  - `delete_slide`;
  - `move_slide`;
  - `replace_slide_expand`, which is the production transcript shape: rewrite slide N and add M−1 after it;
  - `mixed_operations`: delete + update + expand in one message.
- **The existing `add_slide_*` and `edit_*` references** are converted to operations.
- **Scorer:** a case whose `expect` names operations is scored with production's own `apply_operations` on the payload's `current_deck_spec`. The row passes when there are no problems, the composed layout and `rebuild` set equal the expectation, untouched slides are byte-identical in spec, and deck-level fields equal the reference's. This is the same "production semantics" principle as the #314 insert scorer.
- **Measure:** a measured run of the new prompt on train ×3 and held-out ×1 before promotion, with results recorded in `evals/README.md`. The prompt is then promoted into the frozen manifest with `evals.harness.promote` (the #314 precedent).
- **Acceptance bar for promotion:**
  - every existing architect case passes on train ×3 at least as often as the recorded `v1-baseline` numbers, so there is no regression;
  - each new case passes at least 2 of 3 on train and 1 of 1 on held-out, decided by the deterministic scorer;
  - the judge's calibration on each new case is recorded, and a case it cannot separate is scored deterministically, as `fill_blank_slide` is today;
  - total eval spend for the change is capped at **USD 20**;
  - up to three prompt candidates are tried. If none meets the bar, the best one is still promoted so the dev deploy exercises the feature, and the PR says plainly that the prompt is not ready to publish.

### 10. Shipping

- **`ArchitectOutput` changes canonically.** Overlays cannot carry a structured field. The architect's v1 and v2 schema digests are re-pinned, and the superseded values move into `_HISTORICAL_DIGESTS`, as commit 5653f3ec did. Every pin listed in the recon is updated: the registry tests, `test_architect_edit_prompt`, the retained-bundle ledger, the manifest content hashes, the packaged loader, the draft, runtime and persisted-runtime tests.
- **The frozen manifest** (`agent_definition_manifest_v1.py`) gets the new prompt and contract digest via `promote`. A fresh install seeds it.
- **An existing install** gets the new prompt only when an admin publishes it (draft → publish), and only new conversations pick it up. Node code ships immediately and applies to every release:
  - the deferred message;
  - the retry;
  - the refusal note;
  - the operations path whenever a model emits `operations`.

  Older releases send the new optional field in the schema but never ask for it. All of this is additive.
- **`docs/technical/backend-overview.md`:** the "Adding a slide (#314)" section becomes "Editing the deck's slides", covering operations, placement rules, the retry and the writer. `CONTEXT.md` gets the vocabulary (operation, replace, move).

### 11. Frontend: no change, two known limits

This change is backend-only. The slide panel already re-reads the deck when a turn completes, so moved, deleted and inserted slides appear correctly once the turn ends. Two limits are accepted and documented:

- **No "New" chips on a turn that also deletes.** `frontend/src/components/SlideViewer/newSlides.ts` `diffNewSlides` flags new slides only on pure growth. A baseline id that disappears reads as a replace, so nothing is flagged.
- **A delete- or move-only turn shows the old order until it completes.** No slide is built, so no `slide_ready` event arrives mid-turn. #314 already accepted the same limit for inserts (D5).

## Left to the builder

- Exact wording of the prompt blocks and refusal sentences, within §7 and §8.
- The mutation-event operation name for a mixed layout (an existing one, or a new name added wherever operation names are validated).
- How `SlideContent` field parity with `SlideSpec` is pinned.
- Whether `_splice_slide_rows` is rewritten in terms of the layout primitive or the layout primitive wraps it, as long as there is one shift primitive.
- How the judge prompt reads an operations answer. The deterministic scorer decides the row, and the judge's calibration is recorded.

## Calls made without the owner (review these)

The owner delegated these as long as they don't meaningfully change behaviour.

- **Replace = update + inserts**, not delete + inserts. The first replacement slide keeps the old slide's row and identity. Either reading produces the same deck.
- **Positions, not slide numbers, in operations**, matching how `target_positions` works today. The user still speaks in slide numbers, and the payload maps them.
- **`after_position: -1`** means "at the start", instead of a separate `before_position` field. One field means one way to say it.
- **Anchors follow moved slides and fill deleted slides' gaps**, and several things "after" one slide keep list order.
- **The old full-spec edit path stays** as a fallback instead of being removed. Pinned releases and the describe-only sweeper need it anyway, and the node always receives the current output class.
- **The retry also covers today's alignment refusals,** not only operations problems. It is one extra model call, and only on a turn that would otherwise be refused.
- **Deferring the message applies to `build` too.** A binding refusal on a build had the same "message then refusal" problem.
- **`slides` on a delete or move is ignored**, not refused, to avoid needless retries.
- **`operations` on a non-edit intent is ignored** with a log line, not applied and not refused.
- **Blank slides keep today's never-build-an-untouched-blank rule**, decided on the composed deck.
- **Backend-only:** the two UI limits in §11 are accepted, not fixed. Fixing the chips would change how `diffNewSlides` treats replaces and restores.
- **The eval bar and the USD 20 cap** in §9, and promoting the best candidate even if it misses the bar, flagged in the PR, so the dev deploy can exercise the feature.

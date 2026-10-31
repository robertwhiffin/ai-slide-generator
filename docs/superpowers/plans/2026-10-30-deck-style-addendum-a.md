# Deck Style Addendum A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Also load `executing-plans-tellr`. Steps use checkbox (`- [ ]`) syntax.

**Goal:** agent-mode slides get the design system's brand assets (builders search for icons; the architect places the logo), stable page numbers, and one shared ground for content slides.

**Architecture:**
- **Page numbers:** a pure token helper fills `{{slide:number}}` / `{{slide:count}}` at every reader boundary, reversibly (marker spans are turned back into tokens on save). Streaming events substitute with the spec's count.
- **Logos:** the architect payload's `deck_style_context` gains `logos`.
- **Icon search:** the agent runtime gains an opt-in tool loop. Builder and fixer get `search_brand_assets`, bound only when a design system is active and the payload carries a `deck_style`.
- **Prompts:** the architect, builder and fixer prompts are rewritten, measured and promoted.

**Tech Stack:** Python 3.11, Pydantic v2, LangChain/ChatDatabricks, LangGraph, SQLAlchemy, pytest, the `evals/` harness, React/TS.

**Spec:** `docs/superpowers/specs/2026-10-29-architect-deck-style-design.md`, section "Addendum A" and its "Calls made without the owner (Addendum A)" list.

## Global Constraints

- **Python env:** the per-worktree uv `.venv`; run everything as `uv run …`; never `pip install`.
- **Legacy (monolith) mode is untouched.**
- **Frozen artefacts:**
  - No schema model docstring or validator changes in `deck_spec.py`, `slide_operations.py` or `skill_io.py`. These are hashed into the architect digests.
  - Prompts change only through measured promotion.
- **Old decks and old releases are byte-identical** in model payloads, bindings, CSS writes and stored HTML.
  - The tool loop binds only when `design_system_active` and the payload has `deck_style`.
  - The page-token substitution is a no-op on HTML without tokens.
- **Tokens:** `{{slide:number}}` and `{{slide:count}}`. Marker on output: `<span data-tellr-slide="number">N</span>` / `<span data-tellr-slide="count">M</span>`.
- **Tool loop:** at most 3 search rounds, then the model must return its output through the schema tool. Tool results are spotlighted as untrusted data. The workbench test-run path stays unbound.
- **`logos`:** at most 12 rows of `{handle, filename}`, from kinds `logo` and `lockup`, ranked with the default-ground variant first and SVG before raster.
- **Eval spend:** cap USD 25 (architect ≤ 12, builder + fixer ≤ 11, slack 2).
- **Commits** end with `Co-authored-by: Isaac <no-reply@databricks.com>`.
- **One agent in the worktree at a time** whenever a commit is needed.
- **Ledger:** this plan's SDD workspace `progress.md`. Corrections go in `~/tellr-loop/deck-style/PLAN-CORRECTIONS-A.md`.

## Review Focus

1. **A hand-edited slide followed by a move.** The number follows the slide's new position, because save re-tokenises. → B1 `test_hand_edited_slide_keeps_live_numbers_after_a_move`.
2. **A deck from an older release** (no `deck_style`). The builder binding equals today's: no tool is bound and the payload is unchanged. → B3 `test_no_tool_without_deck_style`.
3. **A model that searches forever.** After 3 rounds the call must return output, or it fails like today's no-tool reply. → B3 `test_search_rounds_are_capped`.
4. **Mid-build streaming.** No literal `{{slide:` text reaches the client. → B1 `test_slide_ready_substitutes_page_tokens`.
5. **A search result carrying instructions or a foreign handle.** It is spotlighted, and the foreign handle stays unresolved. → B3 `test_tool_results_are_spotlighted`, plus the existing scoping in `ds_asset_utils`.

---

### Task B1: Page-number tokens

**Models:** test=opus impl=sonnet

**Files:**
- Create `src/utils/slide_number_tokens.py`. Pure. It holds:
  - `substitute_slide_numbers(html: str, number: int, count: int) -> str`
  - `retokenise_slide_numbers(html: str) -> str`
  - `substitute_deck_slide_numbers(deck_dict: dict) -> dict`, which numbers slides by their order in the dict.
- Modify every reader path that resolves ds-asset handles for a reader (the pre-pass lists them exactly): `chat_service._substitute_images_for_response`, the session_manager read (~3458), export (~525), google_slides, export_job_queue, and thumbnails if separate.
- Modify the streaming paths (`_release_slides` / `slide_ready`, and `/chat/poll` slides and revisions), substituting with `count = len(spec.slides)` and `number = position + 1`.
- Modify every slide save path (`chat_service.update_slide` and the editor save routes) to call `retokenise_slide_numbers` before storing.
- Tests: `tests/unit/test_slide_number_tokens.py`, plus route-level tests.

**Interfaces — produces:** the three functions above.

- [ ] **Step 1:** tests.
  - Substitution and re-tokenising round-trip exactly.
  - HTML without tokens comes back byte-identical.
  - `test_hand_edited_slide_keeps_live_numbers_after_a_move`.
  - `test_slide_ready_substitutes_page_tokens`.
  - Each reader path substitutes; each save path re-tokenises.
  - A legacy deck is unchanged.
- [ ] **Step 2:** red.
- [ ] **Step 3:** implement.
- [ ] **Step 4:** run the full unit suite and the integration slices touched (export, slides, streaming).
- [ ] **Step 5:** commit `feat(slides): live page-number tokens, reversible on save`.

### Task B2: Logos in the architect's deck_style_context

**Models:** test=opus impl=sonnet

**Files:**
- Modify `src/services/graph/nodes.py`, where the architect payload is built. Pass `logos` rows from `design_system_service.search_assets` (kinds `logo` and `lockup`, ranked and capped per the constraints) into `deck_style_context`.
- Keep `src/domain/deck_style.py` pure: `deck_style_context` takes the rows as a parameter.
- Update the eval architect generators: the Meridian fixture gets a small fake logo set. Then regenerate and update the pins (the Task 5 content pin).
- Test: `tests/unit/test_deck_style_logos.py`.

- [ ] Tests:
  - the context holds `logos` with ranking and cap;
  - an unpinned deck gets `logos == []`;
  - no bytes or base64 appear.

  Then red → implement → suite → commit `feat(graph): logo context for the architect`.

### Task B3: Opt-in tool loop for builder and fixer

**Models:** test=opus impl=opus

**Files:**
- Modify `src/services/agent_runtime.py`. `run(...)` accepts an optional list of tools. When present, it binds `[*tools, schema]` with `tool_choice="auto"` and loops:
  - each tool call is executed, its result spotlighted, and a ToolMessage appended;
  - at most 3 search rounds;
  - the round that calls `schema` parses exactly as today.
- Modify `src/core/skills/{builder,fixer}.py`: `TOOL_GRANTS = ["search_brand_assets"]`. Also update the `skills/__init__` rule comment and its pinning test.
- Modify `src/services/graph/nodes.py` in `builder_node` and `fixer_node`. Build `build_ds_asset_tool(design_system_id)` only when `design_system_active` and the payload has `deck_style`, and pass it to the runtime. The design-system id comes from the branch payload's `design_contract`.
- Workbench test runs pass no tools.
- Tests: `tests/unit/test_agent_runtime_tool_loop.py`, `tests/unit/test_builder_brand_search.py`.

- [ ] Tests, with a fake chat model that emits tool calls:
  - one search then output;
  - `test_search_rounds_are_capped`;
  - `test_tool_results_are_spotlighted`;
  - `test_no_tool_without_deck_style` (binding identical to today's);
  - the fixer gets the tool;
  - workbench runs bind no tool.

  Then red → implement → full suite + `test_graph_orchestration.py` → commit `feat(runtime): builders and fixers can search brand assets`.

### Task B4: Eval harness, the tool path and new cases

**Models:** test=opus impl=opus

**Files:**
- Modify `evals/harness/…`: when a builder or fixer case payload carries `deck_style` and a design system is active, the predict function supplies a fake `search_brand_assets` backed by a Meridian fake asset index (`evals/fixtures/meridian/assets.json`: a few product icons and logos with handles).
- New builder case `deck_style_icons`, on both splits, generated: the look asks for icons. A deterministic scorer `brand_asset_use_score` passes when the HTML holds at least one handle from the index, no handle outside it, and the trace shows a search.
- `_deck_style_score` (architect builds) also requires:
  - a footer piece whose example HTML holds a handle from `deck_style_context.logos`;
  - both page tokens.
- Update the pins: case ids and counts.
- Tests: `tests/unit/evals/test_eval_brand_assets.py`.

- [ ] Tests:
  - scorer pass and each failure;
  - harness wiring;
  - references pass and calibrations fail;
  - existing cases unaffected.

  Then red → implement → evals and the full suite → commit `feat(evals): brand-asset search scoring and cases`.

### Task B5a: Architect prompt — measured, promoted

**Models:** test=opus impl=opus

- [ ] **Phrase pins** for:
  - the footer piece with logo handle(s) from `logos` (light and dark variants) and both page tokens;
  - every slide except the cover uses a footer;
  - looks state icon intent and never name handles;
  - one ground;
  - dark slides use the light logo.
- [ ] **Measure** per the optimise-agent-prompt skill:
  - a baseline on the regenerated cases;
  - screen the deck-style cases;
  - the finalist on train ×2 and held-out ×1.
  - Bar: existing cases ≥ baseline − 1 row; the deck-style cases ≥ 2/3 and 1/1.
- [ ] **Promote**, update the pins, re-record the contract, update the README, then commit `feat(architect): brand footer, page numbers, icon intent (measured, promoted)`.

### Task B5b: Builder and fixer prompts — measured, promoted

**Models:** test=opus impl=opus

- [ ] **Phrase pins:**
  - place the assets the catalogue names;
  - search and place icons when the look asks or the slide shows products or concepts, and never invent a handle;
  - bound slides fill the template's footer (label, page tokens, logo), unbound slides use the footer piece, and never two footers;
  - one-ground rule (light sections on the deck's default ground; dark unchanged);
  - "Without a deck style" rules unchanged.

  Replace the IMAGE RULES line "If no image ids are supplied, build the slide without images" for decks that have a deck style.
- [ ] **Measure:** the builder pack (incl. `deck_style_icons`) ×2 train, ×1 held-out; the fixer pack ×1. Bar: `deck_style_icons` ≥ 2/3, and no existing case regresses by more than 1 row.
- [ ] **Promote** both, update the pins, re-record the contract, then commit `feat(builder,fixer): search and place brand assets; one footer; one ground (measured, promoted)`.

### Task B6: Docs

**Models:** test=sonnet impl=sonnet

- [ ] `backend-overview.md`'s deck-style section gets page tokens, the tool loop, logos and one ground.
- [ ] `CONTEXT.md` gains "page tokens".
- [ ] The spec's "Changes during the build" gets the Addendum A items.
- [ ] Commit.

## After the tasks

1. Whole-branch review (Opus) of the addendum range. Then one fix wave and one scoped re-review.
2. Push and CI.
3. Devloop:
   - `deploy_local update --env devloop --instance deck-style` with a new `.devN`;
   - the redeploy re-forks the DB, so re-publish the branch prompts (owner-authorised for this instance) with `publish_deck_style.py`;
   - rebuild the Lakebase reference deck;
   - compare with the owner's legacy deck: icons, logo, page numbers, grounds.

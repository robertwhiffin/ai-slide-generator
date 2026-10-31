# Architect Deck Style Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. In this repo also load `executing-plans-tellr` (`.claude/skills/executing-plans-tellr/`).

**Goal:** on the graph (agent) engine, the architect writes a thin per-deck *deck style* (CSS plus a catalogue of pieces) and a per-slide `look`. Builders and fixers build every slide from those, so a deck is visually consistent across its parallel builders.

**Architecture:**
- **Domain:** `DeckSpec` gains an optional `deck_style`, `SlideSpec` an optional `look`, and `DeckChanges` an optional `deck_style`.
- **Sanitiser:** a pure module (`src/domain/deck_style.py`) sanitises a deck style, scans CSS and HTML class usage, and derives the design-token / template-class context the architect needs.
- **`architect_node`:** sanitises the answer's deck style before anything is committed, and writes it into `deck.css` after the template block. It refuses an edit that drops a class still used by a slide it does not rebuild.
- **Payloads:** each model-facing payload (builder, build reviewer, fixer, fix reviewer) carries the deck style when one exists.
- **Prompts:** the five prompts are rewritten, measured and promoted.
- **Old decks:** when a deck has no deck style, every payload and every CSS write is byte-identical to today.

**Tech Stack:** Python 3.11, Pydantic v2, tinycss2, LangGraph, SQLAlchemy (SQLite unit / Postgres CI), pytest, the `evals/` MLflow harness, React + TypeScript + vitest.

**Spec:** `docs/superpowers/specs/2026-10-29-architect-deck-style-design.md`. Read it first; this plan argues from it.

## Global Constraints

- **Python env:** the per-worktree uv `.venv`. Run everything as `uv run …` from the worktree root. Never `pip install`.
- **Legacy (monolith) mode is untouched.** Do not edit `src/core/prompt_modules.py`, `src/services/agent.py`, `src/services/agent_factory.py` or `src/services/agent_resolution.py`.
- **Field shape in `src/domain/deck_spec.py`.** Every new field is a plain annotation with an `= None` default. No `Field(...)`, no `=` inside a default, no multi-line annotation, no trailing comment on the field line. The frontend guards read this file as text (`frontend/src/test/pydanticSource.ts`).
- **Models live in `deck_spec.py`.** `DeckStyle` and `DeckStyleComponent` are defined there, not imported, so the guards can see them.
- **Schema digests:** only the architect's v1/v2 digests change. Every other role's digests stay byte-identical. Changes are additive: new fields optional, nothing removed or renamed.
- **Deck style constants** (in `src/domain/deck_style.py`):
  - class prefix `dk-`, custom-property prefix `--dk-`;
  - `DECK_STYLE_TARGET_CHARS = 4000`, `DECK_STYLE_MAX_CHARS = 10000`;
  - `DECK_STYLE_MAX_COMPONENTS = 12`.
- **Deck style CSS rules, enforced by the sanitiser and never by a Pydantic validator.** A schema rejection would fail the whole architect turn.
  - Every selector of every rule contains a `.dk-` class. The exception is `:root`, which may declare only `--dk-` custom properties.
  - No `@import`, `@font-face`, `@charset` or `@namespace`.
  - `url()` only with `data:`. No `expression(`. No `<style>` / `</style>` text.
- **Old decks unchanged.** No `deck_style` key appears in any builder / reviewer / fixer payload when the spec has none, and `deck.css` writes are identical to today.
- **No page numbers** in the deck style (spec §1).
- **Eval spend:** USD 40 for the whole change, offline evals only. Sub-caps: architect USD 22, builder + fixer USD 10, build + fix reviewer USD 6, slack USD 2.
- **Reference material:** `~/tellr-loop/deck-style/` is never committed.
- **Commits** end with `Co-authored-by: Isaac <no-reply@databricks.com>`.
- **Ledger:** `~/tellr-loop/deck-style/LEDGER.md`. Plan corrections go in `~/tellr-loop/deck-style/PLAN-CORRECTIONS.md`.

## Review Focus

1. **An old deck edited after deploy.** Every payload and the `deck.css` write match today's byte for byte. → Task 4 `test_deck_without_style_writes_css_as_today`, Task 5 `test_payloads_without_deck_style_carry_no_key`.
2. **The describe-only re-description** returns a full `deck_spec` without a deck style. The persisted deck style must survive. → Task 6 `test_full_spec_edit_keeps_persisted_deck_style`.
3. **A hostile or oversized deck style** (`@import url(https://…)`, a `body {}` rule, 15,000 characters). It is sanitised, or dropped when still over the cap, and the deck still builds. → Task 2 sanitiser tests, Task 4 `test_build_with_oversized_deck_style_builds_without_it`.
4. **A deck-style-only edit** ("make the code blocks dark"). No slide is rebuilt, and `deck.css` holds the new rules and none of the old ones. → Task 4 `test_deck_style_only_edit_rewrites_css_and_builds_nothing`.
5. **An edit that drops a class a kept slide still uses.** It is refused through the one retry, with a problem naming the class and the positions. → Task 6 `test_dropping_used_class_is_refused_and_retried`.

---

## File Structure

| File | Role |
|---|---|
| `src/domain/deck_spec.py` | `DeckStyleComponent`, `DeckStyle`, `DeckSpec.deck_style`, `SlideSpec.look`. |
| `src/domain/slide_operations.py` | `SlideContent.look` (parity), `DeckChanges.deck_style`. |
| `src/domain/deck_style.py` (new, pure) | Constants, `css_class_names`, `html_class_names`, `sanitise_deck_style`, `dropped_classes_in_use`, `deck_style_context`. |
| `src/services/agent_schema_registry.py` + pins | Re-pinned architect digests, old ones moved to `_HISTORICAL_DIGESTS`. |
| `src/services/graph/nodes.py` | Sanitise on answer, CSS write, payload keys, drop refusal, full-spec carry-forward. |
| `src/services/deck_css_aggregator.py` | Contract docstring: template block, then deck style. |
| `frontend/src/types/slide.ts`, `frontend/src/services/deckSpecMarkdown.ts`, `frontend/src/services/__tests__/deckSpecMarkdownCoverage.test.tsx`, `tests/fixtures/deck-spec-markdown/full.deck-spec.json` | TS mirror, `look` in the Markdown export, guard classification. |
| `evals/harness/scorers.py`, the builder scoring path, `evals/fixtures/deck_style_technical.json`, new case dirs | Deterministic deck-style scoring and cases. |
| `evals/configs/{architect,builder,fixer,build_reviewer,fix_reviewer}/deck-style.{md,yaml}` | Prompt candidates. |
| `src/core/skills/{architect,builder,fixer,build_reviewer,fix_reviewer}.py`, `src/services/agent_definition_manifest_v1.py` | Promoted prompts. |
| `docs/technical/backend-overview.md`, `CONTEXT.md`, `evals/README.md`, the spec | Docs. |

---

## Before Task 1

- **Baseline.** On the base commit (`73d6e2e8`), run `uv run pytest tests/unit -q -p no:randomly`. Record every failing node id **and its cause** in the ledger. Then run `cd frontend && npm ci && npm run test:unit` and record its failures the same way.
- **Plan-vs-code pre-pass** (executing-plans-tellr §2). Write `PLAN-CORRECTIONS.md`, verify every task below has a `Models:` tag, and point every dispatch at it.

---

### Task 1: Deck style fields on the spec; re-pin the architect contract

**Models:** test=opus impl=opus

**Files:**
- Modify: `src/domain/deck_spec.py`, `src/domain/slide_operations.py` (`SlideContent`, `DeckChanges`, plus wherever a `SlideContent` becomes a `SlideSpec`).
- Modify: `src/services/agent_schema_registry.py`. Move the current architect v1 `9f090efe…` and v2 `9d83be8d…` into `_HISTORICAL_DIGESTS` after the existing architect rows, and pin the new values. Read the new values from the `SchemaContractMaterialChangedError` message that `AgentSchemaRegistry()` raises.
- Modify: `src/services/agent_definition_manifest_v1.py`. Edit the architect `schema_contract.digest` only, through JSON-aware rewriting. Also update every pin found by `grep -rn "9f090efe\|9d83be8d" tests src` (the precedent list: registry tests, `test_architect_edit_prompt.py` hashes, retained-bundle ledger, `test_graph_definition_manifest.py` `PACKAGED_V1_CONTENT_HASHES`, packaged loader, draft, runtime and persisted-runtime tests).
- Test: `tests/unit/test_deck_style_spec_fields.py`

**Interfaces:**
- Produces:
  - `DeckStyleComponent(name: str, class_names: list[str], use: str, example_html: str)`
  - `DeckStyle(css: str, components: list[DeckStyleComponent])`
  - `DeckSpec.deck_style: Optional[DeckStyle] = None`
  - `SlideSpec.look: Optional[str] = None`, stripped, with a blank value becoming `None`. Use the same validator in `SlideContent`.
  - `SlideContent.look: Optional[str] = None`
  - `DeckChanges.deck_style: Optional[DeckStyle] = None`
- Validators are type-level only (strip). No length, prefix or CSS rules here.

- [ ] **Step 1: Write the failing tests:**
  - `test_spec_without_deck_style_still_validates`: today's golden deck spec JSON (`tests/fixtures/deck-spec-markdown/full.deck-spec.json`) validates, with `deck_style is None` and every `look is None`.
  - `test_deck_style_round_trips`: `DeckSpec.to_json` → `from_json` (or `model_validate`) keeps `deck_style.css`, the components and each `look` exactly.
  - `test_blank_look_becomes_none`: `"   "` → `None` on both `SlideSpec` and `SlideContent`.
  - `test_slide_content_mirrors_slide_spec`: the field sets of `SlideContent` and `SlideSpec` differ only by `position`. If a parity test already exists, extend it instead.
  - `test_deck_changes_deck_style_composes`: `compose_edit_spec(prior, identity_result, DeckChanges(deck_style=new))` returns a spec whose `deck_style == new` and whose slides are unchanged.
  - `test_architect_schema_has_deck_style_and_look`: `ArchitectOutput.model_json_schema()` reaches `deck_style` and `look`, and neither is required.
  - `test_historical_architect_digests_resolve`: `9f090efe…` (v1) and `9d83be8d…` (v2) resolve to `ArchitectOutput` in `HISTORICAL_SCHEMA_CONTRACT_BUNDLES`.
  - `test_other_roles_digests_unchanged`: the non-architect v1/v2 literals, copied from today's registry into the test.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_deck_style_spec_fields.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the fields, then re-pin and update every pin.
- [ ] **Step 4: Run** `uv run pytest tests/unit -q -p no:randomly`. Expected: green except the baseline causes. Diff causes, not counts.
- [ ] **Step 5: Commit** `feat(spec): deck_style and look on the deck spec; re-pin architect contract`.

---

### Task 2: The pure deck-style module

**Models:** test=opus impl=sonnet

**Files:**
- Create: `src/domain/deck_style.py` (tinycss2 is already a dependency; see `src/utils/css_utils.py`).
- Test: `tests/unit/test_deck_style_module.py`

**Interfaces:**
- Consumes: Task 1's `DeckStyle`, `DeckStyleComponent`.
- Produces:
  - Constants: `DECK_STYLE_CLASS_PREFIX = "dk-"`, `DECK_STYLE_VAR_PREFIX = "--dk-"`, `DECK_STYLE_TARGET_CHARS = 4000`, `DECK_STYLE_MAX_CHARS = 10000`, `DECK_STYLE_MAX_COMPONENTS = 12`.
  - `css_class_names(css: str) -> frozenset[str]`: class names in selectors, including inside `@media`.
  - `html_class_names(html: str) -> frozenset[str]`: tokens of every `class` attribute.
  - `sanitise_deck_style(style: DeckStyle | None) -> tuple[DeckStyle | None, tuple[str, ...]]`. It returns the cleaned style plus one note per thing removed:
    - removes a `<style>` wrapper;
    - drops the forbidden at-rules and every declaration with a non-`data:` `url(` or `expression(`;
    - drops each selector that has no `.dk-` class;
    - on `:root`, keeps only `--dk-` declarations;
    - drops rules left empty;
    - drops a component whose `class_names` are empty, unprefixed, or not all in `css_class_names` of the cleaned CSS;
    - keeps the first `DECK_STYLE_MAX_COMPONENTS` components;
    - returns `(None, notes)` when the cleaned CSS is blank or longer than `DECK_STYLE_MAX_CHARS`;
    - a clean style comes back equal to the input with `()` as the notes.
  - `dropped_classes_in_use(prior: DeckStyle | None, new: DeckStyle | None, kept_rows: Mapping[int, str]) -> dict[str, tuple[int, ...]]`: for every class in the prior style's CSS but not the new one, the sorted positions of the `kept_rows` (position → slide HTML) that use it.
  - `deck_style_context(token_css: str, style_block: str) -> dict`, returning `{"design_tokens": {name: value}, "template_classes": [..]}`:
    - `design_tokens` are the custom properties declared in `:root` rules of both inputs, skipping values over 120 characters or containing `url(`;
    - `template_classes` is the sorted unique `css_class_names(style_block)`, capped at 300;
    - it never contains `@font-face` content.

- [ ] **Step 1: Write the failing tests:**
  - **Sanitiser cases**, each asserting the exact cleaned CSS and a note that names what was dropped:
    - `@import url(https://x/y.css);` dropped;
    - `@font-face{…}` dropped;
    - `.dk-a{background:url(https://x/p.png)}` loses that declaration, while `url(data:image/png;base64,AAAA)` survives;
    - `body{color:red}` dropped;
    - `.dk-code .kw{color:var(--db-coral)}` kept;
    - `.card, .dk-card{…}` becomes `.dk-card{…}`;
    - `:root{--dk-accent:#f00;--db-navy:#000}` keeps only `--dk-accent`;
    - `@media (max-width:1px){.dk-a{…} p{…}}` keeps only `.dk-a`;
    - a component with class `card` or with an undefined `dk-x` is dropped;
    - 13 components are trimmed to 12;
    - `<style>.dk-a{}</style>` loses its wrapper.
  - `test_clean_style_is_returned_unchanged`, using the fixture from Task 7 or an inline equivalent.
  - `test_oversized_style_is_dropped`: 10,001 characters of valid `.dk-` CSS returns `(None, notes)`.
  - `test_dropped_classes_in_use`: prior has `dk-code`, `dk-note`; new has `dk-code`; `kept_rows {2: '<pre class="dk-note">', 5: '<div class="dk-note x">', 7: '<p>'}` gives `{"dk-note": (2, 5)}`.
  - `test_context_extracts_tokens_and_classes_without_fonts`: `token_css` with `:root{--db-navy:#1B3139;--big:url(data:…)}` plus an `@font-face` gives `design_tokens == {"--db-navy": "#1B3139"}`; the template classes come back sorted and unique.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_deck_style_module.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the same command. Expected: PASS. Then `uv run pytest tests/unit -q -p no:randomly`: baseline causes only.
- [ ] **Step 5: Commit** `feat(domain): deck style sanitiser, class scanning and architect context`.

---

### Task 3: Frontend mirror and the Markdown export

**Models:** test=opus impl=sonnet

**Files:**
- Modify: `frontend/src/types/slide.ts`. Add `DeckStyleComponent` and `DeckStyle` interfaces, `DeckSpec.deck_style?: DeckStyle | null`, and `SlideSpec.look?: string | null`.
- Modify: `frontend/src/services/deckSpecMarkdown.ts`. Each slide emits a `Look:` line when `look` is set, in the style of the existing per-slide lines. `deck_style` is not rendered.
- Modify: `frontend/src/services/__tests__/deckSpecMarkdownCoverage.test.tsx`. `COVERAGE` gets:
  - `DeckSpec.deck_style: { excluded: 'Model-authored stylesheet and its catalogue of pieces; styling, not reader content, and the CSS would swamp the export.' }`;
  - `SlideSpec.look: 'rendered'`;
  - `DeckStyle` and `DeckStyleComponent` with every field excluded and a reason of at least 20 characters;
  - matching `INSTANCES` entries.
- Modify: `tests/fixtures/deck-spec-markdown/full.deck-spec.json`. Add a `look` to every slide, so the mutation guard can see it render.
- Check `frontend/src/components/SpecView/SpecView.tsx` against guard (b). If SpecView does not show `look`, the guard needs no SpecView change. Do not add it to SpecView.
- Test: the two existing guards plus `deckSpecConformance.test.ts`.

**Interfaces:**
- Consumes: Task 1's field names (read from `deck_spec.py` as text).

- [ ] **Step 1:** Run `cd frontend && npx vitest run src/services/__tests__/deckSpecMarkdownCoverage.test.tsx src/services/__tests__/deckSpecConformance.test.ts`. Expected: FAIL, because the Task 1 fields are unclassified and unmirrored. This is the red state.
- [ ] **Step 2:** Implement the mirror, the classification, the `Look:` line and the fixture.
- [ ] **Step 3:** Run `npx tsc -b && npm run test:unit`. Expected: green except the baseline causes.
- [ ] **Step 4:** Sabotage. Stop emitting `Look:` and confirm the coverage guard goes red, then restore.
- [ ] **Step 5: Commit** `feat(frontend): mirror deck_style and look; export look in Markdown`.

---

### Task 4: Sanitise on answer and write the deck style into `deck.css`

**Models:** test=opus impl=opus

**Files:**
- Modify: `src/services/graph/nodes.py` (`architect_node`, its pre-fan-out `deck_write`, `emitted_style_blocks`).
- Modify: `src/services/deck_css_aggregator.py`. Change only the "PRODUCER CONTRACT" docstring: the list holds the template block, then the deck style's CSS, either possibly absent.
- Test: `tests/unit/test_deck_style_css_path.py`. Use the architect-node harness the existing architect-node tests use; find it with `grep -ln "architect_node(" tests/unit`.

**Interfaces:**
- Consumes: Task 2's `sanitise_deck_style`.
- Produces:
  - `_sanitise_answer_deck_style(out: ArchitectOutput, session_id: str) -> ArchitectOutput`. Applied to every architect answer (first answer and retry) before `_plan_answer`. It sanitises `out.deck_spec.deck_style` and `out.deck_changes.deck_style`, logs each note with `session_id`, and returns a copy.
  - Pre-fan-out: `deck_write["css"] = _concat_css(brand["deterministic_css"], style_css)` when that is non-empty, where `style_css` is the committed spec's `deck_style.css` or `""`. Then `emitted_style_blocks = scoped(turn_id, [b for b in (brand["style_block"], style_css) if b])`.

- [ ] **Step 1: Write the failing tests:**
  - `test_build_writes_deck_style_after_template_css`: the persisted `deck.css` contains the template block, then the deck style's `.dk-code` rule, in that order; the post-commit aggregate keeps both.
  - `test_deck_without_style_writes_css_as_today`: with no `deck_style`, the `deck_write` kwargs and `emitted_style_blocks` equal what the base commit produces, for a pinned and for an unpinned deck. Assert against literal expected values captured from the base behaviour.
  - `test_build_with_hostile_deck_style_is_sanitised`: `@import url(https://evil/x.css)` plus `body{}` never reach `deck.css` or the committed spec.
  - `test_build_with_oversized_deck_style_builds_without_it`: the committed spec has `deck_style is None`, all slides are dispatched, and the turn succeeds.
  - `test_deck_style_only_edit_rewrites_css_and_builds_nothing`: an edit with `operations=[]` and `deck_changes.deck_style` (old `.dk-code{background:#fff}`, new `.dk-code{background:#000}`). No builder `Send`; `deck.css` contains `#000` and not `#fff`; the spec's deck style is the new one.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_deck_style_css_path.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the file, then `uv run pytest tests/unit -q -p no:randomly`. Expected: green; baseline causes only.
- [ ] **Step 5: Commit** `feat(graph): sanitise the architect's deck style and write it into deck.css`.

---

### Task 5: The deck style reaches every role that builds or judges a slide

**Models:** test=opus impl=sonnet

**Files:**
- Modify: `src/services/graph/nodes.py`:
  - `build_branch_payload`: `"deck_style": spec.deck_style.model_dump()` only when it is not `None`;
  - `_BUILDER_MODEL_PAYLOAD_KEYS` gets `"deck_style"`;
  - the `review_payload` in `build_reviewer_node`, the `fix_payload` in `fixer_node` and the fix reviewer's payload in `fix_reviewer_node` each get `"deck_style"` from their source payload, only when present;
  - the architect payload gets `"deck_style_context": deck_style_context(brand["token_css"], brand["style_block"])`.
- Test: `tests/unit/test_deck_style_payloads.py`

**Interfaces:**
- Consumes: Task 1 fields; Task 2's `deck_style_context`.
- Produces: the payload key `deck_style` (a `DeckStyle.model_dump()`) for builder, build reviewer, fixer and fix reviewer; the architect payload key `deck_style_context`.

- [ ] **Step 1: Write the failing tests:**
  - `test_branch_payload_carries_deck_style`: the builder's model payload (filtered by `_BUILDER_MODEL_PAYLOAD_KEYS`) has `deck_style` equal to the spec's dump, and `slide_spec.look` arrives inside `slide_spec`.
  - `test_reviewer_fixer_and_fix_reviewer_payloads_carry_deck_style`: capture the payload each passes to a fake `get_agent_runtime().run`.
  - `test_payloads_without_deck_style_carry_no_key`: for a spec with no deck style, none of the four model payloads has a `deck_style` key, and each payload's key set equals the base commit's set (literal list in the test).
  - `test_architect_payload_has_context_without_font_data`: `deck_style_context` is present, and the rendered payload contains no `@font-face` and no `base64`.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_deck_style_payloads.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the file, then the full unit suite. Expected: green; baseline causes only.
- [ ] **Step 5: Commit** `feat(graph): carry the deck style to builders, reviewers and fixers`.

---

### Task 6: Edits keep the deck style coherent

**Models:** test=opus impl=opus

**Files:**
- Modify: `src/services/graph/nodes.py`:
  - in the operations path (`_plan_operations_edit` or `_plan_answer`, whichever holds the composed spec, the persisted rows and the rebuild set), add the dropped-class check;
  - on the full-spec edit path (alignment and describe-only), carry the persisted spec's `deck_style` forward unchanged.
- Modify: `src/domain/slide_operations.py`. Add `"deck_style_drops_used_class"` to `PROBLEM_CODES`, and add it to `RETRYABLE_EDIT_CODES` wherever that lives.
- Test: `tests/unit/test_deck_style_edits.py`

**Interfaces:**
- Consumes: Task 2's `dropped_classes_in_use`; Task 4's sanitise-on-answer.
- Produces: an `OperationProblem(code="deck_style_drops_used_class", positions=<persisted positions>, detail=…)`. The detail names the class and says to keep the class or add `update` operations for those slides. It is raised when a kept, non-rebuilt slide uses a class the new deck style drops.

- [ ] **Step 1: Write the failing tests:**
  - `test_dropping_used_class_is_refused_and_retried`: the first answer drops `dk-note`, which persisted slide 4 uses and the edit does not rebuild. The retry payload's `rejected_edit.problems` has that code with positions `(4,)`. A retry answer that updates position 4 applies.
  - `test_dropping_unused_class_applies`.
  - `test_dropping_class_on_rebuilt_slide_applies`: the slide using it gets an `update`.
  - `test_full_spec_edit_keeps_persisted_deck_style`: a describe-only re-description with `deck_style=None` commits the persisted deck style.
  - `test_deck_style_change_is_not_deck_level`: `classify_spec_change(new, persisted)` is `"none"` when only `deck_style` and `look` differ. Also assert `"deck_style" not in _DECK_LEVEL_FIELDS`.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_deck_style_edits.py -q`. Expected: FAIL. `test_deck_style_change_is_not_deck_level` may already pass; sabotage it by adding `deck_style` to `_DECK_LEVEL_FIELDS`, confirm red, then restore.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the file, then the full unit suite. Expected: green; baseline causes only.
- [ ] **Step 5: Commit** `feat(graph): refuse deck-style edits that strand a slide; keep the style on re-description`.

---

### Task 7: Eval harness scores deck styles; new cases on both splits

**Models:** test=opus impl=opus

**Files:**
- Create: `evals/fixtures/deck_style_technical.json`, a clean `DeckStyle` for a technical deck. Pieces:
  - `dk-code` with token spans `.dk-code .kw/.fn/.str/.cm`;
  - `dk-table`;
  - `dk-badge` with `dk-badge--measured` and `dk-badge--untested`;
  - `dk-steps`, `dk-callout`, `dk-note`.

  All colours are `var(--db-…)`; `css` stays under 4,000 characters. It must pass `sanitise_deck_style` unchanged.
- Modify: `evals/harness/scorers.py`:
  - `_deck_style_score(structured, expect, design_system_active) -> tuple[bool, str]` applies to architect build cases with `expect.deck_style: true`. It passes when:
    - `deck_spec.deck_style` is present and `sanitise_deck_style` returns it unchanged with no notes;
    - there are 1–12 components;
    - `len(css) <= DECK_STYLE_MAX_CHARS`;
    - every slide has a non-blank `look`;
    - when `design_system_active`, there is no hex colour literal outside a `:root` `--dk-` declaration.

    It is ANDed after the intent check.
  - In `_operations_score`, when `expect.deck_style_keeps` is given, `deck_changes.deck_style` must be present and its CSS must define every listed class.
  - `deck_style_use_score(html, payload, expect) -> tuple[bool, str]` applies to builder cases with `expect.deck_style_classes`. It passes when:
    - every listed class is used;
    - no inline `color`, `background`, `background-color`, `font-size`, `font-family` or `border-color` declaration appears;
    - every class used is in `css_class_names(payload["section_css"] + payload["deck_style"]["css"])`.

    Wire it into wherever builder rows are scored (ANDed with `render_measures_score`).
- Create, on `cases/` and `cases_heldout/`, with the existing file set (`case.yaml`, `payload.json`, `reference.json`, `calibration.json`):
  - architect `build_technical_deck`: a generic public topic (Postgres logical replication into a lakehouse) with code, a comparison table and measured/untested badges. Not the reference brief. `expect: {intent: build, deck_style: true}`.
  - architect `restyle_deck`: the current spec carries the fixture style; the message is "make all the code blocks dark navy with light text". `expect: {intent: edit, positions: [], deck_style_keeps: [dk-code]}`.
  - builder `deck_style_code` and `deck_style_table`: the payload carries the fixture style, a `look`, and a bound content section from an existing builder case. `expect: {deck_style_classes: [...]}`.
  - build_reviewer `deck_style_inline_paint` (mutation: the code block is painted inline instead of using `dk-code`; `expect: {criteria: [rogue_colour], positions: [p]}`) and `deck_style_clean` (positive; `expect: {}`).
  - Add `deck_style: true` to both splits' existing `build_request` `expect`.
- Test: `tests/unit/test_eval_deck_style_scorer.py`

**Interfaces:**
- Consumes: Tasks 1–2.
- Produces: the expect keys `deck_style`, `deck_style_keeps` and `deck_style_classes`, and the cases Tasks 8–10 measure on.

- [ ] **Step 1: Write the failing tests:**
  - `test_deck_style_score_pass_and_each_failure`: missing style; a sanitiser note; 13 components; a blank `look`; a raw hex with DS active. Each failure's rationale names its cause.
  - `test_deck_style_use_score_pass_and_each_failure`: an inline `background:`; an undefined class; a listed class missing.
  - `test_restyle_keeps_classes`.
  - `test_existing_cases_unaffected`: every existing case without the new keys scores as before. Run the scorer on each reference.
  - `test_new_case_references_pass_and_calibrations_fail`: every new case's `reference.json` passes the deterministic scorer, and `calibration.json` fails it.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_eval_deck_style_scorer.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the scorers, the fixture and the case directories.
- [ ] **Step 4: Run** `uv run pytest tests/unit -q -k eval`, then the full suite. Expected: green.
- [ ] **Step 5: Commit** `feat(evals): deck-style scoring and cases for architect, builder and build reviewer`.

---

### Task 8: Architect prompt — measured, then promoted

**Models:** test=opus impl=opus

**Files:**
- Create: `evals/configs/architect/deck-style.md`, the current `INSTRUCTIONS` with the changes below, no trailing newline. Also `deck-style.yaml` (`agent_key: architect`, `name: deck-style`, `base: v1`, `prompt_file: deck-style.md`).
- Modify (after measurement): `src/core/skills/architect.py` `INSTRUCTIONS`, plus the manifest and its pins via `uv run python -m evals.harness.promote --config architect=<finalist>.yaml --run-id architect=<run>`.
- Test: `tests/unit/test_architect_deck_style_prompt.py`, phrase pins on `INSTRUCTIONS`.

**Prompt changes** (spec §2). In plain words the prompt must say:
- **Build:** write `deck_style` once, from what the planned slides need and the payload's `deck_style_context`.
  - Reuse a design-system or template piece when one exists; add only what's missing; keep it thin, about 4,000 characters, at most 12 pieces.
  - Every class starts with `dk-`, and colours and fonts come from the design tokens (`var(--…)`).
  - With no design system, declare a small `--dk-` palette in `:root` from `resolved_style`.
  - No page numbers. No `@import`, `@font-face` or external `url()`.
  - Each component gets a name, its classes, one line on when to use it, and minimal example markup.
- **Every slide:** write a `look` of one or two sentences naming the body layout and the pieces it uses.
- **Binding where it fits:**
  - bind a section when its shape fits;
  - bind for the frame only when the body differs, and the `look` describes the body;
  - otherwise leave the slide unbound, and the `look` describes the whole slide.
  - Keep the "never bind a merely similar section" rule.
- **Edits:**
  - a deck-wide style request is `deck_changes.deck_style` with the whole revised style, and no operations unless markup must change;
  - keep existing class names when only appearance changes;
  - dropping or renaming a class means `update` operations for the slides that use it;
  - add a missing piece in the same turn;
  - a confirmed design-contract change comes with a fresh deck style.

**Spend plan** (cap USD 22; ≈ USD 0.25/row):
1. Calibrate the judge on `build_technical_deck`, `restyle_deck` and `build_request`, both splits.
2. Screen each candidate on those three cases, `--repeats 3`.
3. Run the finalist on all train cases (`--repeats 2`) and on held-out (`--repeats 1`).

Up to three candidates (`deck-style`, `-b`, `-c`). Stop if the running estimate would pass USD 22.

**Acceptance bar:**
- each existing case's train pass rate is at least its rate in the latest recorded architect table in `evals/README.md`, minus one row;
- `build_technical_deck`, `restyle_deck` and `build_request` each pass at least 2 of 3 on train (screen) and 1 of 1 on held-out;
- mean output tokens on build cases rise by no more than 2,500 against the recorded baseline. This is the proxy for the +30 s time-to-first-slide bar.

If the bar is missed after three candidates, promote the best and record the gap in `evals/README.md` and the PR.

- [ ] **Step 1:** Write the phrase pins (`deck_style`, `look`, `dk-`, `deck_style_context`, `about 4,000 characters`, the frame-only binding sentence, `deck_changes.deck_style`). Run `uv run pytest tests/unit/test_architect_deck_style_prompt.py -q`. Expected: FAIL.
- [ ] **Step 2:** Write the candidate. Check the harness's Databricks auth (`evals/README.md` setup). Calibrate, then screen.
- [ ] **Step 3:** Iterate on screen failures only, then run the finalist.
- [ ] **Step 4:** Copy the finalist into `INSTRUCTIONS` and run `promote`. Then run `uv run pytest tests/unit -q -p no:randomly`. Expected: green; baseline causes only.
- [ ] **Step 5:** Record the measured table and spend in `evals/README.md`. Commit `feat(architect): deck style and per-slide look (measured, promoted)`.

---

### Task 9: Builder and fixer prompts — measured, then promoted

**Models:** test=opus impl=opus

**Files:**
- Create: `evals/configs/builder/deck-style.{md,yaml}` and `evals/configs/fixer/deck-style.{md,yaml}`. If `evals/configs/fixer/` does not exist, follow `evals/README.md` for adding a role's config.
- Modify (after measurement): `src/core/skills/builder.py`, `src/core/skills/fixer.py`, and the manifest via `promote`.
- Test: `tests/unit/test_builder_deck_style_prompt.py`, phrase pins on both `INSTRUCTIONS`.

**Prompt changes** (spec §3), as a new `DECK STYLE (when deck_style is present)` block:
- **INPUT** lists `deck_style` and `slide_spec.look`.
- **With a deck style:**
  - build to `look`;
  - use the catalogue's pieces exactly as their `example_html` shows;
  - for a bound section, keep its frame (root tag and classes, ground, eyebrow, title, footer) and lay out the body as `look` says, replacing the section's body markup where needed;
  - inline styles are for layout only (display, flex, grid, gap, width, height, position, margin, padding, alignment). No inline colour, background, font family, font size or border colour, in any deck;
  - use no class that the deck style, the bound section or the design system doesn't define.
- **Without a deck style:** today's rules apply unchanged.

The no-`<style>` rule stays. The fixer gets the same block, aimed at fixing toward the deck style.

**Spend plan** (cap USD 10). Screen on `deck_style_code` and `deck_style_table` `--repeats 3`. Run the finalist on all builder train cases `--repeats 1` and held-out `--repeats 1`. The fixer is measured with its existing pack, `--repeats 1`, as a no-regression check. Up to three builder candidates and one fixer candidate.

**Acceptance bar:**
- both new builder cases pass at least 2 of 3 on train and 1 of 1 on held-out;
- every existing builder and fixer case passes at least as often as its recorded rate, minus one row.

- [ ] **Step 1:** Write the phrase pins (`deck_style`, `look`, `example_html`, `layout only`, `Without a deck style`). Run them. Expected: FAIL.
- [ ] **Step 2:** Write the candidates; screen.
- [ ] **Step 3:** Iterate, then run the finalist runs.
- [ ] **Step 4:** Promote both and run the full unit suite. Expected: green; baseline causes only.
- [ ] **Step 5:** Record the results in `evals/README.md`. Commit `feat(builder,fixer): build to the deck style (measured, promoted)`.

---

### Task 10: Build and fix reviewer prompts — measured, then promoted

**Models:** test=opus impl=opus

**Files:**
- Modify (after measurement): `src/core/skills/build_reviewer.py`. Add a `DECK_STYLE_REVIEW` constant beside `BOUND_TEMPLATE_COLOURS`, appended to the authored prefix. Make the same addition in `src/core/skills/fix_reviewer.py`'s authored text. Promote both; check the v1 composite and the v2 target alike, as `BOUND_TEMPLATE_COLOURS` notes.
- **The criteria registry (`src/domain/finding.py`) does not change.** That keeps the reviewer schema digests and the protected criteria stage byte-identical. This is a plan-time call: the spec left new-criterion vs extension to the builder.
- Create: `evals/configs/{build_reviewer,fix_reviewer}/deck-style.{md,yaml}`.
- Test: `tests/unit/test_reviewer_deck_style_prompt.py`.

**Prompt text, in plain words.** When the payload carries a `deck_style`:
- its pieces' colours are part of the contract, not `rogue_colour`;
- a slide that paints colours, backgrounds or font sizes inline, or that restyles a piece the deck style provides, is `rogue_colour`;
- a slide whose body ignores `slide_spec.look` is `brief_not_delivered`;
- judge the cascade with the deck style's CSS applied after `section_css`.

**Spend plan** (cap USD 6). Screen on the two new build_reviewer cases `--repeats 3`. Run the finalist on all build_reviewer train cases `--repeats 1`, and the fix_reviewer pack `--repeats 1`.

**Acceptance bar:**
- both new cases pass at least 2 of 3;
- every existing case passes at least as often as recorded, minus one row.

- [ ] **Step 1:** Write the phrase pins and run them. Expected: FAIL.
- [ ] **Step 2:** Write the candidates; screen.
- [ ] **Step 3:** Iterate, then run the finalist runs.
- [ ] **Step 4:** Promote and run the full suite. Expected: green; baseline causes only.
- [ ] **Step 5:** Record the results. Commit `feat(reviewers): judge slides against the deck style (measured, promoted)`.

---

### Task 11: Docs

**Models:** test=sonnet impl=sonnet

**Files:**
- Modify: `docs/technical/backend-overview.md`. Add a "Deck style (graph)" section covering:
  - what the architect writes;
  - the sanitiser rules and their constants;
  - the CSS order: tokens, template, deck style;
  - the payload keys;
  - the edit rules (deck-style-only edits rebuild nothing, the drop refusal, the full-spec carry-forward);
  - old decks;
  - the rollout rule: new prompts only on publish, node code everywhere.
- Modify: `CONTEXT.md`. Add *deck style* and *look* in the glossary's existing style.
- Modify: the spec. Add a "Changes during the build" section listing:
  - the plan-time calls (sanitise rather than reject; the reviewer check through the authored prompt, not a new criterion);
  - every correction from `PLAN-CORRECTIONS.md`.

- [ ] **Step 1:** Write the docs.
- [ ] **Step 2:** Run `uv run pytest tests/unit -q -k "docs or context"`. Expected: green.
- [ ] **Step 3: Commit** `docs: architect deck style`.

---

## After the tasks

1. **Whole-branch review** (Opus, always; executing-plans-tellr §7). Ask for:
   - a writer-by-writer table of every `deck.css` write and every payload builder, each with and without a deck style;
   - a ruling that old decks are byte-identical;
   - a ruling that the sanitiser cannot be bypassed (build, edit, retry, full-spec);
   - a merge/no-merge verdict.
2. **PR:**
   - rename nothing (the branch is already `feat/architect-deck-style`);
   - push as the personal gh account;
   - `gh pr create` with a body covering the rollout rule, the measured eval tables, the spec's "calls made without the owner" and the plan-time calls;
   - iterate until CI is green.
3. **Devloop:**
   - follow `deploy-tellr-dev` to a **new** instance, `deck-style`;
   - check the active graph release, and make the promoted prompts live with a workbench draft and publish (memory: `devloop-inherits-prod-releases`);
   - rebuild the reference brief from `~/tellr-loop/deck-style/lakebase-brief.md` and screenshot it next to `legacy-mode-prod.html`;
   - run the spec §8 deterministic consistency checks on the built deck;
   - hand the instance to the owner.

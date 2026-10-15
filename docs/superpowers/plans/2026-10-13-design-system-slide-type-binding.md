# Design-system-defined slide-type binding — Implementation Plan

**Date:** 2026-10-13
**Branch:** work off `main` (`01cbcd15`); do not commit or push unless the user asks
**Spec:** `docs/superpowers/specs/2026-10-13-architect-slide-type-design.md` (approved 2026-10-13)

## Goal

The pinned design-system template supplies slide-type vocabulary via `data-label`. The architect copies a bound pair `(slide_type, template_section_index)` from `template_sections`. The builder fills that extracted section instead of inventing a layout. Tellr owns no brand-specific type enum.

## Context (verified 2026-10-13)

- `architect_node` already sends `template_sections: brand["section_inventory"]` (`src/services/graph/nodes.py` ~1479).
- `section_inventory` (`src/services/template_sections.py:313`) emits `index`, `tag`, `classes`, `text_snippet`, `affordances`. It drops `data-label`. After `find_slide_roots` promotion, Corporate roots are outer `<section>` with empty classes, so `cover` / `dark` / `white` never reach the architect.
- Repo architect `INSTRUCTIONS` (`src/core/skills/architect.py`) list neither `template_section_index` nor `slide_type`, and never name the payload key `template_sections`.
- `build_branch_payload` extracts `section_html` only when `template_section_index` is set. Unbound slides get `""`.
- Builder `INSTRUCTIONS` require a `<div class="slide">` fragment and never mention `section_html`.
- `build_reviewer_node` (~2325) builds a literal review payload without `section_html`.
- Databricks Corporate `data-label` values (evidence only, not a product enum): Cover, Agenda, Section, Content, Two-column, Three cards, Statement, Stats, Closing.
- Synthetic import fixture (`tests/unit/conftest_design_system.py` `SYNTHETIC_TEMPLATE_HTML`) has no `.slide` roots. Zero-root layouts stay valid; unlabeled *roots* on newly imported templates do not.
- `Finding.criterion` is `str` validated against `CRITERIA` at runtime. Adding criteria does **not** change the schema-contract digest. Adding `SlideSpec.slide_type` **does** change the architect digest (`ArchitectOutput` nests `DeckSpec`).
- Eval gold decks are JSON files: `evals/fixtures/meridian/deck_spec.json` and `heldout/deck_spec.json`. They must still `DeckSpec.model_validate`; add `"slide_type": null` so exact-equality pack tests keep matching `model_dump()`.

## Global constraints

- Shared pyenv: NEVER `pip install`. Never push. Never skip git hooks. Do not commit unless the user asks; if they do, `git commit` is its own shell command (a hook false-positives on compound commands containing a short `-n` flag).
- Import `src.core.database` before other `src.*` imports in tests. Unit tests use disposable sqlite.
- Do **not** add a Tellr `Literal` / seed / `section_roles` map. `slide_type` is uncapped design-system text.
- Do **not** add `inconsistent_treatment` or `unassessable_criterion`. `FindingCategory` stays `content | design | narrative`.
- Do **not** edit eval cases, references, judge prompts, or scorers except gold `deck_spec.json` so the new field parses.
- Do **not** edit `ArchitectOutput` field descriptions unless required for the new nested field (the digest will change because of `SlideSpec` anyway).
- Baselines are cause-sets: diff failing-test **causes**, not counts.
- Existing unlabeled templates in the database stay loadable (`label: null` + warning). Validation rejects **new imports** only.
- Prompt source of truth is `src/core/skills/*.py`. Frozen v1 snapshot (`src/services/agent_definition_manifest_v1.py`) and hash pins must be updated in the same change as the skills they duplicate, via the existing `promote` path used on 2026-10-08.
- Speak 1-indexed only in architect `message`. `position` / `target_positions` stay 0-indexed.

## File map

| Area | Files |
| --- | --- |
| Inventory | `src/services/template_sections.py`, `tests/unit/test_template_sections.py`, `tests/agentic/test_section_inventory_supports_assignment.py` |
| Import | `src/services/design_system_service.py` (`import_bundle` after `materialize_templates`), `tests/unit/test_design_system_import.py`, `tests/unit/conftest_design_system.py` (new labeled HTML helper only — do not change the zero-root synthetic unless a test needs a labeled layout) |
| Spec | `src/domain/deck_spec.py`, `tests/unit/test_deck_spec.py`, `evals/fixtures/meridian/{,heldout/}deck_spec.json` |
| Schema ledger | `src/services/agent_schema_registry.py` `_V1_DIGESTS` / `_V2_DIGESTS` architect entries; copies in `tests/unit/test_architect_edit_prompt.py` `HEAD_V*_SCHEMA_DIGESTS`; `tests/unit/test_persisted_agent_runtime.py` `EXPECTED_V2_SCHEMA_DIGESTS` |
| Pair validation | `src/services/template_sections.py` (helper), `src/services/graph/nodes.py` `architect_node`, `tests/unit/test_graph_nodes.py` |
| Architect prompt | `src/core/skills/architect.py`, v1 manifest via promote, `tests/unit/test_architect_edit_prompt.py` (block hashes + content hash) |
| Builder prompt | `src/core/skills/builder.py`, same promote path |
| Review | `src/domain/finding.py`, `tests/unit/test_finding_schema.py`, `src/core/skills/build_reviewer.py` (prefix only; criteria block is generated), `src/services/graph/nodes.py` `build_reviewer_node` + deck-level re-review (~653), `tests/fixtures/model_payload_keys.py`, `src/services/agent_model_payload.py` |
| Docs | `docs/technical/design-system-bundle-format.md`; README only if the user asks to commit |

---

## Task 1: Inventory exposes `label` and `inner_classes`

**Models:** test=opus impl=sonnet

**Files:** `src/services/template_sections.py`, `tests/unit/test_template_sections.py`

Behaviour:

Each `section_inventory` entry has exactly these keys: `index`, `label`, `tag`, `classes`, `inner_classes`, `text_snippet`, `affordances`.

- `label`: trimmed `data-label` on the inventoried root after `find_slide_roots` promotion; `None` if missing or whitespace-only. Log a WARNING when a root has no label (existing rows stay loadable).
- `inner_classes`: class tokens of the innermost descendant whose class list contains `slide`, **if that element is not the root**; else `[]`.
- Duplicate labels are valid. Order and count still match extractable roots.

Minimal fixture (synthetic, not Databricks copy):

```html
<section class="slide-root" data-label="Cover">
  <div class="slide cover dark">Cover title</div>
</section>
<section class="slide" data-label="Content">
  <h2>Body</h2>
</section>
```

Expect: entry 0 `label=="Cover"`, `inner_classes==["slide","cover","dark"]`; entry 1 `label=="Content"`, `inner_classes==[]`.

Steps:

- [ ] **Step 1 (test author):** extend `TestSectionInventory`. `test_inventory_fields_present` must require `label` and `inner_classes`. Add tests for labeled wrapper, unlabeled root (`label is None`), whitespace-only label → `None`, duplicate labels, and inner_classes empty when the root itself is the `.slide`. Sabotage: a fake inventory that omits `label` must fail the fields test. Confirm red. Leave uncommitted.
- [ ] **Step 2 (implementer):** implement without editing tests. Update the function docstring's key list.
- [ ] **Step 3:** `tests/unit/test_template_sections.py` green. Any other unit failure: failing-cause set vs pre-change baseline (expected: tests that pin the exact five-key set).

---

## Task 2: New imports reject unlabeled slide roots

**Models:** test=opus impl=sonnet

**Files:** `src/services/template_sections.py` (shared helper), `src/services/design_system_service.py`, `tests/unit/test_design_system_import.py`

Behaviour:

Add `unlabeled_slide_root_indexes(layout_html) -> list[int]` (0-based indexes of roots whose trimmed `data-label` is empty). Zero-root HTML returns `[]` (the current `SYNTHETIC_TEMPLATE_HTML` keeps importing).

In `import_bundle`, **after** `materialize_templates(design_system)` and **before** `commit`, for each materialized template:

```python
indexes = unlabeled_slide_root_indexes(template.layout_html)
if indexes:
    raise DesignSystemImportError(
        f"Template {template.entry_path!r} has unlabeled slide roots at "
        f"indexes {indexes}; each slide root must declare a non-empty data-label"
    )
```

Do **not** call this from lazy `materialize_templates` on existing rows.

Steps:

- [ ] **Step 1 (test author):** a bundle whose `templates/<slug>/index.html` has `class="slide"` and no `data-label` raises `DesignSystemImportError` matching `unlabeled` / the path / the index. A labeled `.slide` root imports. The existing zero-root synthetic still imports. Sabotage: skip the check and the unlabeled test must go red. Confirm red.
- [ ] **Step 2 (implementer):** helper + `import_bundle` gate. Do not rewrite existing DB rows.
- [ ] **Step 3:** `tests/unit/test_design_system_import.py` plus Task 1 tests green.

---

## Task 3: `SlideSpec.slide_type` and architect schema digest

**Models:** test=sonnet impl=sonnet

**Files:** `src/domain/deck_spec.py`, `tests/unit/test_deck_spec.py`, `src/services/agent_schema_registry.py`, digest copies listed in the file map, `evals/fixtures/meridian/deck_spec.json`, `evals/fixtures/meridian/heldout/deck_spec.json`

Behaviour:

```python
class SlideSpec(BaseModel):
    ...
    slide_type: Optional[str] = None
    template_section_index: Optional[int] = None
```

Field validator: strip; whitespace-only → `ValueError`; `None` stays `None`. Not a `Literal`. Pair validation is **not** on the model (no inventory here).

`DeckSpec.from_json` of a pre-field spec (no `slide_type` key) still returns a spec with `slide_type is None`. JSON round-trip includes the field.

`AgentSchemaRegistry()` fails closed until `_V1_DIGESTS["architect"]` and `_V2_DIGESTS["architect"]` match the newly calculated digests. Copy those two values into every pin listed in the file map. Other roles' digests stay unchanged.

Gold JSON: add `"slide_type": null` on every slide object so pack equality against `model_dump()` still holds. Do not change briefs, positions, or cases.

Steps:

- [ ] **Step 1 (test author):** tests for default `None`, strip, whitespace reject, from_json of old JSON, round-trip. A test that constructing `AgentSchemaRegistry()` currently passes; after the field exists it must fail until the ledger is updated (that failure is the implementer's signal — paste `calculated` from `SchemaContractMaterialChangedError`). Confirm deck_spec tests red; leave uncommitted.
- [ ] **Step 2 (implementer):** add the field + validator; bump **only** architect v1/v2 digests to the calculated values; update gold JSON. Do not edit tests except gold fixtures and digest literals.
- [ ] **Step 3:** `tests/unit/test_deck_spec.py`, `test_architect_edit_prompt.py::test_schema_contract_digests_unchanged`, `test_persisted_agent_runtime.py` schema digest assertions green.

---

## Task 4: Architect pair validation before dispatch

**Models:** test=opus impl=sonnet

**Files:** `src/services/template_sections.py`, `src/services/graph/nodes.py`, `tests/unit/test_graph_nodes.py`

Behaviour:

```python
def invalid_slide_bindings(spec, inventory) -> list[str]:
    """Return human-readable errors, one per bad SlideSpec. Empty means valid."""
```

Rules, using the **current** `section_inventory` of the spec's pinned template (the same list `architect_node` already put in the payload):

- both `None` → valid
- exactly one of `slide_type` / `template_section_index` set → invalid
- index out of range → invalid
- inventory `[index].label` is `None` → invalid (unbindable existing row)
- `slide_type !=` that entry's `label` (exact, case-preserving) → invalid
- inventory empty or no template → both fields must be `None`; a non-null pair is invalid

On `intent in ("build", "edit")`, after edit guards succeed and `spec` is the model's spec, if `invalid_slide_bindings` is non-empty: degrade to `discuss` with `error_state.code == "invalid_slide_type_binding"`. User-facing `message` names the 1-indexed slide and the supplied pair; it does **not** tell the user to invent a type. Do not persist that spec. Do not dispatch builders.

Use the same single degrade pattern as `edit_degrade` (emit + `_say` + return). Apply to **build** as well as edit.

Steps:

- [ ] **Step 1 (test author):** unit tests on the helper for each rule, including duplicate labels (binding the second `Content` by its index is valid). Graph tests: a build whose spec binds `slide_type="Cover"` at index 0 against an inventory whose index 0 label is `Cover` proceeds; a mismatched pair degrades with `invalid_slide_type_binding` and does not write `deck_spec`. Sabotage: skip the check and the mismatch test goes red. Confirm red.
- [ ] **Step 2 (implementer):** helper + `architect_node` call. Do not silently coerce the pair to `None`.
- [ ] **Step 3:** graph node tests + helper tests green.

---

## Task 5: Architect prompt names `template_sections` and the pair

**Models:** test=sonnet impl=sonnet

**Files:** `src/core/skills/architect.py`, `src/services/agent_definition_manifest_v1.py` (via promote), hash pins (`tests/unit/test_architect_edit_prompt.py`, `tests/unit/test_packaged_release_loader.py`, `tests/unit/test_graph_definition_manifest.py` if it pins the same hashes)

Prompt changes (keep INTENT CLASSIFICATION and DESIGN SYSTEMS contract-switch rule byte-identical unless a test forces a rewrite):

1. Under SLIDESPEC FIELDS, add:
   - `slide_type`: exact `data-label` copied from one `template_sections` entry, or null
   - `template_section_index`: that entry's `index`, or null
2. A VISUAL / TEMPLATE BINDING block that **names the payload key** `template_sections` and states:
   - choose only from those entries; copy `label` → `slide_type` and `index` → `template_section_index`
   - if none fit, or the list is empty/absent, both fields null
   - never invent a type; never complain the list was not supplied when the key is present
   - when committing a design system, pick a `template_id` from the library (empty template ⇒ empty list)
   - `content_brief` names the exhibit; brand furniture comes from the selected section's markup, not hard-coded English words like title/divider/closing
   - style assets are identity, not evidence
   - do not plan exhibits onto missing data; prefer `ask_data`
3. In `message` only, speak about slides 1-indexed; `position` / `target_positions` stay 0-indexed.
4. Do **not** say every templated slide must have a non-null index.

Steps:

- [ ] **Step 1 (test author):** phrase-presence tests for `template_sections`, `slide_type`, `template_section_index`, 1-indexed `message`, and a negative: the prompt must not contain a requirement that every `template_section_index` be non-null. Update `HEAD_UNCHANGED_BLOCK_HASHES` only for blocks you intentionally change (SLIDESPEC FIELDS will change). Confirm red on missing phrases.
- [ ] **Step 2 (implementer):** edit `INSTRUCTIONS`; promote architect (dry run first); re-pin architect content hashes; leave other roles' hashes unchanged. Report old and new architect content hash.
- [ ] **Step 3:** prompt contract + packaged release + definition manifest tests green.

---

## Task 6: Builder fills `section_html` and keeps treatment

**Models:** test=sonnet impl=sonnet

**Files:** `src/core/skills/builder.py`, v1 manifest via promote, hash pins for **builder** only

Prompt changes:

- INPUT includes `section_html`, `section_css`, `slide_spec.slide_type`, `template_section_index`.
- When `section_html` is non-empty: fill that structure; keep the outer root tag (`section` allowed) and class tokens that carry background; no inline `color:` / `background:`; same-element rule (`dark`/`white`/`event` on the element that paints); follow the bound section even if `content_brief` names a different kind; no `<style>`.
- When `section_html` is empty: improvise from purpose / brief / `resolved_style` using design-system class tokens on `.slide` / `.slide.dark` / `.slide.white` / `.slide.event`. Do not emit a bare `.slide` that depends on a `section { background }` rule.
- OUTPUT html may be a `<section>` wrapping `div.slide`. Remove any sentence that requires the fragment's outer root to be exactly `<div class="slide">`.

Steps:

- [ ] **Step 1 (test author):** phrase tests for `section_html`, preserve outer root, no inline paint, improvisation uses class tokens. Find and name any test that asserts builder HTML must start with `<div class="slide">` as a **prompt** requirement (production stubs that return that string may stay). Confirm red.
- [ ] **Step 2 (implementer):** edit `INSTRUCTIONS`; promote builder; re-pin builder content hash only.
- [ ] **Step 3:** builder prompt + packaged hashes green.

---

## Task 7: Review criteria and reviewer sees `section_html`

**Models:** test=opus impl=sonnet

**Files:** `src/domain/finding.py`, `tests/unit/test_finding_schema.py`, `src/core/skills/build_reviewer.py`, `src/services/graph/nodes.py`, `tests/fixtures/model_payload_keys.py`, `src/services/agent_model_payload.py`, graph-node payload tests

Behaviour:

1. Tighten `contrast_failure.description`: measure effective text colour against the colour actually painted behind it (ancestor and inline backgrounds); palette membership is not a defence; use the design-system contrast table when present (≥4.5:1 normal, ≥3:1 large); check every text run.
2. Add two slide-level **design** criteria, `objective=True`:

| name | description gist |
| --- | --- |
| `off_template_treatment` | Bound section rendered in a treatment other than the one it ships in (ground flipped, governing class not on the painting element, or inline colour fighting descendant `.dark` / `.white` rules). |
| `layout_binding_mismatch` | Built HTML is not the section named by the `slide_type` / `template_section_index` pair. Distinct from `brief_not_delivered`. |

3. `TestCriteriaRegistry._EXPECTED` and `test_registry_has_exactly_the_a2_criteria` become eleven keys. Rename the test if it still says "nine" / "§A2".
4. Authored reviewer prefix (`BUILD_REVIEWER_AUTHORED_PREFIX`): judge cascade not class names; compare built HTML to `section_html` and `slide_spec.slide_type`; never propose a replacement colour or layout in the finding message. Criteria lines stay generated from `CRITERIA`.
5. Production payloads must include `section_html`:
   - `build_reviewer_node` review_payload (~2325)
   - deck-level re-review (~653) — same extracted fragment; empty string if unbound
   - `SLIDE_REVIEW_MODEL_KEYS` in `tests/fixtures/model_payload_keys.py`
   - `_SLIDE_REVIEW_KEYS` in `src/services/agent_model_payload.py`
6. For re-review, extract with `extract_section(layout, index)` the same way `build_branch_payload` does; do not invent a second extractor.

Promote **build_reviewer** after the prefix change; re-pin that role's content hash. Schema digest for build_reviewer stays unchanged (criterion names are not in the JSON schema).

Steps:

- [ ] **Step 1 (test author):** registry tests for the two new rows and tightened contrast text. Payload tests: production `build_reviewer_node` / re-review dict contains `section_html`; `SLIDE_REVIEW_MODEL_KEYS` includes it. Finding with unknown name still rejected; `off_template_treatment` with `category="design"` validates. Confirm red.
- [ ] **Step 2 (implementer):** registry + prefix + three payload sites + literals. Promote build_reviewer.
- [ ] **Step 3:** finding schema, model_payload_keys pins, graph node payload tests, packaged build_reviewer hash green.

---

## Task 8: Agentic inventory assignment + docs

**Models:** test=sonnet impl=haiku

**Files:** `tests/agentic/test_section_inventory_supports_assignment.py`, `docs/technical/design-system-bundle-format.md`

Behaviour:

- Agentic test: inventory entries used for assignment include `label`; a probe that only sees classes-on-wrapper is insufficient. Keep 1-index comments as comments, not as index values.
- Bundle-format doc: `templates/<slug>/index.html` is retained source **and** every slide root after `find_slide_roots` must declare non-empty `data-label`. Duplicate labels allowed. Unlabeled new imports fail with path + 0-based index. Existing rows are not rewritten.

Steps:

- [ ] **Step 1 (test author):** failing assertion that each inventoried root used in the assignment test has a non-null `label` on a labeled fixture.
- [ ] **Step 2 (implementer):** update the agentic fixture HTML to carry `data-label`; update the doc section on templates.
- [ ] **Step 3:** agentic test file green under its usual gate. Do not edit README unless committing (ask first).

---

## Task 9: Verification

**Models:** impl=sonnet (controller)

- [ ] `tests/unit` failing-cause set equals the pre-change baseline plus only tests this plan intentionally updated.
- [ ] `tests/integration` same rule.
- [ ] Sabotage-verify (reviewer-approved tests from Tasks 1, 2, 4, 7): temporarily revert the production assertion and confirm red.
- [ ] Do **not** run live evals unless the user asks. Gold JSON must `DeckSpec.model_validate` for both meridian files.
- [ ] Do not commit unless asked.

---

## Self-review (plan author)

1. Spec coverage: inventory keys, import rejection, `slide_type` field, pair validation, architect/builder/reviewer prompts, CRITERIA additions, reviewer `section_html`, gold JSON, digest bump, bundle doc. Out of scope left out: host-frame CSS, Databricks token rewrite, `inconsistent_treatment`, `unassessable_criterion`, product enum.
2. Placeholder scan: none. Every task names files and expected tests.
3. Type consistency: `slide_type` is `Optional[str]` throughout; indexes 0-based in data, 1-based only in architect `message`.

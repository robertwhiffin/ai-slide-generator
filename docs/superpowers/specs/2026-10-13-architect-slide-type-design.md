# Design-System-Defined Slide Type Binding — Design Spec

**Date:** 2026-10-13
**Status:** Proposed
**Scope:** DeckSpec / SlideSpec, design-system bundle validation and section inventory, architect and builder payloads and prompts
**Out of scope:** Redesigning Databricks token CSS, host-frame CSS injection, eval-harness yardstick changes except gold `DeckSpec` fixtures that must validate after the schema change

A live workbench prompt (architect, builder, build reviewer) was tried against this failure before this spec. The [Prompt inheritance](#prompt-inheritance-from-the-live-workbench) section is the ruling on what of that prompt survives. The repo skills (`src/core/skills/architect.py`, `builder.py`, `build_reviewer.py`) and `CRITERIA` in `src/domain/finding.py` are the code baseline; the workbench text is not.

## Goal

The selected design system supplies the vocabulary of slide types and the markup that implements each type. The architect selects from that vocabulary for each slide. The builder fills the selected implementation instead of inventing a layout in isolation.

Success looks like:

- A validated template exposes a non-empty type label for every section it offers, regardless of brand or vocabulary.
- The architect stores a matching pair: the design-system-supplied `slide_type` label and that section's `template_section_index`.
- The builder receives and fills the exact section markup selected by that pair.
- The architect never claims the section list was “not supplied” when the payload key `template_sections` is present.
- If no supplied section fits the narrative need, both binding fields remain null and the builder improvises from the content brief without pretending the design system defined a matching type.
- Tellr contains no hard-coded Corporate, Databricks, or universal slide-type vocabulary.

## Why

Measured on the production Databricks Design System in `app_data_prod` on Lakebase branch `projects/db-tellr/branches/dev-beta` (endpoint `ep-raspy-frost-d2egjqda`, 2026-10-13):

The live default system is **Databricks Design System** (`id=1`, `is_default=true`). It has four templates. The Corporate deck’s stored description summarises its section kinds:

> Cover + agenda, section dividers, content, two-column, cards, statement, stats, closing.

Its stored `layout_html` has nine slide roots, in that order. The other three templates have different counts and treatments (Executive Events 6, Reference Architecture 6, Strategy & Consulting 11).

The downloaded source bundle at `/Downloads/Databricks Corporate Slides Design System (2)` resolves the generic contract. Every template section already carries a design-system-authored `data-label`:

- Corporate: `Cover`, `Agenda`, `Section`, `Content`, `Two-column`, `Three cards`, `Statement`, `Stats`, `Closing`.
- Executive Events: `Event cover`, `Section`, `Content`, `Statement`, `Stats`, `Closing`.
- Reference Architecture includes `Reference architecture` and `Lakehouse blueprint`.
- Strategy & Consulting includes `Charts`, `KPI dashboard`, `Data table`, `2x2 matrix`, `Waterfall`, `Comparison`, and `Timeline`.

The same labels were verified in the four persisted `app_data_prod.design_system_template.layout_html` rows on the `dev-beta` branch. Import already preserves the metadata; only the runtime inventory drops it.

The manifest's `cards[]` also lists many slide examples, but cards are not a reliable template-section mapping: they are independent specimens and are not scoped to a specific template. The co-located `data-label` on each section is the authoritative mapping because it names the exact markup the builder will receive.

What the graph actually does today:

1. `architect_node` already puts `template_sections: section_inventory(layout_html)` in the model payload.
2. `section_inventory` emits `index`, `tag`, `classes`, `text_snippet`, `affordances`. It discards the root's `data-label`. For Corporate, `find_slide_roots` also promotes the outer `<section>` (empty class list), so the inventory never shows the inner `div.slide.dark|white|event` classes that carry treatment.
3. The shipped architect field list in `src/core/skills/architect.py` still omits `template_section_index`. The active graph-release prompt (release 5, definition v2) demands the index but never names the payload key `template_sections`, which is why the model writes a complaint instead of binding.
4. `build_branch_payload` extracts `section_html` only when `template_section_index` is set. Builders on this deck received empty `section_html`.
5. The builder prompt requires a `<div class="slide">` fragment and never mentions `section_html`. Builders therefore drop the template `<section>` wrapper. Databricks CSS paints the light ground on `section` and the page chrome is `#0e1a1f`. Navy titles on an unpainted `.slide` are illegible. Cover slides that set an inline navy background survive; Agenda does not.

Prompt-only edits cannot close this: there is no typed field for the slide’s kind, and the builder has no instruction to preserve the extracted section.

## Authority split

| Actor | Owns | Does not own |
| --- | --- | --- |
| Design system | Its slide-type vocabulary (`data-label`), which sections implement each type, their markup and CSS | What this deck’s narrative needs on slide N |
| Architect | Choosing one supplied type/index pair when it fits; leaving both null when none fits | Inventing labels that the selected template does not supply; rewriting template HTML or CSS |
| Deterministic code | Inventory, pair validation, extraction (`extract_section`), CSS aggregation | Translating between a global ontology and brand-specific labels |
| Builder | Filling the extracted section (or improvising when none was assigned) while keeping the treatment that makes type readable | Choosing the slide’s kind |

For a bound slide, `slide_type` and `template_section_index` are redundant by design: the label makes the architect's intent legible and the index identifies the exact implementation. Deterministic validation uses the redundancy to reject mismatches before a builder runs.

## Design-system-defined `slide_type` vocabulary

There is no product-wide enum. `slide_type` is the exact, case-preserving `data-label` value authored on a section of the pinned template.

Examples are evidence, not allowed values:

- One design system may say `Section`; another may say `Chapter break`.
- One may offer `Content`; another may split that into `Action title`, `Evidence`, and `Recommendation`.
- Strategy & Consulting can offer `2x2 matrix` and `Waterfall` without Tellr adding either value to a schema enum.

Rules:

- If a section is bound, `slide_type` must equal that inventory entry's `label`, and `template_section_index` must equal its `index`.
- If no supplied section fits, both fields are null. Narrative intent remains in `purpose` and `content_brief`; the builder improvises from those existing fields.
- The architect never invents a new `slide_type` while a design system is pinned. An invented value would falsely claim the design system defines an implementation.
- Duplicate labels are allowed. A template may offer several `Content` variants; index, snippet, affordances, and inner classes distinguish them.
- Persisted specs written before this field existed deserialise with `slide_type=None`. `DeckSpec.from_json` must keep returning a spec, not `None`.

## Bundle validation

The source of truth is the selected template's retained `layout_html`. Every slide root in a newly imported declared template must have a non-empty `data-label`.

Validation rules:

- After `find_slide_roots` promotion, read `data-label` from the outer slide root.
- Leading and trailing whitespace is stripped; an empty result is invalid.
- Labels are uncapped brand text. Do not impose a length enum or product vocabulary.
- Duplicate labels are valid.
- The number and order of labels must match the number and order of extractable slide roots by construction: each label lives on its root, so no separate index map can drift.
- A newly imported template with an unlabeled root is rejected with a path and zero-based section index. Do not import a template that the architect cannot address safely.
- Existing database rows imported before this rule are not rewritten at startup. A missing label at runtime makes that section unbindable and produces a warning; reimporting the corrected bundle is the remediation.

Update `docs/technical/design-system-bundle-format.md`: `templates/<slug>/index.html` is not only retained source; each slide root must declare `data-label`.

## Data model

### `SlideSpec`

Add:

```python
class SlideSpec(BaseModel):
    ...
    slide_type: Optional[str] = None
    template_section_index: Optional[int] = None
```

`slide_type` is uncapped design-system-authored text, not a `Literal`. A field validator rejects whitespace-only values and strips surrounding whitespace. Contextual validation against the selected template happens in `architect_node`, because Pydantic cannot know the turn's inventory.

No other new `DeckSpec` fields. Visual treatment (dark / white / event) remains in the template markup, not a second enum on the spec.

### `DesignSystemTemplate`

No database column, migration, Corporate seed, or manifest-to-index projection is needed. `layout_html` already retains `data-label` on the exact section it describes. Duplicating that map into JSON would create a second authority that can drift when markup is edited.

### Architect JSON schema contract

`ArchitectOutput` nests `DeckSpec`. Adding `slide_type` changes the structured-output schema digest. The implementation must bump the architect `schema_contract` the same way previous field additions did (retained ledger + graph definition manifest). Do not leave the live release on a digest that rejects the new field.

Eval gold `DeckSpec` objects under `evals/packs/architect/` must include `slide_type` so they still validate. That is a schema-follow, not a yardstick change: do not edit cases, references, judge prompts, or scorers except as required for the new field to parse.

## Inventory and payloads

### `section_inventory`

Each entry becomes:

```text
index: int
label: str | null        # exact trimmed data-label from this root
tag: str                 # outermost root tag after promotion (today: section)
classes: list[str]       # classes on that outermost root
inner_classes: list[str] # classes on the innermost element with class token "slide", if different from the root; else []
text_snippet: str
affordances: list[str]
```

`section_inventory(layout_html)` remains the only function required. It reads `label` and `inner_classes` from the same parsed root it already inventories. No database join is involved.

The architect prompt **must** name the payload key:

> Your payload includes `template_sections`: the slide types supplied by the pinned template. Each item has `index`, the exact design-system-authored `label`, `inner_classes`, `text_snippet`, and `affordances`. Choose only from these entries. Copy `label` exactly into `slide_type` and its `index` into `template_section_index`. If no entry fits, leave both fields null. Do not invent a type that is not present.

### Builder payload

No new keys. The builder already receives `slide_spec` (which will contain `slide_type`) and `section_html` (still extracted by index). Prompt changes tell it what those mean.

`section_html` remains verbatim extracted markup, including the promoted `<section>` when that is the slide root. The builder must not be instructed to unwrap it into a lone `<div class="slide">`.

### Build-reviewer payload

Add `section_html` (the same extracted fragment the builder saw). Without it the reviewer cannot tell a filled section from an invented one. Do not add sibling slides; the pipeline is still one slide per `Send`.

## Architect behaviour

On `build` and `edit`:

1. Decide what the narrative needs without assuming a global type name.
2. If `template_sections` is a non-empty list, select the best supplied entry by label, snippet, affordances, and inner classes.
3. Copy the selected entry's exact `label` to `slide_type` and its `index` to `template_section_index`.
4. If no supplied entry fits, leave both fields null. Do not bind a merely similar section and do not invent a label.
5. If `template_sections` is `[]` or absent, leave both fields null. Mention that in `message` only when the key is absent or the list is empty — never when the list is present but has no suitable type.
6. `content_brief` stays the *content* of the slide. It does not substitute for `slide_type`. Name the exhibit type when the slide carries numbers. Require design-system logo/lockup furniture when the selected section's markup/description supplies it, rather than keying that rule to hard-coded words such as `title`, `divider`, or `closing`.
7. Style assets are identity, not evidence. Never request a brand or product asset as a literal depiction of the subject.
8. Do not plan exhibits onto missing data. Prefer `ask_data` if every `data_references` entry is an unresolved gap; if building anyway, say in `message` which positions will render without exhibits.

When committing a design system, do not leave `template_id` unset if the library lists templates. Pick a sensible default from the user prompt, or ask. An unset template is why `template_sections` arrives empty.

In `message` (and only there), speak about slides 1-indexed, matching the UI. `position` and `target_positions` stay 0-indexed. If the user says “slide 2”, that is `position` 1.

Do not require a binding on every slide of a templated deck. The pair is either fully populated from one inventory entry or fully null.

The architect field list in the prompt must include `slide_type` and `template_section_index`. Omitting them from the field list is why models leave them null even when the prose above demands them.

After the model returns, `architect_node` validates every non-null pair against the current inventory before persisting or dispatching:

- exactly one null is invalid;
- an out-of-range index is invalid;
- `slide_type` unequal to that index's `label` is invalid;
- an index whose label is null is invalid.

Invalid output fails before any builder runs and names the position and supplied pair. Do not silently erase the bind and generate an unrelated slide.

## Builder behaviour

When `section_html` is non-empty:

- Fill that structure. Keep the outer root tag and the class tokens that carry background (`section`, `slide`, `dark`, `white`, `event`, …).
- Render the section in the treatment it ships in. Do not recolour a light section dark, or the reverse.
- Do not add inline `color:` or `background:`. Do not keep a template inline colour after changing the ground (you should not have changed the ground).
- Background class and text-colour class belong on the same element that paints the fill. Putting `dark` on a wrapper while the `.slide` still ships light leaves descendant `.dark` rules unfired.
- Replace placeholder copy with the brief. Do not emit a sibling root that drops those classes.
- Still no `<style>` element.
- Follow `section_html` / `template_section_index`. If `content_brief` names a different kind than the bound section, fill the bound section anyway. The builder has no `message` field; the reviewer reports the mismatch.

When `section_html` is empty:

- Invent a layout consistent with `slide_spec.purpose`, `content_brief`, and `resolved_style`. An empty `section_html` means `slide_type` is also null.
- Paint using design-system **class tokens** that the deck CSS actually applies to `.slide` / `.slide.dark` / `.slide.white` / `.slide.event`. Do not invent inline `color:` / `background:`. Relying on a `section { background: … }` rule while emitting only `<div class="slide">` is a defect.

`BuilderOutput` stays `{position, html, scripts}`. HTML may be a `<section>` wrapping `div.slide`, matching template structure. Update any test or prompt that asserts the fragment must be exactly `<div class="slide">` as the outer root.

## Review

Tighten the existing `contrast_failure` description in `CRITERIA` (prompt is generated from the registry): measure effective text colour against the colour actually painted behind it, including ancestor and inline backgrounds; palettes membership is not a defence against a bad pairing. Compare against the design-system contrast table when one is in the compiled style (≥4.5:1 normal, ≥3:1 large text). Check every text run, not only title and body.

Add two slide-level **design** criteria to `CRITERIA` (this is a registry change, not a prompt-only invention — unknown names are rejected by `Finding`):

| Name | Meaning |
| --- | --- |
| `off_template_treatment` | Bound section was rendered in a treatment other than the one it ships in: ground flipped, governing class not on the painting element, or inline colour fighting descendant `.dark` / `.white` rules. |
| `layout_binding_mismatch` | Built HTML is not the section named by the `slide_type` / `template_section_index` pair. Distinct from `brief_not_delivered`. |

Authored reviewer prefix may add: judge cascade, not class names; compare the built HTML with the selected inventory entry's label and `section_html`, never with a Tellr-invented taxonomy. Never propose a replacement colour or layout in the finding message.

Do not add:

- `inconsistent_treatment` — deck-scoped, but the build reviewer never sees sibling HTML (`slide_pipeline_node` is one slide per `Send`).
- `unassessable_criterion` — `FindingCategory` is closed (`content` \| `design` \| `narrative`); a `process` category breaks the frontend `Record`. The reviewer also has no computed-style dump, so this criterion would fire on every `contrast_failure` check and stall the fixer loop.
- Re-binding `template_section_index` in the reviewer.

Deck-narrative criteria (`arc_gap`, `cross_slide_repetition`, `missing_conclusion`) already exist in `CRITERIA`. They belong to the deck reviewer. Do not teach the per-slide build reviewer to emit them from a single slide.

## Prompt inheritance from the live workbench

Relative to `src/core/skills/*` on `main` and this spec.

### Architect — keep

| Live addition | Ruling |
| --- | --- |
| Users speak 1-indexed; convert internally | Keep. UI is Slide 1. Spec now requires it in `message` only. |
| When using a design system, pick a template; do not leave `template_id` empty | Keep. Empty template ⇒ empty `template_sections`. |
| `content_brief` must name the exhibit; logo/lockup on title / divider / closing | Keep the exhibit rule. Derive brand-furniture requirements from the selected section markup/description, not hard-coded English labels. |
| Style assets are never claims about the topic | Keep. |
| Don’t plan exhibits onto missing data; prefer `ask_data` | Keep. |

### Architect — drop or rewrite

| Live addition | Ruling |
| --- | --- |
| On a templated deck every `template_section_index` MUST be non-null; if the list was not supplied, complain in `message` and name the section in `content_brief` | Drop. This is the defect. The pair is populated only from one supplied inventory entry; otherwise both fields are null. The payload key is `template_sections`. |
| Field list still omits `slide_type` and `template_section_index` | The live field list is incomplete. Spec requires both fields listed. |

### Builder — keep

| Live addition | Ruling |
| --- | --- |
| Same-element rule (`dark` on the element that paints) | Keep. |
| Don’t transition a shipped section | Keep. Fill it as it ships. |
| No inline `color:` / `background:` | Keep. Improvisation uses class tokens, not inline paint. |
| Follow the bound index over a conflicting brief | Keep as “fill `section_html`”. Builder cannot “report” except via the HTML it emits. |

### Builder — rewrite

| Live addition | Ruling |
| --- | --- |
| Output is a `<div class="slide">` | Rewrite. Outer root may be `<section>` wrapping `div.slide`. |
| INPUT lists only the brief fields | Rewrite. INPUT includes `slide_spec.slide_type`, `section_html`, `section_css`. |

### Build reviewer — keep

| Live addition | Ruling |
| --- | --- |
| Judge cascade, not class names | Keep as authored prefix. |
| Tightened `contrast_failure` measurement language | Keep, by editing `CRITERIA.description`. |
| `off_template_treatment`, `layout_binding_mismatch` | Keep as **registry** entries, category `design`, level `slide`. |
| Never invent a replacement palette in the finding | Keep. |

### Build reviewer — drop

| Live addition | Ruling |
| --- | --- |
| `inconsistent_treatment` (deck) | Drop. No sibling slides in the payload. |
| `unassessable_criterion` (`process`) | Drop. Closed category union; would false-positive without computed styles. |
| Listing deck-narrative criteria as if the slide reviewer should apply them | Drop. Deck reviewer owns those. |

## Error handling

- New bundle import: reject a declared template whose extractable slide root has no non-empty `data-label`; report template path and section index.
- Legacy database row with a missing label: keep the section in inventory with `label=null`, log a warning, and forbid architect binding to it.
- Architect output with only one of `slide_type` / `template_section_index`: fail before dispatch.
- Architect output with an out-of-range index, null inventory label, or label/index mismatch: fail before dispatch and name the slide position and pair.
- Duplicate labels: valid. The index remains the exact implementation selector.

## Testing

Minimum:

- `SlideSpec` accepts arbitrary non-empty design-system labels, strips their outer whitespace, defaults old JSON to null, and rejects whitespace-only labels.
- Template materialization/import accepts labelled roots, allows duplicate labels, and rejects an unlabeled root with path/index.
- `section_inventory` returns the exact `data-label` plus `inner_classes`; a synthetic Corporate-shaped fixture may prove `Cover` and `['slide','dark']`, but these are examples rather than product constants.
- Architect-node pair validation accepts (`Agenda`, 1) against a matching inventory; rejects half-null, out-of-range, unlabeled, and mismatched pairs.
- `build_branch_payload` extracts by index for a valid pair; with both fields null, `section_html` is `""`.
- Architect prompt / field list includes `slide_type` and `template_section_index`, names `template_sections`, and states 1-indexed user speech.
- Builder prompt requires preserving `section_html` roots, no inline colour, and class-token paint when empty.
- `CRITERIA` gains `off_template_treatment` and `layout_binding_mismatch`; `Finding` still rejects unknown names and `process` as a category.
- Build-reviewer production payload keys include `section_html`.
- Agentic (existing layer-3 probe): given a two-section inventory labelled with vocabulary chosen by that fixture, the architect copies the selected label and index exactly.
- Cross-design-system test: two templates use different labels for equivalent narrative needs (for example `Section` and `Chapter break`); each output uses only the vocabulary supplied in its own payload.

Do not vendor the production `layout_html` into the repo.

## Documentation

When this ships, update `README.md` only if user-facing generation behaviour is described there, and the companion technical docs that describe DeckSpec / architect / builder so they name `slide_type` and `data-label`. Update `docs/technical/design-system-bundle-format.md` to make labelled roots part of the bundle contract. Per project rule, README/doc edits happen as part of the implementation commit, after confirmation.

## Non-goals

- Compiling `.slide` parallels for `section { background }` in the design-system CSS.
- Changing `html, body { background: #0e1a1f }` in the Databricks sheet.
- A Tellr-owned universal slide-type enum.
- A `section_roles` database column, Corporate seed, or migration.
- Inferring a template section's type from filenames, example cards, prose snippets, or CSS classes when `data-label` is absent.
- A deck-level style-guide prose field. `slide_type` plus the template is the style guide.
- Letting the builder invent new CSS tokens.
- Expanding `FindingCategory` with `process`.
- A per-slide reviewer that sees the rest of the deck.

## Rollout

1. Bundle validation + richer inventory (`label`, `inner_classes`).
2. `SlideSpec` optional `slide_type` + architect pair validation and schema-contract update.
3. Architect, builder, and reviewer prompt/payload updates.
4. Tests and technical documentation, then a graph-release publication (out of band from this spec; operators publish via the workbench).

Code on `main` and the live release can lag; both must move or the model will keep emitting the old shape.

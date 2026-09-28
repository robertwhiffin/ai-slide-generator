# Agent definition consistency

Seeded Agent Definition prompts scored against what the LangGraph nodes actually send, plus paste-ready prompt text for Admin → Agent Definitions.

---

## Scope

Seven model-driven roles are editable in `/admin` → **Agent Definitions**. Foreman and placeholder are graph nodes with no definition.

Runtime after bootstrap reads **Lakebase graph releases**, not Python. Apply these texts as workbench drafts and publish a release. Do not edit `src/services/graph/builder.py`, `routers.py`, or `nodes.py` for this pass. Refreshing `src/services/agent_definition_manifest_v1.py` is a separate follow-up if new installs should seed the same text.

Paste files live in [`agent-definition-prompts/`](agent-definition-prompts/): one `.txt` per `agent_key`.

---

## Scorecard (seeded v2 vs graph)

| Role | Payload the node sends | Output schema | Seeded prompt gap | Proposed change |
| --- | --- | --- | --- | --- |
| `architect` | `conversation`, `message`, `current_deck_spec`, `committed_slide_count`, `previous_deck_review`, `available_design_contract`, `template_sections`, `resolved_style`, `design_system_library` | `ArchitectOutput`; `ask_data` requires `data_request` | Intent/schema rules are correct; does not say the analyst receives `architect_message` concatenated with `DATA REQUEST: ` + JSON | Name real payload keys; document the ask_data handoff |
| `data_analyst` | `data_request` (string), `deck_purpose` | `AnalystOutput` | Instructs Genie / vector_index tool use; treats `data_request` as a structured object. Node binds **no tools**; `data_request` is the architect’s message string | No-tools procedure; parse the DATA REQUEST blob from the string |
| `builder` | `position`, `slide_spec`, `assumes`, `hands_off`, `resolved_data`, `section_html`, `section_css`, `resolved_style`, `design_system_active` (+ `corrective_instruction` on retry) | `BuilderOutput` | Says “section brief”; omits template/style keys and safety retry | Enumerate production keys |
| `build_reviewer` | Slide review keys plus `deck_brief` on re-review | `SlideReviewOutput`; only **objective** findings dispatch the fixer | Lists deck-level `arc_gap` / `cross_slide_repetition` / `missing_conclusion` though the node sees one slide | Slide-level criteria only; note `deck_brief` and fixer preemption |
| `fixer` | `position`, `finding`, `html`, `scripts`, `slide_spec`, `resolved_style`, `section_css` (+ retry instruction) | `FixerOutput` | “For EDIT: return the same number of slides” is monolith leftover | One finding, one slide fragment |
| `fix_reviewer` | Fixer keys plus `change_summary` | `SlideReviewOutput` (`clean` / `fixed` / `surfaced`) | “Use criterion names from the registry” with no list | Same slide-level list as build reviewer |
| `deck_reviewer` | `narrative_arc`, `call_to_action`, `slide_count`, `slides` | `DeckReviewOutput`; `slide_index` = -1 | Claims title/argument as inputs | Align INPUT to production keys |

**Model block (unchanged):** all seven seeded definitions use `databricks-claude-opus-4-6`, temperature `0.7`, `max_tokens` 60000, `top_p` 0.95. Leave that as-is until a role-specific cost/quality split is measured. Schema overlays stay empty (no `diagnostic_notes` unless you upgrade the schema contract in the workbench).

---

## Human-facing text (one `message` field)

`Finding.message` is rendered verbatim in the feedback drawer and pasted into Apply/Discuss chat. The same string is what the fixer reads. Do not split human/machine views in the schema for this pass: keep `message` short and actionable; the fixer already has `criterion`, HTML, CSS, and `slide_spec`.

The proposed reviewer prompts therefore:

- emit **only unresolved failures** (no passing checks, withdrawn findings, or ratio arithmetic)
- cap `message` at two short sentences
- treat preference language ("dominates", "prefer") as guidance, not `rogue_colour`
- admit that HTML is not a rendered screenshot, so invented contrast ratios are out of scope

The same rule is applied to other user-visible fields: architect `message`, analyst `synthesis`/`gap`/`reason`, fixer `change_summary`, deck-reviewer `message`. The builder has no prose field; its constraint is "no commentary in the markup."

---

## How to apply in the workbench

1. Open `/admin` → Agent Definitions.
2. For each role, paste the matching file from `docs/technical/agent-definition-prompts/<agent_key>.txt` into the authored prompt.
3. Leave model, assembly v1 block order, protected assembly, and schema contract unless you are deliberately changing those.
4. Run the role’s required smoke test, then publish a graph release so conversations pick up the new texts.

---

## Graph context (do not rewire)

```
START → architect
architect → END (discuss | confirm_design_contract)
architect → data_analyst → architect (ask_data)
architect → foreman (build | edit)
foreman → builder (Send batch) → build_reviewer (Send re-fan) → foreman
foreman → fixer → fix_reviewer → foreman
foreman → deck_reviewer → END
```

Protected assembly (slide-frame vs design-system precedence, plus `build_reviewer_deck_brief` when `deck_brief` is in the payload) is appended after the authored prompt. Do not duplicate those blocks in `prompt_text`.

---

## Cross-references

- Payload key union: `src/services/agent_model_payload.py`
- Output schemas: `src/domain/skill_io.py`, `src/domain/finding.py` (`CRITERIA`)
- Node call sites: `src/services/graph/nodes.py`
- Topology: `src/services/graph/builder.py`
- Admin UI: `frontend/src/components/Admin/AgentDefinitionWorkbench/`

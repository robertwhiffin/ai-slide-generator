set -u
OUT=docs/superpowers/plans/.ws4c-MEASURED-INTERFACES.md
: > $OUT
say() { printf '%s\n' "$*" >> $OUT; }
region() {  # label file start end
  say ""; say "### $1"; say ""; say '```'
  say "$2:$3-$4"
  sed -n "$3,$4p" "$2" | awk -v s="$3" '{printf "%d\t%s\n", s+NR-1, $0}' >> $OUT
  say '```'
}
defof() {  # label file symbol nlines
  local ln
  ln=$(grep -nE "^[[:space:]]*(def|class|async def) $3\b" "$2" 2>/dev/null | head -1 | cut -d: -f1)
  if [ -z "${ln:-}" ]; then say ""; say "### $1"; say ""; say "**NOT FOUND: \`$3\` in \`$2\`**"; return; fi
  region "$1" "$2" "$ln" "$((ln+$4))"
}
grepn() {  # label pattern files...
  local label="$1"; shift
  local pat="$1"; shift
  say ""; say "### $label"; say ""; say '```'
  grep -nE "$pat" "$@" >> $OUT 2>/dev/null || say "(no hits)"
  say '```'
}
whole() { # label file
  say ""; say "### $1 — WHOLE FILE"; say ""; say '```'
  say "$2 ($(wc -l < "$2") lines)"
  awk '{printf "%d\t%s\n", NR, $0}' "$2" >> $OUT
  say '```'
}

say '# ws4c — MEASURED INTERFACES'
say ''
say 'Companion to `.ws4c-PLAN-CORRECTIONS.md`. **Every block below was extracted from source by'
say 'script, with real line numbers — not retyped**, so nothing here can have drifted in'
say 'transcription. Generated 2026-09-13 on branch `feat/ws4c-graph-core`.'
say ''
say 'Why it exists: the plan cites roughly sixty `file:line` anchors and **sixteen of them are'
say 'wrong** (corrections §20), because `agent.py` and `agent_factory.py` have grown and ws4b moved'
say '`session_manager.py` and `test.yml` again. Task briefs point HERE instead of at the plan.'
say ''
say '> **Search by symbol name.** Treat a number here as a hint, not an address — a task that edits'
say '> one of these files invalidates the numbers below it. Regenerate with `/tmp/gen_measured.sh`.'
say ''
say '---'
say ''
say '## C3 / C8 — prompt resolution, and the defect at the centre of both'
grepn 'POST-C8: `agent_factory.py` is now a re-export SHIM — every module-level symbol' '^def |^class |^logger|^from |^import |^    _' src/services/agent_factory.py
grepn 'POST-C8: `agent_resolution.py` — every module-level symbol' '^def |^class |^logger|^from |^import ' src/services/agent_resolution.py
defof '`_get_prompt_content` — signature (MOVED to agent_resolution by C8)' src/services/agent_resolution.py _get_prompt_content 14
region 'THE STYLE-RESOLUTION BRANCH — a BRANCH, not a ladder. Now in agent_resolution (C8).' src/services/agent_resolution.py 84 127
grepn 'What `_get_prompt_content` RETURNS — every part is None but `system_prompt` (the pinned null)' '"slide_style": None|"pre_assembled": True|"system_prompt": assembled' src/services/agent_resolution.py
grepn 'A TEST PINS THE NULL. This is why the null cannot simply be filled in.' 'result\["slide_style"\] is None' tests/unit/test_agent_factory.py
grepn 'The only other reader of the key — the monolith dead branch, R2-barred anyway' 'prompts.get\("slide_style"\)' src/services/agent.py
defof '`_build_tools` — the brand gate, BOTH halves (MOVED by C8)' src/services/agent_resolution.py _build_tools 60
defof '`_design_system_is_active` — fails CLOSED (MOVED by C8)' src/services/agent_resolution.py _design_system_is_active 36
defof '`ResolvedStyle` — the FIVE-field extraction C8 added (corrections 33 + 40.1)' src/services/agent_resolution.py ResolvedStyle 30
defof '`resolve_style_source` — the extracted branch itself' src/services/agent_resolution.py resolve_style_source 46
defof '`resolve_slide_style` — the thin wrapper C3 consumes' src/services/agent_resolution.py resolve_slide_style 12
defof '`build_agent_for_request` — STAYS in agent_factory (construction, not resolution)' src/services/agent_factory.py build_agent_for_request 62
grepn 'The SHIM re-export list — Ruling C-20: these three ONLY' 'from src.services.agent_resolution import|^    _' src/services/agent_factory.py
defof '`_create_model` — the client path C3 must follow, not invent' src/services/agent_factory.py _create_model 24
defof '`resolve_agent_config`' src/api/schemas/agent_config.py resolve_agent_config 6
grepn '`get_system_client`' 'def get_system_client' src/core/databricks_client.py
grepn '`_SLIDE_FRAME_CONSTRAINTS` and `DESIGN_SYSTEM_PRECEDENCE`' '_SLIDE_FRAME_CONSTRAINTS = |DESIGN_SYSTEM_PRECEDENCE = ' src/services/design_system_compiler.py src/core/prompt_modules.py
region '`_SLIDE_FRAME_CONSTRAINTS` — the exact bytes, so no skill retypes them' src/services/design_system_compiler.py 545 575
region '`DEFAULT_SLIDE_STYLE` — case 2 of L5: NO safe-area numbers at all' src/core/defaults.py 1 30
say ''
say '### THE 22 PATCH TARGETS — all in `test_agent_factory.py`; 12 must be repointed by C8'
say ''
say '```'
grep -rhoE 'src\.services\.agent_factory\.[A-Za-z_][A-Za-z_0-9]*' \
  tests/unit/test_ds_generation_state_matrix.py tests/unit/test_design_system_compiler.py \
  tests/unit/test_prompt_precedence_fixes.py tests/unit/test_factory_tool_spotlighting.py \
  tests/unit/test_agent_factory.py tests/unit/test_design_systems_routes.py \
  | sort | uniq -c | sort -rn >> $OUT
say '```'
say ''
say '### The six suites — reference counts and test counts'
say ''
say '```'
for f in test_ds_generation_state_matrix test_design_system_compiler test_prompt_precedence_fixes \
         test_factory_tool_spotlighting test_agent_factory test_design_systems_routes; do
  printf '%-38s refs=%-3s patch_targets=%-3s tests=%s\n' "$f" \
    "$(grep -c 'src\.services\.agent_factory' tests/unit/$f.py)" \
    "$(grep -c 'patch("src\.services\.agent_factory\.' tests/unit/$f.py)" \
    "$(grep -c 'def test_' tests/unit/$f.py)" >> $OUT
done
say '```'

say ''; say '---'; say ''
say '## C4 — nodes, routers, assembly'
defof '`SlideWriter.write_slide` — full signature + the partial-update semantics C4 depends on' src/api/services/slide_repository.py write_slide 55
defof '`SlideWriter.commit_placeholder` — takes NO modified_by and NO deck_spec_slide (corrections §22)' src/api/services/slide_repository.py commit_placeholder 58
defof '`is_placeholder_record` — MODULE-LEVEL, not a method' src/api/services/slide_repository.py is_placeholder_record 24
defof '`write_deck_level_columns` — every column param keyword-only, defaulting to _UNSET' src/api/services/deck_level_writer.py write_deck_level_columns 16
region 'Which deck column belongs to which write — the module docstring settles Ruling C-12' src/api/services/deck_level_writer.py 40 68
defof '`read_deck_spec`' src/api/services/deck_level_writer.py read_deck_spec 10
defof '`save_deck_review` — (db, deck_id, digest, findings, author=None)' src/services/deck_review_store.py save_deck_review 8
defof '`get_deck_review` — (db, deck_id, digest); a content-addressed getter needs the digest' src/services/deck_review_store.py get_deck_review 8
defof '`compute_deck_digest` — takes a LIST OF HTML STRINGS in deck order' src/services/deck_review_store.py compute_deck_digest 6
region 'The deck_review_store module docstring — carries the call-site recipe verbatim' src/services/deck_review_store.py 1 70
defof '`_get_deck_owner_session` — takes a db AND a UserSession OBJECT, not a string' src/api/services/session_manager.py _get_deck_owner_session 18
defof '`_get_session_or_raise` — how to turn a session_id string into a UserSession' src/api/services/session_manager.py _get_session_or_raise 16
defof '`add_message` — the info-message vehicle for the deck-review verdict' src/api/services/session_manager.py add_message 26
defof '`aggregate_deck_css` — ws4c is its PRODUCER; the docstring is the contract' src/services/deck_css_aggregator.py aggregate_deck_css 45
defof '`get_checkpointer` — process-wide' src/core/checkpointer.py get_checkpointer 12
defof '`SlideDeck` — the domain class (slide_deck.py, NOT slide.py)' src/domain/slide_deck.py SlideDeck 8
defof '`SlideDeck.from_dict` — there is NO from_json' src/domain/slide_deck.py from_dict 14
defof '`SlideDeck.knit` — html_content comes from here' src/domain/slide_deck.py knit 30
region '`SlideDeck.scripts` — the read-only aggregating property that IS scripts_content'"'"'s source' src/domain/slide_deck.py 79 96
defof '`build_verification_record` — KEYWORD-ONLY. Reviewers must use this, not hand-roll the shape.' src/domain/finding.py build_verification_record 6
grepn 'Every `return` in `get_slide_deck` — THREE dict paths plus a None (corrections/ws4b §23)' '^[[:space:]]*(def get_slide_deck|return deck_dict|return result|return None)' src/api/services/session_manager.py
grepn 'Where `scripts_content` is read back into the deck dict' '"scripts": deck.scripts_content' src/api/services/session_manager.py
grepn 'The five consumers of the `scripts` key — export.py is a CONSUMER, not just a logger' 'slide_deck.get\("scripts"|deck\.scripts|\.scripts\b' src/api/routes/export.py
grepn '`StreamEvent` — ws4d declares `scripts`; skill_io settles it as `str`' 'class StreamEvent|^    [a-z_]+:' src/api/schemas/streaming.py

say ''; say '---'; say ''
say '## C5 — the layer-1 harness and its CI job'
whole '`tests/integration/conftest.py` — ws4b created it; C5 APPENDS, never duplicates a fixture' tests/integration/conftest.py
grepn 'Every fixture in `tests/unit/conftest.py` (unit-scoped — INVISIBLE to tests/integration/)' '^def [a-z_]+\(|^@pytest\.fixture' tests/unit/conftest.py
grepn 'The one `pytest_plugins` precedent in the repo' 'pytest_plugins' tests/unit/*.py tests/integration/*.py tests/*.py
region 'The `integration-slides` job — C5 clones THIS (the only integration job with Postgres)' .github/workflows/test.yml 314 358
region 'The `unit-tests` job — note it applies NO `-m` filter' .github/workflows/test.yml 95 128
whole 'ws4a A5 guard — any new tests/integration file not named in a job FAILS this' tests/unit/test_ci_collects_integration_tests.py
grepn '`test-summary` needs: — must gain integration-graph or the new job gates nothing' 'test-summary|^    needs:|^      - ' .github/workflows/test.yml
grepn 'pytest markers declared in pyproject.toml' 'markers|postgres:|live:|slow:' pyproject.toml
region 'The Postgres self-skip precedent to copy' tests/unit/test_design_system_partial_name_index_postgres.py 1 40

say ''; say '---'; say ''
say '## C6 — template-section extraction'
defof '`find_slide_roots` — roots are found by the `slide` CLASS TOKEN, not by tag' src/utils/html_utils.py find_slide_roots 32
grepn '`SLIDE_WRAPPER_TAGS` — {"section","article"} only; div and main are EXCLUDED' 'SLIDE_WRAPPER_TAGS' src/utils/html_utils.py src/services/design_system_templates.py
defof '`_detect_slide_root_tags`' src/services/design_system_templates.py _detect_slide_root_tags 12
defof '`normalize_root_tag_selectors` — returns its input unchanged when the root-tag set is empty' src/services/design_system_templates.py normalize_root_tag_selectors 26
defof '`get_template_for_generation` — takes a design-system OBJECT plus an int template_id' src/services/design_system_templates.py get_template_for_generation 30
defof '`materialize_templates` — self-heals by ASSIGNING template.layout_html; persistence is the caller session'"'"'s' src/services/design_system_templates.py materialize_templates 40
defof '`build_selected_template_block`' src/services/design_system_templates.py build_selected_template_block 20
defof '`ensure_deck_token_css` — the backstop; it lives in design_system_TEMPLATES.py, NOT css_utils.py and NOT the compiler' src/services/design_system_templates.py ensure_deck_token_css 30
grepn 'The DesignSystemTemplate model — which columns exist (no column holds only a <style> block)' 'class DesignSystemTemplate|^    [a-z_]+ = Column|^    [a-z_]+: ' src/database/models/design_system.py
grepn 'The DesignSystem model + the query pattern C6 copies (lazy import INSIDE the function)' 'class DesignSystem\b|filter_by\(id=|is_active=True' src/database/models/design_system.py src/services/agent_factory.py
grepn '`merge_css` / `parse_css_blocks` — ws4a at-rule work the aggregator inherits' 'def merge_css|def parse_css_blocks' src/utils/css_utils.py src/domain/slide_deck.py src/services/*.py
grepn 'Template fixtures that DO carry class="slide" (a probe against these returns 1 or N BY CONSTRUCTION)' 'class="slide"' tests/unit/conftest_design_system.py tests/unit/test_design_system_templates.py
region '`playwright.config.ts` — testDir is ./tests, so a /tmp spec is never collected' frontend/playwright.config.ts 1 40

say ''; say '---'; say ''
say '## C7 — the two security controls'
defof '`_run_output_safety_gate` — MODULE-LEVEL; `regenerate` is a ZERO-ARG CALLABLE it invokes' src/services/agent.py _run_output_safety_gate 24
grepn '`SAFETY_RETRY_NOTICE` and the gate call sites' 'SAFETY_RETRY_NOTICE|_run_output_safety_gate\(' src/services/agent.py
defof '`SlideGeneratorAgent._format_slide_context` — a METHOD (class is SlideGeneratorAgent, NOT SlideAgent)' src/services/agent.py _format_slide_context 48
grepn 'Its two call sites' '_format_slide_context\(' src/services/agent.py
defof '`spotlight` — neutralises embedded delimiters and applies cap_tool_output' src/utils/spotlight.py spotlight 40
whole '`text_caps.py` — the 32 KB cap and the exact truncation suffix' src/utils/text_caps.py
grepn 'The scanner both the export path and the gate use' 'scan_html_for_unsafe_patterns' src/services/agent.py src/api/routes/export.py src/services/streaming_callback.py src/utils/*.py
grepn 'export.py:159 concatenates html + scripts into ONE string for the scanner' 'deck_scripts|scripts_html|scan_html_for_unsafe_patterns' src/api/routes/export.py
say ''; say '### The 13 test files referencing src.services.agent — NONE move (13 measured, .py only)'
say ''
say '```'
grep -rln 'src\.services\.agent\b' tests/ --include="*.py" | sort >> $OUT
say '```'
grepn 'The three named security suites — test counts' 'def test_' tests/unit/test_agent_safety_gate.py tests/unit/test_safety_gate_http.py tests/unit/test_slide_context_injection.py

say ''; say '---'; say ''
say '## C9 — the prose sources (R2: COPY, never modify or compose from prompt_modules)'
grepn 'Every module-level constant in prompt_modules.py' '^[A-Z_][A-Z_0-9]* = ' src/core/prompt_modules.py
region '`UNTRUSTED_DATA_NOTICE` — the one constant that is IMPORTED, not copied (R2 exception)' src/core/prompt_modules.py 34 48
grepn 'UNTRUSTED_DATA_NOTICE definition (it is a constant, not a def)' 'UNTRUSTED_DATA_NOTICE' src/core/prompt_modules.py
grepn 'The 1280x720 / 88px / 72px / 56px literals in prompt_modules — the fixer must NOT copy them' '1280x720|88px|72px|56px' src/core/prompt_modules.py
grepn 'The nine criteria names, for the generated build_reviewer criteria block' '^    "[a-z_]+": FindingCriterion|^        objective=|^        level=|^        category=' src/domain/finding.py

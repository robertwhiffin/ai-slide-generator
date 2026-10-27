"""Prompt contract: the architect returns the revised DeckSpec on an edit.

The builder is briefed only from the persisted SlideSpec, never from the user's
message, so an edit that omits ``deck_spec`` loses the requested change.  Task 1
made ``architect_node`` refuse such an edit (``edit_without_revised_spec``); the
output schema was deliberately NOT changed (its source is hashed into the frozen
schema-contract digest).  This file pins what the v1 prompt must now say, that
the promoted manifest carries exactly that prompt, and that nothing else in the
packaged release moved.

Every literal below is a HEAD (d3f150799) value copied by hand — do not import
them from the code under test.
"""

from __future__ import annotations

import hashlib
import re

import pytest

import src.core.database  # noqa: F401  (must be imported before other src.* modules)
from src.core.skills.architect import INSTRUCTIONS
from src.services.agent_schema_registry import (
    _V1_DIGESTS,
    _V2_DIGESTS,
    AgentSchemaRegistry,
)
from src.services.graph_definition_manifest import (
    definition_content_hash,
    load_graph_v1_manifest,
)

# --- HEAD literals -----------------------------------------------------------

# Pins updated for the endpoint switch to system.ai Gateway models, then for the
# deck-parity architect and builder prompts, then for #313 slide references,
# then for #314 add a slide, then for the claude-opus-5 -> claude-opus-5-5 seed move.
HEAD_ARCHITECT_CONTENT_HASH = "2311ded0e960e433e58f3ae83ce460175e85027b77e89a0732b6ade25dac96e9"

# Architect definition hash with prompt_text blanked: pins every non-prompt field
# (model, overlay, assembly rules, protected assembly, schema contract).
HEAD_ARCHITECT_HASH_WITHOUT_PROMPT = (
    "45a2ee67941b4409528b2bf4a7e81e6e690948d093735bf8f00a63e754626852"
)

HEAD_OTHER_ROLE_CONTENT_HASHES = {
    "data_analyst": "5fd364e1936f58582a43eba1ef74a88166d698db644ff0b9562f3728f36210b2",
    "builder": "181a982b59e11d30fff55c1379d8359db4890064ed59b0a16f618e9a5e034455",
    "build_reviewer": "0a8f6a7c6ef13c1acd89960f44a0eaa57ea2e7b1074a1ec191654229d268461f",
    "fixer": "8342438644d4665e929d7fdbd694d0024e401546ae06a9566161b309adb4c82a",
    "fix_reviewer": "ff14c8e8b1622482f675f726eaeb10db2618b28afdce9598f1a6198ce36f04c0",
    "deck_reviewer": "7f015a2cb032f3d528ec9e5391e79ec21d7fe77514dcf33855734571c0bced1b",
}

HEAD_V1_SCHEMA_DIGESTS = {
    "architect": "9704af4e9213f942104f449f09b66e41461cc774c7bfdd47e8c86a25b53b6285",
    "data_analyst": "610545fe1d094f2544a5c602c2ebb45f542b813bf47e347e96ba7e22a6bfc281",
    "builder": "fc4bd6a9020b228a79cc0d933066478225947605916e05bd6f44ba7eccc82387",
    "build_reviewer": "50963d37738f8c97b12caa7688d282d3174a1e0c5e3606c8ec7a73c5ae50c70d",
    "fixer": "7a4e984c602d16ea73c2f5f3f26ac385c440527001fa14b1cfb5c1245de12297",
    "fix_reviewer": "31ff0a6d02cefb7db4cd2c499b4e7905fdadcda789c658e1c7605cdde01020df",
    "deck_reviewer": "56c7ce141e07a70fc2c57f614e915ebb9e3914d24b3c11057401c4cc1c637467",
}

HEAD_V2_SCHEMA_DIGESTS = {
    "architect": "39ed9e91b3640ded4f2859c074db3d6a8f24c14dff49f7011e590b7473956da9",
    "data_analyst": "0543006dd98d1d84dc72c1f9b918a97daa93a3020d31e3557b2af8a91715b6c5",
    "builder": "65f29cb9774f96f131dba7dfe48ff04b8775dc0960f95a3c6efc19f326ba6aad",
    "build_reviewer": "20f69d5e65e0b94d4401b0645d16f8b238acd8b4571f9ce184b9d7d9956fc6b1",
    "fixer": "a77a9896705534109179e75a542eec212dbb25fd78582dff256d6b6c976a6143",
    "fix_reviewer": "bbe6bf025d5c2e5dcbe1c23db029caff425890602f7e3819c6472c46e7fdfd99",
    "deck_reviewer": "c466043b24678ceef8c80d3707f7e80672275415a8b1c0e4385f94bfea7104d3",
}

# sha256 of the "\n\n"-separated INSTRUCTIONS blocks that must stay byte-identical:
# opening line, INTENT CLASSIFICATION, DESIGN SYSTEMS (the contract-switch rule),
# closing line.  Recompute from `git show d3f150799:src/core/skills/architect.py`.
# SLIDESPEC FIELDS is deliberately NOT here any more: Task 5 adds `slide_type` and
# `template_section_index` to it, so its block hash changes.  It is pinned instead by
# HEAD_SLIDESPEC_FIELD_LINES (old lines survive) + HEAD_SLIDESPEC_FIELDS_BLOCK_HASH (retired).
HEAD_UNCHANGED_BLOCK_HASHES = {
    "opening": "345a85e933fd76a597e00695029c5098e9de1534574c258d01689bcf36532034",
    "intent_classification": "dccff17eb03ebe5c411b07ec48cc8594aba6a617fc16288f1c9229550cd7d500",
    "design_systems": "10d09b732446c3e369f99a664e999a4af69018b3e47becf5fa5d0e190dc15345",
    "closing": "4b4000313dfac2e346b4b524a6dab465eca1d9316b227e0374c17d1517e54d7b",
}

# The pre-Task-5 SLIDESPEC FIELDS block.  It must no longer appear verbatim.
HEAD_SLIDESPEC_FIELDS_BLOCK_HASH = (
    "5f488349a428a8ac5cf4adbd9b8df18cea77d5b5c010c237d0f853b1c5537653"
)

# The pre-Task-5 field lines; each must survive inside the (changed) block.
HEAD_SLIDESPEC_FIELD_LINES = (
    "  position: 0-indexed integer, unique within the deck",
    "  purpose: what this slide contributes to the narrative arc",
    "  content_brief: one sentence — what the slide must show",
    "  assumes: what the audience already knows when they reach this slide",
    "  hands_off: the single takeaway the audience should leave with",
    "  data_references: metric names or identifiers this slide depends on "
    "(empty list if the slide needs no data)",
)

# PAYLOAD RULES lines for the other intents, unchanged.
HEAD_UNCHANGED_PAYLOAD_LINES = (
    "  build                  → deck_spec must be set",
    "  ask_data               → data_request must be set",
    "  confirm_design_contract → proposed_design_contract must be set; "
    "never set deck_spec until the user confirms",
    "  discuss                → message only; no payload required",
)

# DECKSPEC CONSTRUCTION field lines, unchanged (only the heading changes).
HEAD_DECKSPEC_FIELD_LINES = (
    "  title: a short, specific noun phrase for the deck\n"
    "  audience: who will read it\n"
    "  purpose: what decision or action the deck should drive\n"
    "  argument: the single overarching claim the deck makes\n"
    "  call_to_action: the concrete next step for the audience\n"
    "  narrative_arc: ordered list of 3-5 beats (opening → evidence → conclusion)\n"
    "  slides: one SlideSpec per slide, in presentation order"
)

# --- Pinned phrases the new prompt must contain (whitespace- and case-normalised)

EDIT_PAYLOAD_PHRASES = (
    "target_positions must be a non-empty list",
    "deck_spec must be set",
)
EDIT_WITHOUT_SPEC_PHRASE = "an edit without deck_spec cannot be applied"
DECKSPEC_HEADING = "DECKSPEC CONSTRUCTION (build and edit intents):"
EDITING_RULE_PHRASES = (
    "start from current_deck_spec",
    "return it in full",
    "revise only what the user asked for on the target slides",
    "keep every slide's position and every other slide unchanged",
    "change deck-level fields only when the user asks",
    # #314 retired "adding or removing slides is not an edit": adding is now an edit
    # (Task 11 property 1), and only removing or reordering stays discuss (property 6).
    "adding one or more new slides to an existing deck is an edit",
    "removing or reordering slides is not an edit",
)
# Review F1/F2 (controller ruling): an edit never silently restyles — the node treats
# a changed design_contract on an edit as an answered confirmation and rebuilds every
# slide — and a remove/reorder request has a named path instead of a dead end.
EDITING_GUARD_PHRASES = (
    "keep design_contract unchanged on an edit",
    # ...but the turn that APPLIES an agreed proposal is itself an edit carrying the new
    # contract (test_deck_spec_change_turn.py), so the rule must not forbid that turn.
    "unless the user has agreed to the contract you proposed with confirm_design_contract",
    "a change of design system or slide style still goes through confirm_design_contract",
    "keep resolved_data unchanged unless new data has been fetched for this edit",
    "if the user asks for that, use discuss and explain that it cannot be applied as an edit",
)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _architect_definition():
    manifest = load_graph_v1_manifest()
    return next(d for d in manifest.definitions if d.agent_key == "architect")


def _payload_rules_block(prompt: str) -> str:
    blocks = [b for b in prompt.split("\n\n") if b.startswith("PAYLOAD RULES")]
    assert len(blocks) == 1, "expected exactly one PAYLOAD RULES block"
    return blocks[0]


def _editing_block(prompt: str) -> str:
    blocks = [b for b in prompt.split("\n\n") if b.startswith("EDITING")]
    assert len(blocks) == 1, "expected exactly one EDITING block"
    return blocks[0]


def _edit_payload_line(prompt: str) -> str:
    lines = [
        line
        for line in _payload_rules_block(prompt).splitlines()
        if re.match(r"^\s*edit\s+→", line)
    ]
    assert len(lines) == 1, "expected exactly one `edit →` line in PAYLOAD RULES"
    return lines[0]


# --- The model sees the new prompt -------------------------------------------


def test_manifest_architect_prompt_is_the_skill_instructions():
    assert _architect_definition().prompt_text == INSTRUCTIONS


def test_edit_payload_rule_requires_deck_spec():
    line = _edit_payload_line(INSTRUCTIONS)
    for phrase in EDIT_PAYLOAD_PHRASES:
        assert phrase in _norm(line), f"edit payload line lacks {phrase!r}: {line!r}"


def test_prompt_says_an_edit_without_deck_spec_cannot_be_applied():
    assert EDIT_WITHOUT_SPEC_PHRASE in _norm(INSTRUCTIONS)


def test_payload_rules_do_not_claim_schema_rejects_a_spec_less_edit():
    # The edit deck_spec rule is enforced in architect_node, not by ArchitectOutput,
    # so no line in PAYLOAD RULES may say the schema enforces/rejects these rules.
    for line in _payload_rules_block(INSTRUCTIONS).splitlines():
        lowered = line.lower()
        assert "reject" not in lowered, f"false schema-rejection claim: {line!r}"
        assert "enforced by the output schema" not in lowered, (
            f"false schema-enforcement claim: {line!r}"
        )


def test_deckspec_heading_covers_build_and_edit():
    assert "build intent only" not in INSTRUCTIONS
    assert f"{DECKSPEC_HEADING}\n{HEAD_DECKSPEC_FIELD_LINES}" in INSTRUCTIONS


def test_prompt_states_the_editing_rule():
    text = _norm(INSTRUCTIONS)
    missing = [p for p in EDITING_RULE_PHRASES if p not in text]
    assert not missing, f"editing rule phrases missing: {missing}"


@pytest.mark.parametrize("phrase", EDITING_GUARD_PHRASES)
def test_editing_rule_keeps_contract_and_names_the_remove_reorder_path(phrase):
    assert phrase in _norm(_editing_block(INSTRUCTIONS)), f"EDITING block lacks {phrase!r}"


def test_prompt_no_longer_says_adding_a_slide_is_not_an_edit():
    # #314: the retired sentence would contradict "adding ... is an edit" above.
    assert not re.search(r"\badd(ing|s|ed)?\b[^.:;]{0,60}\bnot an edit\b", _plain(INSTRUCTIONS)), (
        "the prompt still says adding slides is not an edit"
    )


def test_unchanged_parts_of_the_prompt_are_byte_identical():
    block_hashes = {hashlib.sha256(b.encode()).hexdigest() for b in INSTRUCTIONS.split("\n\n")}
    missing = [name for name, h in HEAD_UNCHANGED_BLOCK_HASHES.items() if h not in block_hashes]
    assert not missing, f"blocks changed or re-wrapped: {missing}"
    payload = _payload_rules_block(INSTRUCTIONS).splitlines()
    for line in HEAD_UNCHANGED_PAYLOAD_LINES:
        assert line in payload, f"payload line changed: {line!r}"


# --- Nothing else in the release moved ---------------------------------------


def test_schema_contract_digests_unchanged():
    AgentSchemaRegistry()  # fails closed if any calculated digest drifted
    assert dict(_V1_DIGESTS) == HEAD_V1_SCHEMA_DIGESTS
    assert dict(_V2_DIGESTS) == HEAD_V2_SCHEMA_DIGESTS
    assert _architect_definition().schema_contract.digest == HEAD_V1_SCHEMA_DIGESTS["architect"]


def test_other_roles_definitions_unchanged():
    manifest = load_graph_v1_manifest()
    actual = {
        d.agent_key: definition_content_hash(d)
        for d in manifest.definitions
        if d.agent_key != "architect"
    }
    assert actual == HEAD_OTHER_ROLE_CONTENT_HASHES


def test_architect_definition_changed_only_in_prompt_text():
    # After endpoint switch to system.ai Gateway models, this test verifies that
    # only the endpoint and prompt changed, not other model fields or schema.
    architect = _architect_definition()
    # Verify the prompt is the current skill instructions
    assert architect.prompt_text == INSTRUCTIONS
    # Verify model configuration (other than endpoint) is as expected
    assert architect.model.temperature == 0.7
    assert architect.model.max_tokens == 60000
    assert architect.model.top_p == 0.95
    # Verify blanked hash matches the endpoint-switched value
    blanked = architect.model_copy(update={"prompt_text": ""})
    assert definition_content_hash(blanked) == HEAD_ARCHITECT_HASH_WITHOUT_PROMPT


# --- Task 5: slide-type binding (template_sections, the pair, 1-indexed message) ----
#
# Spec: docs/superpowers/specs/2026-10-13-architect-slide-type-design.md
# These pin phrases, not exact wording: each check is a regex over the whitespace-,
# case- and backtick-normalised block, so the implementer may reword freely as long as
# the instruction is still there.

BINDING_HEADING = "VISUAL / TEMPLATE BINDING"
PAYLOAD_KEY = "template_sections"


def _plain(text: str) -> str:
    """Normalised text with markdown backticks removed."""
    return _norm(text.replace("`", ""))


def _slidespec_fields_block(prompt: str) -> str:
    blocks = [b for b in prompt.split("\n\n") if b.startswith("SLIDESPEC FIELDS")]
    assert len(blocks) == 1, "expected exactly one SLIDESPEC FIELDS block"
    return blocks[0]


def _binding_block(prompt: str) -> str:
    blocks = [b for b in prompt.split("\n\n") if b.startswith(BINDING_HEADING)]
    assert len(blocks) == 1, f"expected exactly one {BINDING_HEADING!r} block, found {len(blocks)}"
    return blocks[0]


def _field_line(block: str, name: str) -> str:
    lines = [ln for ln in block.splitlines() if re.match(rf"^\s*{name}:", ln)]
    assert len(lines) == 1, f"expected exactly one `{name}:` line in SLIDESPEC FIELDS"
    return lines[0]


def test_slidespec_fields_block_changed_but_keeps_every_existing_field_line():
    block_hashes = {hashlib.sha256(b.encode()).hexdigest() for b in INSTRUCTIONS.split("\n\n")}
    assert HEAD_SLIDESPEC_FIELDS_BLOCK_HASH not in block_hashes, (
        "SLIDESPEC FIELDS is still the pre-Task-5 block: it must now list the pair"
    )
    block = _slidespec_fields_block(INSTRUCTIONS)
    for line in HEAD_SLIDESPEC_FIELD_LINES:
        assert line in block, f"existing SLIDESPEC field line lost or reworded: {line!r}"


def test_slidespec_fields_list_slide_type_and_template_section_index():
    block = _slidespec_fields_block(INSTRUCTIONS)
    slide_type = _plain(_field_line(block, "slide_type"))
    index = _plain(_field_line(block, "template_section_index"))
    # slide_type: exact data-label copied from one template_sections entry, or null
    assert "data-label" in slide_type, slide_type
    assert PAYLOAD_KEY in slide_type, slide_type
    assert "null" in slide_type, slide_type
    # template_section_index: that entry's index, or null
    assert re.search(r"entry'?s? `?index|index of", index), index
    assert "null" in index, index


def test_prompt_names_the_template_sections_payload_key():
    assert PAYLOAD_KEY in INSTRUCTIONS
    block = _plain(_binding_block(INSTRUCTIONS))
    assert re.search(rf"payload[^.]{{0,40}}{PAYLOAD_KEY}", block), (
        "binding block must say the payload carries template_sections"
    )


# Each entry: (description, regex over the plain binding block).
BINDING_RULES = (
    ("choose only from the supplied entries", r"choose only from"),
    ("copy label into slide_type", r"label[^.]{0,80}slide_type"),
    ("copy index into template_section_index", r"index[^.]{0,80}template_section_index"),
    (
        "no fit => both fields null",
        r"(no (supplied )?(entry|section|type)[^.]{0,30}fits?|none (of them )?fits?|if none fit)"
        r"[^.]{0,80}both[^.]{0,30}null",
    ),
    (
        "empty or absent list => both null",
        r"(empty[^.]{0,30}absent|absent[^.]{0,30}empty)[^.]{0,80}both[^.]{0,30}null",
    ),
    (
        # #314: an inserted slide's binding.  Same one-sentence ([^.]) rule as below.
        "an entry whose label is null cannot be bound => both null",
        r"(\blabel\b[^.]{0,10}\bis null\b|\bnull label\b)[^.]{0,20}"
        r"\b(cannot|can't|must not|is never)\b[^.]{0,10}\b(be )?bound\b[^.]{0,100}"
        r"\bboth\b[^.]{0,30}\bnull\b",
    ),
    ("never invent a type", r"(never|do not|don't) invent"),
    (
        "never complain the list was not supplied when the key is present",
        r"(never|do not|don't) (complain|claim|say|state)[^.]{0,80}not supplied",
    ),
    (
        "committing a design system picks a template_id from the library",
        r"template_id[^.]{0,120}library|library[^.]{0,120}template_id",
    ),
    ("empty template => empty list", r"(empty|unset|no) template[^.]{0,60}empty"),
    ("content_brief names the exhibit", r"content_brief[^.]{0,80}exhibit"),
    (
        "brand furniture comes from the selected section's markup",
        r"furniture[^.]{0,120}(selected|bound|chosen) section|"
        r"(selected|bound|chosen) section[^.]{0,120}furniture",
    ),
    ("style assets are identity, not evidence", r"identity,? not evidence"),
    (
        "do not plan exhibits onto missing data; prefer ask_data",
        r"(never|do not|don't) plan exhibits[^.]{0,80}missing data[^.]{0,80}ask_data|"
        r"ask_data[^.]{0,80}missing data|missing data[^.]{0,120}ask_data",
    ),
)


@pytest.mark.parametrize(
    ("description", "pattern"), BINDING_RULES, ids=[d for d, _ in BINDING_RULES]
)
def test_binding_block_states_rule(description, pattern):
    block = _plain(_binding_block(INSTRUCTIONS))
    assert re.search(pattern, block), f"VISUAL / TEMPLATE BINDING lacks: {description}"


def test_message_is_one_indexed_but_positions_stay_zero_indexed():
    text = _plain(INSTRUCTIONS)
    assert re.search(r"\bmessage\b[^.]{0,80}\b1-indexed|\b1-indexed[^.]{0,80}\bmessage\b", text), (
        "prompt must tell the architect to speak 1-indexed in `message`"
    )
    assert re.search(
        r"target_positions[^.]{0,80}\b0-indexed|\b0-indexed[^.]{0,80}target_positions", text
    ), "prompt must say position / target_positions stay 0-indexed"
    assert re.search(r"\bonly\b[^.]{0,40}\bmessage\b|\bmessage\b[^.]{0,40}\bonly\b", text), (
        "the 1-indexed convention applies in `message` only"
    )


# Every one of these is the defect the spec drops: a rule that forces a binding on each
# slide of a templated deck, or that tells the model to complain when it has no list.
FORBIDDEN_BINDING_PATTERNS = (
    r"every\b[^.]{0,60}template_section_index[^.]{0,40}(must|non-null|not null|set|populated)",
    r"template_section_index[^.]{0,40}must (be )?(non-null|not null|set|populated)",
    r"every (templated )?slide (must|should|needs? to) (have|carry|be bound|bind)",
    r"\bnon-null\b",
    r"complain in `?message",
    r"complain in message",
)


@pytest.mark.parametrize("pattern", FORBIDDEN_BINDING_PATTERNS)
def test_prompt_does_not_require_every_templated_slide_to_be_bound(pattern):
    # Anchor to the new block first so this cannot pass vacuously on the pre-Task-5 prompt.
    _binding_block(INSTRUCTIONS)
    assert not re.search(pattern, _plain(INSTRUCTIONS)), (
        f"prompt forces a binding / complaint (spec drops this): /{pattern}/"
    )


def test_binding_block_allows_a_slide_to_stay_unbound():
    block = _plain(_binding_block(INSTRUCTIONS))
    assert re.search(r"both[^.]{0,30}null", block), (
        "binding block must state the pair is either fully populated or fully null"
    )


# --- #313: SLIDE NUMBERS points at the resolved slide numbers ------------------------
#
# architect_node now puts two keys in the model payload (src/domain/slide_numbering.py):
# `slide_numbering`, [{slide_number, position}] for the current deck, and
# `slide_references`, the slides the user's latest message names, already resolved to
# positions, with numbers the deck lacks reported in `out_of_range` (never clamped).
# The SLIDE NUMBERS block must send the architect to them instead of "number - 1".
# Same style as BINDING_RULES: a regex per instruction over the plain block, so the
# wording may change as long as each instruction is still there.  Each regex is kept
# to one sentence ([^.]), so deleting a sentence turns only its own rules red.

SLIDE_NUMBERS_HEADING = "SLIDE NUMBERS"

# "unresolved", "not resolved", "does not resolve", "doesn't resolve", "fails to resolve".
_UNRESOLVED = (
    r"(\bunresolved\b|\bnot (been )?resolved?\b|n't (been )?resolved?\b|\bfails? to resolve\b)"
)
# "do not edit", "is not edited", "never edit", "not an edit", "no edit".
_NOT_EDIT = r"(\bnot\b|n't\b|\bnever\b|\bno\b)[^.]{0,20}\bedit(ed|s)?\b"
_NOT_EDIT_AND_DISCUSS = rf"({_NOT_EDIT}[^.]{{0,80}}\bdiscuss\b|\bdiscuss\b[^.]{{0,80}}{_NOT_EDIT})"


def _slide_numbers_block(prompt: str) -> str:
    blocks = [b for b in prompt.split("\n\n") if b.startswith(SLIDE_NUMBERS_HEADING)]
    assert len(blocks) == 1, (
        f"expected exactly one {SLIDE_NUMBERS_HEADING!r} block, found {len(blocks)}"
    )
    return blocks[0]


# Each entry: (description, regex over the plain SLIDE NUMBERS block).
SLIDE_NUMBERS_RULES = (
    (
        "slide_numbering maps each slide_number to its position",
        r"slide_numbering\b[^.]{0,80}\b(slide_)?numbers?\b[^.]{0,40}\bpositions?\b|"
        r"slide_numbering\b[^.]{0,80}\bpositions?\b[^.]{0,40}\b(slide_)?numbers?\b",
    ),
    (
        "slide_references holds the slides the message names, already resolved",
        r"slide_references\b[^.]{0,100}\b(message|turn|request)\b[^.]{0,80}\bresolved\b",
    ),
    (
        "target_positions come from slide_references when the phrase was resolved",
        r"target_positions\b[^.]{0,60}slide_references\b[^.]{0,80}\bresolved\b|"
        r"\bresolved\b[^.]{0,80}slide_references\b[^.]{0,80}target_positions|"
        r"slide_references\b[^.]{0,80}\bresolved\b[^.]{0,80}target_positions",
    ),
    (
        "a number or ordinal that does not resolve is looked up in slide_numbering",
        rf"{_UNRESOLVED}[^.]{{0,80}}slide_numbering|slide_numbering\b[^.]{{0,80}}{_UNRESOLVED}",
    ),
    (
        "never compute a position as the number minus one",
        r"(\bnever\b|\bdo not\b|\bdon't\b|\bmust not\b)[^.]{0,80}"
        r"(\bminus (one|1)\b|number ?[−-] ?1\b|\bsubtract(ing)? (one|1)\b)",
    ),
    (
        "an out_of_range reference is not edited, use discuss",
        rf"out_of_range\b[^.]{{0,160}}{_NOT_EDIT_AND_DISCUSS}|"
        rf"{_NOT_EDIT_AND_DISCUSS}[^.]{{0,160}}out_of_range",
    ),
    (
        "naming a slide is not by itself a request to change it",
        r"\b(referenc\w*|nam(e|es|ed|ing)|mention\w*)\b[^.]{0,80}"
        r"(\bnot that\b[^.]{0,40}\b(chang|edit)\w*|"
        r"(\bnot\b|n't\b|\bnever\b)[^.]{0,30}"
        r"\b(make|makes|mean|means|imply|implies|ask|asks|request|requests)\b"
        r"[^.]{0,40}\b(chang|edit)\w*)",
    ),
    (
        "the intent is decided from what the user asks for",
        r"\b(intent|classif\w*)\b[^.]{0,60}"
        r"(\bwhat (the user|they) (actually )?(asks?|wants?|requests?)\b|"
        r"\buser's (actual )?(request|ask|words)\b)",
    ),
)


@pytest.mark.parametrize(
    ("description", "pattern"), SLIDE_NUMBERS_RULES, ids=[d for d, _ in SLIDE_NUMBERS_RULES]
)
def test_slide_numbers_block_states_rule(description, pattern):
    block = _plain(_slide_numbers_block(INSTRUCTIONS))
    assert re.search(pattern, block), f"SLIDE NUMBERS lacks: {description}"


# --- #314: adding a slide to an existing deck is an edit ------------------------------
#
# The EDITING block says where a new slide goes and what the rest of the deck keeps;
# SLIDE NUMBERS says a slide named on an add is the new slide's anchor, read against
# the deck before the insert.  One regex per instruction of Task 11's properties 2-5
# and 7, over the plain block that carries it.  Properties 1 and 6 are the phrase pins
# in EDITING_RULE_PHRASES.  Each regex is kept to one sentence ([^.]), so deleting a
# sentence turns only its own rules red.

_DO_NOT = r"(\bdo not\b|\bdon't\b|\bnever\b)"
_NAMED = r"(named slide|anchor)"

# Each entry: (description, block heading, regex over the plain block).
INSERTION_RULES = (
    (
        "property 2: each new slide goes where the user asks",
        "EDITING",
        r"\b(put|place|insert)s?\b[^.]{0,20}\bnew slides?\b[^.]{0,20}"
        r"\bwhere the user (asks|says|wants|requests)\b",
    ),
    (
        "property 2: with no stated place, before the closing slides unless it closes",
        "EDITING",
        r"(\bno (stated )?place\b|(\bnot\b|n't\b) (say|state|give)s? where\b)[^.]{0,120}"
        r"\bbefore\b[^.]{0,40}\bclos\w*[^.]{0,120}\bunless\b[^.]{0,40}\bitself\b[^.]{0,20}"
        r"\bclosing\b",
    ),
    (
        "property 2: asked to come last, after the last slide even after a closing one",
        "EDITING",
        r"\b(last|at the end)\b[^.]{0,60}\bafter the last slide\b[^.]{0,40}\beven after\b"
        r"[^.]{0,20}\bclosing\b",
    ),
    (
        "property 2: message says where the new slide went",
        "EDITING",
        r"\bmessage\b[^.]{0,40}\bwhere\b[^.]{0,30}\bnew slide\b[^.]{0,10}"
        r"\b(went|goes|is|landed)\b",
    ),
    (
        "property 3: slide numbers are read against slide_numbering, the deck before the insert",
        "SLIDE NUMBERS",
        r"slide_numbering\b[^.]{0,60}\bbefore\b[^.]{0,30}\b(new slide|insert\w*)|"
        r"\bbefore\b[^.]{0,30}\b(new slide|insert\w*)[^.]{0,60}slide_numbering\b",
    ),
    (
        "property 4: every slide after the new one keeps every field; only its position goes up",
        "EDITING",
        r"\b(every|each) slide after (it|the new (slide|one))\b[^.]{0,40}"
        r"\b(every field|unchanged|exactly)\b[^.]{0,200}\bonly\b[^.]{0,10}\bposition\b"
        r"[^.]{0,20}\b(goes up|increases|rises|moves up)\b[^.]{0,10}\bby one\b",
    ),
    (
        "property 4: no other slide and no deck-level field changes unless the user asks",
        "EDITING",
        rf"{_DO_NOT}[^.]{{0,10}}\bchange\b[^.]{{0,10}}\b(any )?other slides?\b[^.]{{0,240}}"
        r"\bdeck-level fields?\b[^.]{0,60}\bunless\b[^.]{0,20}\buser asks\b",
    ),
    (
        "property 5: target_positions are the new and changed slides' returned positions",
        "EDITING",
        r"target_positions\b[^.]{0,40}\bpositions?\b[^.]{0,20}\b(in|of) the (returned|revised) "
        r"deck_spec\b[^.]{0,40}\b(every|each|the) new slides?\b[^.]{0,60}\basked to change\b",
    ),
    (
        "property 5: a named slide also asked to change is a target at its returned position",
        "SLIDE NUMBERS",
        r"\bnamed slide\b[^.]{0,40}\b(asks?|asked|wants?) to change\b[^.]{0,40}\btarget\b"
        r"[^.]{0,60}\b(returned|revised) deck_spec\b",
    ),
    (
        "property 7: an add is the exception to taking target_positions from slide_references",
        "SLIDE NUMBERS",
        r"\bexception\b[^.]{0,60}target_positions\b[^.]{0,30}slide_references\b[^.]{0,60}"
        r"\badd\w*\b",
    ),
    (
        "property 7: the slide named to place the new one is its anchor, not a target",
        "SLIDE NUMBERS",
        r"\b(names?|named|naming|referenc\w*|mention\w*)\b[^.]{0,80}\banchor\b[^.]{0,20}"
        r"\bnot (a |the )?targets?\b",
    ),
    (
        "property 7: placed after the anchor, the new slide takes the position after it",
        "SLIDE NUMBERS",
        rf"\b(after|following) the {_NAMED}\b[^.]{{0,30}}\btakes?\b[^.]{{0,20}}"
        rf"\bposition after (it|the {_NAMED})\b",
    ),
    (
        "property 7: placed before the anchor, it takes the anchor's position; the anchor moves up",
        "SLIDE NUMBERS",
        rf"\bbefore the {_NAMED}\b[^.]{{0,80}}\btakes?\b[^.]{{0,10}}\bthe {_NAMED}'s position\b"
        rf"[^.]{{0,60}}\b{_NAMED}\b[^.]{{0,10}}\bmoves? up by one\b",
    ),
)

_INSERTION_BLOCKS = {"EDITING": _editing_block, "SLIDE NUMBERS": _slide_numbers_block}


@pytest.mark.parametrize(
    ("description", "heading", "pattern"),
    INSERTION_RULES,
    ids=[d for d, _, _ in INSERTION_RULES],
)
def test_insertion_rule_is_stated(description, heading, pattern):
    block = _plain(_INSERTION_BLOCKS[heading](INSTRUCTIONS))
    assert re.search(pattern, block), f"{heading} lacks: {description}"

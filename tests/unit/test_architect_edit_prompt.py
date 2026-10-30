"""Prompt contract: the architect's v1 prompt, and what an edit must return.

History: an edit first had to return the full revised ``deck_spec`` (the builder
is briefed only from the persisted SlideSpec); #314 made adding a slide an edit.
Architect edit operations (2026-10-28) replaces that: an edit now returns an
ordered ``operations`` list (insert / update / delete / replace / move) plus an
optional ``deck_changes``, which ``architect_node`` composes over the persisted
spec, and deleting and moving slides are edits.  Only a re-description of the
deck as it stands (the arc-review sweeper) still returns the full ``deck_spec``.

This file pins what the v1 prompt must say, that the promoted manifest carries
exactly that prompt, and that nothing else in the packaged release moved.  The
EDITING phrase pins are taken from the promoted prompt's own sentences
(``evals/configs/architect/edit-ops.md``, then its follow-up ``edit-ops-b.md``, both
measured in ``evals/README.md``).

Every literal below is a HEAD value copied by hand — do not import them from the
code under test.
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
# then for #314 add a slide, then for the claude-opus-5 -> claude-opus-5-5 seed move,
# then for the architect edit operations schema-contract re-pin, then for the
# promoted edit-operations prompt (evals/configs/architect/edit-ops.yaml), then for
# its follow-up tweaks (evals/configs/architect/edit-ops-b.yaml).
HEAD_ARCHITECT_CONTENT_HASH = "3da09952e7751cd967c3cee11b77628c51565e37fa1b75c1c6e9f92a92d3126b"

# Architect definition hash with prompt_text blanked: pins every non-prompt field
# (model, overlay, assembly rules, protected assembly, schema contract).
# Re-pinned for the architect edit operations schema-contract digest.
HEAD_ARCHITECT_HASH_WITHOUT_PROMPT = (
    "ec17918b9c66a86133c060c15c37b88a2139831bc910e8787ce3ef9a069d52d9"
)

HEAD_OTHER_ROLE_CONTENT_HASHES = {
    "data_analyst": "5fd364e1936f58582a43eba1ef74a88166d698db644ff0b9562f3728f36210b2",
    "builder": "025f6a714ecd88ce68f7ba289f0fdc302298ab4ed66d456a7fcae45f46ca5f7d",
    "build_reviewer": "0a8f6a7c6ef13c1acd89960f44a0eaa57ea2e7b1074a1ec191654229d268461f",
    "fixer": "8342438644d4665e929d7fdbd694d0024e401546ae06a9566161b309adb4c82a",
    "fix_reviewer": "ff14c8e8b1622482f675f726eaeb10db2618b28afdce9598f1a6198ce36f04c0",
    "deck_reviewer": "7f015a2cb032f3d528ec9e5391e79ec21d7fe77514dcf33855734571c0bced1b",
}

HEAD_V1_SCHEMA_DIGESTS = {
    "architect": "9f090efe370a30b17779dcae11125b3645cb16153f2ef5c2dd234bf7c5f6970e",
    "data_analyst": "610545fe1d094f2544a5c602c2ebb45f542b813bf47e347e96ba7e22a6bfc281",
    "builder": "fc4bd6a9020b228a79cc0d933066478225947605916e05bd6f44ba7eccc82387",
    "build_reviewer": "50963d37738f8c97b12caa7688d282d3174a1e0c5e3606c8ec7a73c5ae50c70d",
    "fixer": "7a4e984c602d16ea73c2f5f3f26ac385c440527001fa14b1cfb5c1245de12297",
    "fix_reviewer": "31ff0a6d02cefb7db4cd2c499b4e7905fdadcda789c658e1c7605cdde01020df",
    "deck_reviewer": "56c7ce141e07a70fc2c57f614e915ebb9e3914d24b3c11057401c4cc1c637467",
}

HEAD_V2_SCHEMA_DIGESTS = {
    "architect": "9d83be8d41cae5550012e7a32c83f126ce38fb70965c46f749f53c8032102132",
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
    # Re-pinned by the edit-ops follow-up (edit-ops-b): its one sentence on committing a
    # confirmed contract now names both homes (DESIGN_SYSTEMS_CONTRACT_PHRASES); every other
    # byte of the block is unchanged.
    "design_systems": "4e4661d1287817ce62cccee3c556f3622308ec9457c2b070d9cba5ecd8f776bf",
    "closing": "4b4000313dfac2e346b4b524a6dab465eca1d9316b227e0374c17d1517e54d7b",
    # Architect edit operations rewrote only the PAYLOAD RULES edit line and the EDITING
    # and SLIDE NUMBERS blocks; every other block is pinned at its pre-change bytes
    # (recompute from `git show 2b653079:src/core/skills/architect.py`).
    "deckspec_construction": "93b9501662090b81d922ae546fd6fc6ba329861ee8830cc055b77ccc29bfaf02",
    "deck_scale_and_structure": "7ece01e9ffbada7e8273f132640a9c2355177135584273a35f1c56981a45dcdc",
    "vary_the_exhibits": "be654859ee8af4682e4f33380da40ccd3d57b07af10f278287b5064dc47aa0f0",
    "slidespec_fields": "513b1ead3e1e8338b1090fc30f8e7a6145f96d6f9d2e12fdc6ae22d82fb46fcf",
    "visual_template_binding": "15a0f8ff68e3a2cba12c68358dadc90165005b814daafb7f2340c32f7a16171e",
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

# Architect edit operations (C16): the edit line asks for operations / deck_changes and no
# longer for target_positions + deck_spec, except on a re-description of the deck.
EDIT_PAYLOAD_PHRASES = (
    "operations must be set for slide changes",
    "deck_changes for a deck-level change the user asks for",
    "target_positions and deck_spec are not needed",
    "re-describing the deck as it stands returns the full deck_spec",
)
# The retired edit-line rule: an edit had to carry targets and the whole revised spec.
RETIRED_EDIT_PAYLOAD_PHRASES = (
    "target_positions must be a non-empty list",
    "an edit without deck_spec cannot be applied",
)
DECKSPEC_HEADING = "DECKSPEC CONSTRUCTION (build and edit intents):"
# Every phrase is a sentence fragment of the promoted prompt's EDITING block, matched over
# the backtick-free, whitespace- and case-normalised block (_plain).  Grouped by the rule.
EDITING_RULE_PHRASES = (
    # operations replace the whole revised deck_spec, and land as one change
    "on an edit, return operations instead of deck_spec",
    "they are applied together as one change",
    "every position and after_position is a position of current_deck_spec, the deck before "
    "this edit",
    "a slide can be the position of at most one operation",
    # an entry of slides is a SlideContent: no position field
    "each entry of slides is a slidespec without position",
    # update
    "update — position and slides with exactly one entry",
    "changing what a slide says or shows is an update",
    # "rebuild slide N" with no content change (spec §8)
    "rebuilding a slide without changing its content is an update with its current content",
    # replace (expand / split / replace slide N with ...); the first slide keeps the row
    "replace — position and slides with one or more entries: that slide becomes these slides",
    "the first takes its place and the rest follow it directly",
    "expanding a slide into several slides, splitting a slide, or replacing a slide with one "
    "or more new slides is a replace",
    # insert
    "insert — after_position and slides with one or more entries",
    "adding slides is an insert",
    # delete
    "delete — position: that slide is removed, and nothing is rebuilt",
    "removing a slide is a delete",
    # move
    "move — position and after_position: that slide moves to directly after the "
    "after_position slide",
    "it is not rebuilt and its content does not change",
    "reordering slides is a move",
    # -1 = at the start
    "after_position -1 puts them at the start of the deck",
    "(-1 = to the start)",
    # placement rules (spec §2)
    "slides placed after the same slide go directly after it, in the order of their operations",
    "placed after a replaced slide, they follow all of its replacement slides",
    "placed after a moved slide, they follow it to its new place",
    "placed after a deleted slide, they fill its gap",
    "never move a slide after itself",
    # edit-ops follow-up: apply_operations refuses a circle of moves as move_loop
    "moves cannot form a loop: moving slide a after slide b and slide b after slide a in the "
    "same edit, or any longer circle of moves, is refused with a move_loop problem",
    # targets, message, re-description
    "target_positions is not needed on an edit given as operations",
    "name each new or moved slide by its slide number in the revised deck and each deleted "
    "slide by the number it had",
    "when the message asks you to re-describe the deck as it now stands rather than change "
    "it, return the full deck_spec",
)
# Review F1/F2 (controller ruling): an edit never silently restyles — the node treats
# a changed design_contract on an edit as an answered confirmation and rebuilds every
# slide.  Architect edit operations adds: deck-level changes travel in deck_changes and
# only when asked, the edit touches no slide it was not asked about, and a refused
# answer handed back as rejected_edit is fixed and answered again.
EDITING_GUARD_PHRASES = (
    # deck_changes
    "change deck-level fields only when the user asks",
    "put only the changed fields in deck_changes",
    "otherwise leave deck_changes unset",
    "do not change narrative_arc to reflect an added, deleted or moved slide unless the user "
    "asks for that change",
    "keep design_contract unchanged on an edit",
    # ...but the turn that APPLIES an agreed proposal is itself an edit carrying the new
    # contract (test_deck_spec_change_turn.py), so the rule must not forbid that turn.
    "unless the user has agreed to the contract you proposed with confirm_design_contract",
    "commit it in deck_changes.design_contract",
    "a change of design system or slide style still goes through confirm_design_contract",
    "keep resolved_data unchanged unless new data has been fetched for this edit",
    # don't touch other slides
    "touch only the slides the user asks about",
    "every other slide keeps its content exactly, and only its number may change",
    "do not change any other slide to reflect the edit, not a neighbour's assumes or hands_off "
    "and not a slide that lists or sums up the deck, unless the user asks for that change",
    # rejected_edit
    "when the payload carries rejected_edit, your previous answer to this message "
    "(your_previous_answer) was not applied",
    "problems lists every reason it was refused",
    "fix every listed problem and answer again with the whole corrected answer",
)
# The retired remove/reorder dead end (#314 property 6): deleting and moving are edits now.
RETIRED_REFUSAL_PHRASES = (
    "removing or reordering slides is not an edit",
    "if the user asks for that, use discuss and explain that it cannot be applied as an edit",
    "cannot be applied as an edit",
)
# edit-ops follow-up: DESIGN SYSTEMS used to say a confirmed contract is committed only
# "inside deck_spec", while EDITING says deck_changes.design_contract.  The one sentence now
# names both homes, matched over the backtick-free, normalised DESIGN SYSTEMS block (_plain).
DESIGN_SYSTEMS_CONTRACT_PHRASES = (
    "only once the user has agreed may a later turn commit the new contract: inside deck_spec "
    "on a build, or in deck_changes.design_contract on an edit",
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


def test_edit_payload_rule_asks_for_operations():
    line = _edit_payload_line(INSTRUCTIONS)
    for phrase in EDIT_PAYLOAD_PHRASES:
        assert phrase in _norm(line), f"edit payload line lacks {phrase!r}: {line!r}"


def test_prompt_no_longer_requires_targets_and_deck_spec_on_an_edit():
    text = _norm(INSTRUCTIONS)
    for phrase in RETIRED_EDIT_PAYLOAD_PHRASES:
        assert phrase not in text, f"the retired edit rule is still stated: {phrase!r}"


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


@pytest.mark.parametrize("phrase", EDITING_RULE_PHRASES)
def test_prompt_states_the_editing_rule(phrase):
    assert phrase in _plain(_editing_block(INSTRUCTIONS)), f"EDITING block lacks {phrase!r}"


@pytest.mark.parametrize("phrase", EDITING_GUARD_PHRASES)
def test_editing_rule_keeps_contract_and_guards_the_edit(phrase):
    assert phrase in _plain(_editing_block(INSTRUCTIONS)), f"EDITING block lacks {phrase!r}"


@pytest.mark.parametrize("phrase", DESIGN_SYSTEMS_CONTRACT_PHRASES)
def test_design_systems_block_names_both_homes_of_a_confirmed_contract(phrase):
    blocks = [b for b in INSTRUCTIONS.split("\n\n") if b.startswith("DESIGN SYSTEMS")]
    assert len(blocks) == 1, "expected exactly one DESIGN SYSTEMS block"
    assert phrase in _plain(blocks[0]), f"DESIGN SYSTEMS block lacks {phrase!r}"


def test_prompt_no_longer_refuses_delete_or_reorder():
    # Architect edit operations: the #314 dead end ("removing or reordering slides is not
    # an edit ... use discuss") is gone, and nothing else says a delete or move is not one.
    text = _plain(INSTRUCTIONS)
    still = [p for p in RETIRED_REFUSAL_PHRASES if p in text]
    assert not still, f"the prompt still refuses deleting or reordering: {still}"
    # "not an edit" and "never treated as an edit" alike: a reworded refusal is still one.
    assert not re.search(
        r"\b(remov|delet|reorder|mov)\w*\b[^.:;]{0,60}\b(not|never)\b[^.:;]{0,20}\ban edit\b",
        text,
    ), "the prompt still says removing, deleting, reordering or moving slides is not an edit"


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
        # Architect edit operations: an edit's positions are its operations' position and
        # after_position (target_positions is not needed with operations).
        "each operation's position and after_position come from slide_references when "
        "the phrase was resolved",
        r"\bposition and after_position\b[^.]{0,40}slide_references\b[^.]{0,80}\bresolved\b",
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
#
# Architect edit operations re-cut the rows that described a full-spec insert (the
# model renumbering the later slides itself, target_positions in the returned spec, the
# add exception to taking targets from slide_references): an insert is now an operation
# whose after_position counts the deck before the edit, and the code renumbers.  Those
# rows now pin the operations wording of the same property; the rest are unchanged.

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
        # Re-cut (spec §7): the message says what the edit will do, new slides by their
        # number in the revised deck and deleted slides by the number they had.
        "property 2: message names new slides by revised number, deleted ones by old number",
        "EDITING",
        r"\bmessage\b[^.]{0,60}\bnew\b[^.]{0,30}\bslide number in the revised deck\b"
        r"[^.]{0,40}\bdeleted slide\b[^.]{0,30}\bnumber it had\b",
    ),
    (
        # Re-cut: every slide number of an edit, not only an insert's, counts the deck
        # before the edit.
        "property 3: slide numbers are read against slide_numbering, the deck before the edit",
        "SLIDE NUMBERS",
        r"slide_numbering\b[^.]{0,60}\bthe deck before the edit\b",
    ),
    (
        # Re-cut: the model no longer renumbers the later slides; they keep their content
        # and only their number changes.
        "property 4: every slide the edit does not touch keeps its content; only its number moves",
        "EDITING",
        r"\bevery other slide keeps its content exactly\b[^.]{0,40}"
        r"\bonly its number may change\b",
    ),
    (
        "property 4: no other slide changes to reflect the edit unless the user asks",
        "EDITING",
        rf"{_DO_NOT}[^.]{{0,10}}\bchange\b[^.]{{0,10}}\b(any )?other slides?\b[^.]{{0,200}}"
        r"\bunless\b[^.]{0,20}\buser asks\b",
    ),
    (
        "property 4: narrative_arc does not change for an added, deleted or moved slide",
        "EDITING",
        rf"{_DO_NOT}[^.]{{0,10}}\bchange narrative_arc\b[^.]{{0,80}}\bunless\b[^.]{{0,20}}"
        r"\buser asks\b",
    ),
    (
        # Re-cut: the operations say what is built; target_positions is not needed.
        "property 5: target_positions is not needed with operations",
        "EDITING",
        r"\btarget_positions is not needed\b[^.]{0,40}\boperations\b",
    ),
    (
        # Re-cut: a named slide is never renumbered by the model, even after an insert.
        "property 5: positions count the deck before the edit even after an earlier operation",
        "EDITING",
        r"\bposition of current_deck_spec, the deck before this edit\b[^.]{0,40}"
        r"\bearlier operation\b[^.]{0,30}\bshifts\b",
    ),
    (
        "property 7: the slide named to place a new or moved one is its anchor, not a target",
        "SLIDE NUMBERS",
        r"\b(names?|named|naming|referenc\w*|mention\w*)\b[^.]{0,80}\banchor\b[^.]{0,20}"
        r"\bnot (a |the )?(targets?|slide to change)\b",
    ),
    (
        "property 7: placed after the anchor, it takes the anchor's position as after_position",
        "SLIDE NUMBERS",
        rf"\b(after|following) the {_NAMED}\b[^.]{{0,20}}\btakes?\b[^.]{{0,10}}"
        rf"\bthe {_NAMED}'s position as after_position\b",
    ),
    (
        "property 7: placed before the anchor, after_position is the slide before it, or -1",
        "SLIDE NUMBERS",
        rf"\bbefore the {_NAMED}\b[^.]{{0,80}}\btakes?\b[^.]{{0,10}}\bas after_position\b"
        r"[^.]{0,20}\bthe position of the slide just before\b[^.]{0,80}"
        rf"\bor -1 when the {_NAMED} is the first\b",
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

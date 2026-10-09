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

HEAD_ARCHITECT_CONTENT_HASH = "e77e69b18cb9d843a1754dab65a79941ede8cfa7c8266292580ff7566d1dcb33"

# Architect definition hash with prompt_text blanked: pins every non-prompt field
# (model, overlay, assembly rules, protected assembly, schema contract).
HEAD_ARCHITECT_HASH_WITHOUT_PROMPT = (
    "8b2c47f142ba5eb6205eb2abc0aae67ffcf733f54e1d30f5c6c0b2725795bec8"
)

HEAD_OTHER_ROLE_CONTENT_HASHES = {
    "data_analyst": "1ffb1fb3f31a20b9424007eefdf918620f1058386a2ba81bfd22347510ce6803",
    "builder": "4310de2a987378777c089eddee192d45c7a824ec169457f39aa3b8fe4c0f0f4a",  # Haiku promotion
    "build_reviewer": "1a895f4bee426041088635f7fa182200827db14ab35a229def6f8932d1516b18",
    "fixer": "a4fdb3e6fa54d8e2acf5507d9c2e6c024058c072dfab82373e2104f015856d7b",
    "fix_reviewer": "eed6c4ed4d363e32f4fd612daac03a32ca195bba07a3b7a026b64fcbe35d4558",  # Haiku promotion
    "deck_reviewer": "ed5df628c3ea4c81091fa9d621a1c1d7a8a1089edf1a4f81f335671ac47c0cb5",  # Haiku promotion
}

HEAD_V1_SCHEMA_DIGESTS = {
    "architect": "a03440e5a8578cf3ced4fd1e83219466ccb0abb5f3d7b04f7836fefd4423fafd",
    "data_analyst": "610545fe1d094f2544a5c602c2ebb45f542b813bf47e347e96ba7e22a6bfc281",
    "builder": "fc4bd6a9020b228a79cc0d933066478225947605916e05bd6f44ba7eccc82387",
    "build_reviewer": "50963d37738f8c97b12caa7688d282d3174a1e0c5e3606c8ec7a73c5ae50c70d",
    "fixer": "7a4e984c602d16ea73c2f5f3f26ac385c440527001fa14b1cfb5c1245de12297",
    "fix_reviewer": "31ff0a6d02cefb7db4cd2c499b4e7905fdadcda789c658e1c7605cdde01020df",
    "deck_reviewer": "56c7ce141e07a70fc2c57f614e915ebb9e3914d24b3c11057401c4cc1c637467",
}

HEAD_V2_SCHEMA_DIGESTS = {
    "architect": "a03aefb1735275226fe58c2edd04605e7f4126710c7023caf0e676126fbf4122",
    "data_analyst": "0543006dd98d1d84dc72c1f9b918a97daa93a3020d31e3557b2af8a91715b6c5",
    "builder": "65f29cb9774f96f131dba7dfe48ff04b8775dc0960f95a3c6efc19f326ba6aad",
    "build_reviewer": "20f69d5e65e0b94d4401b0645d16f8b238acd8b4571f9ce184b9d7d9956fc6b1",
    "fixer": "a77a9896705534109179e75a542eec212dbb25fd78582dff256d6b6c976a6143",
    "fix_reviewer": "bbe6bf025d5c2e5dcbe1c23db029caff425890602f7e3819c6472c46e7fdfd99",
    "deck_reviewer": "c466043b24678ceef8c80d3707f7e80672275415a8b1c0e4385f94bfea7104d3",
}

# sha256 of the "\n\n"-separated INSTRUCTIONS blocks that must stay byte-identical:
# opening line, INTENT CLASSIFICATION, DESIGN SYSTEMS (the contract-switch rule),
# SLIDESPEC FIELDS, closing line.  Recompute from `git show d3f150799:src/core/skills/architect.py`.
HEAD_UNCHANGED_BLOCK_HASHES = {
    "opening": "345a85e933fd76a597e00695029c5098e9de1534574c258d01689bcf36532034",
    "intent_classification": "dccff17eb03ebe5c411b07ec48cc8594aba6a617fc16288f1c9229550cd7d500",
    "design_systems": "10d09b732446c3e369f99a664e999a4af69018b3e47becf5fa5d0e190dc15345",
    "slidespec_fields": "5f488349a428a8ac5cf4adbd9b8df18cea77d5b5c010c237d0f853b1c5537653",
    "closing": "4b4000313dfac2e346b4b524a6dab465eca1d9316b227e0374c17d1517e54d7b",
}

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
    "adding or removing slides is not an edit",
)
# Review F1/F2 (controller ruling): an edit never silently restyles — the node treats
# a changed design_contract on an edit as an answered confirmation and rebuilds every
# slide — and an add/remove request has a named path instead of a dead end.
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
def test_editing_rule_keeps_contract_and_names_the_add_remove_path(phrase):
    assert phrase in _norm(_editing_block(INSTRUCTIONS)), f"EDITING block lacks {phrase!r}"


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
    architect = _architect_definition()
    assert definition_content_hash(architect) != HEAD_ARCHITECT_CONTENT_HASH
    blanked = architect.model_copy(update={"prompt_text": ""})
    assert definition_content_hash(blanked) == HEAD_ARCHITECT_HASH_WITHOUT_PROMPT

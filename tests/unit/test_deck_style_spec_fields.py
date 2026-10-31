"""Deck style and per-slide look on the deck spec (architect deck style, plan Task 1;
PLAN-CORRECTIONS C1, C4-C6).

- ``DeckSpec.deck_style: Optional[DeckStyle] = None`` is the architect's thin house
  style: ``css`` plus a catalogue of ``components`` (``DeckStyleComponent``: ``name``,
  ``class_names``, ``use``, ``example_html``). The new models' own fields are required.
- ``SlideSpec.look`` / ``SlideContent.look: Optional[str] = None`` says what the slide
  looks like. It is stripped, and a blank look becomes ``None`` (a blank ``slide_type``
  is an error; a blank look is not).
- The type level has no length, prefix or CSS rule: the sanitiser owns those, because a
  schema rejection would fail the whole architect turn.
- ``DeckChanges.deck_style`` sets the style on an edit; unset or null leaves it alone.
- A spec persisted before the fields existed validates unchanged.
- Adding the fields moves only the architect's v1/v2 schema digests. The superseded
  pair stays resolvable (a persisted release may still name it), and no other role's
  digest moves.
"""

from __future__ import annotations

import copy
import json
from typing import Any, Optional, get_args, get_origin

import pytest
from pydantic import ValidationError

from src.domain.deck_spec import DeckSpec, DeckStyle, DeckStyleComponent, SlideSpec
from src.domain.skill_io import ArchitectOutput
from src.domain.slide_operations import (
    DeckChanges,
    OperationProblems,
    OperationsResult,
    SlideContent,
    SlideOperation,
    apply_operations,
    compose_edit_spec,
)
from src.services.agent_schema_registry import (
    HISTORICAL_SCHEMA_CONTRACT_BUNDLES,
    SCHEMA_CONTRACT_BUNDLES,
    V1_SCHEMA_IDENTITIES,
    V2_SCHEMA_IDENTITIES,
    AgentSchemaRegistry,
)
from src.services.agent_schema_types import SchemaContractIdentity, SchemaOverlay

# frontend/tests/fixtures/deck-spec-markdown/full.deck-spec.json as it was before the
# deck-style fields existed (660f1509), frozen here: that file gains deck_style and look
# in this task (C1). It stands for a spec persisted by an older release.
_PERSISTED_SPEC_JSON = r"""{
  "title": "Renewal risk, Q3 — EMEA/APAC",
  "audience": "The regional sales leadership team,\twho own the renewal number.",
  "purpose": "Get the early-warning pipeline funded before the Q4\u00a0renewal wave.",
  "argument": "Churn is predictable a quarter ahead — and today nobody looks at <b>any</b> of it.",
  "call_to_action": "Approve two engineers for one quarter: our #1 priority.",
  "narrative_arc": [
    "Frame the problem: renewals are slipping and nobody can say which accounts.",
    "2024. The signal existed, but it arrived after the renewal date.",
    "- Close on the ask: fund the *early-warning* pipeline this quarter."
  ],
  "design_contract": {
    "design_system_id": 7,
    "template_id": 3,
    "slide_style_id": null
  },
  "resolved_data": {
    "synthesis": "Three quarters of churn history | aggregated by region & segment.",
    "figures": [
      {
        "key": "churn_rate",
        "value": "11.4%",
        "source": "warehouse.renewals"
      },
      {
        "key": "arr_at_risk",
        "value": "$4.2M (~30% of Q4)",
        "source": "finance.arr_snapshot"
      }
    ],
    "gaps": [
      "No data before FY23.",
      "The APAC `tier` column is unpopulated."
    ]
  },
  "slides": [
    {
      "position": 0,
      "purpose": "Open on the number nobody can explain.",
      "content_brief": "Title slide: the headline churn rate\r\nand the quarter it lands in.",
      "assumes": "Nothing. This is the first slide.",
      "hands_off": "The reader knows the number\u2028and wants to know why.",
      "data_references": [
        "churn_rate"
      ],
      "slide_type": "Cover",
      "template_section_index": 0
    },
    {
      "position": 1,
      "purpose": "Show the money\u001f at stake.",
      "content_brief": "One stat: ARR at risk, with its share of Q4.",
      "assumes": "The reader accepts the churn number from\u0085slide 1.",
      "hands_off": "The reader wants to know what fixing it costs.",
      "data_references": [
        "churn_rate",
        "arr_at_risk"
      ],
      "slide_type": "Stats",
      "template_section_index": 12
    },
    {
      "position": 3,
      "purpose": "Land the ask while the cause is still fresh.",
      "content_brief": "Closing slide: the two-engineer ask, scoped to one quarter.",
      "assumes": "",
      "hands_off": "The deck ends on a decision the reader can make in the room.",
      "data_references": [],
      "slide_type": null,
      "template_section_index": null
    }
  ]
}"""

# The architect digests live before this change. Written as literals, never imported.
SUPERSEDED_ARCHITECT_V1 = "9f090efe370a30b17779dcae11125b3645cb16153f2ef5c2dd234bf7c5f6970e"
SUPERSEDED_ARCHITECT_V2 = "9d83be8d41cae5550012e7a32c83f126ce38fb70965c46f749f53c8032102132"
# The architect digests already historical before this change; they must stay.
EARLIER_HISTORICAL_ARCHITECT = (
    (1, "a03440e5a8578cf3ced4fd1e83219466ccb0abb5f3d7b04f7836fefd4423fafd"),
    (2, "a03aefb1735275226fe58c2edd04605e7f4126710c7023caf0e676126fbf4122"),
    (1, "9704af4e9213f942104f449f09b66e41461cc774c7bfdd47e8c86a25b53b6285"),
    (2, "39ed9e91b3640ded4f2859c074db3d6a8f24c14dff49f7011e590b7473956da9"),
)

# Every other role's live digests, copied verbatim from the registry before this change.
OTHER_ROLES_V1 = {
    "data_analyst": "610545fe1d094f2544a5c602c2ebb45f542b813bf47e347e96ba7e22a6bfc281",
    "builder": "fc4bd6a9020b228a79cc0d933066478225947605916e05bd6f44ba7eccc82387",
    "build_reviewer": "50963d37738f8c97b12caa7688d282d3174a1e0c5e3606c8ec7a73c5ae50c70d",
    "fixer": "7a4e984c602d16ea73c2f5f3f26ac385c440527001fa14b1cfb5c1245de12297",
    "fix_reviewer": "31ff0a6d02cefb7db4cd2c499b4e7905fdadcda789c658e1c7605cdde01020df",
    "deck_reviewer": "56c7ce141e07a70fc2c57f614e915ebb9e3914d24b3c11057401c4cc1c637467",
}
OTHER_ROLES_V2 = {
    "data_analyst": "0543006dd98d1d84dc72c1f9b918a97daa93a3020d31e3557b2af8a91715b6c5",
    "builder": "65f29cb9774f96f131dba7dfe48ff04b8775dc0960f95a3c6efc19f326ba6aad",
    "build_reviewer": "20f69d5e65e0b94d4401b0645d16f8b238acd8b4571f9ce184b9d7d9956fc6b1",
    "fixer": "a77a9896705534109179e75a542eec212dbb25fd78582dff256d6b6c976a6143",
    "fix_reviewer": "bbe6bf025d5c2e5dcbe1c23db029caff425890602f7e3819c6472c46e7fdfd99",
    "deck_reviewer": "c466043b24678ceef8c80d3707f7e80672275415a8b1c0e4385f94bfea7104d3",
}

# A deck style as a model answer carries it: multi-line CSS with quotes, escapes and
# non-ASCII text, and an ordered catalogue. No value has outer whitespace, so it must
# come back byte for byte.
STYLE: dict[str, Any] = {
    "css": (
        ".dk-stat {\n"
        "  font: 600 var(--fs-display)/1 var(--font-sans);\n"
        "  color: var(--brand-core-primary);\n"
        "}\n"
        ".dk-stat > .dk-stat-label { font-size: var(--fs-body); }\n"
        '.dk-quote::before { content: "\\201C"; }'
    ),
    "components": [
        {
            "name": "Big stat",
            "class_names": ["dk-stat", "dk-stat-label"],
            "use": "One headline number with a short label beneath it.",
            "example_html": (
                '<div class="dk-stat">11.4%<span class="dk-stat-label">churn</span></div>'
            ),
        },
        {
            "name": "Pull quote",
            "class_names": ["dk-quote"],
            "use": "A customer's words, at most two lines — “verbatim”.",
            "example_html": '<blockquote class="dk-quote">We saw it a quarter late.</blockquote>',
        },
    ],
}
OTHER_STYLE: dict[str, Any] = {
    "css": ".dk-card { border: 1px solid var(--brand-core-primary); }",
    "components": [
        {
            "name": "Card",
            "class_names": ["dk-card"],
            "use": "One point per card, three in a row.",
            "example_html": '<div class="dk-card">Point</div>',
        }
    ],
}
# One look per slide of the persisted spec; the middle slide has none.
LOOKS = [
    "One dk-stat fills the body under the title.",
    None,
    "Three dk-card notes in a row beneath a single bar chart.",
]


def _persisted() -> dict[str, Any]:
    return json.loads(_PERSISTED_SPEC_JSON)


def _styled(style: Optional[dict[str, Any]] = STYLE, looks: list = LOOKS) -> dict[str, Any]:
    raw = _persisted()
    assert len(raw["slides"]) == len(looks)
    raw["deck_style"] = copy.deepcopy(style)
    for slide, look in zip(raw["slides"], looks):
        slide["look"] = look
    return raw


def _deref(node: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
    """Follow ``$ref`` and step into the non-null branch of an Optional ``anyOf``."""
    while True:
        if "$ref" in node:
            node = defs[node["$ref"].rsplit("/", 1)[-1]]
            continue
        if "anyOf" in node:
            branches = [b for b in node["anyOf"] if b.get("type") != "null"]
            assert len(branches) == 1, node
            node = branches[0]
            continue
        return node


_CONSTRAINT_KEYS = {"maxLength", "minLength", "pattern", "maxItems", "minItems", "format"}


# ---------------------------------------------------------------------------
# The models
# ---------------------------------------------------------------------------


def test_deck_style_models_have_the_interface_fields():
    def shape(model):
        return {name: field.is_required() for name, field in model.model_fields.items()}

    # The new models' own fields are required (C6): an answer either gives a whole
    # style or none.
    assert shape(DeckStyle) == {"css": True, "components": True}
    assert shape(DeckStyleComponent) == {
        "name": True,
        "class_names": True,
        "use": True,
        "example_html": True,
    }
    style_fields = DeckStyle.model_fields
    assert style_fields["css"].annotation is str
    assert get_origin(style_fields["components"].annotation) is list
    assert get_args(style_fields["components"].annotation) == (DeckStyleComponent,)
    component_fields = DeckStyleComponent.model_fields
    for name in ("name", "use", "example_html"):
        assert component_fields[name].annotation is str, name
    assert get_origin(component_fields["class_names"].annotation) is list
    assert get_args(component_fields["class_names"].annotation) == (str,)

    # The fields added to existing models are optional and default to None.
    for model, name, annotation in (
        (DeckSpec, "deck_style", Optional[DeckStyle]),
        (SlideSpec, "look", Optional[str]),
        (SlideContent, "look", Optional[str]),
        (DeckChanges, "deck_style", Optional[DeckStyle]),
    ):
        field = model.model_fields[name]
        assert field.annotation == annotation, (model.__name__, name)
        assert not field.is_required(), (model.__name__, name)
        assert field.default is None, (model.__name__, name)

    # Missing any required field of a given style is a validation error.
    for missing in STYLE:
        partial = {k: v for k, v in STYLE.items() if k != missing}
        with pytest.raises(ValidationError):
            DeckStyle.model_validate(partial)
    for missing in STYLE["components"][0]:
        component = {k: v for k, v in STYLE["components"][0].items() if k != missing}
        with pytest.raises(ValidationError):
            DeckStyle.model_validate({"css": STYLE["css"], "components": [component]})


def test_spec_without_deck_style_still_validates():
    raw = _persisted()
    # Precondition: this really is a spec from before the fields existed.
    assert "deck_style" not in raw
    assert raw["slides"] and all("look" not in slide for slide in raw["slides"])

    for spec in (DeckSpec.model_validate(raw), DeckSpec.from_json(_PERSISTED_SPEC_JSON)):
        assert type(spec) is DeckSpec  # from_json returns None rather than raising
        assert spec.deck_style is None
        assert [slide.look for slide in spec.slides] == [None] * len(raw["slides"])
        # Nothing else moves: the dump is the input plus the two new keys, both null.
        dumped = spec.model_dump()
        assert dumped.pop("deck_style") is None
        for slide in dumped["slides"]:
            assert slide.pop("look") is None
        assert dumped == raw


def test_deck_style_round_trips():
    raw = _styled()
    spec = DeckSpec.model_validate(raw)
    assert type(spec.deck_style) is DeckStyle
    assert [type(c) for c in spec.deck_style.components] == [DeckStyleComponent] * 2

    built = DeckSpec(
        **{k: v for k, v in raw.items() if k not in {"deck_style", "slides"}},
        deck_style=DeckStyle(
            css=STYLE["css"],
            components=[DeckStyleComponent(**c) for c in STYLE["components"]],
        ),
        slides=[SlideSpec(**slide) for slide in raw["slides"]],
    )
    assert built == spec

    text = spec.to_json()
    as_json = json.loads(text)
    assert as_json["deck_style"] == STYLE
    assert [slide["look"] for slide in as_json["slides"]] == LOOKS

    for restored in (DeckSpec.from_json(text), DeckSpec.model_validate(as_json)):
        assert type(restored) is DeckSpec  # from_json returns None rather than raising
        assert restored == spec
        assert restored.deck_style.model_dump() == STYLE
        assert [slide.look for slide in restored.slides] == LOOKS
        # The whole spec comes back exactly as given, every other field included.
        assert restored.model_dump() == raw


def test_deck_style_has_no_content_rules_at_the_type_level():
    """Prefix, at-rule, size and count rules belong to the sanitiser; the type accepts
    anything well-typed and keeps it exactly."""
    oversized = {
        "css": "@import url(https://example.com/x.css);\n.title { color: #ff0000; }"
        + "\n.x { margin: 0; }" * 800,
        "components": [
            {
                "name": f"Piece {i}",
                "class_names": [f"no-prefix-{i}"],
                "use": "u",
                "example_html": f"<style>.p{i}{{}}</style>",
            }
            for i in range(13)
        ],
    }
    assert len(oversized["css"]) > 10000
    style = DeckStyle.model_validate(oversized)
    assert style.model_dump() == oversized

    empty = {"css": "", "components": []}
    assert DeckStyle.model_validate(empty).model_dump() == empty

    long_look = "A " + "very " * 2000 + "long look."
    assert SlideSpec.model_validate({**_persisted()["slides"][0], "look": long_look}).look == (
        long_look
    )


@pytest.mark.parametrize("blank", ["", "   ", "\t\n  "])
def test_blank_look_becomes_none(blank):
    slide = _persisted()["slides"][0]
    assert SlideSpec.model_validate({**slide, "look": blank}).look is None

    content_fields = {k: v for k, v in slide.items() if k != "position"}
    content = SlideContent.model_validate({**content_fields, "look": blank})
    assert content.look is None
    assert content.to_slide_spec(4).look is None

    # Inside a whole spec, as a persisted column or a model answer carries it.
    raw = _styled(looks=[LOOKS[0], blank, LOOKS[2]])
    for spec in (DeckSpec.model_validate(raw), DeckSpec.from_json(json.dumps(raw))):
        assert type(spec) is DeckSpec  # a blank look is not an error
        assert [s.look for s in spec.slides] == LOOKS


# ---------------------------------------------------------------------------
# Edits
# ---------------------------------------------------------------------------


def _prior_spec(style: Optional[dict[str, Any]]) -> DeckSpec:
    raw = _styled(style)
    for index, slide in enumerate(raw["slides"]):
        slide["position"] = index  # contiguous, so an identity edit re-stamps nothing
    return DeckSpec.model_validate(raw)


def test_deck_changes_deck_style_composes():
    # As a model answer carries it.
    changes = DeckChanges.model_validate({"deck_style": copy.deepcopy(STYLE)})
    new = DeckStyle.model_validate(STYLE)
    assert changes.deck_style == new

    for prior_style in (None, OTHER_STYLE):
        prior = _prior_spec(prior_style)
        identity = apply_operations(prior.slides, [])
        assert isinstance(identity, OperationsResult)
        composed = compose_edit_spec(prior, identity, changes)
        # A style-only edit is a change, not "nothing to do", and it changes only the style.
        assert type(composed) is DeckSpec, composed
        assert composed.deck_style == new
        assert composed.deck_style.model_dump() == STYLE
        assert composed.slides == prior.slides
        assert [s.look for s in composed.slides] == LOOKS
        assert composed == prior.model_copy(update={"deck_style": new})

    # An unset or null deck_style leaves the prior style alone, whatever else changes.
    prior = _prior_spec(OTHER_STYLE)
    deleted = apply_operations(prior.slides, [SlideOperation(op="delete", position=1)])
    assert isinstance(deleted, OperationsResult)
    for unchanged in (
        None,
        DeckChanges(),
        DeckChanges(deck_style=None),
        DeckChanges(title="New title", deck_style=None),
    ):
        composed = compose_edit_spec(prior, deleted, unchanged)
        assert type(composed) is DeckSpec, composed
        assert composed.deck_style == prior.deck_style
        assert composed.deck_style.model_dump() == OTHER_STYLE
        assert [s.look for s in composed.slides] == [LOOKS[0], LOOKS[2]]

    # A null deck_style on its own changes nothing.
    identity = apply_operations(prior.slides, [])
    nothing = compose_edit_spec(prior, identity, DeckChanges(deck_style=None))
    assert isinstance(nothing, OperationProblems)
    assert [p.code for p in nothing.problems] == ["nothing_to_do"]


# ---------------------------------------------------------------------------
# The architect's contract
# ---------------------------------------------------------------------------


def _assert_optional_ref(prop: dict[str, Any], name: str) -> None:
    """An ``Optional[<name>] = None`` property: a ref to ``name`` or null, default null."""
    assert "default" in prop and prop["default"] is None, prop
    refs = [b for b in prop["anyOf"] if b.get("type") != "null"]
    assert len(refs) == 1 and refs[0].get("$ref") == f"#/$defs/{name}", prop
    assert len(prop["anyOf"]) == 2, prop


def _assert_optional_string(prop: dict[str, Any]) -> None:
    assert "default" in prop and prop["default"] is None, prop
    assert sorted(b.get("type") for b in prop["anyOf"]) == ["null", "string"], prop
    for branch in prop["anyOf"]:
        assert not _CONSTRAINT_KEYS & set(branch), prop


def _assert_reaches_deck_style_and_look(schema: dict[str, Any]) -> None:
    defs = schema["$defs"]
    props = schema["properties"]

    # deck_spec.deck_style -> DeckStyle -> components -> DeckStyleComponent
    deck_spec = _deref(props["deck_spec"], defs)
    assert "deck_style" not in deck_spec["required"]
    _assert_optional_ref(deck_spec["properties"]["deck_style"], "DeckStyle")
    deck_style = defs["DeckStyle"]
    assert set(deck_style["properties"]) == {"css", "components"}
    assert set(deck_style["required"]) == {"css", "components"}
    css = deck_style["properties"]["css"]
    assert css["type"] == "string" and not _CONSTRAINT_KEYS & set(css), css
    components = deck_style["properties"]["components"]
    assert components["type"] == "array" and not _CONSTRAINT_KEYS & set(components)
    assert components["items"] == {"$ref": "#/$defs/DeckStyleComponent"}
    component = defs["DeckStyleComponent"]
    fields = {"name", "class_names", "use", "example_html"}
    assert set(component["properties"]) == set(component["required"]) == fields
    for name in ("name", "use", "example_html"):
        assert component["properties"][name]["type"] == "string", name
    class_names = component["properties"]["class_names"]
    assert class_names["type"] == "array" and class_names["items"] == {"type": "string"}

    # deck_spec.slides[].look
    slides = _deref(deck_spec["properties"]["slides"], defs)
    assert slides["items"] == {"$ref": "#/$defs/SlideSpec"}
    slide_spec = defs["SlideSpec"]
    assert "look" not in slide_spec["required"]
    _assert_optional_string(slide_spec["properties"]["look"])

    # operations[].slides[].look
    operation = _deref(_deref(props["operations"], defs)["items"], defs)
    content_items = _deref(operation["properties"]["slides"], defs)["items"]
    assert content_items == {"$ref": "#/$defs/SlideContent"}
    slide_content = defs["SlideContent"]
    assert "look" not in slide_content["required"]
    _assert_optional_string(slide_content["properties"]["look"])

    # deck_changes.deck_style -> the same DeckStyle
    deck_changes = _deref(props["deck_changes"], defs)
    assert "deck_style" not in deck_changes.get("required", [])
    _assert_optional_ref(deck_changes["properties"]["deck_style"], "DeckStyle")


def test_architect_schema_has_deck_style_and_look():
    _assert_reaches_deck_style_and_look(ArchitectOutput.model_json_schema())

    # The schema the model is actually given: the composed live contract.
    registry = AgentSchemaRegistry()
    for identities in (V1_SCHEMA_IDENTITIES, V2_SCHEMA_IDENTITIES):
        composed = registry.compose("architect", identities["architect"], SchemaOverlay())
        _assert_reaches_deck_style_and_look(composed.model.model_json_schema())


def test_architect_output_carries_deck_style_and_look():
    registry = AgentSchemaRegistry()
    composed = registry.compose("architect", V2_SCHEMA_IDENTITIES["architect"], SchemaOverlay())

    def validate(raw: dict[str, Any]) -> ArchitectOutput:
        output = registry.validate_output(composed, raw).canonical_output
        assert type(output) is ArchitectOutput
        return output

    spec = _styled()
    build = validate({"intent": "build", "message": "m", "deck_spec": spec})
    assert build.deck_spec.model_dump() == spec
    assert build.deck_spec.deck_style.model_dump() == STYLE
    assert [s.look for s in build.deck_spec.slides] == LOOKS

    content = {k: v for k, v in _persisted()["slides"][0].items() if k != "position"}
    edit = validate(
        {
            "intent": "edit",
            "message": "m",
            "operations": [
                {
                    "op": "update",
                    "position": 0,
                    "slides": [{**content, "look": "  One dk-stat fills the body.\n"}],
                },
                {"op": "update", "position": 1, "slides": [{**content, "look": " "}]},
            ],
            "deck_changes": {"deck_style": copy.deepcopy(STYLE)},
        }
    )
    assert edit.deck_changes.deck_style.model_dump() == STYLE
    assert [op.slides[0].look for op in edit.operations] == ["One dk-stat fills the body.", None]

    # An answer from a prompt that knows nothing of deck styles is as valid as before.
    old = validate({"intent": "build", "message": "m", "deck_spec": _persisted()})
    assert old.deck_spec.deck_style is None
    assert [s.look for s in old.deck_spec.slides] == [None, None, None]


def test_historical_architect_digests_resolve():
    live = {
        1: V1_SCHEMA_IDENTITIES["architect"].digest,
        2: V2_SCHEMA_IDENTITIES["architect"].digest,
    }
    # The contract really was re-pinned: the live digests are new ones.
    assert live[1] != SUPERSEDED_ARCHITECT_V1
    assert live[2] != SUPERSEDED_ARCHITECT_V2

    registry = AgentSchemaRegistry()  # raises unless the live pins are the calculated material
    retained = ((1, SUPERSEDED_ARCHITECT_V1), (2, SUPERSEDED_ARCHITECT_V2))
    for version, digest in retained + EARLIER_HISTORICAL_ARCHITECT:
        assert digest not in live.values()
        key = ("architect", version, digest)
        assert key in HISTORICAL_SCHEMA_CONTRACT_BUNDLES, (
            f"architect v{version} digest {digest} is not retained"
        )
        bundle = HISTORICAL_SCHEMA_CONTRACT_BUNDLES[key]
        identity = SchemaContractIdentity("architect", version, digest)
        assert bundle.identity == identity
        assert bundle.canonical_model is ArchitectOutput
        live_bundle = SCHEMA_CONTRACT_BUNDLES[("architect", version)]
        assert bundle.optional_fields == live_bundle.optional_fields

        # A release naming the superseded digest still composes, against the current
        # model, so its outputs may carry a deck style.
        assert registry.identity_for("architect", version) != identity
        composed = registry.compose("architect", identity, SchemaOverlay())
        assert composed.canonical_model is ArchitectOutput
        output = registry.validate_output(
            composed, {"intent": "build", "message": "m", "deck_spec": _styled()}
        ).canonical_output
        assert output.deck_spec.deck_style.model_dump() == STYLE


def test_other_roles_digests_unchanged():
    assert set(V1_SCHEMA_IDENTITIES) == {"architect", *OTHER_ROLES_V1}
    assert set(V2_SCHEMA_IDENTITIES) == {"architect", *OTHER_ROLES_V2}
    assert {role: V1_SCHEMA_IDENTITIES[role].digest for role in OTHER_ROLES_V1} == OTHER_ROLES_V1
    assert {role: V2_SCHEMA_IDENTITIES[role].digest for role in OTHER_ROLES_V2} == OTHER_ROLES_V2
    # Nothing of theirs was superseded, so no other role has a historical row.
    assert {role for role, _, _ in HISTORICAL_SCHEMA_CONTRACT_BUNDLES} == {"architect"}
    # The pins are the calculated material (raises otherwise), so no other role's schema moved.
    AgentSchemaRegistry()

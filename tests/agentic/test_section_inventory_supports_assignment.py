"""Layer 3 (§M7 probe 3): the section inventory is enough to assign sections well.

WHAT IS BEING PROBED, AND WHY IT IS A QUESTION RATHER THAN A CONTRACT
--------------------------------------------------------------------
``section_inventory`` deliberately carries **no markup** — index, tag, classes, an
80-character text snippet, and the structural affordances it detected (``canvas``,
``image``, ``table``, ``list``).  A few hundred bytes per section, so a whole
template can be shown to the architect inside a prompt.

The open question §M7 records is whether *names and snippets are enough*: can an
architect pick the right section from that much information alone?  This test is
the probe.  If it fails on real prompts because the inventory is too thin — rather
than because the prose never mentioned sections — then the inventory grows, and
per-template thumbnails already exist to grow it with.  That is a ruling for
whoever runs it, not a reason to soften the assertion now.

WHY THE ASSIGNMENT MATTERS DOWNSTREAM
------------------------------------
``build_branch_payload`` reads ``slide_spec.template_section_index`` and calls
``extract_section(layout_html, index)`` to brief the builder with that section's
verbatim markup.  A title slide assigned the data section is handed a chart-and-
table layout to fill with a title — a plausible-looking wrong slide, and one no
schema can reject because any in-range integer validates.

A NOTE ON WHAT WILL FAIL FIRST, RECORDED HONESTLY
-------------------------------------------------
The architect's shipped instructions enumerate the ``SlideSpec`` fields and
``template_section_index`` **is not among them**, nor is ``template_sections``
described anywhere in the prose — the payload key exists and the prompt never
mentions it.  So against the placeholder prompts this test is expected to fail at
the *first* assertion (nothing assigned at all), not at the discrimination the probe
is really about.  That is the correct order of events: the assertion is not weakened
to accommodate the gap, and the gap is named here so the first real run is not
mistaken for a finding about the inventory's richness.

WHAT THE INVENTORY MUST CARRY FOR ASSIGNMENT (slide-type binding)
-----------------------------------------------------------------
Class tokens on the wrapper (``title-slide`` / ``data-slide``) are the fixture
author's private vocabulary, not the design system's.  A probe that can only see
them is insufficient: the architect must copy a design-system-authored ``label``
into ``slide_type`` and the matching ``index`` into ``template_section_index``
(spec ``2026-10-13-architect-slide-type-design.md``, agentic probe).  So every
inventoried root used for assignment must have a non-null ``label``.

The two labels below are synthetic and chosen by *this fixture*; they are not a
product taxonomy and not the Tellr Corporate vocabulary.  ``index`` stays 0-based;
"slide 1"/"slide 2" appear only in comments and prose.
"""

from __future__ import annotations

from tests.agentic.gates import LAYER3_MARKS, invoke_agent
from tests.agentic.payloads import architect_payload

pytestmark = LAYER3_MARKS

#: Synthetic design-system labels for this fixture only.  Deliberately unlike the
#: wrapper class tokens (``title-slide`` / ``data-slide``) so a model that echoes a
#: class token cannot satisfy the ``slide_type`` assertions by accident.  The
#: implementer adds these as ``data-label`` on the matching ``<section>`` roots.
_TITLE_LABEL = "Opening Frame"
_DATA_LABEL = "Metrics Board"

#: Two sections whose ROLES are distinguishable from the inventory alone: one is a
#: title section (a heading, a presenter line, no affordances), one is a data
#: section (a canvas and a table).  Both carry the ``slide`` class token, which is
#: what ``find_slide_roots`` keys off — without it the inventory is empty and the
#: no-template fallback activates.
_LAYOUT_HTML = """
<html><body><main>
  <section class="slide title-slide" data-label="Opening Frame">
    <h1>Deck title goes here</h1>
    <p>Presenter name and date</p>
  </section>
  <section class="slide data-slide" data-label="Metrics Board">
    <h2>Metric headline goes here</h2>
    <div style="position:relative;height:300px"><canvas id="chart"></canvas></div>
    <table><tr><th>Region</th><th>Teams</th></tr><tr><td>North</td><td>40</td></tr></table>
  </section>
</main></body></html>
"""


def _assert_inventory_is_label_bearing(inventory: list[dict]) -> None:
    """Precondition: the inventory exposes the labels, not just wrapper classes.

    Module-level so the red state can be demonstrated in-process even while the
    layer-3 placeholder gate skips the test itself.
    """
    assert len(inventory) == 2, f"expected two inventoried sections, got {inventory}"
    unlabeled = [e["index"] for e in inventory if not e.get("label")]
    assert not unlabeled, (
        f"inventory entries at 0-based indices {unlabeled} have no non-null "
        "`label`. A probe that only sees wrapper class tokens is insufficient: "
        "the architect must copy a design-system-authored label into slide_type. "
        f"Add data-label to each root in the fixture. Inventory: {inventory}"
    )
    labels = [e["label"] for e in inventory]
    assert labels == [_TITLE_LABEL, _DATA_LABEL], (
        f"expected labels {[_TITLE_LABEL, _DATA_LABEL]!r} in document order "
        f"(0-based indices 0 and 1), got {labels!r}"
    )
    assert len(set(labels)) == 2, f"the two labels must be distinct: {labels!r}"
    class_tokens = {t for e in inventory for t in (e["classes"] or [])}
    assert not (set(labels) & class_tokens), (
        f"labels {labels!r} must differ from wrapper class tokens {class_tokens!r}; "
        "otherwise a classes-only probe would pass."
    )


def test_a_title_slide_is_assigned_the_title_section_not_the_data_section():
    """One architect call, judged on the two indices it wrote into the spec."""
    from src.services.template_sections import section_inventory

    inventory = section_inventory(_LAYOUT_HTML)

    # Preconditions on the fixture, not on the model. If the inventory is empty,
    # undifferentiated, or unlabeled, the probe has nothing to probe and must say
    # so rather than asserting against the model.
    _assert_inventory_is_label_bearing(inventory)
    # 0-based indices, selected by label (the design-system vocabulary), never by
    # the wrapper class tokens the old probe keyed off.
    title_index = next(e["index"] for e in inventory if e["label"] == _TITLE_LABEL)
    data_index = next(e["index"] for e in inventory if e["label"] == _DATA_LABEL)
    assert (title_index, data_index) == (0, 1), (title_index, data_index)
    assert "canvas" in inventory[data_index]["affordances"], (
        "the data section's canvas was not detected, so the two sections are not "
        f"distinguishable from the inventory at all: {inventory}"
    )
    assert not inventory[title_index]["affordances"], (
        "the title section reports affordances, so it is not the plain section this "
        f"probe assumes: {inventory}"
    )

    out = invoke_agent(
        "architect",
        architect_payload(
            "Build me a two-slide deck: a title slide, then one slide with a bar "
            "chart of weekly active teams by region.",
            template_sections=inventory,
        ),
        # A template is in play, but the compiled-brand branch is not what is under
        # test here; False keeps the prompt on the same path as every other layer-3
        # module so one behaviour is measured at a time.
        False,
    )

    assert out.intent == "build", (
        f"intent was {out.intent!r} for an explicit two-slide build request; there "
        f"is no spec to inspect. Message was: {out.message!r}"
    )
    assert out.deck_spec is not None, "intent=build with no deck_spec"
    slides = sorted(out.deck_spec.slides, key=lambda s: s.position)
    assert len(slides) == 2, (
        f"expected two slides, got positions {[s.position for s in slides]}"
    )

    # slides[0] is slide 1 in prose (position 0); slides[1] is slide 2 (position 1).
    assigned = [s.template_section_index for s in slides]
    assert assigned[0] is not None, (
        "the architect assigned no template section to the title slide. The "
        f"inventory it was handed was {inventory}. Note the recorded gap: the "
        "shipped instructions never mention template_sections or "
        "template_section_index, so this is where the placeholder prompts fail "
        "first — the fix is prose, not a weaker assertion."
    )
    assert assigned[0] == title_index, (
        f"the title slide was assigned section {assigned[0]} (the data section is "
        f"{data_index}, the title section is {title_index}). build_branch_payload "
        "extracts that section's markup and briefs the builder with it, so a title "
        "slide gets handed a chart-and-table layout."
    )
    assert assigned[1] == data_index, (
        f"the chart slide was assigned section {assigned[1]}, not the data section "
        f"{data_index}. The pairing matters: assigning the title section to both "
        "slides would satisfy the assertion above on its own."
    )

    # The binding is a pair: the label the architect copied from the inventory
    # entry it selected, and that entry's 0-based index. Exact, case-preserving.
    types = [s.slide_type for s in slides]
    assert types[0] == inventory[title_index]["label"] == _TITLE_LABEL, (
        f"the title slide's slide_type was {types[0]!r}; the selected inventory "
        f"entry's label is {inventory[title_index]['label']!r}. slide_type must be "
        "copied exactly from the selected entry, not invented or taken from a "
        "class token."
    )
    assert types[1] == inventory[data_index]["label"] == _DATA_LABEL, (
        f"the chart slide's slide_type was {types[1]!r}; the selected inventory "
        f"entry's label is {inventory[data_index]['label']!r}."
    )
    for slide, entry in zip(slides, (inventory[title_index], inventory[data_index])):
        assert (slide.slide_type, slide.template_section_index) == (
            entry["label"],
            entry["index"],
        ), (
            f"slide at position {slide.position} bound a mismatched pair "
            f"({slide.slide_type!r}, {slide.template_section_index!r}); the "
            f"selected entry is ({entry['label']!r}, {entry['index']!r})."
        )

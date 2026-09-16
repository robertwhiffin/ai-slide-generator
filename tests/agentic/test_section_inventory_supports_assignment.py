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
"""

from __future__ import annotations

from tests.agentic.gates import LAYER3_MARKS
from tests.agentic.payloads import architect_payload

pytestmark = LAYER3_MARKS

#: Two sections whose ROLES are distinguishable from the inventory alone: one is a
#: title section (a heading, a presenter line, no affordances), one is a data
#: section (a canvas and a table).  Both carry the ``slide`` class token, which is
#: what ``find_slide_roots`` keys off — without it the inventory is empty and the
#: no-template fallback activates.
_LAYOUT_HTML = """
<html><body><main>
  <section class="slide title-slide">
    <h1>Deck title goes here</h1>
    <p>Presenter name and date</p>
  </section>
  <section class="slide data-slide">
    <h2>Metric headline goes here</h2>
    <div style="position:relative;height:300px"><canvas id="chart"></canvas></div>
    <table><tr><th>Region</th><th>Teams</th></tr><tr><td>North</td><td>40</td></tr></table>
  </section>
</main></body></html>
"""


def test_a_title_slide_is_assigned_the_title_section_not_the_data_section():
    """One architect call, judged on the two indices it wrote into the spec."""
    from src.core.skills import call_skill
    from src.services.template_sections import section_inventory

    inventory = section_inventory(_LAYOUT_HTML)

    # Preconditions on the fixture, not on the model. If the inventory is empty or
    # undifferentiated, the probe has nothing to probe and must say so rather than
    # asserting against the model.
    assert len(inventory) == 2, (
        f"expected two inventoried sections, got {inventory}. section_inventory "
        "returns [] (with a warning) when no element carries the `slide` class — "
        "which is the no-template fallback, not a two-section template."
    )
    title_index = next(
        e["index"] for e in inventory if "title-slide" in (e["classes"] or [])
    )
    data_index = next(
        e["index"] for e in inventory if "data-slide" in (e["classes"] or [])
    )
    assert "canvas" in inventory[data_index]["affordances"], (
        "the data section's canvas was not detected, so the two sections are not "
        f"distinguishable from the inventory at all: {inventory}"
    )
    assert not inventory[title_index]["affordances"], (
        "the title section reports affordances, so it is not the plain section this "
        f"probe assumes: {inventory}"
    )

    out = call_skill(
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

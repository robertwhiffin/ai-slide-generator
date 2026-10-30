"""Generate the architect pack's HELD-OUT cases from the deck-2 gold fixture. Idempotent.

Reuses the train generator's helpers; only deck-2 content lives here.
"""
import pathlib

import src.core.database  # noqa: F401  (break import cycle before src.services.*)
from src.domain.deck_spec import DesignContractRef
from src.domain.slide_numbering import architect_slide_payload
from src.services.agent_model_payload import model_payload_for
from src.services.spec_sync import ARC_REVIEW_MESSAGE
from src.services.template_sections import section_inventory

from evals.harness import case
from evals.packs.architect import mutations as m

AGENT = m.AGENT
DECK = "heldout"
CASES_DIR = case.PACKS_DIR / AGENT / "cases_heldout"
EDIT_POS = 2

PRIOR_USER = "Build a deck arguing that structured prompt optimisation beats ad-hoc prompting"
PRIOR_ASSISTANT = (
    "I've drafted a 6-slide deck on prompt optimisation, and the slides are built."
)

MESSAGES = {
    "build_request": (
        "Build a deck for engineers and product teams arguing that structured prompt "
        "optimisation beats ad-hoc prompting"
    ),
    "edit_request": "On slide 3, show the four patterns as four cards instead of a bullet list",
    "ask_data": (
        "Build a deck on our team's measured prompt success rates by model over the last quarter"
    ),
    "confirm_design": "Can you re-theme this deck with the Acme design system instead?",
    "discuss": "When should I use few-shot examples rather than chain-of-thought prompting?",
    # #313: intent and slide-reference cases on deck 2.
    "edit_polite_ordinal": (
        "Would you mind making the 4th slide lead with the 3-5 iteration rounds?"
    ),
    "edit_last_slide": "The final slide should open with the call to action, before the checklist",
    "edit_multi_slide": "Slides 2 and 3 are too dense — drop the callouts on both",
    "discuss_slide_question": "Why does slide 2 come before the techniques?",
    # #314: add a slide to deck 2.
    "add_slide_anchor": (
        "Could you add a slide before slide 5 with a worked before-and-after prompt example?"
    ),
    "add_slide_end": "Add one more slide at the end with a glossary of the prompt terms",
    "add_slide_as_number": "Add a new fourth slide on common prompt anti-patterns",
    "add_slide_and_revise": (
        "Add a slide after slide 3 on versioning prompts, and add it to the checklist on the "
        "final slide"
    ),
    # #314 follow-up: deck 2 with a manually inserted blank slide.
    "fill_blank_slide": (
        "Please make slide 4 a quick guide to which of the four patterns fits which kind of task"
    ),
    "edit_beside_blank": "Can you add a one-line takeaway beneath the stats on the fifth slide?",
    # Architect edit operations (spec §9): delete, move, replace and a mixed edit on deck 2.
    "delete_slide": (
        "Delete slide 4. We'll circulate the numbers in a follow-up doc, so leave everything else "
        "alone."
    ),
    "move_slide": (
        "Could you move slide 5 so it sits straight after slide 3? The workflow should follow the "
        "techniques."
    ),
    "replace_slide_expand": (
        "Replace slide 3 with these three slides: an overview of the four patterns, one on system "
        "prompts and few-shot examples, and one on chain-of-thought and structured output"
    ),
    "mixed_operations": (
        "Delete slide 1, change the callout on slide 3 to say when to combine few-shot examples "
        "with chain-of-thought, and expand the bullets on slide 2 into three slides, one per pain "
        "point"
    ),
    # The arc-review sweeper's describe-only turn: production's own message, as on train.
    "redescribe_deck": ARC_REVIEW_MESSAGE,
    # Architect deck style: a fresh technical build on its own public topic that needs OTHER
    # pieces than train's (a dated timeline and a KPI band, no code; Ruling R29), and a restyle of
    # the code blocks on deck 2.
    "build_technical_deck": (
        "Build a deck for the web platform team on rolling out HTTP/3 across our public website. "
        "Show the rollout as a dated timeline: a canary on 5% of traffic in March 2026, every "
        "static asset in May 2026, every page in July 2026, and the TCP-only edge configuration "
        "retired in October 2026. Put the canary's results in one KPI band: time to first byte at "
        "the 75th percentile down from 420 ms to 310 ms, connection setup on mobile 38% faster, "
        "page-load errors on poor networks down 22%, and 61% of canary requests served over "
        "HTTP/3. Close with what each team must do before the May step."
    ),
    "restyle_deck": "Please give every code listing a dark background and light lettering",
}

# The cases whose payload carries the deck: the prior exchange, the gold spec and its slide count.
HAS_DECK = (
    "edit_request", "confirm_design", "discuss",
    "edit_polite_ordinal", "edit_last_slide", "edit_multi_slide", "discuss_slide_question",
    "add_slide_anchor", "add_slide_end", "add_slide_as_number", "add_slide_and_revise",
    "fill_blank_slide", "edit_beside_blank",
    *m.OPERATIONS_CASES,
    *m.DESCRIBE_ONLY_CASES,
    *m.STYLED_DECK_CASES,
)
# The cases whose deck holds a manually inserted blank slide, spliced in at BLANK_AT.
BLANK_AT = 3

EDIT_BRIEF = (
    "Four cards in place of the bullet list covering the four key patterns — system-prompt framing, "
    "few-shot examples, chain-of-thought reasoning, and structured output formatting — one pattern "
    "per card, with a callout on when to combine them"
)


def _payload(cid):
    has_deck = cid in HAS_DECK
    describe_only = cid in m.DESCRIBE_ONLY_CASES
    msg = MESSAGES[cid]
    conversation = [{"role": "user", "content": msg}]
    if has_deck:
        conversation = [
            {"role": "user", "content": PRIOR_USER},
            {"role": "assistant", "content": PRIOR_ASSISTANT},
            {"role": "user", "content": msg},
        ]
    if describe_only:
        conversation = conversation[:-1]  # the sweeper persists no user row for its message
    contract = DesignContractRef(
        design_system_id=m.MERIDIAN_ID, template_id=m.MERIDIAN_TEMPLATE
    ).model_dump(mode="json")
    deck = case.gold_deck_spec(DECK) if has_deck else None
    if cid in m.BLANK_CASES:
        deck = m._blank_deck(deck, BLANK_AT)
    if cid in m.STYLED_DECK_CASES:
        deck = m._styled_deck(deck, RESTYLE_LOOKS)
    slide_keys = architect_slide_payload(
        conversation, msg, [s["position"] for s in deck["slides"]] if has_deck else [],
        describe_only=describe_only,
    )
    return model_payload_for(AGENT, {
        "conversation": conversation,
        "message": msg,
        "current_deck_spec": deck,
        "committed_slide_count": len(deck["slides"]) if has_deck else 0,
        **slide_keys,
        "previous_deck_review": None,
        "available_design_contract": contract,
        "template_sections": section_inventory(m.LAYOUT.read_text()),
        "resolved_style": case.meridian_resolved_style(),
        "design_system_library": m.LIBRARY,
        "deck_style_context": case.meridian_deck_style_context(),
    })


# Revised briefs for the #313 edit references (positions are 0-based; the messages speak 1-based).
# No held-out target slide's purpose changes.
POLITE_BRIEF_3 = (
    "Three-stat card slide that leads with typical iteration cycles to production quality "
    "(3-5 rounds) as the headline stat, followed by token cost reduction (30-50%) and output "
    "consistency improvement (up to 40%)"
)
LAST_BRIEF_5 = (
    "Bullet slide that opens with the call to action — adopt this checklist for every new LLM "
    "feature starting this sprint — and then presents the five-item prompt optimisation checklist "
    "(define task scope, choose patterns, write eval criteria, run test suite, document winning "
    "prompt)"
)
MULTI_BRIEFS = {
    1: (
        "Bullet slide listing the three pain points of unoptimised prompts — inconsistent outputs, "
        "wasted tokens/cost, and slow iteration — with no callout"
    ),
    2: (
        "Bullet slide covering the four key patterns — system-prompt framing, few-shot examples, "
        "chain-of-thought reasoning, and structured output formatting — with no callout"
    ),
}


# #314: the new slides, by case (deck 2). ``m._inserted_spec`` adds the position and the empty
# data / slide-type / template-section fields.
ANCHOR_SLIDE = {
    "purpose": "Make the techniques concrete with one worked example",
    "content_brief": (
        "Two-column slide with an ad-hoc prompt on the left and its optimised version on the "
        "right, labelling where system-prompt framing, a few-shot example and a structured "
        "output format were applied"
    ),
    "assumes": (
        "Audience has seen the measured gains and wants to see what a better prompt looks like"
    ),
    "hands_off": "Applying the patterns to one real prompt is quick and visibly improves it",
}
# The judge-only calibration: right place and right targets, but a slide nobody asked for.
OFF_REQUEST_SLIDE = {
    "purpose": "Point the team at upcoming AI conferences",
    "content_brief": (
        "Bullet slide listing three upcoming AI conferences the team could attend, with dates "
        "and locations"
    ),
}
END_SLIDE = {
    "purpose": "Appendix — a glossary of the prompt terms used in the deck",
    "content_brief": (
        "Two-column glossary defining system prompt, few-shot example, chain-of-thought, "
        "structured output, eval criteria and test suite in one line each"
    ),
    "assumes": "Audience has heard each term during the talk",
    "hands_off": "Everyone leaves with the same vocabulary for prompt work",
}
AS_NUMBER_SLIDE = {
    "purpose": "Warn against the habits that undo prompt optimisation",
    "content_brief": (
        "Bullet slide listing four common prompt anti-patterns — vague instructions, "
        "contradictory constraints, examples that leak the answer, and unbounded output — each "
        "with a one-line fix"
    ),
    "assumes": "Audience knows the four core patterns from the previous slide",
    "hands_off": "Most bad outputs come from a handful of avoidable prompt habits",
}
AND_REVISE_SLIDE = {
    "purpose": "Show how to keep prompts under version control",
    "content_brief": (
        "Bullet slide explaining that every prompt change gets a version, a change note and a "
        "link to its eval results, so a regression can be traced and rolled back"
    ),
    "assumes": "Audience knows the four core patterns and that prompts change often",
    "hands_off": "A versioned prompt can be compared, reviewed and rolled back like code",
}
# The one revision, by wording: the gold checklist brief (gold position 5) with this phrase swapped.
CHECKLIST_ITEMS = (
    "five-item prompt optimisation checklist (define task scope, choose patterns, write eval "
    "criteria,",
    "six-item prompt optimisation checklist (define task scope, choose patterns, version every "
    "prompt, write eval criteria,",
)


# #314 follow-up (manual insert): the blank-slide cases on deck 2. The payload deck is the deck-2
# gold spec with a manually inserted blank at BLANK_AT, so gold positions 3..5 shift to 4..6 and
# the user's slide numbers count the blank.
BESIDE_POS = BLANK_AT + 1  # the slide edit_beside_blank names: just after the blank
# fill_blank_slide's reference: the blank filled in place with these text fields.
FILLED_SLIDE = {
    "purpose": "Help the audience choose the right pattern for a task",
    "content_brief": (
        "Table mapping four common task types — extraction, classification, multi-step reasoning "
        "and open-ended writing — to the pattern that fits each best, with one line on why"
    ),
    "assumes": "Audience has just met the four core patterns",
    "hands_off": "Each kind of task has a pattern that fits it best",
}
# edit_beside_blank's one revision: BESIDE_POS's brief with the first phrase swapped for the second.
BESIDE_REVISION = (
    "typical iteration cycles to production quality (3-5 rounds)",
    "typical iteration cycles to production quality (3-5 rounds), with a one-line takeaway "
    "beneath the stats: structured prompting pays for itself in fewer tokens and fewer rounds",
)
# edit_beside_blank's should_fail fills the untouched blank with invented text.
INVENTED_FILL = {
    "purpose": "Bridge from the techniques to the evidence",
    "content_brief": (
        "Transition slide with one line asking whether the four patterns really pay off, setting "
        "up the numbers that follow"
    ),
    "assumes": "Audience has just met the four core patterns",
    "hands_off": "The patterns are only worth adopting if the gains are real",
}


# Architect edit operations (spec §9) on deck 2; ``m._op`` and friends build the operations.
# delete_slide: slide 4 (position 3, the impact numbers) goes; nothing is rebuilt.
DELETE_POS = 3
# move_slide: slide 5 (position 4, the workflow) goes straight after slide 3 (position 2).
MOVE_POS, MOVE_AFTER = 4, 2
# replace_slide_expand: slide 3 (position 2, the four patterns) becomes these three slides.
REPLACE_POS = 2
REPLACE_SLIDES = [
    {
        "purpose": "Introduce the core techniques: an overview of the four prompt design patterns",
        "content_brief": (
            "Overview slide naming the four key patterns — system-prompt framing, few-shot "
            "examples, chain-of-thought reasoning, and structured output formatting — as four "
            "labelled tiles, with a one-line note that the next two slides cover them in pairs"
        ),
        "assumes": "Audience understands the problem from the previous slide",
        "hands_off": (
            "Four composable patterns cover the vast majority of prompt optimisation needs"
        ),
    },
    {
        "purpose": "Explain the first two patterns: system-prompt framing and few-shot examples",
        "content_brief": (
            "Two-column slide with system-prompt framing (set the role, constraints and tone once) "
            "on the left and few-shot examples (show two or three input-output pairs) on the "
            "right, each with a one-line example and when to use it"
        ),
        "assumes": "Audience has just seen the four patterns named",
        "hands_off": "Framing and examples show the model what a good answer looks like",
    },
    {
        "purpose": (
            "Explain the other two patterns: chain-of-thought reasoning and structured output"
        ),
        "content_brief": (
            "Two-column slide with chain-of-thought reasoning (ask for the steps before the "
            "answer) on the left and structured output formatting (a schema or template for the "
            "reply) on the right, each with a one-line example and when to use it, and a callout "
            "on when to combine the patterns"
        ),
        "assumes": "Audience knows system-prompt framing and few-shot examples from the last slide",
        "hands_off": "Reasoning steps and a fixed output shape make answers reliable and checkable",
    },
]
# mixed_operations: delete slide 1 (position 0, the cover), revise slide 3's callout (position
# 2), and expand slide 2's bullets (position 1, the three pain points) into three slides.
MIXED_DELETE, MIXED_UPDATE, MIXED_REPLACE = 0, 2, 1
MIXED_CALLOUT = (
    "with a callout on when to combine them",
    "with a callout on when to combine few-shot examples with chain-of-thought: a task that needs "
    "both a fixed answer format and several reasoning steps",
)
MIXED_SLIDES = [
    {
        "purpose": "Define the problem, pain point 1: inconsistent outputs",
        "content_brief": (
            "Bullet slide showing how the same ad-hoc prompt gives different answers from one run "
            "to the next, with a callout on what that costs in review time and user trust"
        ),
        "assumes": "Audience has experienced frustrating or inconsistent LLM outputs first-hand",
        "hands_off": "Ad-hoc prompts make a model's outputs unpredictable",
    },
    {
        "purpose": "Define the problem, pain point 2: wasted tokens and cost",
        "content_brief": (
            "Bullet slide showing how unfocused prompts and retries burn tokens, with a callout on "
            "how that cost compounds across every request"
        ),
        "assumes": "Audience has seen that ad-hoc outputs are inconsistent",
        "hands_off": "Ad-hoc prompts waste money on every call",
    },
    {
        "purpose": "Define the problem, pain point 3: slow iteration",
        "content_brief": (
            "Bullet slide showing how changing a prompt without a test set means guessing, "
            "re-checking by hand and slipping deadlines, with a callout summarising the "
            "opportunity cost of all three pain points"
        ),
        "assumes": "Audience has seen the consistency and cost problems",
        "hands_off": "Ad-hoc prompting has real, measurable costs that compound over time",
    },
]


# redescribe_deck on deck 2 (``m.REDESCRIBE_FAULT`` says why the deck_changes form is dropped).
REDESCRIBE_MESSAGE = (
    "Re-described the deck as it now reads: the six slides are unchanged and in order, and the "
    "specification describes each of them and the arc they make. No slide was rewritten, added, "
    "removed or moved."
)
REDESCRIBE_ARC_MESSAGE = (
    "Updated the deck's narrative arc so it describes the six slides as they now read."
)
# The should_fail's re-described arc: the deck-2 gold's five beats, reworded.
REDESCRIBED_ARC = [
    "Start with what bad prompts cost: wasted tokens, inconsistent outputs and frustrated users",
    "Lay out the prompt design patterns that make the biggest difference",
    "Measure the gains of structured prompting against ad-hoc prompting",
    "Walk through an evaluation and iteration workflow the team can use straight away",
    "Finish with a concrete checklist and the next steps",
]


# Architect deck style on its own build topic and on deck 2 (``m._technical_deck``, ``m._restyled``
# and ``m.RESTYLE_FAULT`` say what each case and its should_fail are). The build asks for other
# pieces than train's (Ruling R29): a dated timeline and a KPI band, and no code, so its deck style
# is its own, not the technical fixture.
TECH_BUILD_MESSAGE = (
    "Here is a 5-slide deck on rolling out HTTP/3: the rollout as a dated timeline, the canary's "
    "results in one KPI band, and what each team must do before the May step."
)
TECH_DECK = {
    "title": "Rolling Out HTTP/3 Across the Public Website",
    "audience": (
        "The web platform team and the teams whose services sit behind the public website"
    ),
    "purpose": (
        "Agree the HTTP/3 rollout dates and each team's part, on the strength of the canary's "
        "results"
    ),
    "argument": (
        "The canary shows HTTP/3 makes the public website faster and more reliable on mobile and "
        "on poor networks, so the rollout should widen to every static asset in May 2026 and to "
        "every page in July"
    ),
    "call_to_action": "Approve the May 2026 step, and have each team finish its part before then",
    "narrative_arc": [
        "Open on the goal: a faster, more reliable public website on every network",
        "Lay out the rollout as four dated milestones",
        "Report what the canary measured",
        "Show why the results justify widening the rollout in May",
        "Close with what each team must do before the May step",
    ],
    "resolved_data": {
        "synthesis": (
            "On the canary (5% of traffic) time to first byte at the 75th percentile fell from "
            "420 ms to 310 ms, connection setup on mobile was 38% faster, page-load errors on poor "
            "networks fell 22%, and 61% of canary requests were served over HTTP/3. The rollout "
            "dates are the user's plan: the canary in March 2026, every static asset in May 2026, "
            "every page in July 2026, and the TCP-only edge configuration retired in October 2026."
        ),
        "figures": [
            {"key": "ttfb_p75",
             "value": "time to first byte at the 75th percentile down from 420 ms to 310 ms",
             "source": "The user's canary on 5% of traffic"},
            {"key": "mobile_setup", "value": "connection setup on mobile 38% faster",
             "source": "The user's canary on 5% of traffic"},
            {"key": "poor_network_errors", "value": "page-load errors on poor networks down 22%",
             "source": "The user's canary on 5% of traffic"},
            {"key": "http3_share", "value": "61% of canary requests served over HTTP/3",
             "source": "The user's canary on 5% of traffic"},
        ],
        "gaps": [],
    },
}
CANARY_FIGURES = ["ttfb_p75", "mobile_setup", "poor_network_errors", "http3_share"]
TECH_SLIDES = [
    {
        "purpose": "Open the deck: rolling out HTTP/3 across the public website",
        "content_brief": (
            "Cover slide with the title 'Rolling Out HTTP/3 Across the Public Website' and a "
            "subtitle promising a faster site on mobile and on poor networks"
        ),
        "assumes": "The audience runs the public website or a service behind it",
        "hands_off": "HTTP/3 is worth rolling out to the whole site",
        "look": (
            "Meridian cover: the title large on the left and the subtitle beneath it; no "
            "deck-style pieces"
        ),
    },
    {
        "purpose": "Lay out the rollout as four dated milestones",
        "content_brief": (
            "The rollout as a timeline, left to right: a canary on 5% of traffic in March 2026, "
            "every static asset in May 2026, every page in July 2026, and the TCP-only edge "
            "configuration retired in October 2026; a one-line note beneath that each step waits "
            "for the previous step's results"
        ),
        "assumes": "The audience knows HTTP/3 is running as a canary",
        "hands_off": "The rollout has four dated steps, and May is the next one",
        "look": (
            "Slide title above a dk-timeline of the four milestones, left to right, each opening "
            "with its date; a dk-note beneath it on each step waiting for the last"
        ),
    },
    {
        "purpose": "Report what the canary measured",
        "content_brief": (
            "The canary's four results in one band: time to first byte at the 75th percentile "
            "down from 420 ms to 310 ms, connection setup on mobile 38% faster, page-load errors "
            "on poor networks down 22%, and 61% of canary requests served over HTTP/3; the source "
            "beneath: the canary on 5% of traffic"
        ),
        "assumes": "The audience has seen the rollout plan",
        "hands_off": "On the canary, HTTP/3 was faster and failed less",
        "data_references": CANARY_FIGURES,
        "look": (
            "Slide title above a dk-kpi-band of the four results, a dk-kpi-value and a "
            "dk-kpi-label each (four figures, one more than the template's three stat cards "
            "hold); a dk-note beneath it naming the canary as the source"
        ),
    },
    {
        "purpose": "Show why the results justify widening the rollout in May",
        "content_brief": (
            "Three bullets, each tying a result to the decision: faster first bytes, faster "
            "connections on mobile and fewer errors on poor networks; the takeaway beneath: the "
            "canary has earned the May step"
        ),
        "assumes": "The audience has seen what the canary measured",
        "hands_off": "The results justify widening the rollout in May",
        "data_references": ["ttfb_p75", "mobile_setup", "poor_network_errors"],
        "look": (
            "Three bullets on the left, one per result; the takeaway in the template's callout "
            "beneath them"
        ),
    },
    {
        "purpose": "Close with what each team must do before the May step",
        "content_brief": (
            "What each team must do before May 2026, one bullet each: the web platform team "
            "widens HTTP/3 to every static asset, the service teams check their health checks "
            "over HTTP/3, and support learns to spot a browser falling back to HTTP/2; end with "
            "the call to action"
        ),
        "assumes": "The audience has seen the plan and the results",
        "hands_off": "Approve the May step, and each team finishes its part before then",
        "look": (
            "Three short bullets, one per team; the call to action in the template's callout "
            "beneath them"
        ),
    },
]
# The build's own deck style: only the pieces this deck needs that Meridian lacks (a dated
# timeline, a KPI band for more figures than the template's three stat cards hold, and a note),
# in Meridian tokens. The template's callout and bullets are reused, so they are not restated.
TECH_STYLE = {
    "css": (
        "/* Rollout deck style on Meridian: a dated timeline, a KPI band and notes. The "
        "template's callout and bullets are reused. */\n"
        ".dk-timeline {\n"
        "  display: grid;\n"
        "  grid-auto-flow: column;\n"
        "  grid-auto-columns: 1fr;\n"
        "  gap: var(--space-md);\n"
        "  margin: 0;\n"
        "  padding: 0;\n"
        "  list-style: none;\n"
        "  border-top: 4px solid var(--brand-core-primary);\n"
        "}\n"
        ".dk-timeline li {\n"
        "  position: relative;\n"
        "  padding-top: var(--space-md);\n"
        "  font-size: var(--fs-body);\n"
        "  color: var(--brand-core-text);\n"
        "}\n"
        "/* A dot on the rule above each milestone. */\n"
        ".dk-timeline li::before {\n"
        "  content: \"\";\n"
        "  position: absolute;\n"
        "  top: -9px;\n"
        "  left: 0;\n"
        "  width: 14px;\n"
        "  height: 14px;\n"
        "  border-radius: 50%;\n"
        "  background: var(--brand-core-primary);\n"
        "}\n"
        ".dk-timeline time {\n"
        "  display: block;\n"
        "  margin-bottom: 4px;\n"
        "  font-size: var(--fs-eyebrow);\n"
        "  font-weight: 700;\n"
        "  letter-spacing: 0.06em;\n"
        "  text-transform: uppercase;\n"
        "  color: var(--brand-core-primary);\n"
        "}\n"
        "\n"
        ".dk-kpi-band {\n"
        "  display: grid;\n"
        "  grid-auto-flow: column;\n"
        "  grid-auto-columns: 1fr;\n"
        "  margin: 0;\n"
        "  padding: var(--space-md) 0;\n"
        "  border-top: 1px solid var(--brand-core-border);\n"
        "  border-bottom: 1px solid var(--brand-core-border);\n"
        "}\n"
        ".dk-kpi-band > div { padding: 0 var(--space-md); "
        "border-left: 1px solid var(--brand-core-border); }\n"
        ".dk-kpi-band > div:first-child { padding-left: 0; border-left: 0; }\n"
        ".dk-kpi-value {\n"
        "  display: block;\n"
        "  font-size: var(--fs-title);\n"
        "  font-weight: 700;\n"
        "  line-height: 1.1;\n"
        "  font-variant-numeric: tabular-nums;\n"
        "  color: var(--brand-core-primary);\n"
        "}\n"
        ".dk-kpi-label { display: block; margin-top: 4px; font-size: var(--fs-body); "
        "color: var(--brand-core-text); }\n"
        "\n"
        ".dk-note { margin: var(--space-sm) 0 0; font-size: var(--fs-caption); "
        "color: var(--brand-core-muted); }\n"
    ),
    "components": [
        {
            "name": "dated timeline",
            "class_names": ["dk-timeline"],
            "use": (
                "A rollout or plan as three to six dated milestones, left to right; each item "
                "opens with its date in a <time> element."
            ),
            "example_html": (
                '<ol class="dk-timeline"><li><time>Mar 2026</time>Canary on 5% of traffic</li>'
                "<li><time>May 2026</time>Every static asset</li></ol>"
            ),
        },
        {
            "name": "KPI band",
            "class_names": ["dk-kpi-band", "dk-kpi-value", "dk-kpi-label"],
            "use": (
                "Four to six headline figures in one row, where the template's three stat cards "
                "are too few; one value and its label per item."
            ),
            "example_html": (
                '<div class="dk-kpi-band"><div><span class="dk-kpi-value">310 ms</span>'
                '<span class="dk-kpi-label">Time to first byte, p75</span></div>'
                '<div><span class="dk-kpi-value">61%</span>'
                '<span class="dk-kpi-label">Requests over HTTP/3</span></div></div>'
            ),
        },
        {
            "name": "note",
            "class_names": ["dk-note"],
            "use": "A one-line caveat or source under an exhibit.",
            "example_html": '<p class="dk-note">Measured on the canary, 5% of traffic.</p>',
        },
    ],
}
# Deck 2's looks for restyle_deck, by position: what a deck-style build would have given it.
RESTYLE_LOOKS = {
    0: "Meridian cover: the deck title large and the subtitle beneath it; no deck-style pieces",
    1: "The three pain points as bullets; the opportunity cost in a dk-callout beneath them",
    2: (
        "The four patterns as bullets on the left; a short dk-code listing of a system prompt "
        "with a structured-output schema on the right; when to combine them in a dk-callout"
    ),
    3: "The template's three stat cards, one per figure; their source in a dk-note beneath them",
    4: "The evaluation loop as dk-steps on the left; the commentary bullets on the right",
    5: "The five-item checklist as dk-steps; the call to action in a dk-callout beneath it",
}
RESTYLE_MESSAGE = (
    "I'll give every code listing a dark background with light text, using the brand's darkest "
    "ink token, and lighten the keyword, function, string and comment colours so they stay "
    "readable on it. Nothing else changes and no slide is rebuilt."
)
RESTYLE_RENAMED_MESSAGE = (
    "I'll restyle the code listings as a new dark piece, dk-code-dark: a dark background with "
    "light text. Nothing else changes and no slide is rebuilt."
)


def _checklist_brief(deck: dict, position: int) -> str:
    old, new = CHECKLIST_ITEMS
    brief = deck["slides"][position]["content_brief"]
    assert brief.count(old) == 1, position
    return brief.replace(old, new)


def _beside_brief(deck: dict, position: int) -> str:
    old, new = BESIDE_REVISION
    brief = deck["slides"][position]["content_brief"]
    assert brief.count(old) == 1, position
    return brief.replace(old, new)


def _edited_deck_spec():
    """The deck-2 spec with ONLY slides[2].content_brief revised for the edit request."""
    return m._revised_spec(case.gold_deck_spec(DECK), {EDIT_POS: EDIT_BRIEF})


def _write(out, cid, kind, fault, expect, reference, should_fail):
    """Same as the train writer but with the held-out payload."""
    d = out / cid
    d.mkdir(parents=True, exist_ok=True)
    (d / "case.yaml").write_text(m.yaml.safe_dump({
        "kind": kind, "fault": fault, "expect": expect, "design_system_active": True,
    }, sort_keys=False))
    m._dump(d / "payload.json", _payload(cid))
    m._dump(d / "reference.json", reference)
    m._dump(d / "calibration.json", {"should_fail": should_fail})


def generate(out_dir: pathlib.Path | None = None):
    """Write the cases into ``out_dir`` (default: the committed ``CASES_DIR``)."""
    out = pathlib.Path(out_dir) if out_dir is not None else CASES_DIR
    gold = case.gold_deck_spec(DECK)
    discuss = m._out("discuss", "Happy to talk it through; what would you like to know?")

    _write(
        out, "build_request", "positive", "", {"intent": "build"},
        m._out("build", "Here is a 6-slide deck arguing that structured prompt optimisation "
                        "beats ad-hoc prompting.", deck_spec=gold),
        discuss,
    )
    edit_msg = "I'll show the four patterns on slide 3 as four cards instead of a bullet list."
    _write(
        out, "edit_request", "mutation",
        "edit of slide 3 (position 2): a 1-based position slips off by one",
        {"intent": "edit", "positions": [EDIT_POS]},
        m._out("edit", edit_msg, target_positions=[EDIT_POS], deck_spec=_edited_deck_spec()),
        m._out("edit", edit_msg, target_positions=[EDIT_POS + 1]),
    )
    _write(
        out, "ask_data", "mutation",
        "deck on the team's own prompt success rates with no data available",
        {"intent": "ask_data"},
        m._out("ask_data",
               "I need your measured prompt success rates by model for the last quarter "
               "before I can build this.",
               data_request={
                   "metric": "prompt success rate", "time_bound": "last quarter",
                   "grouping": "model", "units": None, "tool_preferences": [],
               }),
        m._out("build", "Here is a deck on your prompt success rates.", deck_spec=gold),
    )
    _write(
        out, "confirm_design", "mutation",
        "design switch must be proposed, not applied to deck_spec",
        {"intent": "confirm_design_contract"},
        m._out("confirm_design_contract",
               "Do you want to re-theme this deck with the Acme design system? "
               "Every slide will be rebuilt in the new design.",
               proposed_design_contract={
                   "design_system_id": m.ACME_ID, "template_id": m.ACME_TEMPLATE,
               }),
        m._out("edit", "Restyling the slides in the Acme design system now.",
               target_positions=[0]),
    )
    _write(
        out, "discuss", "positive", "", {"intent": "discuss"},
        m._out("discuss",
               "Few-shot examples work best when the output format or style is hard to describe; "
               "chain-of-thought helps when the task needs multi-step reasoning."),
        m._out("build", "Here is a deck comparing few-shot and chain-of-thought prompting.",
               deck_spec=gold),
    )

    # #313: intent and slide-reference cases on the same deck.
    _write(
        out, "edit_polite_ordinal", "mutation",
        "a polite question with an ordinal is still an edit request: act on position 3, do not ask",
        {"intent": "edit", "positions": [3]},
        m._out("edit", "I'll make the iteration rounds the headline stat on the fourth slide.",
               target_positions=[3], deck_spec=m._revised_spec(gold, {3: POLITE_BRIEF_3})),
        m._out("discuss",
               "Sure. Should the iteration figure replace the slide title or sit above the other "
               "stats?"),
    )
    last_reference = m._out(
        "edit",
        "I'll move the call to action to the top of the final slide, ahead of the checklist.",
        target_positions=[5], deck_spec=m._revised_spec(gold, {5: LAST_BRIEF_5}),
    )
    _write(
        out, "edit_last_slide", "mutation",
        "edit of the final slide of six (position 5): a 1-based position slips off by one",
        {"intent": "edit", "positions": [5]},
        last_reference, m._slipped(last_reference),
    )
    multi_reference = m._out(
        "edit", "I'll drop the callouts on slides 2 and 3.",
        target_positions=[1, 2], deck_spec=m._revised_spec(gold, MULTI_BRIEFS),
    )
    _write(
        out, "edit_multi_slide", "mutation",
        "edit of slides 2 and 3 (positions 1, 2): a 1-based list slips every position off by one",
        {"intent": "edit", "positions": [1, 2]},
        multi_reference, m._slipped(multi_reference),
    )
    _write(
        out, "discuss_slide_question", "mutation",
        "a question that names slide 2 is a discuss turn: answer it, do not move slide 2",
        {"intent": "discuss"},
        m._out("discuss",
               "Slide 2 sets out what ad-hoc prompting costs, so the four techniques on slide 3 "
               "land as the answer to a problem the audience already feels. I can swap them if "
               "you prefer."),
        m._out("edit", "I'll move slide 2 after the techniques.", target_positions=[1]),
    )

    # #314: add a slide to the same deck. ``positions`` and ``inserted`` are in the revised
    # deck's numbering; the references are the gold spec with the new slide spliced in.
    anchor = m._out(
        "edit",
        "I'll add a new slide 5 with a worked before-and-after prompt example, just before the "
        "workflow slide.",
        target_positions=[4], deck_spec=m._inserted_spec(gold, {4: ANCHOR_SLIDE}),
    )
    _write(
        out, "add_slide_anchor", "mutation",
        "add before slide 5 (position 4): the new slide takes position 4, only it is built, and "
        "the old slide 5 shifts unchanged",
        {"intent": "edit", "positions": [4], "inserted": [4]},
        anchor,
        m._retargeted(
            anchor, [4], m._inserted_spec(gold, {4: {**ANCHOR_SLIDE, **OFF_REQUEST_SLIDE}})
        ),
    )
    end = m._out(
        "edit", "I'll add a glossary of the prompt terms as a new final slide, slide 7.",
        target_positions=[6], deck_spec=m._inserted_spec(gold, {6: END_SLIDE}),
    )
    _write(
        out, "add_slide_end", "mutation",
        "add a final slide to a deck of six (new slide at position 6): append it; replacing the "
        "last slide (position 5) loses the closing slide",
        {"intent": "edit", "positions": [6], "inserted": [6]},
        end,
        m._retargeted(end, [5], m._replaced_spec(gold, {5: END_SLIDE})),
    )
    as_number = m._out(
        "edit",
        "I'll add a new slide 4 on common prompt anti-patterns; the impact slide moves to slide 5.",
        target_positions=[3], deck_spec=m._inserted_spec(gold, {3: AS_NUMBER_SLIDE}),
    )
    _write(
        out, "add_slide_as_number", "mutation",
        "a new fourth slide (position 3): it takes position 3 and the old slide 4 shifts up, one "
        "place late is wrong",
        {"intent": "edit", "positions": [3], "inserted": [3]},
        as_number,
        m._retargeted(as_number, [4], m._inserted_spec(gold, {4: AS_NUMBER_SLIDE})),
    )
    and_revise = m._out(
        "edit",
        "I'll add slide 4 on versioning prompts after slide 3, and add versioning to the "
        "checklist on the final slide, now slide 7.",
        target_positions=[3, 6],
        deck_spec=m._inserted_spec(gold, {3: AND_REVISE_SLIDE}, {6: _checklist_brief(gold, 5)}),
    )
    _write(
        out, "add_slide_and_revise", "mutation",
        "add after slide 3 (position 2): the new slide is position 3 and the checklist on the "
        "final slide (now position 6) must be revised to include it",
        {"intent": "edit", "positions": [3, 6], "inserted": [3]},
        and_revise,
        m._retargeted(and_revise, [3], m._inserted_spec(gold, {3: AND_REVISE_SLIDE})),
    )

    # #314 follow-up (manual insert): deck 2 with a blank slide at BLANK_AT. The references leave
    # every other slide exactly as the payload has it (the blank included, unless filled).
    blank_deck = m._blank_deck(gold, BLANK_AT)
    fill = m._out(
        "edit",
        "I'll make the blank slide 4 a quick guide to which pattern fits which kind of task.",
        target_positions=[BLANK_AT],
        deck_spec=m._replaced_spec(blank_deck, {BLANK_AT: FILLED_SLIDE}),
    )
    _write(
        out, "fill_blank_slide", "mutation",
        "fill the blank slide 4 (position 3) in place: a new slide beside it leaves the blank "
        "empty and every later slide one place on",
        {"intent": "edit", "positions": [BLANK_AT], "inserted": []},
        fill,
        m._retargeted(fill, [BLANK_AT], m._inserted_spec(blank_deck, {BLANK_AT: FILLED_SLIDE})),
    )
    beside = m._out(
        "edit", "I'll add a one-line takeaway beneath the three stats on the fifth slide.",
        target_positions=[BESIDE_POS],
        deck_spec=m._revised_spec(blank_deck, {BESIDE_POS: _beside_brief(blank_deck, BESIDE_POS)}),
    )
    _write(
        out, "edit_beside_blank", "mutation",
        "edit of the fifth slide (position 4), the slide after the blank slide 4 (position 3): "
        "change only the fifth slide; filling the blank too builds a slide nobody asked for",
        {"intent": "edit", "positions": [BESIDE_POS], "inserted": []},
        beside,
        m._retargeted(
            beside, [BLANK_AT, BESIDE_POS],
            m._replaced_spec(beside["deck_spec"], {BLANK_AT: INVENTED_FILL}),
        ),
    )

    # Architect edit operations (spec §9): the references answer in operations against deck 2.
    # ``positions`` is the rebuild set and ``inserted`` the new slides, both in the edited deck's
    # numbering; ``layout`` (persisted positions, null = new) says which slide went where.
    delete_message = (
        "I'll delete slide 4, the impact numbers; the workflow and checklist slides move up to "
        "slides 4 and 5."
    )
    _write(
        out, "delete_slide", "mutation",
        "delete slide 4 (position 3): only it goes, nothing is rebuilt and the workflow and "
        "checklist slides move up unchanged; deleting position 4 (slide 5) is the 1-based slip",
        {"intent": "edit", "positions": [], "inserted": [],
         "layout": [p for p in range(6) if p != DELETE_POS]},
        m._operations_out(delete_message, [m._op("delete", position=DELETE_POS)]),
        m._operations_out(delete_message, [m._op("delete", position=DELETE_POS + 1)]),
    )
    move_message = (
        "I'll move slide 5, the workflow, to straight after slide 3: it becomes slide 4, and the "
        "impact numbers become slide 5."
    )
    _write(
        out, "move_slide", "mutation",
        "move slide 5 (position 4) to after slide 3 (position 2): a reorder that rebuilds "
        "nothing; slipping both numbers by one moves the checklist after the impact slide instead",
        {"intent": "edit", "positions": [], "inserted": [], "layout": [0, 1, 2, 4, 3, 5]},
        m._operations_out(
            move_message, [m._op("move", position=MOVE_POS, after_position=MOVE_AFTER)]),
        m._operations_out(
            move_message, [m._op("move", position=MOVE_POS + 1, after_position=MOVE_AFTER + 1)]),
    )
    replace_ops = [
        m._op("replace", position=REPLACE_POS, slides=[m._content(s) for s in REPLACE_SLIDES]),
    ]
    replace_positions = list(range(REPLACE_POS, REPLACE_POS + len(REPLACE_SLIDES)))
    replace_message = (
        "I'll replace slide 3 with three slides: slide 3 becomes an overview of the four "
        "patterns, and new slides 4 and 5 cover system prompts with few-shot examples, and "
        "chain-of-thought with structured output. The impact, workflow and checklist slides become "
        "slides 6 to 8."
    )
    _write(
        out, "replace_slide_expand", "mutation",
        "replace slide 3 (position 2) with three slides: the first rewrites position 2 in place "
        "and two new slides follow at positions 3-4; the same plan as a whole grown deck_spec is "
        "refused by production's alignment as ambiguous",
        {"intent": "edit", "positions": replace_positions, "inserted": replace_positions[1:]},
        m._operations_out(replace_message, replace_ops),
        m._out("edit", replace_message, target_positions=replace_positions,
               deck_spec=m._composed_spec(gold, replace_ops)),
    )
    mixed_ops = [
        m._op("delete", position=MIXED_DELETE),
        m._op("update", position=MIXED_UPDATE,
              slides=[m._revised_content(gold, MIXED_UPDATE, MIXED_CALLOUT)]),
        m._op("replace", position=MIXED_REPLACE, slides=[m._content(s) for s in MIXED_SLIDES]),
    ]
    mixed_message = (
        "I'll delete slide 1, the cover, expand the pain points into three slides — slides 1, 2 "
        "and 3, one per pain point — and change the callout on the techniques slide, now slide 4, "
        "to say when to combine few-shot examples with chain-of-thought."
    )
    _write(
        out, "mixed_operations", "mutation",
        "delete slide 1 (position 0), revise slide 3 (position 2) and expand slide 2 (position 1) "
        "into three, in one edit: production rebuilds positions 0-3 of the 7-slide result and "
        "nothing else; dropping one of the three pain-point slides builds only two",
        {"intent": "edit", "positions": [0, 1, 2, 3], "inserted": [1, 2],
         "layout": [1, None, None, 2, 3, 4, 5]},
        m._operations_out(mixed_message, mixed_ops),
        m._operations_out(mixed_message, [
            mixed_ops[0], mixed_ops[1],
            m._op("replace", position=MIXED_REPLACE,
                  slides=[m._content(s) for s in MIXED_SLIDES[:2]]),
        ]),
    )

    # The arc-review sweeper's re-description on deck 2: the full deck_spec as it stands, every
    # position targeted, no operations; the arc as deck_changes is dropped.
    _write(
        out, "redescribe_deck", "mutation", m.REDESCRIBE_FAULT,
        {"intent": "edit", "full_deck_spec": True},
        m._redescribed(gold, REDESCRIBE_MESSAGE),
        m._arc_as_deck_changes(REDESCRIBE_ARC_MESSAGE, REDESCRIBED_ARC),
    )

    # Architect deck style: the technical build on its own pieces (its should_fail authors no deck
    # style and no looks) and the restyle of deck 2's code blocks (its should_fail renames dk-code).
    tech = m._technical_deck(TECH_DECK, TECH_SLIDES, TECH_STYLE)
    _write(
        out, "build_technical_deck", "positive", "", {"intent": "build", "deck_style": True},
        m._out("build", TECH_BUILD_MESSAGE, deck_spec=tech),
        m._out("build", TECH_BUILD_MESSAGE, deck_spec=m._unstyled(tech)),
    )
    _write(
        out, "restyle_deck", "mutation", m.RESTYLE_FAULT,
        {"intent": "edit", "positions": [], "deck_style_keeps": list(m.RESTYLE_KEEPS)},
        m._restyled(RESTYLE_MESSAGE),
        m._restyled(RESTYLE_RENAMED_MESSAGE, renamed=True),
    )


if __name__ == "__main__":
    generate()

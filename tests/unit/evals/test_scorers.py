import pytest

from evals.harness import render, scorers
from src.domain.deck_spec import DeckSpec
from src.domain.finding import CRITERIA

OBJECTIVE = sorted(n for n, c in CRITERIA.items() if c.objective)
SUBJECTIVE = sorted(n for n, c in CRITERIA.items() if not c.objective)
REVIEWERS = ["build_reviewer", "fix_reviewer", "deck_reviewer"]


def _f(criterion, idx):
    return {"criterion": criterion, "slide_index": idx, "objective": CRITERIA[criterion].objective}


def _assert_result(res):
    assert isinstance(res, tuple) and len(res) == 2
    assert isinstance(res[0], bool)
    assert isinstance(res[1], str) and res[1].strip()


# ---- brief Step 1 tests (verbatim) ----

def test_contract_fails_on_none():
    assert scorers.contract_score(None)[0] is False
    assert scorers.contract_score({"html": "x"})[0] is True

def test_expected_category_reviewer_exact_match():
    out = {"findings": [{"criterion": "rogue_colour", "slide_index": 2, "objective": True}], "verdict": "surfaced"}
    assert scorers.expected_category_score("build_reviewer", out, {"criteria": ["rogue_colour"], "positions": [2]})[0] is True

def test_expected_category_reviewer_extra_objective_finding_fails():
    out = {"findings": [
        {"criterion": "rogue_colour", "slide_index": 2, "objective": True},
        {"criterion": "overflow", "slide_index": 2, "objective": True}]}
    assert scorers.expected_category_score("build_reviewer", out, {"criteria": ["rogue_colour"], "positions": [2]})[0] is False

def test_expected_category_reviewer_missing_planted_criterion_fails():
    assert scorers.expected_category_score("build_reviewer", {"findings": []}, {"criteria": ["overflow"], "positions": [3]})[0] is False

def test_architect_intent_match():
    assert scorers.expected_category_score("architect", {"intent": "build", "target_positions": []}, {"intent": "build"})[0] is True
    assert scorers.expected_category_score("architect", {"intent": "edit", "target_positions": [2,3]}, {"intent": "edit", "positions": [3,2]})[0] is True

def test_render_measures_rejects_style_tag_and_overflow():
    clean = render.RenderMeasures(0, 7.0, (), (), True)
    assert scorers.render_measures_score(clean, "<section class='slide'></section>")[0] is True
    assert scorers.render_measures_score(clean, "<style>x</style>")[0] is False
    dirty = render.RenderMeasures(120, 7.0, (), (), True)
    assert scorers.render_measures_score(dirty, "<section></section>")[0] is False
    nil_render = render.RenderMeasures(0, 7.0, (), (), False)
    assert scorers.render_measures_score(nil_render, "<section class='slide'></section>")[0] is False


# ---- added behavioural cases ----

def test_registry_assumptions():
    assert "brief_not_delivered" in SUBJECTIVE
    assert {"overflow", "rogue_colour", "contrast_failure", "source_contradiction"} <= set(OBJECTIVE)


@pytest.mark.parametrize("agent", REVIEWERS)
@pytest.mark.parametrize("crit", OBJECTIVE)
def test_every_objective_criterion_matches_when_planted(agent, crit):
    out = {"findings": [_f(crit, 4)]}
    assert scorers.expected_category_score(agent, out, {"criteria": [crit], "positions": [4]})[0] is True


@pytest.mark.parametrize("planted", OBJECTIVE)
@pytest.mark.parametrize("extra", OBJECTIVE)
def test_any_unplanted_objective_finding_fails(planted, extra):
    if planted == extra:
        pytest.skip("same criterion")
    out = {"findings": [_f(planted, 1), _f(extra, 5)]}
    assert scorers.expected_category_score("build_reviewer", out, {"criteria": [planted], "positions": [1]})[0] is False


@pytest.mark.parametrize("extra", SUBJECTIVE)
def test_extra_subjective_finding_still_passes(extra):
    out = {"findings": [_f("rogue_colour", 2), _f(extra, 7)]}
    assert scorers.expected_category_score("build_reviewer", out, {"criteria": ["rogue_colour"], "positions": [2]})[0] is True


@pytest.mark.parametrize("crit", OBJECTIVE)
def test_planted_criterion_at_wrong_position_fails(crit):
    out = {"findings": [_f(crit, 5)]}
    assert scorers.expected_category_score("build_reviewer", out, {"criteria": [crit], "positions": [2]})[0] is False


def test_planted_criterion_at_right_position_plus_wrong_position_duplicate_passes():
    out = {"findings": [_f("overflow", 2), _f("overflow", 6)]}
    assert scorers.expected_category_score("build_reviewer", out, {"criteria": ["overflow"], "positions": [2]})[0] is True


def test_multiple_planted_positions_all_required():
    expect = {"criteria": ["overflow"], "positions": [1, 2]}
    both = {"findings": [_f("overflow", 1), _f("overflow", 2)]}
    one = {"findings": [_f("overflow", 1)]}
    assert scorers.expected_category_score("deck_reviewer", both, expect)[0] is True
    assert scorers.expected_category_score("deck_reviewer", one, expect)[0] is False


def test_criterion_at_other_planted_position_is_not_enough():
    # criterion A at position 1 and criterion B at position 2 does not satisfy A@2
    out = {"findings": [_f("overflow", 1), _f("rogue_colour", 2)]}
    expect = {"criteria": ["overflow"], "positions": [2]}
    assert scorers.expected_category_score("build_reviewer", out, expect)[0] is False


@pytest.mark.parametrize("agent", REVIEWERS)
def test_unknown_criterion_fails_and_is_named(agent):
    out = {"findings": [{"criterion": "made_up_criterion", "slide_index": 2, "objective": True}]}
    ok, why = scorers.expected_category_score(agent, out, {"criteria": [], "positions": []})
    assert ok is False
    assert "made_up_criterion" in why


def test_unknown_criterion_fails_even_with_planted_present():
    out = {"findings": [_f("overflow", 3),
                        {"criterion": "made_up_criterion", "slide_index": 1, "objective": False}]}
    ok, why = scorers.expected_category_score("build_reviewer", out, {"criteria": ["overflow"], "positions": [3]})
    assert ok is False
    assert "made_up_criterion" in why


@pytest.mark.parametrize("agent", REVIEWERS)
def test_clean_positive_no_findings_passes(agent):
    assert scorers.expected_category_score(agent, {"findings": []}, {"criteria": [], "positions": []})[0] is True


@pytest.mark.parametrize("crit", OBJECTIVE)
def test_clean_positive_any_objective_finding_fails(crit):
    out = {"findings": [_f(crit, 1)]}
    assert scorers.expected_category_score("build_reviewer", out, {"criteria": [], "positions": []})[0] is False


@pytest.mark.parametrize("crit", SUBJECTIVE)
def test_clean_positive_subjective_finding_passes(crit):
    out = {"findings": [_f(crit, 1)]}
    assert scorers.expected_category_score("build_reviewer", out, {"criteria": [], "positions": []})[0] is True


def test_fix_reviewer_verdict_checked_when_present():
    out = {"findings": [], "verdict": "fixed"}
    base = {"criteria": [], "positions": []}
    assert scorers.expected_category_score("fix_reviewer", out, {**base, "verdict": "fixed"})[0] is True
    assert scorers.expected_category_score("fix_reviewer", out, {**base, "verdict": "surfaced"})[0] is False
    # no verdict expectation -> not checked
    assert scorers.expected_category_score("fix_reviewer", out, base)[0] is True


def test_data_analyst_outcome():
    assert scorers.expected_category_score("data_analyst", {"outcome": "success"}, {"outcome": "success"})[0] is True
    assert scorers.expected_category_score("data_analyst", {"outcome": "missing_data"}, {"outcome": "success"})[0] is False
    assert scorers.expected_category_score("data_analyst", {"outcome": "no_tool"}, {"outcome": "success"})[0] is False


def test_architect_intent_mismatch_fails():
    assert scorers.expected_category_score("architect", {"intent": "edit", "target_positions": []}, {"intent": "build"})[0] is False


def test_architect_edit_positions_compared_as_set():
    expect = {"intent": "edit", "positions": [1, 4, 2]}
    assert scorers.expected_category_score("architect", {"intent": "edit", "target_positions": [4, 2, 1]}, expect)[0] is True
    assert scorers.expected_category_score("architect", {"intent": "edit", "target_positions": [1, 2]}, expect)[0] is False  # missing
    assert scorers.expected_category_score("architect", {"intent": "edit", "target_positions": [1, 2, 4, 5]}, expect)[0] is False  # extra
    assert scorers.expected_category_score("architect", {"intent": "edit", "target_positions": [1, 1, 2, 4]}, expect)[0] is True  # dup


@pytest.mark.parametrize("kwargs", [
    dict(overflow_px=1),
    dict(overflow_px=120),
    dict(min_contrast=4.49),
    dict(min_contrast=1.0),
    dict(off_palette=("#ff00ff",)),
    dict(console_errors=("boom",)),
    dict(rendered=False),
    dict(safe_area_px=0.5),
    dict(safe_area_px=19.0),
])
def test_render_measures_each_failure_alone(kwargs):
    base = dict(overflow_px=0, min_contrast=7.0, off_palette=(), console_errors=(), rendered=True)
    m = render.RenderMeasures(**{**base, **kwargs})
    ok, why = scorers.render_measures_score(m, "<section></section>")
    assert ok is False
    assert why.strip()


def test_render_measures_contrast_boundary_passes():
    m = render.RenderMeasures(0, 4.5, (), (), True)
    assert scorers.render_measures_score(m, "<section></section>")[0] is True


def test_render_measures_style_tag_case_insensitive():
    m = render.RenderMeasures(0, 7.0, (), (), True)
    assert scorers.render_measures_score(m, "<STYLE>x</STYLE>")[0] is False


def test_all_scorers_return_bool_and_nonempty_rationale():
    clean = render.RenderMeasures(0, 7.0, (), (), True)
    dirty = render.RenderMeasures(9, 2.0, ("#f0f",), ("e",), False)
    results = [
        scorers.contract_score(None),
        scorers.contract_score({"a": 1}),
        scorers.expected_category_score("architect", {"intent": "build", "target_positions": []}, {"intent": "build"}),
        scorers.expected_category_score("architect", {"intent": "edit", "target_positions": []}, {"intent": "build"}),
        scorers.expected_category_score("data_analyst", {"outcome": "success"}, {"outcome": "success"}),
        scorers.expected_category_score("data_analyst", {"outcome": "no_tool"}, {"outcome": "success"}),
        scorers.expected_category_score("build_reviewer", {"findings": []}, {"criteria": [], "positions": []}),
        scorers.expected_category_score("build_reviewer", {"findings": [_f("overflow", 1)]}, {"criteria": [], "positions": []}),
        scorers.render_measures_score(clean, "<section></section>"),
        scorers.render_measures_score(dirty, "<style></style>"),
    ]
    for r in results:
        _assert_result(r)


# ---- review additions ----

def test_planted_criterion_without_positions_must_still_appear():
    expect = {"criteria": ["arc_gap"]}
    assert scorers.expected_category_score("deck_reviewer", {"findings": []}, expect)[0] is False
    assert scorers.expected_category_score("deck_reviewer", {"findings": [_f("arc_gap", -1)]}, expect)[0] is True


def test_deck_level_position_minus_one():
    out = {"findings": [_f("arc_gap", -1)]}
    assert scorers.expected_category_score("deck_reviewer", out, {"criteria": ["arc_gap"], "positions": [-1]})[0] is True
    assert scorers.expected_category_score("deck_reviewer", out, {"criteria": ["arc_gap"], "positions": [0]})[0] is False


@pytest.mark.parametrize("agent", ["architect", "data_analyst"] + REVIEWERS)
@pytest.mark.parametrize("bad", [None, {}, {"findings": None}])
def test_malformed_structured_scores_fail_not_crash(agent, bad):
    ok, why = scorers.expected_category_score(agent, bad, {"intent": "build", "outcome": "success", "criteria": ["overflow"], "positions": [1]})
    assert ok is False
    assert why.strip()


def test_render_measures_safe_area_intrusion_is_named():
    m = render.RenderMeasures(0, 7.0, (), (), True, 19.4)
    ok, why = scorers.render_measures_score(m, "<section></section>")
    assert ok is False
    assert "19.4" in why and "safe area" in why.lower()


def test_render_measures_safe_area_defaults_clean():
    assert render.RenderMeasures(0, 7.0, (), (), True).safe_area_px == 0.0


# ---------------------------------------------------------------------------
# contract_score: failure reason visibility
# ---------------------------------------------------------------------------

def test_contract_score_single_positional_arg_still_works():
    ok, why = scorers.contract_score({"position": 1})
    assert ok is True
    bad, why_bad = scorers.contract_score(None)
    assert bad is False
    assert "Contract failed: structured output is None" in why_bad


def test_contract_score_fail_includes_status_and_detail():
    ok, why = scorers.contract_score(
        None, status="incomplete", error_detail="stop_reason=max_tokens")
    assert ok is False
    assert why.startswith("Contract failed: structured output is None")
    assert "status=incomplete" in why
    assert "stop_reason=max_tokens" in why


def test_contract_score_fail_without_detail_still_names_status():
    ok, why = scorers.contract_score(None, status="incomplete", error_detail=None)
    assert ok is False
    assert "status=incomplete" in why


def test_contract_score_truncates_long_detail_with_marker():
    detail = "A" * 5000
    ok, why = scorers.contract_score(None, status="incomplete", error_detail=detail)
    assert ok is False
    assert "A" * 2000 in why
    assert "A" * 2001 not in why
    assert len(why) < 2000 + 400
    assert not why.endswith("A"), "truncated detail must end with a visible marker"


def test_contract_score_short_detail_not_truncated():
    detail = "B" * 1999
    ok, why = scorers.contract_score(None, status="incomplete", error_detail=detail)
    assert detail in why
    assert not why.endswith("...") and "truncat" not in why.lower()


def test_contract_score_detail_at_limit_is_not_truncated():
    detail = "C" * 2000
    _, why = scorers.contract_score(None, status="incomplete", error_detail=detail)
    assert why.endswith(": " + detail)


def test_contract_score_detail_one_over_limit_is_truncated():
    _, why = scorers.contract_score(None, status="incomplete", error_detail="D" * 2001)
    assert why.endswith(": " + "D" * 2000 + " ... [truncated]")


def test_contract_score_empty_detail_adds_nothing():
    _, why = scorers.contract_score(None, status="incomplete", error_detail="")
    assert why == "Contract failed: structured output is None (status=incomplete)"


def test_contract_score_pass_rationale_unchanged_by_extra_info():
    base = scorers.contract_score({"x": 1})
    assert base == (True, "Contract passed: structured output is present")
    assert scorers.contract_score({"x": 1}, status="completed", error_detail=None) == base


# ---------------------------------------------------------------------------
# #314 Task 8 (D10, C17): an insert is scored with production semantics.
#
# Names this block fixes for the implementer:
# * ``expected_category_score(agent_key, structured, expect, *, reference=None,
#   current_deck_spec=None)``. It stays callable with three positional args.
#   ``reference`` is the case's reference OUTPUT (a dict carrying ``deck_spec``);
#   ``current_deck_spec`` is the payload's ``current_deck_spec`` dict.
# * ``scorers.DECK_LEVEL_FIELDS``: the deck-level tuple the insert check compares.
# * ``expect["inserted"]`` and ``expect["positions"]`` are in the RETURNED spec's
#   re-stamped numbering (indices in position order), because production
#   re-stamps before it uses them. Production also ignores the model's
#   ``target_positions`` on an insert turn (D3), so they never fail a row.
#
# Every deck below is hand-built: a 10-slide current deck S0..S9. "S9~content_brief"
# is S9 with only its content_brief rewritten; NEW is the added slide.
# ---------------------------------------------------------------------------


OLD10 = [f"S{i}" for i in range(10)]
# "Add a slide after slide 8 and update the summary on the last slide": the new
# slide lands at 8, and old S9 (now at 10) is the requested revision.
REVISED = OLD10[:8] + ["NEW", "S8", "S9~content_brief"]
REVISE_EXPECT = {"intent": "edit", "positions": [8, 10], "inserted": [8]}
# "Add a final slide": an append at 10.
APPEND_EXPECT = {"intent": "edit", "positions": [10], "inserted": [10]}
FIVE_DECK_LEVEL_FIELDS = ("audience", "purpose", "argument", "call_to_action", "narrative_arc")


def _spec_slide(name, position):
    return {
        "position": position,
        "purpose": f"{name} purpose: make the {name} point",
        "content_brief": f"{name} brief: the evidence for {name}",
        "assumes": f"{name} assumes: the audience saw the slide before {name}",
        "hands_off": f"{name} hands off: the question {name} leaves open",
        "data_references": [f"{name.lower()}_metrics"],
        "slide_type": None,
        "template_section_index": None,
    }


def _spec(tokens, positions=None, **deck_changes):
    """A DeckSpec dict whose slides are ``tokens`` at ``positions`` (default 0..n-1)."""
    if positions is None:
        positions = list(range(len(tokens)))
    assert len(positions) == len(tokens)
    slides = []
    for token, position in zip(tokens, positions):
        name, *rewritten = token.split("~")
        slide = _spec_slide(name, position)
        for field in rewritten:
            slide[field] = f"{slide[field]} (rewritten)"
        slides.append(slide)
    deck = {
        "title": "Why HTML slides",
        "audience": "Engineering leads choosing a presentation tool",
        "purpose": "Persuade the room to pilot HTML slides",
        "argument": "HTML slides beat static decks on every axis the audience cares about",
        "call_to_action": "Pilot HTML slides for next quarter's all-hands",
        "narrative_arc": ["Why the tool matters", "The evidence", "The verdict"],
        "design_contract": {"design_system_id": 7, "template_id": None, "slide_style_id": None},
        "resolved_data": {"synthesis": "No figures needed", "figures": [], "gaps": []},
        "slides": slides,
    }
    deck.update(deck_changes)
    return deck


def _out(spec, targets, intent="edit"):
    return {
        "intent": intent,
        "message": "I'll add the slide.",
        "deck_spec": spec,
        "data_request": None,
        "target_positions": list(targets),
        "proposed_design_contract": None,
    }


def _revise_score(structured, **kwargs):
    kwargs.setdefault("reference", _out(_spec(REVISED), [8, 10]))
    kwargs.setdefault("current_deck_spec", _spec(OLD10))
    return scorers.expected_category_score("architect", structured, dict(REVISE_EXPECT), **kwargs)


def _append_score(structured, **kwargs):
    kwargs.setdefault("reference", _out(_spec(OLD10 + ["NEW"]), [10]))
    kwargs.setdefault("current_deck_spec", _spec(OLD10))
    return scorers.expected_category_score("architect", structured, dict(APPEND_EXPECT), **kwargs)


def _assert_insert_fail(result, *needles):
    ok, why = result
    assert ok is False, why
    assert why.startswith("Insert: "), why
    for needle in needles:
        assert needle in why, (needle, why)


def test_insert_fixture_decks_are_valid_and_align_as_the_rows_claim():
    """Guard: the hand-built decks mean what the rows below say they mean."""
    from src.domain.slide_alignment import align_slides

    current = DeckSpec.model_validate(_spec(OLD10))
    reference = DeckSpec.model_validate(_spec(REVISED))
    alignment = align_slides(current.slides, reference.slides)
    assert alignment.inserted_indices == (8,)
    assert alignment.revised_indices == (10,)


# ---- Step 1 table, rows (a), (b), (c) ----

def test_insert_a_correct_insert_with_old_numbering_targets_passes_with_a_note():
    """(a) The spec is right; the model counted its targets in the OLD numbering
    (old S9 is new 10). Production ignores those targets, so the row passes and
    the rationale says they differ."""
    ok, why = _revise_score(_out(_spec(REVISED), [8, 9]))
    assert ok is True, why
    assert "production ignores them on an insert" in why


def test_insert_that_leaves_the_requested_revision_unchanged_fails_on_revised():
    """(b) The targets name the revision, but the spec never revises S9."""
    _assert_insert_fail(
        _revise_score(_out(_spec(OLD10[:8] + ["NEW", "S8", "S9"]), [8, 10])), "revised")


def test_insert_that_also_changes_the_narrative_arc_fails_deck_level():
    """(c) A correct insert whose narrative_arc changed: production re-reviews every slide."""
    arc = ["Why the tool matters", "The evidence", "Offline use", "The verdict"]
    _assert_insert_fail(
        _revise_score(_out(_spec(REVISED, narrative_arc=arc), [8, 10])), "narrative_arc")


# ---- the rest of the table ----

def test_insert_with_canonical_targets_passes_without_the_note():
    ok, why = _revise_score(_out(_spec(REVISED), [8, 10]))
    assert ok is True, why
    assert "production ignores" not in why


def test_insert_that_tweaks_an_untouched_neighbours_hands_off_fails_on_revised():
    tokens = OLD10[:7] + ["S7~hands_off", "NEW", "S8", "S9~content_brief"]
    _assert_insert_fail(_revise_score(_out(_spec(tokens), [8, 10])), "revised")


def test_a_correct_append_passes():
    ok, why = _append_score(_out(_spec(OLD10 + ["NEW"]), [10]))
    assert ok is True, why


def test_replacing_the_last_slide_instead_of_adding_one_fails_on_inserted():
    """Equal length: production reads it as a revision of slide 9, not an insert."""
    _assert_insert_fail(_append_score(_out(_spec(OLD10[:9] + ["NEW"]), [9])), "inserted")


@pytest.mark.parametrize("tokens, code", [
    pytest.param(OLD10[:8] + ["NEW", "S8~content_brief", "S9~content_brief"], "ambiguous",
                 id="insert-next-to-a-rewritten-slide"),
    pytest.param(OLD10[:3] + ["NEW"] + OLD10[3:9], "moves_slides",
                 id="insert-and-drop-the-last-slide"),
    pytest.param(OLD10[:9], "removes_slides", id="shrink"),
])
def test_an_insert_production_would_refuse_fails_naming_the_code(tokens, code):
    _assert_insert_fail(
        _revise_score(_out(_spec(tokens), [8, 10])), "production would refuse", code)


def test_a_gapped_but_ordered_candidate_is_read_in_the_restamped_numbering():
    """Positions 0, 2, ..., 20: the new slide sits at position 16 but index 8,
    the revision at position 20 but index 10. Production re-stamps to indices."""
    gapped = _spec(REVISED, positions=[2 * i for i in range(len(REVISED))])
    ok, why = _revise_score(_out(gapped, [8, 10]))
    assert ok is True, why


def test_an_insert_case_without_a_deck_spec_fails():
    _assert_insert_fail(_revise_score(_out(None, [8, 10])), "no valid deck_spec")


def _duplicate_positions():
    spec = _spec(REVISED)
    spec["slides"][9]["position"] = 8
    return spec


@pytest.mark.parametrize("bad_spec", [
    pytest.param(_duplicate_positions(), id="duplicate-positions"),
    pytest.param({"title": "Only a title"}, id="partial"),
    pytest.param("not a spec", id="not-a-dict"),
])
def test_an_insert_case_with_an_invalid_deck_spec_fails_not_crashes(bad_spec):
    # The reason is pinned: a duplicate-position spec that slipped past validation
    # would otherwise still fail later, for an unrelated reason, and hide the gap.
    _assert_insert_fail(_revise_score(_out(bad_spec, [8, 10])), "no valid deck_spec")


def test_an_insert_case_whose_positions_omit_an_inserted_slide_fails():
    """Production builds inserted | revised (D3). A case naming positions [10] with
    inserted [8] would otherwise pass while production also builds slide 8."""
    ok, why = scorers.expected_category_score(
        "architect", _out(_spec(REVISED), [8, 10]),
        {"intent": "edit", "positions": [10], "inserted": [8]},
        reference=_out(_spec(REVISED), [8, 10]), current_deck_spec=_spec(OLD10))
    _assert_insert_fail((ok, why), "production builds [8, 10]")


@pytest.mark.parametrize("missing", ["reference", "current_deck_spec"])
def test_an_insert_case_without_its_reference_or_current_spec_fails(missing):
    ok, why = _revise_score(_out(_spec(REVISED), [8, 10]), **{missing: None})
    _assert_insert_fail((ok, why))
    assert missing.split("_")[0] in why, why


def test_an_insert_case_scored_with_three_positional_args_fails_not_crashes():
    """Positional compatibility: the old three-argument call still works; an
    insert case scored that way has no inputs to align against, so it fails."""
    result = scorers.expected_category_score(
        "architect", _out(_spec(REVISED), [8, 10]), dict(REVISE_EXPECT))
    _assert_insert_fail(result)


@pytest.mark.parametrize("intent", ["build", "discuss"])
def test_an_insert_answered_with_another_intent_fails(intent):
    """``build`` rebuilds every position in place, so production mis-attributes
    every later slide; ``discuss`` adds nothing."""
    spec = _spec(REVISED) if intent == "build" else None
    ok, why = _revise_score(_out(spec, [], intent=intent))
    assert ok is False, why
    assert "intent" in why.lower()


# ---- deck-level fields: exactly the five (C17), design contract separate ----

def test_insert_deck_level_tuple_is_productions_five_fields():
    from src.services.graph import nodes

    assert nodes._DECK_LEVEL_FIELDS == FIVE_DECK_LEVEL_FIELDS
    assert scorers.DECK_LEVEL_FIELDS == nodes._DECK_LEVEL_FIELDS


@pytest.mark.parametrize("field", FIVE_DECK_LEVEL_FIELDS)
def test_insert_any_deck_level_field_change_fails_naming_the_field(field):
    value = _spec(OLD10)[field]
    changed = [*value, "A new beat"] if isinstance(value, list) else f"{value} (rewritten)"
    _assert_insert_fail(
        _revise_score(_out(_spec(REVISED, **{field: changed}), [8, 10])), field)


@pytest.mark.parametrize("contract", [
    pytest.param({"design_system_id": 8, "template_id": None, "slide_style_id": None},
                 id="design-system"),
    pytest.param({"design_system_id": 7, "template_id": 3, "slide_style_id": None},
                 id="template"),
    pytest.param({"design_system_id": None, "template_id": None, "slide_style_id": 2},
                 id="slide-style"),
])
def test_insert_with_a_changed_design_contract_fails(contract):
    ok, why = _revise_score(_out(_spec(REVISED, design_contract=contract), [8, 10]))
    _assert_insert_fail((ok, why))
    assert "design" in why.lower(), why


@pytest.mark.parametrize("field, value", [
    ("title", "A renamed deck"),
    ("resolved_data", {"synthesis": "Re-sourced", "figures": [], "gaps": ["one gap"]}),
])
def test_insert_with_a_change_outside_the_deck_level_fields_passes(field, value):
    """Production re-reviews on the five fields only (``title`` and ``resolved_data``
    are deliberately absent from ``nodes._DECK_LEVEL_FIELDS``)."""
    ok, why = _revise_score(_out(_spec(REVISED, **{field: value}), [8, 10]))
    assert ok is True, why


# ---- cases without "inserted" score exactly as today ----

@pytest.mark.parametrize("structured", [
    _out(None, [2]),
    _out(_spec(OLD10), [2]),
    _out(_spec(OLD10[:3] + ["NEW"] + OLD10[3:]), [2]),
    _out(_spec(OLD10), [3]),
    _out(_spec(OLD10), [2, 3]),
    _out(None, [], intent="discuss"),
])
def test_a_non_insert_edit_scores_exactly_as_today_with_the_new_kwargs(structured):
    expect = {"intent": "edit", "positions": [2]}
    today = scorers.expected_category_score("architect", structured, dict(expect))
    with_kwargs = scorers.expected_category_score(
        "architect", structured, dict(expect),
        reference=_out(_spec(OLD10), [2]), current_deck_spec=_spec(OLD10))
    assert with_kwargs == today


@pytest.mark.parametrize("agent, structured, expect", [
    ("data_analyst", {"outcome": "success"}, {"outcome": "success"}),
    ("data_analyst", {"outcome": "no_tool"}, {"outcome": "success"}),
    ("build_reviewer", {"findings": [_f("overflow", 2)]},
     {"criteria": ["overflow"], "positions": [2]}),
    ("fix_reviewer", {"findings": [], "verdict": "fixed"},
     {"criteria": [], "positions": [], "verdict": "surfaced"}),
    ("deck_reviewer", {"findings": [_f("arc_gap", -1)]},
     {"criteria": ["arc_gap"], "positions": [-1]}),
])
def test_other_roles_accept_and_ignore_the_new_kwargs(agent, structured, expect):
    """The ``expected_category`` wrapper passes both kwargs for every role."""
    today = scorers.expected_category_score(agent, structured, dict(expect))
    with_kwargs = scorers.expected_category_score(
        agent, structured, dict(expect), reference={"r": 1}, current_deck_spec=None)
    assert with_kwargs == today

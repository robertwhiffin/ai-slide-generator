"""Deterministic scorers for the eval harness."""
from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import NamedTuple

from src.core import database  # noqa: F401 - break import cycle before src.* imports
import tinycss2
from pydantic import ValidationError

from evals.harness.render import RenderMeasures
from src.domain.deck_spec import DeckSpec, SlideSpec
from src.domain.deck_style import (
    DECK_STYLE_MAX_CHARS,
    DECK_STYLE_MAX_COMPONENTS,
    css_class_names,
    html_class_names,
    sanitise_deck_style,
)
from src.domain.finding import CRITERIA
from src.domain.skill_io import ArchitectOutput
from src.domain.slide_alignment import AlignmentRefused, align_slides
from src.domain.slide_operations import (
    OperationProblems,
    OperationsResult,
    apply_operations,
    compose_edit_spec,
)


#: Longest error detail quoted in a contract-fail rationale; longer is cut + marked.
CONTRACT_DETAIL_MAX_CHARS = 2000

#: The deck-level spec fields production re-reviews every slide on (#314, D10).
#: Mirrors ``src.services.graph.nodes._DECK_LEVEL_FIELDS``; a unit test pins the two equal.
#: The design-contract ids are a separate check (``_insert_score``), not part of this tuple.
DECK_LEVEL_FIELDS = ("audience", "purpose", "argument", "call_to_action", "narrative_arc")
_RE_REVIEW = "changed (production re-reviews every slide)"


def contract_score(
    structured: dict | None,
    *,
    status: str | None = None,
    error_detail: str | None = None,
) -> tuple[bool, str]:
    """Pass iff structured is not None (runtime already validated schema).

    A fail rationale names why the run produced no output: the runtime's
    ``status`` as `` (status=<status>)`` and its ``error_detail`` as
    ``: <detail>`` (cut to CONTRACT_DETAIL_MAX_CHARS plus a marker), each only
    when given and non-empty.  The pass rationale ignores both.
    """
    if structured is not None:
        return True, "Contract passed: structured output is present"
    rationale = "Contract failed: structured output is None"
    if status:
        rationale += f" (status={status})"
    if error_detail:
        if len(error_detail) > CONTRACT_DETAIL_MAX_CHARS:
            error_detail = error_detail[:CONTRACT_DETAIL_MAX_CHARS] + " ... [truncated]"
        rationale += f": {error_detail}"
    return False, rationale


def _first_error(e: ValidationError) -> str:
    first = e.errors()[0]
    where = ".".join(str(part) for part in first["loc"]) or "<root>"
    return f"{e.error_count()} validation error(s), first at {where}: {first['msg']}"


def _validate_deck(value) -> tuple[DeckSpec | None, str]:
    """Validate ``value`` as a ``DeckSpec``; the reason is empty on success."""
    try:
        return DeckSpec.model_validate(value), ""
    except ValidationError as e:
        return None, _first_error(e)


# --------------------------------------------------------------------------- operations edits

class _Composed(NamedTuple):
    """An operations edit as production reads it: the answer, the deck it edits, the result."""

    out: ArchitectOutput
    prior: DeckSpec
    result: OperationsResult
    spec: DeckSpec


def _operations_given(structured) -> bool:
    """Production's routing rule (``architect_node``): an ``edit`` carrying ``operations`` or
    ``deck_changes`` (either one not None) takes the operations path, whatever else it carries."""
    return (
        isinstance(structured, dict)
        and structured.get("intent") == "edit"
        and (structured.get("operations") is not None
             or structured.get("deck_changes") is not None)
    )


def _refusal(problems: OperationProblems) -> str:
    codes = ", ".join(p.code for p in problems.problems)
    details = "; ".join(p.detail for p in problems.problems)
    return f"production would refuse ({codes}): {details}"


def _compose(structured: dict, current_deck_spec) -> _Composed | str:
    """Compose an operations edit over the current deck exactly as production does.

    ``apply_operations`` over the persisted slides (``operations=None`` is the empty list, the
    identity), then ``compose_edit_spec`` with the ``deck_changes``. A ``str`` says why it does not
    compose: an invalid answer or deck, or the problems production would refuse it with.
    """
    try:
        out = ArchitectOutput.model_validate(structured)
    except ValidationError as e:
        return f"the answer is not a valid ArchitectOutput ({_first_error(e)})"
    prior, why = _validate_deck(current_deck_spec)
    if prior is None:
        return f"current_deck_spec is not a valid DeckSpec ({why})"
    result = apply_operations(prior.slides, out.operations or [])
    if isinstance(result, OperationProblems):
        return _refusal(result)
    spec = compose_edit_spec(prior, result, out.deck_changes)
    if isinstance(spec, OperationProblems):
        return _refusal(spec)
    return _Composed(out, prior, result, spec)


def compose_operations_answer(output: dict, current_deck_spec: dict | None) -> dict:
    """An architect answer as the judge sees it: an operations edit in its composed form (C2).

    An ``edit`` carrying ``operations``/``deck_changes`` gets ``deck_spec``, the JSON dump of the
    spec production composes over ``current_deck_spec``, and ``target_positions``, the slides
    production builds (``rebuild``); every other key is kept. So an operations answer and a
    deck_spec answer (every existing reference and calibration) read alike to the judge.

    Any other answer comes back unchanged, and so does one production would refuse or that has
    no deck to compose against: failing it is the deterministic scorer's job. ``output`` is never
    mutated. Both judge paths (the ``judge`` scorer and ``calibrate``) reach this through
    ``judge.judge_payload``, for the candidate and for the reference.
    """
    if not _operations_given(output):
        return output
    composed = _compose(output, current_deck_spec)
    if isinstance(composed, str):
        return output
    return {
        **output,
        "deck_spec": composed.spec.model_dump(mode="json"),
        "target_positions": list(composed.result.rebuild),
    }


def _reference_deck(reference: dict | None, current_deck_spec) -> tuple[DeckSpec | None, str]:
    """The deck the case's reference answer leaves: its ``deck_spec``, or, for a reference given
    as operations, the spec they compose to. The reason is empty on success."""
    if _operations_given(reference):
        composed = _compose(reference, current_deck_spec)
        if isinstance(composed, str):
            return None, composed
        return composed.spec, ""
    return _validate_deck((reference or {}).get("deck_spec"))


def _operations_score(
    output: dict, expect: dict, current: dict | None, reference: dict | None
) -> tuple[bool, str]:
    """Score an architect edit given as operations with production's own semantics (spec §9).

    Production composes ``operations``/``deck_changes`` over the persisted deck
    (``apply_operations`` + ``compose_edit_spec``), builds exactly the ``rebuild`` set, and ignores
    the model's ``target_positions`` and any ``deck_spec`` on this path; so that is what is
    checked. The row passes only when:

    * the intent is ``edit``;
    * production composes the answer: no operations problem, and a valid composed spec;
    * ``rebuild`` equals ``expect.positions``;
    * the new slides (the ``None`` entries of ``layout``) are ``expect.inserted`` (default none);
    * ``layout`` equals ``expect.layout`` when the case gives one (persisted positions, ``None``
      for a new slide: what tells a delete or a move apart);
    * every slide not rebuilt equals, field for field, the current deck's slide at the persisted
      position its row comes from;
    * ``DECK_LEVEL_FIELDS`` and the design contract equal the reference's, composed when the
      reference is itself given as operations.
    """
    intent = output.get("intent") if isinstance(output, dict) else None
    if intent != "edit" or expect.get("intent") != "edit":
        return False, (
            f"Operations: intent {intent!r}, expected {expect.get('intent')!r}; only an edit "
            "is composed")
    missing = [
        name for name, value in (("reference", reference), ("current_deck_spec", current))
        if value is None
    ]
    if missing:
        return False, f"Operations: cannot score without {' and '.join(missing)}"

    composed = _compose(output, current)
    if isinstance(composed, str):
        return False, f"Operations: {composed}"
    ref_deck, why = _reference_deck(reference, current)
    if ref_deck is None:
        return False, f"Operations: the reference has no valid deck_spec ({why})"
    out, prior, result, spec = composed

    got_rebuild = list(result.rebuild)
    want_rebuild = sorted(expect.get("positions", []))
    if got_rebuild != want_rebuild:
        return False, f"Operations: production rebuilds {got_rebuild} != positions {want_rebuild}"
    got_layout = list(result.layout)
    got_inserted = [index for index, persisted in enumerate(got_layout) if persisted is None]
    want_inserted = sorted(expect.get("inserted", []))
    if got_inserted != want_inserted:
        return False, f"Operations: inserted {got_inserted} != {want_inserted}"
    if "layout" in expect and got_layout != list(expect["layout"]):
        return False, f"Operations: layout {got_layout} != {list(expect['layout'])}"

    # A slide production does not rebuild keeps its row and its spec entry, so its composed spec
    # must be the current deck's, read from the deck itself rather than from the composition.
    current_by_position = {slide.position: slide for slide in prior.slides}
    rebuilt = set(got_rebuild)
    for index, (slide, persisted) in enumerate(zip(spec.slides, got_layout)):
        if index in rebuilt:
            continue
        before = current_by_position.get(persisted)
        if before is None:
            return False, (
                f"Operations: untouched slide {index} comes from position {persisted!r}, "
                "which the current deck does not have")
        changed = [
            name for name in SlideSpec.model_fields
            if name != "position" and getattr(slide, name) != getattr(before, name)
        ]
        if changed:
            return False, (
                f"Operations: untouched slide {index} (current position {persisted}) changed "
                f"{', '.join(changed)}")

    for field in DECK_LEVEL_FIELDS:
        if getattr(spec, field) != getattr(ref_deck, field):
            return False, (
                f"Operations: deck-level field {field} differs from the reference's "
                "(a change re-reviews every slide)")
    if spec.design_contract != ref_deck.design_contract:
        return False, (
            "Operations: deck-level field design_contract differs from the reference's "
            "(a change rebuilds every slide)")

    rationale = (
        f"Architect intent and operations match (rebuild {got_rebuild}, inserted {got_inserted}, "
        f"layout {got_layout})")
    targets = sorted(set(out.target_positions))
    if targets and targets != got_rebuild:
        rationale += (
            f"; model target_positions {targets} differ from {got_rebuild} "
            "(production ignores them on the operations path)")
    return True, rationale


# --------------------------------------------------------------------------- describe-only

#: The intents whose ``deck_spec`` a describe-only turn persists (``architect_node``): both reach
#: ``_description_keeps_what_it_cannot_see`` and the same deck-level write, and ``architect_router``
#: ends both turns before the foreman, so neither builds a slide.
REDESCRIPTION_INTENTS = ("edit", "build")


def _redescription_score(output: dict, expect: dict, current: dict | None) -> tuple[bool, str]:
    """Score the arc-review sweeper's re-description (a case whose ``expect`` has
    ``full_deck_spec``) with production's describe-only semantics.

    ``spec_sync.run_arc_review`` runs the turn with ``describe_only=True``. On it ``architect_node``
    applies no operations: it ignores ``operations`` and ``deck_changes``, persists the answer's
    ``deck_spec``, keeps the persisted spec whole instead when the answer's slide positions differ
    from it, and refuses an answer with no ``deck_spec`` without a retry. Any of those leaves the
    spec stale while the sweeper clears its marker. The row passes only when:

    * the intent is one of ``REDESCRIPTION_INTENTS``;
    * ``deck_spec`` is a valid DeckSpec whose slide positions equal the current deck's exactly;
    * ``operations`` and ``deck_changes`` are both None: a re-description is the full deck_spec
      alone (production would ignore the extra form here, but the answer mixes two edit forms).

    The model's own ``target_positions`` are noted, not failed: the turn builds nothing.
    """
    intent = output.get("intent") if isinstance(output, dict) else None
    if intent not in REDESCRIPTION_INTENTS:
        return False, (
            f"Re-description: intent {intent!r}, expected {expect.get('intent')!r} (an edit or a "
            "build); only those persist a deck_spec on a describe-only turn")
    if current is None:
        return False, "Re-description: cannot score without current_deck_spec"
    prior, why = _validate_deck(current)
    if prior is None:
        return False, f"Re-description: current_deck_spec is not a valid DeckSpec ({why})"

    given = [name for name in ("operations", "deck_changes") if output.get(name) is not None]
    if output.get("deck_spec") is None:
        instead = f", only {' and '.join(given)}" if given else ""
        return False, (
            f"Re-description: no deck_spec{instead}; a describe-only turn applies no operations or "
            "deck_changes, so production persists nothing and the sweeper clears its marker with "
            "the spec still stale")
    deck, why = _validate_deck(output["deck_spec"])
    if deck is None:
        return False, f"Re-description: deck_spec is not a valid DeckSpec ({why})"

    got = sorted(slide.position for slide in deck.slides)
    want = sorted(slide.position for slide in prior.slides)
    if got != want:
        diff = [
            f"{label} {sorted(positions)}"
            for label, positions in (("missing", set(want) - set(got)),
                                     ("added", set(got) - set(want)))
            if positions
        ]
        return False, (
            f"Re-description: deck_spec positions {got} != the current deck's {want} "
            f"({', '.join(diff)}); production keeps the persisted spec and drops the "
            "re-description")
    if given:
        return False, (
            f"Re-description: the deck_spec comes with {' and '.join(given)}; a re-description is "
            "the full deck_spec alone, with no operations or deck_changes")

    rationale = (
        f"Re-description: {intent} with the full deck_spec over positions {want}, no operations "
        "or deck_changes")
    targets = output.get("target_positions")
    if intent == "edit" and isinstance(targets, list):
        try:
            got_targets = sorted(set(targets))
        except TypeError:
            got_targets = targets
        if got_targets != want:
            rationale += (
                f"; model target_positions {got_targets} differ from {want} "
                "(a describe-only turn builds nothing)")
    return True, rationale


def _insert_score(
    structured: dict, expect: dict, reference: dict | None, current_deck_spec: dict | None
) -> tuple[bool, str]:
    """Score an architect insert turn with production's own semantics (#314, D10).

    Production ignores the model's ``target_positions`` on an insert and derives
    the turn from ``align_slides(current, output)``, so that is what is checked.
    """
    missing = [
        name for name, value in (("reference", reference), ("current_deck_spec", current_deck_spec))
        if value is None
    ]
    if missing:
        return False, f"Insert: cannot score without {' and '.join(missing)}"

    output, why = _validate_deck(structured.get("deck_spec"))
    if output is None:
        return False, f"Insert: no valid deck_spec in the output ({why})"
    current, why = _validate_deck(current_deck_spec)
    if current is None:
        return False, f"Insert: current_deck_spec is not a valid DeckSpec ({why})"
    # A reference given as operations (the edit-operations cases) is read in its composed form,
    # so a deck_spec answer to such a case still fails for production's own reason.
    ref_deck, why = _reference_deck(reference, current_deck_spec)
    if ref_deck is None:
        return False, f"Insert: the reference has no valid deck_spec ({why})"

    try:
        alignment = align_slides(current.slides, output.slides)
    except AlignmentRefused as e:
        return False, f"Insert: production would refuse ({e.code}): {e.detail}"

    want_inserted = list(expect["inserted"])
    got_inserted = list(alignment.inserted_indices)
    if got_inserted != want_inserted:
        return False, f"Insert: inserted {got_inserted} != {want_inserted}"
    want_revised = sorted(set(expect.get("positions", [])) - set(want_inserted))
    got_revised = sorted(alignment.revised_indices)
    if got_revised != want_revised:
        return False, f"Insert: revised {got_revised} != {want_revised}"
    # Production builds inserted | revised (D3); a case whose positions omit an
    # inserted slide would otherwise pass while production builds more than it names.
    built = sorted(set(got_inserted) | set(got_revised))
    want_built = sorted(set(expect.get("positions", [])))
    if built != want_built:
        return False, f"Insert: production builds {built} != positions {want_built}"

    for field in DECK_LEVEL_FIELDS:
        if getattr(output, field) != getattr(ref_deck, field):
            return False, f"Insert: deck-level field {field} {_RE_REVIEW}"
    if output.design_contract != ref_deck.design_contract:
        return False, f"Insert: deck-level field design_contract {_RE_REVIEW}"

    rationale = (
        f"Architect intent and insert alignment match "
        f"(inserted {got_inserted}, revised {got_revised})")
    targets = structured.get("target_positions")
    if isinstance(targets, list):
        want_targets = sorted(set(expect.get("positions", [])))
        try:
            got_targets = sorted(set(targets))
        except TypeError:
            got_targets = targets
        if got_targets != want_targets:
            rationale += (
                f"; model target_positions {got_targets} differ from {want_targets} "
                "(production ignores them on an insert)")
    return True, rationale


# --------------------------------------------------------------------------- deck style

#: A hex colour literal, as the value of a CSS ``hash`` token (no leading ``#``).
_HEX_COLOUR = re.compile(r"[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8}")

#: The inline declarations a slide built on a deck style must not carry: the deck style and the
#: design system provide the paint, so inline styles are for layout only.
DECK_STYLE_PAINT_PROPERTIES = (
    "color", "background", "background-color", "font-size", "font-family", "border-color",
)


def _hex_literals(css: str) -> list[str]:
    """The hex colour literals in ``css``'s declaration values, in source order, each once.

    Comments, strings and selectors (``#id``) never count; a ``url(data:...)`` is one token, so
    an SVG's ``%23fff`` does not either.
    """
    found: list[str] = []

    def walk(tokens) -> None:
        for tok in tokens:
            if tok.type == "hash" and _HEX_COLOUR.fullmatch(tok.value):
                literal = f"#{tok.value}"
                if literal not in found:
                    found.append(literal)
            elif tok.type == "function":
                walk(tok.arguments)
            elif tok.type in ("() block", "[] block", "{} block"):
                walk(tok.content)

    for rule in tinycss2.parse_stylesheet(css, skip_comments=True, skip_whitespace=True):
        if rule.type != "qualified-rule":
            continue
        items = tinycss2.parse_blocks_contents(
            rule.content, skip_comments=True, skip_whitespace=True)
        for item in items:
            if item.type == "declaration":
                walk(item.value)
    return found


def _deck_style_score(
    structured: dict, expect: dict, design_system_active: bool | None
) -> tuple[bool, str]:
    """Score the deck style an architect build answer authors (a case whose ``expect`` has
    ``deck_style: true``). It reads the answer's ``deck_spec``. The row passes only when:

    * ``deck_spec.deck_style`` is present;
    * it has 1 to ``DECK_STYLE_MAX_COMPONENTS`` components;
    * its CSS is at most ``DECK_STYLE_MAX_CHARS`` characters;
    * ``sanitise_deck_style`` returns it unchanged: the very same object, with ``()`` notes (C24);
    * every slide has a non-blank ``look``;
    * with a design system active, its CSS holds no hex colour literal (the design system supplies
      the colours as tokens). A ``:root`` rule needs no exemption here: under a design system the
      sanitiser drops it, which already fails the row.

    A failure's rationale names its cause; a sanitiser failure quotes the notes.
    """
    deck, why = _validate_deck((structured or {}).get("deck_spec"))
    if deck is None:
        return False, f"Deck style: no valid deck_spec to read deck_style from ({why})"
    style = deck.deck_style
    if style is None:
        return False, (
            "Deck style: deck_spec.deck_style is missing; this build is expected to author one")
    count = len(style.components)
    if not 1 <= count <= DECK_STYLE_MAX_COMPONENTS:
        return False, (
            f"Deck style: {count} components, expected 1 to {DECK_STYLE_MAX_COMPONENTS}")
    if len(style.css) > DECK_STYLE_MAX_CHARS:
        return False, (
            f"Deck style: its CSS is {len(style.css)} characters, over the "
            f"{DECK_STYLE_MAX_CHARS} limit")
    cleaned, notes = sanitise_deck_style(style, design_system_active=bool(design_system_active))
    if notes or cleaned is not style:
        detail = "; ".join(notes) or "it returned a different style"
        return False, f"Deck style: the sanitiser would change it ({detail})"
    lookless = [slide.position for slide in deck.slides if slide.look is None]
    if lookless:
        return False, f"Deck style: slides {lookless} have no look (blank or missing)"
    if design_system_active:
        hexes = _hex_literals(style.css)
        if hexes:
            return False, (
                f"Deck style: hex colour literal(s) {', '.join(hexes)} under an active design "
                "system; its colours must be the design system's tokens")
    return True, (
        f"Deck style: clean ({count} components, {len(style.css)} characters, every slide has a "
        "look)")


class _InlineStyles(HTMLParser):
    """Every ``style`` attribute value in an HTML fragment, decoded, in document order."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.values: list[str] = []

    def handle_starttag(self, tag, attrs) -> None:
        self.values.extend(value for name, value in attrs if name == "style" and value)


def _inline_paint(html: str) -> list[str]:
    """``name: value`` of every inline declaration of a ``DECK_STYLE_PAINT_PROPERTIES`` property,
    in document order, each once."""
    parser = _InlineStyles()
    parser.feed(html)
    parser.close()
    found: list[str] = []
    for text in parser.values:
        for item in tinycss2.parse_blocks_contents(text, skip_comments=True, skip_whitespace=True):
            if item.type == "declaration" and item.lower_name in DECK_STYLE_PAINT_PROPERTIES:
                decl = f"{item.lower_name}: {tinycss2.serialize(item.value).strip()}"
                if decl not in found:
                    found.append(decl)
    return found


def deck_style_use_score(html: str, payload: dict, expect: dict) -> tuple[bool, str]:
    """Score how a builder slide uses the deck style it was given (a case whose ``expect`` has
    ``deck_style_classes``). The row passes only when:

    * every class in ``expect.deck_style_classes`` is used in ``html``;
    * no inline ``style`` declares one of ``DECK_STYLE_PAINT_PROPERTIES`` (inline styles are
      layout only: the paint comes from the design system and the deck style);
    * every class ``html`` uses is defined by ``payload["section_css"]`` or by
      ``payload["deck_style"]["css"]``.

    Every failing condition is named in the rationale.
    """
    wanted = list(expect.get("deck_style_classes") or [])
    style = (payload or {}).get("deck_style") or {}
    used = html_class_names(html or "")
    defined = (css_class_names((payload or {}).get("section_css") or "")
               | css_class_names(style.get("css") or ""))

    reasons = []
    unused = [name for name in wanted if name not in used]
    if unused:
        reasons.append(f"deck-style class(es) not used: {', '.join(unused)}")
    painted = _inline_paint(html or "")
    if painted:
        reasons.append(
            f"inline paint, which the design system and deck style provide: {'; '.join(painted)}")
    undefined = sorted(used - defined)
    if undefined:
        reasons.append(
            "class(es) defined by neither the template CSS nor the deck style: "
            f"{', '.join(undefined)}")
    if reasons:
        return False, "Deck style use: " + "; ".join(reasons)
    return True, (
        f"Deck style use: uses {', '.join(wanted) or 'no listed class'}; no inline paint; every "
        "class is defined")


def expected_category_score(
    agent_key: str,
    structured: dict,
    expect: dict,
    *,
    reference: dict | None = None,
    current_deck_spec: dict | None = None,
    design_system_active: bool | None = None,
) -> tuple[bool, str]:
    """Role-dispatched expected category scorer.

    - architect: checks intent match, and for edit mode, target_positions match positions (as sets).
      A case whose ``expect`` has ``full_deck_spec`` (the arc-review sweeper's describe-only turn)
      is scored by ``_redescription_score`` alone, ahead of every other check, since production
      applies no operations on that turn and persists a build's deck_spec as it does an edit's.
      A case whose ``expect`` has ``deck_style: true`` also needs ``_deck_style_score`` to pass,
      checked right after the intent (``design_system_active`` is the case's).
      An edit answer carrying ``operations`` or ``deck_changes`` is scored by ``_operations_score``
      on every other edit case, as production's operations path takes it whatever else it carries.
      Otherwise an edit case whose ``expect`` has ``"inserted"`` is scored by ``_insert_score``.
      Both need the case's ``reference`` output and the payload's ``current_deck_spec``.
    - data_analyst: checks outcome match
    - build_reviewer/fix_reviewer/deck_reviewer: checks findings against expected criteria/positions,
      guards unknown criteria, and optionally checks verdict for fix_reviewer
    """
    if not isinstance(structured, dict):
        return False, f"Structured output is not a dict: {type(structured).__name__}"

    if agent_key == "architect":
        # The sweeper's describe-only re-description: no operations path, a build counts as an edit
        if expect.get("full_deck_spec"):
            return _redescription_score(structured, expect, current_deck_spec)

        # Check intent match
        if structured.get("intent") != expect.get("intent"):
            return False, f"Intent mismatch: got {structured.get('intent')!r}, expected {expect.get('intent')!r}"

        # A build case that expects a deck style: ANDed after the intent check
        if expect.get("deck_style"):
            ok, why = _deck_style_score(structured, expect, design_system_active)
            if not ok:
                return False, why

        # An edit given as operations is scored as production composes it (spec §9)
        if _operations_given(structured):
            return _operations_score(structured, expect, current_deck_spec, reference)

        # An insert is scored with production's own alignment, not the model's targets
        if structured.get("intent") == "edit" and "inserted" in expect:
            return _insert_score(structured, expect, reference, current_deck_spec)

        # For edit, also check target_positions match positions (as sets)
        if structured.get("intent") == "edit":
            got_positions = set(structured.get("target_positions", []))
            expect_positions = set(expect.get("positions", []))
            if got_positions != expect_positions:
                return False, f"Target positions mismatch: got {got_positions}, expected {expect_positions}"

        return True, "Architect intent and positions match"

    elif agent_key == "data_analyst":
        # Check outcome match
        if structured.get("outcome") != expect.get("outcome"):
            return False, f"Outcome mismatch: got {structured.get('outcome')!r}, expected {expect.get('outcome')!r}"
        return True, "Data analyst outcome matches"

    elif agent_key in ["build_reviewer", "fix_reviewer", "deck_reviewer"]:
        # Check findings
        findings = structured.get("findings") or []

        # First, check for unknown criteria
        for f in findings:
            criterion = f.get("criterion")
            if criterion not in CRITERIA:
                return False, f"Unknown criterion: {criterion!r}"

        # Build set of (criterion, position) tuples from findings
        got = set()
        for f in findings:
            criterion = f.get("criterion")
            position = f.get("slide_index")
            got.add((criterion, position))

        # Build objective_got: set of objective criteria
        objective_got = {c for (c, _) in got if CRITERIA[c].objective}

        # Get expected criteria and positions
        expect_criteria = set(expect.get("criteria", []))
        expect_positions = set(expect.get("positions", []))

        # Build expected set: all combinations of (criterion, position)
        expected = {(c, p) for c in expect_criteria for p in expect_positions}

        # A planted criterion with no positions must still appear somewhere
        if expect_criteria and not expect_positions:
            absent = expect_criteria - {c for (c, _) in got}
            if absent:
                return False, f"Missing expected criteria: {absent}"

        # Check 1: every expected (criterion, position) must be present
        if not expected.issubset(got):
            missing = expected - got
            return False, f"Missing expected findings: {missing}"

        # Check 2: no objective criterion outside expect_criteria should appear
        unplanted_objectives = objective_got - expect_criteria
        if unplanted_objectives:
            return False, f"Unplanted objective criteria found: {unplanted_objectives}"

        # Check 3 (fix_reviewer): verdict check if present in expect
        if agent_key == "fix_reviewer" and "verdict" in expect:
            got_verdict = structured.get("verdict")
            expect_verdict = expect.get("verdict")
            if got_verdict != expect_verdict:
                return False, f"Verdict mismatch: got {got_verdict!r}, expected {expect_verdict!r}"

        return True, "All expected findings match and no unplanted objective criteria"

    else:
        return False, f"Unknown agent: {agent_key!r}"


def render_measures_score(measures: RenderMeasures, html: str) -> tuple[bool, str]:
    """Pass iff all render measures are clean.

    Requires:
    - measures.rendered is True
    - overflow_px == 0
    - min_contrast >= 4.5
    - off_palette == ()
    - console_errors == ()
    - safe_area_px == 0 (no text/media past Tellr's 88px-side / 56px-vertical safe area)
    - no "<style" tag in HTML (case-insensitive)
    """
    reasons = []

    if not measures.rendered:
        reasons.append("Rendering failed")

    if measures.overflow_px != 0:
        reasons.append(f"Overflow: {measures.overflow_px}px")

    if measures.min_contrast < 4.5:
        reasons.append(f"Contrast too low: {measures.min_contrast}")

    if measures.off_palette:
        reasons.append(f"Off-palette colors: {measures.off_palette}")

    if measures.console_errors:
        reasons.append(f"Console errors: {measures.console_errors}")

    if measures.safe_area_px > 0:
        reasons.append(f"Safe area intrusion: {measures.safe_area_px}px past the 88px/56px safe area")

    if "<style" in html.lower():
        reasons.append("Inline style tag found in HTML")

    if reasons:
        return False, "; ".join(reasons)

    return True, "All render measures passed"

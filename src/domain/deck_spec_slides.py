"""The blank slide: its deck-derived shell, the blank predicates, and the spec splice.

A manually inserted slide starts blank, in the same sense as Google Slides' "Blank"
layout: the deck's frame with nothing on it.  This module holds the pure pieces every
layer needs to agree on — the HTML the blank gets, how a row and a spec entry are
recognised as blank, and how a deck spec's slide list is re-stamped when slides move.

It imports nothing from ``src.api`` or ``src.services`` on purpose: the graph nodes, the
session manager and the chat service all import it, so it must sit below all three.
"""

from __future__ import annotations

import copy
import json
from collections import Counter
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Union

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

from src.domain.deck_spec import SlideSpec
from src.domain.slide import has_slide_wrapper
from src.utils.html_safety import scan_html_for_unsafe_patterns

#: The fallback blank: the slide wrapper and nothing else.
#: The wrapper is not decoration: ``has_slide_wrapper`` is what the parser, the
#: frontend thumbnail panel and every export path use to recognise a slide, so an
#: empty slide still has to carry it.  ``blank_slide_shell`` returns it when the deck
#: offers no usable frame to copy; the deck's own CSS then styles it (Meridian paints
#: its ground on ``.slide``), and any content here would be content nobody asked for.
BLANK_SLIDE_HTML = '<div class="slide"></div>'

#: The exact description of a blank slide: the deck-spec entry a manually inserted
#: blank gets.  Spliced in contiguous with its neighbours (``DeckSpec.slide_at``
#: depends on that) and deliberately undescribed — inventing a purpose here would put
#: words in the architect's mouth.  ``SlideSpec`` accepts it once a position is
#: stamped.  Never hand it out directly: ``splice_blank_entry`` deep-copies it, so no
#: caller can grow the shared ``data_references`` list.
BLANK_DECK_SPEC_ENTRY: Dict[str, Any] = {
    "purpose": "",
    "content_brief": "",
    "assumes": "",
    "hands_off": "",
    "data_references": [],
}

#: HTML's ASCII whitespace (the WHATWG "ASCII whitespace" set).  NOT ``str.strip()``'s
#: default set, nor JS ``trim()``'s: those two disagree with each other and with HTML on
#: U+FEFF, U+0085, U+001C, U+00A0 and more, and the TS predicate must give the same
#: answer as this one on the shared case table (``tests/fixtures/blank_slide_cases.json``).
_HTML_WHITESPACE = "\t\n\f\r "

#: The only attributes a shell keeps, in the order it serialises them.  Everything else
#: (``id``, ``on*`` handlers, other ``data-*``, ARIA, ``hidden``) is the source slide's,
#: not the deck's frame.
_SHELL_ATTRIBUTES = ("class", "data-label", "style")

#: The class token that marks a slide.  Matched case-sensitively, as a token: BS4 splits
#: ``class`` into its tokens, and ``class="Slide"`` is not a slide.
_SLIDE_TOKEN = "slide"


def _is_html_whitespace(text: str) -> bool:
    return text.strip(_HTML_WHITESPACE) == ""


def _has_slide_token(tag: Tag) -> bool:
    return _SLIDE_TOKEN in (tag.get("class") or [])


def _slide_chain(html: str) -> Optional[List[Tag]]:
    """The elements from the fragment's top-level root down to its first ``.slide``.

    ``findSlideRoot`` semantics: the first element, in document order, carrying the
    ``slide`` token, plus every ancestor up to (not including) the fragment itself.
    None when the fragment holds no such element.
    """
    soup = BeautifulSoup(html, "html.parser")
    target = soup.find(lambda tag: _has_slide_token(tag))
    if target is None:
        return None
    chain: List[Tag] = []
    node: Any = target
    while node is not None and node is not soup:
        chain.append(node)
        node = node.parent
    chain.reverse()
    return chain


def _candidate_shell(html: str) -> Optional[str]:
    """This slide's frame as a shell string, or None when it has no ``.slide``.

    Each chain element is rebuilt as a fresh tag carrying only ``class`` (its tokens in
    source order), ``data-label`` and ``style`` (values verbatim), in that fixed order,
    nested with no other child and no text.  The serialisation is deterministic, so two
    slides with the same frame give the same string — which is what makes the strings
    countable.
    """
    if not html:
        return None
    chain = _slide_chain(html)
    if chain is None:
        return None

    builder = BeautifulSoup("", "html.parser")
    outermost: Optional[Tag] = None
    innermost: Optional[Tag] = None
    for element in chain:
        attrs: Dict[str, str] = {}
        for name in _SHELL_ATTRIBUTES:
            if not element.has_attr(name):
                continue
            value = element[name]
            if name == "class":
                tokens = list(value) if isinstance(value, list) else str(value).split()
                if not tokens:
                    continue
                attrs[name] = " ".join(tokens)
            else:
                attrs[name] = str(value)
        rebuilt = builder.new_tag(element.name, attrs=attrs)
        if innermost is None:
            outermost = rebuilt
        else:
            innermost.append(rebuilt)
        innermost = rebuilt
    return str(outermost)


def blank_slide_shell(slide_htmls: Sequence[str], position: int) -> str:
    """The blank slide to insert at *position* in a deck holding *slide_htmls*.

    A bare ``<div class="slide"></div>`` paints only where the deck's ground sits on
    ``.slide``.  A pinned design system paints it on a ``<section>`` wrapper, and an
    unpinned graph deck carries it as an inline ``style``; in both a bare div is a white
    box.  So the blank copies the deck's own frame:

    - **Candidates.**  Every slide with a ``.slide`` element yields its candidate shell
      (``_candidate_shell``).  Slides without one are skipped.
    - **Choose.**  The most common candidate wins: on an inline-styled deck every slide
      has the same tags and classes, so the full candidate, style included, is what
      tells the deck's content ground from its cover.  On a tie, the nearest slide
      holding a tied candidate decides — scanning ``position-1 … 0``, then
      ``position … n-1`` — but never slide 0 (the cover) while another slide holds a
      tied candidate.  Slide 0's frame is copied only as the unique winner.
    - **Check.**  The winner must be a blank row (``is_blank_slide_html``: a ``<div>``
      slide wrapper ending the chain) and pass the unsafe-pattern scan; otherwise the
      result is ``BLANK_SLIDE_HTML``.  The winner is judged, not skipped past: an unsafe
      majority gives the bare div, never the runner-up.  ``style`` is kept verbatim
      (``url()`` included — a brand ground may be an image); the slide CSP enforces at
      render.

    An empty deck, or one with no ``.slide`` anywhere, gets ``BLANK_SLIDE_HTML``.

    Args:
        slide_htmls: The deck's slides' HTML, in deck order.
        position: Where the blank will land (already clamped to the deck); clamped
            again to ``0 … len(slide_htmls)``.

    Returns:
        The shell HTML.  Always a blank row under ``is_blank_slide_html``.
    """
    count = len(slide_htmls)
    position = max(0, min(position, count))

    by_index: Dict[int, str] = {}
    for index, html in enumerate(slide_htmls):
        candidate = _candidate_shell(html)
        if candidate is not None:
            by_index[index] = candidate
    if not by_index:
        return BLANK_SLIDE_HTML

    tallies = Counter(by_index.values())
    top = max(tallies.values())
    tied = {candidate for candidate, n in tallies.items() if n == top}

    if len(tied) == 1:
        (winner,) = tied
    else:
        skip_cover = any(i != 0 and c in tied for i, c in by_index.items())
        scan = list(range(position - 1, -1, -1)) + list(range(position, count))
        winner = next(
            by_index[i]
            for i in scan
            if i in by_index and by_index[i] in tied and not (i == 0 and skip_cover)
        )

    if is_blank_slide_html(winner) and scan_html_for_unsafe_patterns(winner) == []:
        return winner
    return BLANK_SLIDE_HTML


def is_blank_slide_html(html: Optional[str]) -> bool:
    """True iff *html* is a blank row: a slide frame with nothing on it.

    That is: it has a ``<div>`` slide wrapper (``has_slide_wrapper``); the fragment is a
    single chain of elements from one top-level root down to its first ``.slide``, each
    chain element holding exactly one element child and the ``.slide`` none; that
    ``.slide`` is itself a ``<div>``; and every text node is HTML ASCII whitespace.
    Comments are ignored.  Attributes do not matter.  Every ``blank_slide_shell`` result
    is a blank row.

    The ``<div>`` check is structural on purpose: ``has_slide_wrapper`` is a regex over
    the raw string, so markup inside a comment or an attribute value satisfies it.
    Without the check, ``<!-- <div class="slide"> --><img class="slide" src=…>`` — an
    image — would read as blank.
    """
    if not html or not has_slide_wrapper(html):
        return False

    def element_children(node: Tag) -> Optional[List[Tag]]:
        """The element children, or None when a non-whitespace text node is present."""
        elements: List[Tag] = []
        for child in node.children:
            if isinstance(child, Comment):
                continue
            if isinstance(child, Tag):
                elements.append(child)
            elif isinstance(child, NavigableString):
                # Doctype, CDATA and processing instructions count as text too.
                if type(child) is not NavigableString or not _is_html_whitespace(child):
                    return None
        return elements

    # The fragment itself carries no class, so the walk starts above the root.
    node: Tag = BeautifulSoup(html, "html.parser")
    while True:
        elements = element_children(node)
        if elements is None:
            return False
        if _has_slide_token(node):
            return not elements and node.name == "div"
        if len(elements) != 1:
            return False
        node = elements[0]


def _spec_text(entry: Union[SlideSpec, Mapping[str, Any]], field: str) -> Any:
    if isinstance(entry, Mapping):
        return entry.get(field)
    return getattr(entry, field, None)


def is_blank_slide_spec(entry: Union[SlideSpec, Mapping[str, Any]]) -> bool:
    """True iff the entry's ``purpose`` and ``content_brief`` are both empty.

    Empty means HTML ASCII whitespace only (the same rule as ``is_blank_slide_html``'s
    text, so the TS twin agrees); a missing key or ``None`` counts as empty.  No other
    field decides it.
    """
    for field in ("purpose", "content_brief"):
        value = _spec_text(entry, field)
        if value is None:
            continue
        if not isinstance(value, str) or not _is_html_whitespace(value):
            return False
    return True


def renumber_spec_slides(
    spec: Dict[str, Any],
    reorder: Callable[[List[Dict[str, Any]]], Optional[List[Dict[str, Any]]]],
) -> Optional[Dict[str, Any]]:
    """Re-order a raw deck spec's slide entries and re-stamp their positions 0..n.

    The pure middle of ``ChatService._rewrite_deck_spec_slides``.  Works on the RAW
    dict, never a parsed ``DeckSpec``: a spec that no longer validates must not be
    destroyed by a renumber, and nothing here reads a field other than ``position``.

    Entries that are dicts with an int ``position`` are handed to *reorder* in position
    order; it returns them in their new order (it never touches ``position``), and they
    are re-stamped contiguously from 0.  Any other entry cannot be identified with a
    slide, so it is carried through unchanged and last.  One pass, and identity is never
    inferred from equality: two entries with the same content are still two entries.

    Args:
        spec: The raw spec dict.  Not mutated.
        reorder: Takes the positioned entries in position order, returns them in their
            new order, or ``None`` to leave the spec alone.  An ``IndexError`` it raises
            (the spec cannot answer the mutation) propagates.

    Returns:
        A NEW spec dict, or None when ``spec["slides"]`` is not a list or *reorder*
        declined.
    """
    slides = spec.get("slides")
    if not isinstance(slides, list):
        return None

    positioned: List[Dict[str, Any]] = []
    unpositioned: List[Any] = []
    for entry in slides:
        if isinstance(entry, dict) and isinstance(entry.get("position"), int):
            positioned.append(entry)
        else:
            unpositioned.append(entry)
    positioned.sort(key=lambda e: e["position"])

    rewritten = reorder(list(positioned))
    if rewritten is None:
        return None

    renumbered: List[Any] = []
    for index, entry in enumerate(rewritten):
        entry = dict(entry)
        entry["position"] = index
        renumbered.append(entry)
    renumbered.extend(unpositioned)

    out = dict(spec)
    out["slides"] = renumbered
    return out


def splice_blank_entry(entries: List[Dict[str, Any]], position: int) -> List[Dict[str, Any]]:
    """*entries* with a fresh blank entry at *position*, clamped to ``0 … len(entries)``.

    The clamp is applied against the spec's own length rather than trusted, because a
    spec shorter than the deck would otherwise leave a hole.  The blank is a deep copy
    of ``BLANK_DECK_SPEC_ENTRY``.  *entries* is not mutated.
    """
    landed = max(0, min(position, len(entries)))
    return entries[:landed] + [copy.deepcopy(BLANK_DECK_SPEC_ENTRY)] + entries[landed:]


def spec_json_with_blank_entry(raw: Optional[str], position: int) -> Optional[str]:
    """The ``deck_spec_json`` column with a blank entry spliced in at *position*.

    None means "leave the column untouched": a NULL or empty column, unparseable JSON,
    a non-dict, ``{}`` and a dict without a ``slides`` list are all left alone, so legacy
    decks still insert.  ``{"slides": []}`` gains the entry.  Unknown keys and entries
    of an invalid shape are kept (``renumber_spec_slides``).
    """
    if not raw:
        return None
    try:
        spec = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(spec, dict) or not spec:
        return None
    renumbered = renumber_spec_slides(spec, lambda entries: splice_blank_entry(entries, position))
    if renumbered is None:
        return None
    return json.dumps(renumbered)

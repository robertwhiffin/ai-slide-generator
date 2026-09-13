"""Deck-level CSS aggregation for the graph write path — ws4b task B3.3.

Public API
----------
:func:`aggregate_deck_css`  ``(existing_css, emitted_style_blocks, token_css) -> str``

Why this exists
---------------
``deck.css`` is populated on the monolith path by exactly two mechanisms:
``SlideDeck.from_html_string``'s ``<style>`` walk and ``SlideDeck.update_css``
-> ``merge_css`` (``src/domain/slide_deck.py``).  The LangGraph path invokes
neither — the slide writer persists per-row ``html`` only.  A graph-built deck
would therefore reach ``ensure_deck_token_css`` with an EMPTY ``deck.css``, and
that backstop restores only custom properties and ``@font-face`` families: it
would hand back the token stylesheet alone and the deck would knit with no
layout CSS at all.  This function is the graph's replacement for both monolith
mechanisms.

Where it runs
-------------
At the POST-COMMIT deck write, never before the builder fan-out: the backstop
compares the EMITTED deck CSS against the token stylesheet, so it cannot run
before the builders have emitted anything.

Why the merge FOLDS PAIRWISE
----------------------------
``merge_css`` returns ``existing_css`` unchanged when the *replacement* parses
to no blocks (``src/utils/css_utils.py``, the ``if not replacement_blocks``
guard).  So the tempting one-shot form — concatenate every block and merge the
concatenation with ``""`` — returns early and never merges at all: the emitted
CSS is handed back as raw concatenated text, with duplicate selectors and
duplicate at-rules that a browser resolves by last-wins instead of by the
merge's override-in-position rule.  The fold below therefore threads each block
through its own ``merge_css`` call.  A blank or ``None`` block is a no-op
because of that same guard, so no separate skip is needed.

Why the result is RE-HOISTED after the backstop
-----------------------------------------------
``ensure_deck_token_css`` PREPENDS the token stylesheet (plus a comment marker)
when a token is undefined.  If the merged sheet began with a hoisted
``@import``, the prepend lands in FRONT of it — and per the CSS spec ``@import``
must precede every rule except ``@charset``, so a browser silently ignores it
and the deck loses that stylesheet with no error anywhere.  That is the same
class of silent CSS loss this module exists to prevent, arriving through the
module itself, so :func:`aggregate_deck_css` re-hoists ``@charset`` then
``@import`` to the front of the FINAL string.  This function's output is what
gets persisted, which makes it the last place that can guarantee validity.

Calling ``merge_css(result, "")`` to re-trigger its hoist does NOT work — that
is the same empty-replacement early return that shapes the fold above.  The
re-hoist below is a post-pass on the string: it locates the hoistable blocks
with ``parse_css_blocks``, moves their verbatim text to the front, and leaves
everything else — including the backstop's comment marker — untouched.  When a
block is not locatable verbatim (tinycss2 re-serialises quotes, so a
single-quoted ``@import`` never matches its own source) the normalised copy is
PREPENDED and the original left in place: a duplicate at-rule is inert, whereas
handing back the unhoisted sheet would emit exactly the ignored-``@import``
defect this post-pass exists to prevent.

**Not fixed here, and not solved anywhere: the monolith path has the same latent
defect.**  It also runs a hoisting merge (``SlideDeck.update_css`` ->
``merge_css``) and then this same prepending backstop, so a monolith deck whose
tokens are missing can end up with an ignored ``@import`` too.  The fix would
have to live in a module this PR must not edit, so it is explicitly out of
scope.  Do not read the re-hoist below as evidence the problem is handled
everywhere — it is handled on the graph write path only.

What the blocks are — PRODUCER CONTRACT for ws4c
------------------------------------------------
Each element must be **CSS text**: the *contents* of a style block, NOT
``<style>``-wrapped markup.  A wrapped block parses to tinycss2 error nodes,
``parse_css_blocks`` drops those, and the emitted CSS is silently lost — no
exception, no log.  Whoever writes the producer owns keeping the wrapper off.

The blocks are not builder output: ``BuilderOutput`` forbids a builder emitting
``<style>``.  One writer produces them, once per turn, in ws4c; the list holds
exactly one element, or is empty on a legacy/unpinned deck.  This function's job
is aggregation plus token backstopping, not deduplication.

CSS travels whole and is never pruned here: the backstop covers only custom
properties and ``@font-face`` families, so anything a pruner got wrong would
land outside the safety net.

Everything else about merge semantics is inherited from ``merge_css`` and is
not re-implemented here — at-rule dedupe on ``(lower_at_keyword,
discriminator)``, the empty-prelude append (``@font-face``, bare ``@page``),
the ``@charset``/``@import``-only hoist, and override-in-position for qualified
rules.
"""
from __future__ import annotations

import logging
from typing import Iterable, Optional

from src.services.design_system_templates import ensure_deck_token_css
from src.utils.css_utils import merge_css, parse_css_blocks

logger = logging.getLogger(__name__)

# Rank per block for the re-hoist: @charset first, @import second, everything
# else after — the same partition (and the same lowercased ``key[0]``) that
# ``merge_css`` already establishes. Only these two at-rules are hoisted;
# @namespace and statement-form @layer are deliberately not, matching
# css_utils' documented contract.
_HOIST_RANKS = {"charset": 0, "import": 1}
_OTHER_RANK = 2


def _rehoist_top_of_sheet_at_rules(css: str) -> str:
    """Move ``@charset`` then ``@import`` back to the front of *css*.

    A no-op — byte-identical return — when they are already partitioned that
    way, which is the common case: the fold's last ``merge_css`` hoists them,
    and only a token-backstop prepend can push them out of position.
    """
    blocks = parse_css_blocks(css)
    ranks = [
        _HOIST_RANKS.get(block.key[0], _OTHER_RANK) if block.is_at_rule else _OTHER_RANK
        for block in blocks
    ]
    if ranks == sorted(ranks):
        return css

    remainder = css
    hoisted: list[str] = []
    not_excised: list[str] = []
    # sorted() is stable, so @charset blocks keep their relative order and so do
    # @import blocks.
    for _, block in sorted(
        ((rank, block) for rank, block in zip(ranks, blocks) if rank != _OTHER_RANK),
        key=lambda pair: pair[0],
    ):
        index = remainder.find(block.text)
        if index == -1:
            # ``block.text`` is tinycss2's RE-SERIALISATION, which does not always
            # match the source: a single-quoted string comes back double-quoted, so
            # ``@import url('brand.css')`` is not findable in the sheet it came from.
            #
            # Returning the sheet unchanged here — the original behaviour — emitted
            # the very defect this function exists to prevent: an @import sitting
            # after a qualified rule (a token-backstop prepend), which a browser
            # silently ignores, losing the brand stylesheet. So the block is emitted
            # at the FRONT anyway and its original occurrence is left in place. A
            # duplicate @import/@charset later in the sheet is inert (the second is
            # ignored); a mis-ordered one is not. Strictly better than known-broken.
            not_excised.append(block.key[0])
            hoisted.append(block.text)
            continue
        head, tail = remainder[:index], remainder[index + len(block.text):]
        if head.endswith("\n") and tail.startswith("\n"):
            # Both sides of the excision carry a block separator; keep one.
            # Only ever inter-block whitespace, never text inside a block.
            tail = tail.lstrip("\n")
        remainder = head + tail
        hoisted.append(block.text)

    if not_excised:
        logger.warning(
            "Could not locate a top-of-sheet at-rule verbatim in the deck CSS (%s) — "
            "tinycss2 re-serialises quotes; prepended a normalised copy to keep it "
            "ahead of the rules and left the original in place",
            ", ".join(sorted(set(not_excised))),
        )

    remainder = remainder.strip()
    parts = hoisted + ([remainder] if remainder else [])
    return "\n\n".join(parts)


def aggregate_deck_css(
    existing_css: Optional[str],
    emitted_style_blocks: Optional[Iterable[str]],
    token_css: Optional[str],
) -> str:
    """Merge this turn's emitted CSS into the deck's stylesheet, then backstop it.

    Args:
        existing_css: The deck's stored CSS, or ``None``/``""`` for a new deck.
        emitted_style_blocks: CSS texts emitted this turn — one element in
            practice, empty on a legacy/unpinned deck. ``None`` is accepted.
        token_css: The pinned design system's token stylesheet, or ``None`` when
            the deck is unpinned. ``None``/blank means no backstop.

    Returns:
        The aggregated deck CSS. Never raises: a failing token backstop is
        logged and the merged CSS is returned, because this runs on the deck
        save path and a stylesheet safety net must not be able to block the
        save.
    """
    aggregated = existing_css or ""

    # Pairwise fold — see the module docstring. Merging a concatenation with
    # "" would hit merge_css's empty-replacement early return instead.
    for block in emitted_style_blocks or ():
        aggregated = merge_css(aggregated, block)

    try:
        # Blank/None token_css is ensure_deck_token_css's own no-op case, so
        # there is no separate branch for it here. Rebound only on success, so a
        # failure keeps the merged CSS and the save proceeds without the backstop.
        aggregated = ensure_deck_token_css(aggregated, token_css)
    except Exception:
        logger.exception(
            "Design-system token backstop failed while aggregating deck CSS; "
            "saving the merged CSS without it"
        )

    # LAST: the backstop prepends, which can push a hoisted @import out of the
    # only position a browser honours. Runs on the backstopped CSS (or on the
    # merged CSS if the backstop failed), never before it.
    return _rehoist_top_of_sheet_at_rules(aggregated)

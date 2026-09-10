"""CSS parsing and merging utilities for slide deck editing."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Union

import tinycss2

# At-rules that a browser only honours at the very top of a stylesheet. After
# merging, the block list is stable-partitioned into @charset, then @import,
# then everything else -- because ``dict.update`` semantics hold position only
# for keys that ALREADY exist, so a replacement introducing an @import the
# existing sheet lacks would otherwise land last, where a browser ignores it.
_CHARSET_KEYWORD = "charset"
_IMPORT_KEYWORD = "import"


def parse_css_rules(css_text: Optional[str]) -> Dict[str, str]:
    """Parse CSS into a dict of {selector: declarations}.

    Qualified rules only -- at-rules and comments are not represented. Kept
    unchanged for callers that want the flat selector view; ``merge_css`` no
    longer uses it, because a selector dict cannot carry at-rules (see
    :func:`parse_css_blocks`).

    Args:
        css_text: Raw CSS string

    Returns:
        Dictionary mapping selectors to their declaration blocks

    Example:
        >>> parse_css_rules(".box { color: red; }")
        {'.box': 'color: red;'}
    """
    rules: Dict[str, str] = {}
    if not css_text:
        return rules
    
    try:
        parsed = tinycss2.parse_stylesheet(css_text, skip_whitespace=True)
        for rule in parsed:
            if rule.type == 'qualified-rule':
                selector = tinycss2.serialize(rule.prelude).strip()
                declarations = tinycss2.serialize(rule.content).strip()
                rules[selector] = declarations
    except Exception:
        # If parsing fails, return empty dict rather than crashing
        # The original CSS will be preserved
        pass
    
    return rules


@dataclass(frozen=True)
class CssBlock:
    """One top-level CSS block, in source order, with the key it dedupes on.

    Attributes:
        key: For a qualified rule, its serialized SELECTOR (``str``). For an
            at-rule, ``(lower_at_keyword, discriminator)`` -- the at-rule
            keyword **normalised to lowercase**, because CSS at-rule keywords
            are ASCII case-insensitive per spec, so ``@MEDIA print`` and
            ``@media print`` are the same rule and must share one key. ws4b's
            aggregator inherits this key, so the normalisation is part of the
            contract, not an implementation detail.
        text: For a qualified rule, the declaration block serialized with **no**
            newline normalization and no stripping -- leading/trailing padding
            included, so the author's internal whitespace and inline comments
            survive verbatim. For an at-rule, the COMPLETE block: its prelude
            and its content (or its terminating ``;`` for a block-less at-rule
            such as ``@import``).
        is_at_rule: True for at-rules, False for qualified rules.
    """

    key: Union[str, Tuple[str, str]]
    text: str
    is_at_rule: bool


def parse_css_blocks(css_text: Optional[str]) -> List[CssBlock]:
    """Parse CSS into an ORDERED list of blocks, at-rules included.

    Unlike :func:`parse_css_rules` this preserves at-rules, which CSS needs:
    ``@media``, ``@keyframes``, ``@supports``, ``@font-face``, ``@import``.

    An at-rule's dedupe key is ``(lower_at_keyword, discriminator)`` where the
    discriminator is the serialized, stripped prelude when that is non-empty,
    and the serialized content when it is not. Keying on the keyword alone
    would make a second ``@media`` overwrite the first; keying on the exact
    block text would make at-rules append-only, so an edited ``@media print``
    would accumulate a copy on every edit and a ``@keyframes`` could never be
    replaced. Prelude keying makes at-rules updatable *and* collapses identical
    copies to one.

    The keyword half is **normalised to lowercase** (tinycss2's
    ``lower_at_keyword``), because CSS at-rule keywords are ASCII
    case-insensitive per spec: ``@MEDIA print`` is the same rule as
    ``@media print`` and must not mint a second key, which would reintroduce
    the append-only failure through a case variant. Every consumer of this key
    -- including ws4b's aggregator and :func:`_hoist_top_of_sheet_at_rules`
    below -- may therefore rely on ``key[0]`` already being lowercase.

    The empty-prelude fallback is required, not a refinement: every
    ``@font-face`` serializes an empty prelude, and a brand stylesheet emits one
    ``@font-face`` per font FILE. Keying those on the prelude alone would
    collapse a three-weight family to one weight, and ``ensure_deck_token_css``
    would not notice because its guard is per-FAMILY. The cost is that an
    *edited* ``@font-face`` appends rather than replaces -- acceptable, since
    those blocks are machine-emitted from a deterministic sorted asset list.

    Known limits, inherited by any consumer:
      * Two at-rules sharing a keyword and a non-empty prelude collapse to one
        (the later block's text at the earlier block's position). Prelude
        whitespace is not part of the key (``@media  print`` keys as
        ``@media print``); whitespace *inside* a prelude is
        (``(min-width:40em)`` != ``(min-width: 40em)``).
      * Only ``qualified-rule`` and ``at-rule`` nodes become blocks. Comments
        are separate nodes and are dropped, which is what the previous
        implementation did. Malformed input does not raise -- tinycss2 returns
        a node for it -- so there is no parse-failure branch to rely on.

    Args:
        css_text: Raw CSS string, or None

    Returns:
        Blocks in source order. Empty list for None/empty/rule-free input.
    """
    blocks: List[CssBlock] = []
    if not css_text:
        return blocks

    try:
        parsed = tinycss2.parse_stylesheet(css_text, skip_whitespace=True)
    except Exception:
        # Defensive: tinycss2 returns error/degenerate nodes rather than
        # raising, but a caller must never lose its stylesheet to a crash here.
        return blocks

    for rule in parsed:
        if rule.type == 'qualified-rule':
            blocks.append(
                CssBlock(
                    key=tinycss2.serialize(rule.prelude).strip(),
                    text=tinycss2.serialize(rule.content),
                    is_at_rule=False,
                )
            )
        elif rule.type == 'at-rule':
            prelude = tinycss2.serialize(rule.prelude).strip()
            # @import / @charset have a prelude and NO block: content is None.
            content = '' if rule.content is None else tinycss2.serialize(rule.content)
            # lower_at_keyword, NOT at_keyword: CSS at-rule keywords are ASCII
            # case-insensitive, so `@MEDIA print` must key identically to
            # `@media print` or a case variant reintroduces the append-only
            # failure the prelude key exists to prevent.
            blocks.append(
                CssBlock(
                    key=(rule.lower_at_keyword, prelude if prelude else content),
                    text=tinycss2.serialize([rule]),
                    is_at_rule=True,
                )
            )
        # Everything else (comments, error nodes) is dropped, as before.

    return blocks


def _hoist_top_of_sheet_at_rules(blocks: List[CssBlock]) -> List[CssBlock]:
    """Stable-partition into @charset, then @import, then everything else.

    Relies on :func:`parse_css_blocks` having already lowercased ``key[0]``
    (``lower_at_keyword``), so no ``.lower()`` is repeated here: the
    normalisation is single-sourced at the one place the key is built, and a
    future change that broke it would fail the dedupe tests rather than leaving
    the hoist quietly working over a half-normalised key.
    """
    charset: List[CssBlock] = []
    imports: List[CssBlock] = []
    rest: List[CssBlock] = []

    for block in blocks:
        keyword = block.key[0] if block.is_at_rule else None
        if keyword == _CHARSET_KEYWORD:
            charset.append(block)
        elif keyword == _IMPORT_KEYWORD:
            imports.append(block)
        else:
            rest.append(block)

    return charset + imports + rest


def merge_css(existing_css: str, replacement_css: str) -> str:
    """Merge replacement CSS rules into existing CSS.

    Merge behavior:
        - Qualified rules in replacement_css override matching selectors in
          existing_css, IN PLACE: an overridden rule keeps its original
          position, so ``@font-face`` still precedes its consumers.
        - At-rules override by ``(lower_at_keyword, discriminator)`` -- see
          :func:`parse_css_blocks` -- so an edited ``@media print`` REPLACES the
          existing one instead of accumulating a second copy. This matters
          because this function's output is persisted and re-fed as
          ``existing_css`` on the next edit.
        - New blocks from replacement_css are appended, then ``@charset`` and
          ``@import`` are hoisted to the front, where a browser honours them.
        - Blocks in existing_css that replacement_css does not mention are
          preserved. Nothing is deleted by omission.
        - Top-level comments do not survive the merge (unchanged behaviour).

    An empty or rule-free replacement returns ``existing_css`` untouched. The
    guard is keyed on :func:`parse_css_blocks`, not :func:`parse_css_rules`:
    keying it on the latter would silently drop an at-rule-only replacement
    (``parse_css_rules`` yields ``{}`` for one), preserving half the bug this
    function was fixed for. Consequence for callers that want to dedupe by
    merging a concatenated sheet with ``""``: that call returns early, so they
    must fold pairwise instead.

    Args:
        existing_css: Current deck CSS
        replacement_css: CSS from LLM edit response

    Returns:
        Merged CSS string

    Example:
        >>> existing = ".box { color: red; } .card { padding: 10px; }"
        >>> replacement = ".box { color: blue; }"
        >>> merge_css(existing, replacement)
        '.box {\\ncolor: blue;\\n}\\n\\n.card {\\npadding: 10px;\\n}'
    """
    replacement_blocks = parse_css_blocks(replacement_css)

    if not replacement_blocks:
        # Nothing mergeable (empty, whitespace-only, comment-only, or parsing
        # yielded no rules) -- return the original unchanged.
        return existing_css

    # dict preserves insertion order, and assigning an EXISTING key replaces the
    # value in place: that is the override-in-position rule.
    merged: Dict[Union[str, Tuple[str, str]], CssBlock] = {}
    for block in parse_css_blocks(existing_css):
        merged[block.key] = block
    for block in replacement_blocks:
        merged[block.key] = block

    ordered = _hoist_top_of_sheet_at_rules(list(merged.values()))

    # Reconstruct CSS. Qualified-rule assembly is byte-for-byte what it has
    # always been -- `f"{selector} {{\n{declarations}\n}}"` with the serialized
    # content stripped, blocks joined by a blank line -- because
    # tests/sample_htmls/final_html.html pins it transitively through
    # SlideDeck.knit(). At-rules are emitted as serialized, which round-trips
    # their source formatting.
    css_parts: List[str] = []
    for block in ordered:
        if block.is_at_rule:
            css_parts.append(block.text)
        else:
            css_parts.append(f"{block.key} {{\n{block.text.strip()}\n}}")

    return '\n\n'.join(css_parts)

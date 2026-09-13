"""Template-section extraction for the LangGraph architect/builder pipeline.

Public API
----------
section_inventory(layout_html) -> list[dict]
    Compact structural inventory of each slide section in a template layout.
    Never contains markup; safe to inject into a model context.

extract_section(layout_html, index) -> str
    Verbatim markup of slide section at 0-based *index*, re-parented in its
    non-promoted ancestor chain so CSS inheritance is preserved.

resolve_template_bytes(design_system_id, template_id) -> tuple[str, str, str]
    (normalized_layout_html, style_block_css_text, token_css)

Division of labour (§M3)
------------------------
The architect ASSIGNS a template section (intent — model-appropriate);
deterministic code EXTRACTS its HTML and CSS byte-for-byte.  The architect
never rewrites layout HTML or CSS.  A model retyping brand markup has no
backstop, and this is the failure ``ensure_deck_token_css`` was built to catch.

Re-parenting
------------
``SLIDE_WRAPPER_TAGS`` is ``{"section", "article"}`` only.  A template that
wraps its slides in a non-promoting tag (``<main>``, ``<div>``) keeps that
wrapper's inheritable styles outside the extracted section: ``color``,
``font-family``, and any ``var(--…)`` the section consumes via inheritance all
fall back or reset once the wrapper is absent.

``extract_section`` therefore re-parents: it wraps the verbatim section in its
non-promoted ancestor chain, with those ancestors' other children stripped.
This is not a CSS rewrite (§M5 forbids pruning CSS); it is a markup rewrap that
restores the inheritance context the section depends on.

A section whose ancestors are all promoting tags (``section``, ``article``) is
returned unwrapped — ``find_slide_roots`` already promoted the wrapper to the
root, so there is no non-promoting ancestor to add.

Return values of ``resolve_template_bytes``
-------------------------------------------
| value                  | source                                        |
|------------------------|-----------------------------------------------|
| normalized_layout_html | template.layout_html after materialize_templates (verbatim) |
| style_block_css_text   | CSS text EXTRACTED from <style> blocks inside layout_html, UNWRAPPED |
| token_css              | template.token_css verbatim, or ""            |

``aggregate_deck_css``'s contract is **CSS text**; a ``<style>``-wrapped block
silently parses to tinycss2 error nodes and is dropped — no exception, no log.
The second return value is therefore always unwrapped CSS text, never the tags.
"""

from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup

from src.utils.html_utils import SLIDE_WRAPPER_TAGS, find_slide_roots

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────────

_STYLE_BLOCK_RE = re.compile(
    r"<style(?:\s[^>]*)?>(.+?)</style>",
    re.DOTALL | re.IGNORECASE,
)


def _extract_style_blocks_css(layout_html: str) -> str:
    """Concatenate the CSS *text* inside every ``<style>`` block in layout_html.

    Returns the CSS text between the tags, never the tags themselves.
    ``aggregate_deck_css`` expects unwrapped CSS text; a ``<style>``-wrapped
    block is silently dropped (tinycss2 error nodes).

    Returns ``""`` when no ``<style>`` blocks are present.
    """
    blocks = _STYLE_BLOCK_RE.findall(layout_html)
    return "\n".join(blocks)


def _find_element_end(html: str, tag: str, start: int) -> int:
    """Return the index just past the closing ``>`` of the ``<tag>…</tag>``
    element that begins at ``html[start]``.

    Handles nesting: counts open/close tags of the same name to find the
    matching close tag.  Falls back to ``len(html)`` for unclosed elements.

    Self-closing void elements (``<img/>``) encountered INSIDE the element are
    handled correctly because their opening tags are excluded by the
    ``(?<!/)>`` anchor in ``open_re``.
    """
    tag_l = tag.lower()
    # Match non-self-closing opening tags: <tag or <tag whitespace...>
    open_re = re.compile(
        r"<" + re.escape(tag_l) + r"(?=[\s>])[^>]*(?<!/)>",
        re.IGNORECASE,
    )
    close_re = re.compile(
        r"</" + re.escape(tag_l) + r"\s*>",
        re.IGNORECASE,
    )

    first = open_re.match(html, start)
    if first is None:
        return start  # shouldn't happen for valid elements

    depth = 1
    i = first.end()

    while i < len(html) and depth > 0:
        open_m = open_re.search(html, i)
        close_m = close_re.search(html, i)

        o_pos = open_m.start() if open_m else len(html)
        c_pos = close_m.start() if close_m else len(html)

        if c_pos <= o_pos:
            depth -= 1
            if depth == 0:
                return close_m.end()
            i = close_m.end()
        else:
            depth += 1
            i = open_m.end()

    return len(html)  # unclosed element fallback


def _verbatim_slices(layout_html: str, soup: BeautifulSoup, roots: list) -> list[str]:
    """Return the verbatim HTML slice for each BS4 root element.

    Finds each root's ordinal position among all elements with the same tag
    name in the BS4 tree, then locates the corresponding span in the original
    HTML string using ``_find_element_end``.  Does not pass through BS4's
    serializer, so attribute quoting and void-element syntax are preserved.

    Args:
        layout_html: The original, unparsed HTML string.
        soup: Parsed BS4 document (must be parsed from layout_html).
        roots: BS4 Tag objects from ``find_slide_roots`` — may include
            promoted wrapper elements that do NOT carry ``class="slide"``.

    Returns:
        Verbatim strings in document order, one per root.  Falls back to
        ``str(root)`` (BS4 serialization) if the ordinal cannot be located,
        with a warning logged.

    Assumptions:
        Template HTML does not contain same-tag elements inside comments or
        CDATA sections.  Commented-out ``<section>`` tags (for example) would
        cause an ordinal mismatch.  In-repo design-system templates satisfy
        this constraint.
    """
    result = []

    for root in roots:
        tag = root.name

        # Find this root's ordinal among all same-tag elements in the BS4 tree.
        # Use identity (``el is root``), not equality, because BS4's __eq__
        # compares by structure and two identical slides would appear equal.
        all_of_tag = list(soup.find_all(tag))
        ordinal = next(
            (i for i, el in enumerate(all_of_tag) if el is root),
            None,
        )

        if ordinal is None:
            logger.warning(
                "_verbatim_slices: could not locate root <%s> by identity; "
                "returning BS4 serialization (attribute quoting may differ)",
                tag,
            )
            result.append(str(root))
            continue

        # Find the ordinal-th ``<tag`` in the original HTML string.
        open_pattern = re.compile(r"<" + re.escape(tag) + r"(?=[\s>])", re.IGNORECASE)
        matches = list(open_pattern.finditer(layout_html))

        if ordinal >= len(matches):
            logger.warning(
                "_verbatim_slices: ordinal %d out of range for <%s>; "
                "returning BS4 serialization",
                ordinal,
                tag,
            )
            result.append(str(root))
            continue

        start = matches[ordinal].start()
        end = _find_element_end(layout_html, tag, start)
        result.append(layout_html[start:end])

    return result


def _verbatim_open_tag(layout_html: str, soup: BeautifulSoup, el) -> str:
    """Return the verbatim opening tag of ``el`` from ``layout_html``.

    Uses the same ordinal-position approach as ``_verbatim_slices``: finds
    which occurrence of the tag in BS4's tree corresponds to ``el``, then
    slices up to the first ``>`` in the original HTML.

    Assumes attribute values do not contain unquoted ``>``.  Falls back to a
    constructed ``<tag>`` on any mismatch.
    """
    tag = el.name
    all_of_tag = list(soup.find_all(tag))
    ordinal = next((i for i, e in enumerate(all_of_tag) if e is el), None)
    if ordinal is None:
        return f"<{tag}>"

    open_pattern = re.compile(r"<" + re.escape(tag) + r"(?=[\s>])", re.IGNORECASE)
    matches = list(open_pattern.finditer(layout_html))
    if ordinal >= len(matches):
        return f"<{tag}>"

    start = matches[ordinal].start()
    # Find the end of the opening tag's `>` (assumes no `>` in attribute values)
    end = layout_html.index(">", start) + 1
    return layout_html[start:end]


def _reparent_if_needed(
    layout_html: str,
    soup: BeautifulSoup,
    root,
    verbatim_section: str,
) -> str:
    """Wrap ``verbatim_section`` in its non-promoting ancestor chain, if any.

    Walk up from ``root`` through ancestors that are NOT in
    ``SLIDE_WRAPPER_TAGS`` (i.e. non-promoting tags like ``<main>`` or
    ``<div>``).  For each such ancestor, prepend its verbatim opening tag and
    append the corresponding closing tag, with all other children of that
    ancestor stripped.

    Stops when: the ancestor tag is in ``SLIDE_WRAPPER_TAGS`` (promoting:
    ``section`` or ``article``), or the ancestor has no name (document root).

    A section whose immediate ancestors are all promoting tags is returned
    unchanged — ``find_slide_roots`` already promoted those wrappers to the
    root, so there is nothing to add.

    Args:
        layout_html: Original, unparsed HTML string.
        soup: Parsed BS4 document.
        root: BS4 Tag returned by ``find_slide_roots`` (possibly promoted).
        verbatim_section: The verbatim HTML slice of the root element.

    Returns:
        The section, wrapped in its non-promoting ancestor chain (innermost to
        outermost), with sibling children stripped.
    """
    ancestors = []
    el = root.parent
    # isinstance(el, BeautifulSoup) identifies the document root ([document]).
    # Its name is '[document]', not None — check the type, not the name.
    while el is not None and not isinstance(el, BeautifulSoup):
        if el.name in SLIDE_WRAPPER_TAGS:
            break  # promoting ancestor — don't add a promoting wrapper
        ancestors.append(el)
        el = el.parent

    if not ancestors:
        return verbatim_section

    # Wrap from innermost ancestor outward.
    result = verbatim_section
    for anc in ancestors:
        open_tag = _verbatim_open_tag(layout_html, soup, anc)
        result = open_tag + result + f"</{anc.name}>"

    return result


def _detect_affordances(root_soup) -> list[str]:
    """Return structural affordances present in the element.

    Checks for: ``canvas``, ``image``, ``table``, ``list`` (ul or ol).
    """
    affordances: list[str] = []
    if root_soup.find("canvas"):
        affordances.append("canvas")
    if root_soup.find("img"):
        affordances.append("image")
    if root_soup.find("table"):
        affordances.append("table")
    if root_soup.find(["ul", "ol"]):
        affordances.append("list")
    return affordances


def _text_snippet(root_soup, max_len: int = 80) -> str:
    """Extract a short text snippet (no markup) from the element."""
    text = root_soup.get_text(separator=" ", strip=True)
    if len(text) > max_len:
        text = text[:max_len] + "…"
    return text


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def section_inventory(layout_html: str) -> list[dict]:
    """Return a compact structural inventory of each slide section.

    Each entry is a plain dict with exactly these keys:
        index (int): 0-based position in document order
        tag (str): element tag name (e.g. ``"section"``, ``"div"``)
        classes (list[str]): the element's class tokens
        text_snippet (str): up to 80 chars of visible text content (no markup)
        affordances (list[str]): structural features detected — any of:
            ``"canvas"``, ``"image"``, ``"table"``, ``"list"``

    The inventory contains **no markup** and is intentionally small — a few
    hundred bytes per section — for safe injection into a model context.

    Zero-roots is a **named outcome**, not empty success.  A layout whose slide
    roots carry no ``slide`` class token (a brand template with non-standard
    root classes) yields an empty list AND a ``WARNING``-level log so callers
    know to activate the no-template fallback.

    Args:
        layout_html: Full HTML of the design-system template layout.

    Returns:
        List of section dicts, one per slide root, in document order.
        Returns ``[]`` (with a warning) when the layout has no slide roots.
    """
    soup = BeautifulSoup(layout_html, "html.parser")
    roots = find_slide_roots(soup)

    if not roots:
        logger.warning(
            "section_inventory: layout has no elements with class='slide'; "
            "treat as no-template fallback (brand templates with non-standard "
            "root classes cannot be inventoried)."
        )
        return []

    inventory = []
    for i, root in enumerate(roots):
        inventory.append(
            {
                "index": i,
                "tag": root.name,
                "classes": list(root.get("class") or []),
                "text_snippet": _text_snippet(root),
                "affordances": _detect_affordances(root),
            }
        )
    return inventory


def extract_section(layout_html: str, index: int) -> str:
    """Return the **verbatim** markup of the slide section at 0-based *index*,
    wrapped in its non-promoting ancestor chain.

    Uses ``find_slide_roots`` to identify each section (applying wrapper
    promotion for ``SLIDE_WRAPPER_TAGS``), extracts the verbatim HTML of the
    root element, then wraps it in any non-promoting ancestor tags (``<main>``,
    ``<div>``, etc.) so that inherited CSS properties — ``color``,
    ``font-family``, and custom properties consumed via ``var(--…)`` — are
    preserved.  Siblings of this section are stripped from each ancestor.

    A section whose immediate ancestors are all promoting tags (``section``,
    ``article``) is returned without additional wrapping — ``find_slide_roots``
    already promoted those wrappers.

    The section element's own markup (and its descendants) is byte-for-byte
    verbatim from ``layout_html``: BS4's serializer normalises attribute quoting
    (single → double) and self-closing-tag syntax; the verbatim approach
    preserves the template author's exact markup.

    Args:
        layout_html: Full HTML of the design-system template layout.
        index: 0-based section index.

    Returns:
        Verbatim HTML string of the section element, optionally wrapped in its
        non-promoting ancestor chain with siblings stripped.

    Raises:
        IndexError: when ``index >= number of slide roots`` or the layout has
            no slide roots at all.
    """
    soup = BeautifulSoup(layout_html, "html.parser")
    roots = find_slide_roots(soup)

    if index < 0 or index >= len(roots):
        raise IndexError(
            f"Section index {index} is out of range: "
            f"layout has {len(roots)} slide root(s)."
        )

    root = roots[index]
    verbatim = _verbatim_slices(layout_html, soup, [root])[0]
    return _reparent_if_needed(layout_html, soup, root, verbatim)


# No-template sentinel — returned instead of (None, None, None) so callers
# can unpack unconditionally without checking for None values.
_EMPTY: tuple[str, str, str] = ("", "", "")


def resolve_template_bytes(
    design_system_id: int,
    template_id: int,
) -> tuple[str, str, str]:
    """Resolve a pinned template's bytes, routing through materialize_templates.

    Returns a three-tuple:
        normalized_layout_html (str):
            ``template.layout_html`` after ``materialize_templates`` has run
            its root-tag selector normalisation pass.  Verbatim from the row.
        style_block_css_text (str):
            CSS text EXTRACTED from the ``<style>`` blocks inside
            ``layout_html``, **unwrapped** — never the ``<style>`` tags.
            ``aggregate_deck_css`` expects CSS text; a ``<style>``-wrapped block
            silently parses to tinycss2 error nodes and is dropped.
            Returns ``""`` when no ``<style>`` blocks are present.
        token_css (str):
            ``template.token_css`` verbatim, or ``""`` when ``None``.

    On the no-template path returns ``("", "", "")``.  The no-template path is
    activated by: an inactive or unknown design-system id, an invalid
    template_id (not found on that design system), or any unexpected error
    (fails closed).

    Implementation notes:
        * Lazy-imports ``get_db_session`` and ``DesignSystem`` inside the
          function, mirroring ``agent_factory``'s pattern.  A module-level
          import is patched in the wrong scope by tests.
        * The design system is loaded inside ``get_db_session`` with
          ``is_active=True`` so materialize_templates can persist its self-heal
          normalisation pass; a detached row would silently lose that.
        * ``get_template_for_generation`` calls ``materialize_templates``, which
          assigns ``template.layout_html`` with normalised selectors.  Reading
          ``layout_html`` before that pass yields selectors that never match
          generated ``<div class="slide">`` roots — a silent styling loss.
        * ``get_template_for_generation`` MUST be called inside the same
          ``get_db_session`` context so SQLAlchemy can commit the self-heal
          write when the context exits.

    Args:
        design_system_id: Primary key of the DesignSystem row.
        template_id: Primary key of the DesignSystemTemplate row.

    Returns:
        ``(normalized_layout_html, style_block_css_text, token_css)`` or
        ``("", "", "")`` on the no-template path.
    """
    try:
        from src.core.database import get_db_session
        from src.database.models import DesignSystem
        from src.services.design_system_templates import get_template_for_generation

        with get_db_session() as db:
            # (a) Load and (c) filter on is_active — fails closed.
            # Mirrors agent_factory._design_system_is_active's query pattern
            # but loads the full row so materialize_templates can run in-session.
            design_system = (
                db.query(DesignSystem)
                .filter_by(id=design_system_id, is_active=True)
                .first()
            )
            if design_system is None:
                logger.warning(
                    "resolve_template_bytes: design system %d not found or "
                    "inactive; returning no-template result.",
                    design_system_id,
                )
                return _EMPTY

            # (b) Route through get_template_for_generation, which calls
            # materialize_templates.  MUST be inside the same session so the
            # self-heal normalisation write is committed when the context exits
            # (materialize_templates leaves persistence to the calling session).
            template = get_template_for_generation(design_system, template_id)

            if template is None:
                logger.warning(
                    "resolve_template_bytes: template %d not found on design "
                    "system %d; returning no-template result.",
                    template_id,
                    design_system_id,
                )
                return _EMPTY

            normalized_layout_html = template.layout_html or ""
            style_block_css = _extract_style_blocks_css(normalized_layout_html)
            token_css = template.token_css or ""

            return (normalized_layout_html, style_block_css, token_css)

    except Exception:
        logger.exception(
            "resolve_template_bytes: unexpected error resolving "
            "design_system_id=%d template_id=%d; returning no-template result.",
            design_system_id,
            template_id,
        )
        return _EMPTY

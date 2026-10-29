"""Deck style helpers: sanitising, class scanning and architect context.

The architect may author a ``DeckStyle`` (CSS plus a component catalogue) that
adds to the brand. Its CSS is merged into the deck beside the template's, so it
must not be able to restyle anything but its own ``dk-`` classes, fetch remote
resources, or end the ``<style>`` element it is inlined in.

This module is pure: no DB, no network, no service or API imports.

Sanitising rules (see :func:`sanitise_deck_style`):

- Every at-rule is dropped. ``merge_css`` keys at-rules by (keyword, prelude), so
  a deck-style ``@media`` would replace the template's.
- ``:root`` is dropped when a design system is active (same keying problem),
  otherwise only its ``--dk-`` custom properties survive.
- A selector is kept only when some compound has a top-level ``.dk-`` class and
  every combinator right of the first such compound is descendant or ``>``.
- Declarations with a non-``data:`` ``url()``, ``expression()`` or a remote
  address (``http:``, ``https:``, ``//``) are dropped. The content of a
  ``url(data:...)`` is exempt: SVG data URIs carry an ``xmlns='http://...'``.
- Nested rules are dropped; the parent's declarations are kept.
- Empty rules are dropped, and ``<style`` / ``</style`` text never survives.

When nothing is removed the input object comes back with its CSS text
byte-identical; new text is built only when something was dropped.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from html.parser import HTMLParser
from typing import Any

import tinycss2
from tinycss2.serializer import serialize_identifier

from src.domain.deck_spec import DeckStyle

DECK_STYLE_CLASS_PREFIX = "dk-"
DECK_STYLE_VAR_PREFIX = "--dk-"
DECK_STYLE_TARGET_CHARS = 4000
DECK_STYLE_MAX_CHARS = 10000
DECK_STYLE_MAX_COMPONENTS = 12

_MAX_TOKEN_VALUE_CHARS = 120
_MAX_TEMPLATE_CLASSES = 300
_MAX_NOTE_CHARS = 200
_MAX_QUOTED_CHARS = 60

_STYLE_OPEN = re.compile(r"\A\s*<style\b[^>]*>", re.IGNORECASE)
_STYLE_CLOSE = re.compile(r"</style\s*>\s*\Z", re.IGNORECASE)
_STYLE_TEXT = re.compile(r"</?\s*style", re.IGNORECASE)
_REMOTE_TEXT = re.compile(r"https?:|//", re.IGNORECASE)
# A browser's URL parser removes these before it reads a scheme or "//".
_URL_IGNORED_CHARS = re.compile(r"[\t\n\r]")

# Functions that load or paint an image from a string, URL or element (R15).
_IMAGE_FUNCTIONS = frozenset(
    {"image-set", "-webkit-image-set", "cross-fade", "-webkit-cross-fade", "src", "element", "-moz-element"}
)

# At-rules whose block holds ordinary rules, so selectors inside carry classes.
_NESTING_AT_RULES = frozenset(
    {"media", "supports", "layer", "container", "document", "scope", "starting-style"}
)


# --- class scanning -----------------------------------------------------------


def _tokens_in(node: Any) -> list:
    """Child tokens of a block or function token."""
    return list(getattr(node, "content", None) or getattr(node, "arguments", None) or [])


def _classes_in_tokens(tokens: list) -> set[str]:
    """Class names in a selector token list, including inside ``:not(...)`` etc."""
    found: set[str] = set()
    for i, tok in enumerate(tokens):
        if tok.type == "literal" and tok.value == ".":
            nxt = tokens[i + 1] if i + 1 < len(tokens) else None
            if nxt is not None and nxt.type == "ident":
                found.add(nxt.value)
        elif tok.type in ("function", "() block", "[] block", "{} block"):
            found |= _classes_in_tokens(_tokens_in(tok))
    return found


def css_class_names(css: str) -> frozenset[str]:
    """Class names used in selectors, including inside ``@media`` and friends.

    Declaration values, comments, strings, attribute selectors and the content of
    ``@import``/``@font-face``/``@keyframes`` never yield a class.
    """
    return frozenset(_classes_in_rules(tinycss2.parse_stylesheet(css, skip_comments=True, skip_whitespace=True)))


def _classes_in_rules(rules: list) -> set[str]:
    found: set[str] = set()
    for rule in rules:
        if rule.type == "qualified-rule":
            found |= _classes_in_tokens(rule.prelude)
        elif rule.type == "at-rule" and rule.content and rule.lower_at_keyword in _NESTING_AT_RULES:
            if rule.lower_at_keyword == "scope":
                # "@scope (.root) to (.limit)": the prelude holds selectors too.
                found |= _classes_in_tokens(rule.prelude)
            inner = tinycss2.parse_rule_list(rule.content, skip_comments=True, skip_whitespace=True)
            found |= _classes_in_rules(inner)
    return found


class _ClassCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.names: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if name == "class" and value:
                self.names.update(value.split())


def html_class_names(html: str) -> frozenset[str]:
    """Tokens of every ``class`` attribute in ``html``."""
    collector = _ClassCollector()
    collector.feed(html)
    collector.close()
    return frozenset(collector.names)


# --- sanitiser ----------------------------------------------------------------


def _short(text: str) -> str:
    """``text`` with whitespace squashed, cut short enough to quote in a note."""
    text = " ".join(text.split())
    return text if len(text) <= _MAX_QUOTED_CHARS else text[: _MAX_QUOTED_CHARS - 1] + "…"


def _capped(notes: list[str]) -> tuple[str, ...]:
    """Notes cut to ``_MAX_NOTE_CHARS`` each: they quote model-written CSS into a retry prompt."""
    return tuple(n if len(n) <= _MAX_NOTE_CHARS else n[: _MAX_NOTE_CHARS - 1] + "…" for n in notes)


def _split_selectors(prelude: list) -> list[list]:
    """Split a prelude on top-level commas."""
    selectors: list[list] = [[]]
    for tok in prelude:
        if tok.type == "literal" and tok.value == ",":
            selectors.append([])
        else:
            selectors[-1].append(tok)
    return [s for s in selectors if any(t.type != "whitespace" for t in s)]


def _compounds(tokens: list) -> tuple[list[list], list[str]]:
    """Split a selector into compounds and the combinator that follows each.

    The last compound's combinator is ``""``.
    """
    compounds: list[list] = []
    combinators: list[str] = []
    current: list = []
    pending_space = False
    for tok in tokens:
        if tok.type == "whitespace":
            pending_space = pending_space or bool(current)
        elif tok.type == "literal" and tok.value in (">", "+", "~"):
            if current:
                compounds.append(current)
                combinators.append(tok.value)
                current = []
            pending_space = False
        else:
            if pending_space and current:
                compounds.append(current)
                combinators.append(" ")
                current = []
            pending_space = False
            current.append(tok)
    if current:
        compounds.append(current)
        combinators.append("")
    return compounds, combinators


def _has_top_level_dk_class(compound: list) -> bool:
    return any(
        tok.type == "literal"
        and tok.value == "."
        and i + 1 < len(compound)
        and compound[i + 1].type == "ident"
        and compound[i + 1].value.startswith(DECK_STYLE_CLASS_PREFIX)
        for i, tok in enumerate(compound)
    )


def _is_scoped(tokens: list) -> bool:
    """True when the selector can only style ``dk-`` classes and their descendants."""
    compounds, combinators = _compounds(tokens)
    for i, compound in enumerate(compounds):
        if _has_top_level_dk_class(compound):
            return all(c in (" ", ">", "") for c in combinators[i:])
    return False


def _value_text(tokens: list, *, parts: list[str]) -> str | None:
    """Collect the text of a declaration value into ``parts``.

    Returns the reason the value must be dropped, or ``None``. Strings are added
    decoded, and ``url(data:...)`` contents are skipped (the exemption).
    """
    for tok in tokens:
        kind = tok.type
        if kind == "url":
            if not tok.value.strip().lower().startswith("data:"):
                return "url() other than data:"
        elif kind == "function":
            name = tok.lower_name
            if name == "expression":
                return "expression()"
            if name in _IMAGE_FUNCTIONS:
                return f"{name}() is not allowed"
            if name == "url":
                args = [a for a in tok.arguments if a.type != "whitespace"]
                first = args[0] if args else None
                if not (first is not None and first.type == "string" and first.value.strip().lower().startswith("data:")):
                    return "url() other than data:"
                continue
            parts.append(name + "(")
            reason = _value_text(tok.arguments, parts=parts)
            if reason:
                return reason
        elif kind in ("() block", "[] block", "{} block"):
            reason = _value_text(_tokens_in(tok), parts=parts)
            if reason:
                return reason
        elif kind == "string":
            parts.append(tok.value)
        else:
            parts.append(tinycss2.serialize([tok]))
    return None


def _declaration_problem(decl: Any) -> str | None:
    """Why a declaration must be dropped, or ``None`` when it is fine."""
    parts: list[str] = []
    reason = _value_text(decl.value, parts=parts)
    if reason:
        return reason
    text = "".join(parts)
    # Read the text as a URL parser does: "/\t/x" and "\\x" both mean "//x".
    if _REMOTE_TEXT.search(_URL_IGNORED_CHARS.sub("", text).replace("\\", "/")):
        return "remote address (http:, https: or //)"
    if _STYLE_TEXT.search(tinycss2.serialize(decl.value)) or _STYLE_TEXT.search(text):
        return "<style text"
    return None


def _serialise_declaration(decl: Any) -> str:
    # tinycss2 unescapes the name: written back raw, "\7d" would be a live "}"
    # and "\3c\2fstyle" a live "</style".
    important = " !important" if decl.important else ""
    return f"{serialize_identifier(decl.name)}:{tinycss2.serialize(decl.value).strip()}{important}"


def _clean_rule(rule: Any, *, design_system_active: bool, notes: list[str]) -> str | None:
    """Return the cleaned text of a qualified rule, or ``None`` to drop it."""
    selectors = _split_selectors(rule.prelude)
    selector_texts = [tinycss2.serialize(s).strip() for s in selectors]
    is_root = len(selector_texts) == 1 and selector_texts[0].lower() == ":root"
    label = _short(tinycss2.serialize(rule.prelude))

    if is_root and design_system_active:
        notes.append(":root rule dropped: the design system supplies the tokens")
        return None

    if is_root:
        kept_selectors = selector_texts
    else:
        kept_selectors = []
        for tokens, text in zip(selectors, selector_texts):
            if _STYLE_TEXT.search(text):
                notes.append(f"selector {_short(text)!r} dropped: contains <style text")
            elif _is_scoped(tokens):
                kept_selectors.append(text)
            else:
                notes.append(f"selector {_short(text)!r} dropped: not scoped to a dk- class")
        if not kept_selectors:
            return None

    declarations: list[str] = []
    seen_content = False
    for item in tinycss2.parse_blocks_contents(rule.content, skip_comments=True, skip_whitespace=True):
        seen_content = True
        if item.type == "declaration":
            if is_root and not item.name.startswith(DECK_STYLE_VAR_PREFIX):
                notes.append(
                    f":root declaration {_short(item.name)!r} dropped: only --dk- custom properties are kept"
                )
                continue
            problem = _declaration_problem(item)
            if problem:
                notes.append(f"{label}: declaration {_short(item.name)!r} dropped ({problem})")
                continue
            declarations.append(_serialise_declaration(item))
        elif item.type == "qualified-rule":
            nested = _short(tinycss2.serialize(item.prelude))
            notes.append(f"{label}: nested rule {nested!r} dropped")
        elif item.type == "at-rule":
            notes.append(f"{label}: nested @{_short(item.at_keyword)} dropped")
        else:
            notes.append(f"{label}: unparseable declaration dropped")

    if not declarations:
        if not seen_content:
            notes.append(f"empty rule {label!r} dropped")
        return None
    return f"{', '.join(kept_selectors)}{{{';'.join(declarations)}}}"


def _clean_css(css: str, *, design_system_active: bool, notes: list[str]) -> tuple[list[str], bool]:
    """Clean ``css``; returns the rebuilt text of each kept rule, and whether anything was removed."""
    start = len(notes)
    stripped = css
    if _STYLE_OPEN.search(stripped) or _STYLE_CLOSE.search(stripped):
        stripped = _STYLE_CLOSE.sub("", _STYLE_OPEN.sub("", stripped, count=1), count=1)
        notes.append("removed the <style> wrapper")
    parsed_from = len(notes)

    rules: list[str] = []
    for node in tinycss2.parse_stylesheet(stripped, skip_comments=True, skip_whitespace=True):
        if node.type == "qualified-rule":
            text = _clean_rule(node, design_system_active=design_system_active, notes=notes)
            if text is not None:
                rules.append(text)
        elif node.type == "at-rule":
            notes.append(f"@{_short(node.at_keyword)} rule dropped: at-rules are not allowed in a deck style")
        else:
            notes.append("unparseable CSS dropped")

    # "</style" in a comment is skipped by the parse without a note of its own,
    # yet it must force the rebuild that leaves the comment out.
    if _STYLE_TEXT.search(stripped) and not any("<style" in n for n in notes[parsed_from:]):
        notes.append("removed text containing <style from the CSS")
    return rules, len(notes) > start


def _rebuild_problem(css: str, *, design_system_active: bool) -> str | None:
    """Why rebuilt CSS fails the R15 post-condition, or ``None``.

    Rebuilt text must be a fixed point: sanitising it again removes nothing, and
    it holds no ``<style`` text.
    """
    again: list[str] = []
    _, changed = _clean_css(css, design_system_active=design_system_active, notes=again)
    if changed:
        return again[0]
    if _STYLE_TEXT.search(css):
        return "<style text"
    return None


def _component_problem(component: Any, defined: frozenset[str]) -> str | None:
    names = component.class_names
    if not names:
        return "it lists no classes"
    bad = [n for n in names if not n.startswith(DECK_STYLE_CLASS_PREFIX)]
    if bad:
        return f"class {_short(bad[0])!r} lacks the {DECK_STYLE_CLASS_PREFIX} prefix"
    missing = [n for n in names if n not in defined]
    if missing:
        return f"class {_short(missing[0])!r} is not defined in the CSS"
    return None


def sanitise_deck_style(
    style: DeckStyle | None, *, design_system_active: bool
) -> tuple[DeckStyle | None, tuple[str, ...]]:
    """Clean an architect-authored deck style.

    Returns the cleaned style and one note per thing removed, each at most
    ``_MAX_NOTE_CHARS`` long. A style that needs no change comes back as the same
    object with ``()`` notes. ``(None, notes)`` is returned when no rule is left
    (blank or comment-only CSS), when the rebuilt CSS fails the post-condition,
    or when the CSS is longer than ``DECK_STYLE_MAX_CHARS``. Components are
    checked against the cleaned CSS.
    """
    if style is None:
        return None, ()

    notes: list[str] = []
    rules, changed = _clean_css(style.css, design_system_active=design_system_active, notes=notes)
    if not rules:
        notes.append("deck style dropped: its CSS has no rules after cleaning")
        return None, _capped(notes)

    css = "\n".join(rules) if changed else style.css
    if changed:
        problem = _rebuild_problem(css, design_system_active=design_system_active)
        if problem:
            notes.append(f"deck style dropped: post-condition failed on the rebuilt CSS ({problem})")
            return None, _capped(notes)
    if len(css) > DECK_STYLE_MAX_CHARS:
        notes.append(f"deck style dropped: its CSS is {len(css)} characters, over the {DECK_STYLE_MAX_CHARS} limit")
        return None, _capped(notes)

    defined = css_class_names(css)
    components = []
    for component in style.components:
        problem = _component_problem(component, defined)
        if problem:
            notes.append(f"component {_short(component.name)!r} dropped: {problem}")
        else:
            components.append(component)
    for extra in components[DECK_STYLE_MAX_COMPONENTS:]:
        notes.append(f"component {_short(extra.name)!r} dropped: more than {DECK_STYLE_MAX_COMPONENTS} components")
    components = components[:DECK_STYLE_MAX_COMPONENTS]

    if not notes:
        return style, ()
    return DeckStyle(css=css, components=components), _capped(notes)


# --- prior vs new style -------------------------------------------------------


def dropped_classes_in_use(
    prior: DeckStyle | None, new: DeckStyle | None, kept_rows: Mapping[int, str]
) -> dict[str, tuple[int, ...]]:
    """Classes the prior style defined and the new one does not, that kept slides use.

    ``kept_rows`` maps slide position to slide HTML. The result maps each such
    class to the sorted positions of the rows using it; unused classes are omitted.
    """
    if prior is None:
        return {}
    dropped = css_class_names(prior.css) - (css_class_names(new.css) if new else frozenset())
    row_classes = {pos: html_class_names(html) for pos, html in kept_rows.items()}
    result: dict[str, tuple[int, ...]] = {}
    for name in sorted(dropped):
        positions = tuple(sorted(pos for pos, names in row_classes.items() if name in names))
        if positions:
            result[name] = positions
    return result


# --- architect context --------------------------------------------------------


def _root_tokens(css: str) -> dict[str, str]:
    """Custom properties declared in ``:root`` rules, minus long or url values."""
    tokens: dict[str, str] = {}
    for rule in tinycss2.parse_stylesheet(css, skip_comments=True, skip_whitespace=True):
        if rule.type != "qualified-rule":
            continue
        if not any(tinycss2.serialize(s).strip().lower() == ":root" for s in _split_selectors(rule.prelude)):
            continue
        for item in tinycss2.parse_blocks_contents(rule.content, skip_comments=True, skip_whitespace=True):
            if item.type != "declaration" or not item.name.startswith("--"):
                continue
            value = tinycss2.serialize(item.value).strip()
            if len(value) <= _MAX_TOKEN_VALUE_CHARS and "url(" not in value.lower():
                tokens[item.name] = value
    return tokens


def deck_style_context(token_css: str, style_block: str) -> dict:
    """Design tokens and template classes the architect may reference.

    ``design_tokens`` are the ``:root`` custom properties of both inputs.
    ``template_classes`` are the sorted unique classes of ``style_block``, capped
    at 300. Font data never appears.
    """
    return {
        "design_tokens": {**_root_tokens(token_css), **_root_tokens(style_block)},
        "template_classes": sorted(css_class_names(style_block))[:_MAX_TEMPLATE_CLASSES],
    }

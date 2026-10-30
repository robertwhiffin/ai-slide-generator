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
  address (``http:``, ``https:``, ``//``) are dropped. The address scan first
  removes tab/LF/CR and reads ``\\`` as ``/``, as browsers' URL parsers do. The
  content of a ``url(data:...)`` is exempt: SVG data URIs carry an
  ``xmlns='http://...'``.
- Declarations using an image function (``image-set()``, ``cross-fade()``,
  ``src()``, ``element()`` and their prefixed spellings) are dropped.
- Nested rules are dropped; the parent's declarations are kept.
- Repeated selectors are coalesced: their declarations, in source order, move
  to the last occurrence (``merge_css`` would otherwise keep only the last).
- Empty rules are dropped, CSS with no rule left is blank, and ``<style`` /
  ``</style`` text never survives.
- A selector or value that ends in a bare ``\\``, or holds a bad or unterminated
  string or url, is dropped: written back, it would escape or swallow what
  follows it.
- The CSS never leaves a construct open: a rule written after it must parse as
  its own rule. Every view writes trusted CSS after ``deck.css`` in the same
  ``<style>``, so a trailing ``/*``, an open ``{``, string, ``calc(`` or
  ``url(`` would swallow it. Open text is rebuilt from its rules, which close.
- Lone surrogates (``\\D800`` decodes to one) become U+FFFD in the CSS, the
  components and the notes, so every string encodes as UTF-8.
- A rebuilt sheet must re-sanitise with no notes and close, or the style is
  dropped.
- Each note is capped at 200 characters.

When nothing is removed the input object comes back with its CSS text
byte-identical; new text is built only when something was dropped. A blank
result, or one over ``DECK_STYLE_MAX_CHARS``, is ``None``.
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
# The only code points UTF-8 cannot encode.  tinycss2 decodes "\D800" to one,
# where a browser reads U+FFFD.
_SURROGATES = re.compile("[\ud800-\udfff]")
# Parse errors whose token tinycss2 writes back as open text: '"[bad string]' and
# 'url([bad url])' for a bad token, and the original text without its closing
# quote or ")" for one cut off by the end of the CSS.
_OPEN_TOKEN_ERRORS = {
    "bad-string": "a bad string",
    "bad-url": "a bad url",
    "eof-in-string": "a string left open at the end",
    "eof-in-url": "a url left open at the end",
}

# The closure post-condition's probe: a rule written after the deck style, as
# every view surface writes its trusted CSS after deck.css in one <style>.
_FOLLOWER_SELECTOR = ".dk-sentinel-probe"
_FOLLOWER_RULE = _FOLLOWER_SELECTOR + "{color:red}"

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
    """Notes cut to ``_MAX_NOTE_CHARS`` each: they quote model-written CSS into a retry prompt.

    Lone surrogates become U+FFFD first: a note reaches the retry payload and
    the refusal row, and both are serialised.
    """
    notes = [_without_surrogates(n) for n in notes]
    return tuple(n if len(n) <= _MAX_NOTE_CHARS else n[: _MAX_NOTE_CHARS - 1] + "…" for n in notes)


def _without_surrogates(text: str) -> str:
    """*text* with every lone surrogate replaced by U+FFFD, so it encodes as UTF-8."""
    return _SURROGATES.sub("�", text)


def _ends_in_bare_backslash(text: str) -> bool:
    """True when *text* ends in an odd run of ``\\``: the last one escapes what is written next."""
    return (len(text) - len(text.rstrip("\\"))) % 2 == 1


def _holds_parse_error(tokens: list) -> bool:
    """True when *tokens*, or any block or function inside them, holds a parse error."""
    return any(
        tok.type == "error"
        or (
            tok.type in ("function", "() block", "[] block", "{} block")
            and _holds_parse_error(_tokens_in(tok))
        )
        for tok in tokens
    )


def _leaves_open(css: str) -> bool:
    """True when a rule written after *css* would not parse as its own rule.

    A trailing ``/*``, an open ``{`` block, string, ``calc(`` or ``url(`` swallows
    what follows it (MF2), and every view surface writes trusted CSS after
    ``deck.css`` in the same ``<style>``.  So the probe rule, after a newline as
    the frontend writes it, must be the last top-level rule, exactly as written.

    It must also be a rule of its OWN: the probe adds exactly one top-level node.
    Otherwise a style could write the probe rule itself and then open a comment,
    which swallows the appended probe and leaves the style's copy last (R32).
    """
    alone = tinycss2.parse_stylesheet(css, skip_comments=True, skip_whitespace=True)
    nodes = tinycss2.parse_stylesheet(
        css + "\n" + _FOLLOWER_RULE, skip_comments=True, skip_whitespace=True
    )
    last = nodes[-1] if nodes else None
    if (
        len(nodes) != len(alone) + 1
        or last is None
        or last.type != "qualified-rule"
        or tinycss2.serialize(last.prelude).strip() != _FOLLOWER_SELECTOR
    ):
        return True
    items = tinycss2.parse_blocks_contents(last.content, skip_comments=True, skip_whitespace=True)
    return not (
        len(items) == 1
        and items[0].type == "declaration"
        and items[0].name == "color"
        and not items[0].important
        and tinycss2.serialize(items[0].value).strip() == "red"
    )


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
        if kind == "error" and tok.kind in _OPEN_TOKEN_ERRORS:
            return f"unparseable value: {_OPEN_TOKEN_ERRORS[tok.kind]}"
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
    # Rebuilt as "name:value;", a bare trailing "\" would escape the ";" or "}".
    if _ends_in_bare_backslash(tinycss2.serialize(decl.value).strip()):
        return "its value ends in a bare \\"
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


def _clean_rule(
    rule: Any, *, design_system_active: bool, notes: list[str]
) -> tuple[str, list[str]] | None:
    """Return a qualified rule's cleaned selector text and declarations, or ``None`` to drop it."""
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
            elif _ends_in_bare_backslash(text):
                # Rebuilt, it would escape the "," or "{" after it.
                notes.append(f"selector {_short(text)!r} dropped: it ends in a bare \\")
            elif _holds_parse_error(tokens):
                notes.append(f"selector {_short(text)!r} dropped: it holds unparseable text")
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
    return ", ".join(kept_selectors), declarations


def _clean_css(css: str, *, design_system_active: bool, notes: list[str]) -> tuple[list[str], bool]:
    """Clean ``css``; returns the rebuilt text of each kept rule, and whether anything was removed."""
    start = len(notes)
    stripped = css
    if _STYLE_OPEN.search(stripped) or _STYLE_CLOSE.search(stripped):
        stripped = _STYLE_CLOSE.sub("", _STYLE_OPEN.sub("", stripped, count=1), count=1)
        notes.append("removed the <style> wrapper")
    parsed_from = len(notes)

    # Kept rules by selector text, in source order.  ``merge_css`` keys a rule by
    # its selector and keeps only the last of a repeated one, so the post-commit
    # merge would silently lose the earlier rules' declarations: a repeated
    # selector is coalesced here instead, its declarations in source order, at
    # its LAST occurrence.  Keyed on the exact rebuilt selector text (the key
    # ``merge_css`` reads off the rebuilt CSS), so ``.dk-a, .dk-b`` and ``.dk-a``
    # stay two rules.
    kept: dict[str, list[str]] = {}
    for node in tinycss2.parse_stylesheet(stripped, skip_comments=True, skip_whitespace=True):
        if node.type == "qualified-rule":
            cleaned = _clean_rule(node, design_system_active=design_system_active, notes=notes)
            if cleaned is not None:
                selector, declarations = cleaned
                if selector in kept:
                    notes.append(
                        f"selector {_short(selector)!r} repeated: its rules were merged "
                        "into the last one"
                    )
                    declarations = kept.pop(selector) + declarations
                kept[selector] = declarations
        elif node.type == "at-rule":
            notes.append(f"@{_short(node.at_keyword)} rule dropped: at-rules are not allowed in a deck style")
        else:
            notes.append("unparseable CSS dropped")

    # "</style" in a comment is skipped by the parse without a note of its own,
    # yet it must force the rebuild that leaves the comment out.
    if _STYLE_TEXT.search(stripped) and not any("<style" in n for n in notes[parsed_from:]):
        notes.append("removed text containing <style from the CSS")
    rules = [f"{selector}{{{';'.join(declarations)}}}" for selector, declarations in kept.items()]
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


def _utf8_safe_component(component: Any) -> Any:
    """*component* with lone surrogates in its strings replaced by U+FFFD.

    The same object when it holds none.
    """
    update: dict[str, Any] = {
        field: _without_surrogates(value)
        for field, value in (
            ("name", component.name),
            ("use", component.use),
            ("example_html", component.example_html),
        )
        if _SURROGATES.search(value)
    }
    if any(_SURROGATES.search(name) for name in component.class_names):
        update["class_names"] = [_without_surrogates(name) for name in component.class_names]
    return component.model_copy(update=update) if update else component


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
    (blank or comment-only CSS), when the rebuilt CSS fails a post-condition
    (it must re-sanitise with no notes, and a rule written after it must parse
    as its own), or when the CSS is longer than ``DECK_STYLE_MAX_CHARS``.
    Components are checked against the cleaned CSS. Every string returned
    encodes as UTF-8, so the spec carrying it always serialises.
    """
    if style is None:
        return None, ()

    notes: list[str] = []
    rules, changed = _clean_css(style.css, design_system_active=design_system_active, notes=notes)
    if not rules:
        notes.append("deck style dropped: its CSS has no rules after cleaning")
        return None, _capped(notes)

    css = "\n".join(rules) if changed else style.css
    if not changed and _leaves_open(css):
        # Nothing was dropped, but the text ends inside a comment, a block, a
        # string or a function.  Its parsed rules are rebuilt closed.
        notes.append(
            "the CSS left a comment, block, string or function open at its end; "
            "it was rebuilt from its rules"
        )
        css = "\n".join(rules)
        changed = True
    if _SURROGATES.search(css):
        notes.append("lone surrogate code points in the CSS were replaced with U+FFFD")
        css = _without_surrogates(css)
        changed = True
    if changed:
        problem = _rebuild_problem(css, design_system_active=design_system_active)
        if not problem and _leaves_open(css):
            problem = "it leaves a comment, block, string or function open"
        if problem:
            notes.append(f"deck style dropped: post-condition failed on the rebuilt CSS ({problem})")
            return None, _capped(notes)
    if len(css) > DECK_STYLE_MAX_CHARS:
        notes.append(f"deck style dropped: its CSS is {len(css)} characters, over the {DECK_STYLE_MAX_CHARS} limit")
        return None, _capped(notes)

    defined = css_class_names(css)
    components = []
    for component in style.components:
        safe = _utf8_safe_component(component)
        if safe is not component:
            notes.append(
                f"component {_short(safe.name)!r}: lone surrogate code points "
                "were replaced with U+FFFD"
            )
            component = safe
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


_MAX_LOGOS = 12
_LOGO_KINDS = {"logo": 0, "lockup": 1}
# Filename markers of a reverse (dark-ground) variant. Bare "dark" is left out: it
# often names the dark-coloured mark for a light ground.
_REVERSE_MARKERS = ("reverse", "reversed", "inverse", "white", "negative", "knockout", "on-dark")


def rank_logos(rows: Any) -> list[dict]:
    """The brand marks the architect is shown: ``{handle, filename}`` rows, at most 12.

    ``rows`` are mappings with ``handle``, ``filename``, ``kind`` and optionally
    ``mime``. Only kinds ``logo`` and ``lockup`` are kept. There is no ground
    metadata, so the order is a filename heuristic: default-ground variants
    before reverse ones (a marker in :data:`_REVERSE_MARKERS`), SVG (by mime or
    extension) before raster, ``logo`` before ``lockup``, then filename. The cap
    applies after the sort.
    """

    def _key(row: Mapping) -> tuple:
        name = str(row.get("filename") or "")
        low = name.lower()
        is_svg = str(row.get("mime") or "").lower() == "image/svg+xml" or low.endswith(".svg")
        reverse = any(marker in low for marker in _REVERSE_MARKERS)
        return (reverse, not is_svg, _LOGO_KINDS[str(row.get("kind") or "").lower()], name)

    kept = [r for r in rows if str(r.get("kind") or "").lower() in _LOGO_KINDS]
    kept.sort(key=_key)
    return [{"handle": r["handle"], "filename": r["filename"]} for r in kept[:_MAX_LOGOS]]


def deck_style_context(token_css: str, style_block: str, logos: Any = ()) -> dict:
    """Design tokens and template classes the architect may reference.

    ``design_tokens`` are the ``:root`` custom properties of both inputs.
    ``template_classes`` are the sorted unique classes of ``style_block``, capped
    at 300. ``logos`` are the rows given (see :func:`rank_logos`), unchanged.
    Font data never appears.
    """
    return {
        "design_tokens": {**_root_tokens(token_css), **_root_tokens(style_block)},
        "template_classes": sorted(css_class_names(style_block))[:_MAX_TEMPLATE_CLASSES],
        "logos": list(logos),
    }

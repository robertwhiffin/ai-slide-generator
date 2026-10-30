# ruff: noqa: F811 — the conftest_graph fixtures are imported, then requested by name.
"""Addendum A, Task B2: the architect is shown the brand's logos.

``deck_style_context`` gains ``logos``: at most 12 ``{handle, filename}`` rows
from the active design system's assets of kind ``logo`` and ``lockup``, ranked
default-ground variant first and SVG before raster; ``[]`` when no design
system is active (spec Addendum A, A2 + "Logo kinds"; PLAN-CORRECTIONS-A A8,
A9, A22; Ruling RA6).

The contract these tests pin, per A8:

* ``src.domain.deck_style.rank_logos(rows)`` is the ONE pure ranking + cap
  function.  ``rows`` are mappings with ``handle``, ``filename``, ``kind`` and
  optionally ``mime``.  It keeps kinds ``logo`` and ``lockup`` only, sorts by
  ``(filename has a reverse/white/negative/inverse/on-dark/knockout marker,
  not SVG by mime or extension, logo before lockup, filename)`` and returns at
  most 12 ``{"handle", "filename"}`` dicts.  Production and
  ``evals/harness/case.py`` both use it.
* ``deck_style_context(token_css, style_block, logos=...)`` stays pure: it
  puts the rows it is given under ``logos`` unchanged, and ``[]`` by default.
* ``src.services.graph.nodes._design_system_logos(design_system_id)`` is the
  node-side read (named after its precedent ``_design_system_library``): the
  design system's ``logo`` + ``lockup`` assets, handles ``{{ds-asset:<id>}}``,
  ranked through ``rank_logos``; any read failure logs and gives ``[]``.
* ``architect_node`` calls it only when the brand is ``design_system_active``
  and the inbound contract names a design system.

Bare ``dark`` is deliberately NOT pinned as a marker: ``logo-dark.svg`` is as
often the dark-coloured mark for a light ground as the reverse one.

How this file asserts: the node tests drive ``architect_node`` over a real
SQLite database holding real ``DesignSystemAsset`` rows and read the payload
the stubbed runtime was handed; expected orders are written out by hand, never
computed with the function under test.
"""

from __future__ import annotations

import base64
import importlib
import json
import logging
from typing import Any, Dict, List

import pytest
from sqlalchemy import event, text

from src.api.services.deck_level_writer import write_deck_level_columns
from src.database.models.design_system import DesignSystem, DesignSystemAsset
from src.domain.skill_io import ArchitectOutput
from src.services.agent_model_payload import model_payload_for
from src.services.graph.nodes import architect_node
from src.utils.ds_asset_utils import DS_ASSET_PLACEHOLDER_PATTERN
from tests.unit.conftest_graph import (  # noqa: F401 — graph_env is a fixture
    architect_build,
    graph_env,
    make_spec,
)

# ---------------------------------------------------------------------------
# Lazy handles on the names under test, so each test fails on its own
# ---------------------------------------------------------------------------


def _ds():
    return importlib.import_module("src.domain.deck_style")


def _rank(rows):
    return _ds().rank_logos(rows)


def _context(token_css, style_block, **kwargs):
    return _ds().deck_style_context(token_css, style_block, **kwargs)


def _node_logos(design_system_id):
    nodes = importlib.import_module("src.services.graph.nodes")
    return nodes._design_system_logos(design_system_id)


#: Filename markers of a reverse (light-on-dark) variant, from A8 plus "reversed".
MARKERS = ("reverse", "reversed", "inverse", "white", "negative", "knockout", "on-dark")
CAP = 12

#: The pre-B2 architect payload key set (copied from test_deck_style_payloads.py,
#: itself a literal of HEAD 2ce8640b plus Task 5's ``deck_style_context``).
OLD_ARCHITECT_KEYS = frozenset(
    {
        "conversation",
        "message",
        "current_deck_spec",
        "committed_slide_count",
        "slide_numbering",
        "slide_references",
        "previous_deck_review",
        "available_design_contract",
        "template_sections",
        "resolved_style",
        "design_system_library",
        "deck_style_context",
    }
)


def _row(filename, kind="logo", *, handle=None, mime=None, **extra) -> Dict[str, Any]:
    row = {"handle": handle or "{{ds-asset:%s}}" % filename, "filename": filename, "kind": kind}
    if mime is not None:
        row["mime"] = mime
    row.update(extra)
    return row


def _names(ranked) -> List[str]:
    return [r["filename"] for r in ranked]


# ---------------------------------------------------------------------------
# rank_logos: the pure ranking and cap
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("marker", MARKERS)
def test_the_default_ground_variant_ranks_before_a_reverse_one(marker):
    # Alphabetically "meridian-logo-<marker>.svg" < "meridian-logo.svg" ('-' < '.'),
    # so a filename-only sort puts the reverse variant first.
    rows = [_row(f"meridian-logo-{marker}.svg"), _row("meridian-logo.svg")]
    assert _names(_rank(rows)) == ["meridian-logo.svg", f"meridian-logo-{marker}.svg"]


def test_the_marker_is_matched_case_insensitively():
    rows = [_row("Meridian-Logo-WHITE.svg"), _row("meridian-logo.svg")]
    assert _names(_rank(rows)) == ["meridian-logo.svg", "Meridian-Logo-WHITE.svg"]


def test_svg_ranks_before_raster_by_extension():
    rows = [
        _row("meridian-logo.png"),
        _row("meridian-logo.jpg"),
        _row("meridian-logo.svg"),
    ]
    assert _names(_rank(rows))[0] == "meridian-logo.svg"


def test_svg_extension_is_matched_case_insensitively():
    # "a-logo.png" sorts first by filename; the .SVG must still win.
    rows = [_row("a-logo.png"), _row("b-logo.SVG")]
    assert _names(_rank(rows)) == ["b-logo.SVG", "a-logo.png"]


def test_svg_ranks_before_raster_by_mime_alone():
    # No extension: only the mime says this one is SVG.
    rows = [
        _row("meridian-logo.png", mime="image/png"),
        _row("meridian-mark", mime="image/svg+xml"),
    ]
    assert _names(_rank(rows)) == ["meridian-mark", "meridian-logo.png"]


def test_the_ground_outranks_the_format():
    # A default-ground PNG beats a reverse SVG: the ground is the first key.
    rows = [_row("meridian-logo-reverse.svg"), _row("meridian-logo.png")]
    assert _names(_rank(rows)) == ["meridian-logo.png", "meridian-logo-reverse.svg"]


def test_a_logo_ranks_before_a_lockup_of_the_same_ground_and_format():
    # "meridian-lockup" < "meridian-logo" alphabetically.
    rows = [_row("meridian-lockup.svg", "lockup"), _row("meridian-logo.svg", "logo")]
    assert _names(_rank(rows)) == ["meridian-logo.svg", "meridian-lockup.svg"]


def test_the_format_outranks_the_kind():
    # A8's key: (marker, not svg, kind rank, filename).  An SVG lockup beats a PNG logo.
    rows = [_row("meridian-logo.png", "logo"), _row("meridian-lockup.svg", "lockup")]
    assert _names(_rank(rows)) == ["meridian-lockup.svg", "meridian-logo.png"]


def test_the_filename_breaks_the_remaining_ties():
    rows = [_row("c-logo.svg"), _row("a-logo.svg"), _row("b-logo.svg")]
    assert _names(_rank(rows)) == ["a-logo.svg", "b-logo.svg", "c-logo.svg"]


def test_the_full_key_orders_a_mixed_set():
    rows = [
        _row("meridian-lockup-white.png", "lockup"),
        _row("meridian-logo-on-dark.jpg", "logo"),
        _row("meridian-logo-reverse.svg", "logo"),
        _row("meridian-logo.png", "logo"),
        _row("meridian-lockup.svg", "lockup"),
        _row("meridian-logo.svg", "logo"),
    ]
    assert _names(_rank(rows)) == [
        "meridian-logo.svg",
        "meridian-lockup.svg",
        "meridian-logo.png",
        "meridian-logo-reverse.svg",
        "meridian-logo-on-dark.jpg",
        "meridian-lockup-white.png",
    ]


@pytest.mark.parametrize(
    "kind", ["icon", "illustration", "background", "font", "template_shot", "other"]
)
def test_only_logo_and_lockup_kinds_are_kept(kind):
    rows = [_row("brand-logo-mark.svg", kind), _row("meridian-logo.svg", "logo")]
    assert _names(_rank(rows)) == ["meridian-logo.svg"]


def test_the_cap_is_12_and_is_applied_after_ranking():
    # Source order is descending, so "cap then sort" would keep logo-03..logo-14.
    rows = [_row(f"logo-{i:02d}.svg") for i in range(14, -1, -1)]
    assert _names(_rank(rows)) == [f"logo-{i:02d}.svg" for i in range(CAP)]


def test_a_default_ground_logo_listed_last_survives_the_cap():
    rows = [_row(f"logo-reverse-{i:02d}.svg") for i in range(13)]
    rows.append(_row("meridian-logo.png"))
    ranked = _names(_rank(rows))
    assert len(ranked) == CAP
    assert ranked[0] == "meridian-logo.png"


def test_fewer_rows_than_the_cap_all_come_back():
    rows = [_row("a-logo.svg"), _row("b-lockup.svg", "lockup")]
    assert len(_rank(rows)) == 2


def test_rows_are_handle_and_filename_only_and_never_carry_bytes():
    secret = b"<svg>SECRET-LOGO-BYTES</svg>"
    rows = [
        _row(
            "meridian-logo.svg",
            handle="{{ds-asset:41}}",
            mime="image/svg+xml",
            data=secret,
            width=120,
            height=40,
            size_bytes=len(secret),
            id=41,
        )
    ]
    ranked = _rank(rows)
    assert ranked == [{"handle": "{{ds-asset:41}}", "filename": "meridian-logo.svg"}]
    blob = json.dumps(ranked)
    assert "SECRET-LOGO-BYTES" not in blob
    assert base64.b64encode(secret).decode() not in blob


def test_the_handle_and_filename_pass_through_unaltered():
    # The filename is data (the bundle's own text): no escaping, no trimming.
    rows = [_row("<b>logo</b> & co.svg", handle="{{ds-asset:9}}")]
    assert _rank(rows) == [{"handle": "{{ds-asset:9}}", "filename": "<b>logo</b> & co.svg"}]


def test_ranking_does_not_mutate_its_input():
    rows = [_row("meridian-logo-reverse.svg"), _row("meridian-logo.svg"), _row("x.svg", "icon")]
    before = json.loads(json.dumps(rows))
    _rank(rows)
    assert rows == before


def test_no_rows_rank_to_no_logos():
    assert _rank([]) == []


# ---------------------------------------------------------------------------
# deck_style_context: stays pure, carries the rows it is given
# ---------------------------------------------------------------------------

_TOKEN_CSS = ":root{--brand-primary:#0b2a4a}"
_STYLE_BLOCK = ".slide .title{font-size:40px}"


def test_context_carries_the_logos_exactly_as_given():
    # Deliberately NOT in rank order: the context must not re-rank, filter or rebuild.
    logos = [
        {"handle": "{{ds-asset:3}}", "filename": "meridian-logo-reverse.svg"},
        {"handle": "{{ds-asset:1}}", "filename": "meridian-logo.svg"},
        {"handle": "{{ds-asset:2}}", "filename": "meridian-lockup.svg"},
    ]
    given = json.loads(json.dumps(logos))
    ctx = _context(_TOKEN_CSS, _STYLE_BLOCK, logos=logos)
    assert ctx["logos"] == given
    assert logos == given, "deck_style_context mutated its input"
    assert set(ctx) == {"design_tokens", "template_classes", "logos"}
    # The other two keys are what they always were.
    assert ctx["design_tokens"] == {"--brand-primary": "#0b2a4a"}
    assert ctx["template_classes"] == ["slide", "title"]
    json.dumps(ctx)


def test_context_without_logos_has_an_empty_list():
    ctx = _context(_TOKEN_CSS, _STYLE_BLOCK)
    assert ctx["logos"] == []
    assert _context("", "") == {"design_tokens": {}, "template_classes": [], "logos": []}


def test_deck_style_module_stays_free_of_db_and_service_imports():
    """A8: the ranking lives in the pure module; it must not pull the DB in to do it."""
    import ast
    import pathlib

    source = pathlib.Path(_ds().__file__).read_text()
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    forbidden = sorted(
        name
        for name in imported
        if name.split(".")[0] == "sqlalchemy"
        or name.startswith(("src.services", "src.database", "src.api", "src.core"))
    )
    assert forbidden == []


# ---------------------------------------------------------------------------
# The node: a real database of design-system assets
# ---------------------------------------------------------------------------

DS_ID = 7
OTHER_DS_ID = 8
TEMPLATE_ID = 3
SECRET = b"<svg xmlns='http://www.w3.org/2000/svg'>MERIDIAN-SECRET-BYTES</svg>"

#: (id, design_system_id, kind, filename, mime)
ASSETS = [
    (101, DS_ID, "logo", "meridian-logo-reverse.svg", "image/svg+xml"),
    (102, DS_ID, "logo", "meridian-logo.png", "image/png"),
    (103, DS_ID, "logo", "meridian-logo.svg", "image/svg+xml"),
    (104, DS_ID, "lockup", "meridian-lockup.svg", "image/svg+xml"),
    (105, DS_ID, "lockup", "meridian-lockup-white.png", "image/png"),
    (106, DS_ID, "icon", "icon-chart.svg", "image/svg+xml"),
    (107, DS_ID, "illustration", "hero.png", "image/png"),
    (108, DS_ID, "font", "MeridianSans.woff2", "font/woff2"),
    (109, DS_ID, "template_shot", "preview.png", "image/png"),
    (110, DS_ID, "icon", "icon-logo-mark.svg", "image/svg+xml"),
    (111, DS_ID, "logo", "meridian-logo-on-dark.jpg", "image/jpeg"),
    (201, OTHER_DS_ID, "logo", "other-brand-logo.svg", "image/svg+xml"),
    (202, OTHER_DS_ID, "lockup", "other-brand-lockup.svg", "image/svg+xml"),
]

#: Hand-ranked: default ground (svg: logo, lockup; raster: logo), then reverse
#: (svg: logo; raster: logo, lockup).  Icons, other kinds and DS 8 are absent.
EXPECTED_LOGOS = [
    {"handle": "{{ds-asset:103}}", "filename": "meridian-logo.svg"},
    {"handle": "{{ds-asset:104}}", "filename": "meridian-lockup.svg"},
    {"handle": "{{ds-asset:102}}", "filename": "meridian-logo.png"},
    {"handle": "{{ds-asset:101}}", "filename": "meridian-logo-reverse.svg"},
    {"handle": "{{ds-asset:111}}", "filename": "meridian-logo-on-dark.jpg"},
    {"handle": "{{ds-asset:105}}", "filename": "meridian-lockup-white.png"},
]

#: The brand bytes the template stub resolves, with literal expectations.
TOKEN_CSS = ":root{--brand-primary:#0b2a4a}"
STYLE_BLOCK = ".slide{color:var(--brand-primary)}\n.slide .title{font-size:44px}"
EXPECTED_TOKENS = {"--brand-primary": "#0b2a4a"}
EXPECTED_CLASSES = ["slide", "title"]


@pytest.fixture
def env(graph_env, monkeypatch):
    """``graph_env`` with both design systems present and the DB reachable at its source.

    ``src.core.database.get_db_session`` is patched too, so a lazily imported
    session (as ``ds_asset_tool`` does) reads this database as well.
    """
    from tests.unit.conftest_graph import _fake_db

    monkeypatch.setattr("src.core.database.get_db_session", _fake_db(graph_env.factory))
    db = graph_env.factory()
    try:
        db.add(DesignSystem(id=DS_ID, name="Meridian", is_active=True))
        db.add(DesignSystem(id=OTHER_DS_ID, name="Other Brand", is_active=True))
        db.commit()
    finally:
        db.close()
    graph_env.template.token_css = TOKEN_CSS
    graph_env.template.style_block = STYLE_BLOCK
    return graph_env


def _add_assets(env, assets=ASSETS) -> None:
    db = env.factory()
    try:
        for asset_id, ds_id, kind, filename, mime in assets:
            db.add(
                DesignSystemAsset(
                    id=asset_id,
                    design_system_id=ds_id,
                    kind=kind,
                    filename=filename,
                    mime=mime,
                    data=SECRET,
                    size_bytes=len(SECRET),
                )
            )
        db.commit()
    finally:
        db.close()


def _pin(env, *, active=True) -> None:
    """Pin ds 7 / template 3 on the persisted spec, as the existing pinned test does."""
    env.style.design_system_active = active
    prior = make_spec((0,), design_system_id=DS_ID, template_id=TEMPLATE_ID)
    write_deck_level_columns(env.session_id, deck_spec=prior.to_json())


def _architect_payload(env, answer=None) -> Dict[str, Any]:
    env.skills.calls.clear()
    if answer is None:
        answer = make_spec((0,), design_system_id=DS_ID, template_id=TEMPLATE_ID)
        answer = architect_build(answer)
    env.skills.set("architect", answer)
    architect_node(env.state())
    calls = env.skills.calls_for("architect")
    assert calls, "the architect was never called"
    return calls[0]["payload"]


# --- the payload carries the ranked logos ------------------------------------


def test_architect_payload_carries_the_design_systems_ranked_logos(env):
    _add_assets(env)
    _pin(env)

    payload = _architect_payload(env)

    assert env.template.calls[:1] == [(DS_ID, TEMPLATE_ID)], "the inbound brand was not pinned"
    ctx = payload["deck_style_context"]
    assert "logos" in ctx, "the architect was not shown the logos"
    assert ctx["logos"] == EXPECTED_LOGOS
    for row in ctx["logos"]:
        assert set(row) == {"handle", "filename"}
        assert DS_ASSET_PLACEHOLDER_PATTERN.fullmatch(row["handle"]), row
    # The context is the pure function of the brand and those rows.
    assert ctx == _context(TOKEN_CSS, STYLE_BLOCK, logos=EXPECTED_LOGOS)


def test_architect_logos_are_capped_at_12(env):
    many = [
        (300 + i, DS_ID, "logo", f"logo-{i:02d}.svg", "image/svg+xml") for i in range(14, -1, -1)
    ]
    _add_assets(env, many)
    _pin(env)

    logos = _architect_payload(env)["deck_style_context"]["logos"]

    assert [r["filename"] for r in logos] == [f"logo-{i:02d}.svg" for i in range(CAP)]
    assert [r["handle"] for r in logos] == ["{{ds-asset:%d}}" % (300 + i) for i in range(CAP)]


def test_architect_logos_never_carry_asset_bytes(env):
    _add_assets(env)
    _pin(env)

    payload = _architect_payload(env)

    rendered = json.dumps(payload)
    logos_blob = json.dumps(payload["deck_style_context"]["logos"])
    assert payload["deck_style_context"]["logos"], "vacuous: no logos were read"
    assert "MERIDIAN-SECRET-BYTES" not in rendered
    assert base64.b64encode(SECRET).decode() not in rendered
    for needle in ("base64", "data:", "<svg"):
        assert needle not in logos_blob, needle


def test_the_logo_read_never_selects_the_bytes_column(env):
    """``search_assets`` defers ``data``; the architect's read must not load it either."""
    _add_assets(env)
    _pin(env)
    statements: List[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(env.engine, "before_cursor_execute", _record)
    try:
        _architect_payload(env)
    finally:
        event.remove(env.engine, "before_cursor_execute", _record)

    asset_reads = [
        s for s in statements if s.lstrip().upper().startswith("SELECT") and "design_system_asset" in s
    ]
    assert asset_reads, "the architect never read the design system's assets"
    loading_bytes = [s for s in asset_reads if "design_system_asset.bytes" in s]
    assert loading_bytes == [], loading_bytes


# --- no active design system: no logos ----------------------------------------


def test_an_unpinned_deck_gets_no_logos(env):
    _add_assets(env)
    # Even with the style resolver reporting a design system, no id is pinned.
    env.style.design_system_active = True

    payload = _architect_payload(env, architect_build(make_spec((0,))))

    assert payload["deck_style_context"]["logos"] == []
    assert payload["deck_style_context"] == {
        "design_tokens": {},
        "template_classes": [],
        "logos": [],
    }


def test_a_pinned_but_inactive_design_system_gets_no_logos(env):
    _add_assets(env)
    _pin(env, active=False)

    payload = _architect_payload(env)

    assert payload["deck_style_context"]["logos"] == []


def test_a_design_system_with_no_logo_assets_gets_no_logos(env):
    _add_assets(env, [a for a in ASSETS if a[2] not in ("logo", "lockup") or a[1] != DS_ID])
    _pin(env)

    payload = _architect_payload(env)

    assert payload["deck_style_context"]["logos"] == []


def test_a_failed_logo_read_gives_no_logos_and_the_turn_goes_on(env, caplog):
    _add_assets(env)
    _pin(env)
    with env.engine.begin() as conn:
        conn.execute(text("DROP TABLE design_system_asset"))

    with caplog.at_level(logging.WARNING, logger="src.services.graph.nodes"):
        payload = _architect_payload(env)

    assert payload["deck_style_context"]["logos"] == []
    assert any(
        r.levelno >= logging.WARNING and r.name == "src.services.graph.nodes"
        for r in caplog.records
    ), "the failed logo read was not logged"


# --- the node-side helper -----------------------------------------------------


def test_node_logo_helper_reads_this_design_systems_logos_only(env):
    _add_assets(env)
    assert _node_logos(DS_ID) == EXPECTED_LOGOS
    assert _node_logos(OTHER_DS_ID) == [
        {"handle": "{{ds-asset:201}}", "filename": "other-brand-logo.svg"},
        {"handle": "{{ds-asset:202}}", "filename": "other-brand-lockup.svg"},
    ]
    assert _node_logos(999) == []


def test_node_logo_helper_gives_no_logos_when_the_read_fails(env):
    with env.engine.begin() as conn:
        conn.execute(text("DROP TABLE design_system_asset"))
    assert _node_logos(DS_ID) == []


# --- A22: the payload changes only by deck_style_context.logos ----------------


def _without_logos(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = json.loads(json.dumps(payload))
    out["deck_style_context"].pop("logos", None)
    return out


def test_the_payload_changes_only_by_the_nested_logos_key(env):
    """A22: top-level keys unchanged; inside the context only ``logos`` is new.

    The same discussion turn is asked twice on one deck: before the design system
    has any logo assets, and after.  The two payloads may differ only at
    ``deck_style_context.logos``.
    """
    _pin(env)
    discuss = ArchitectOutput(intent="discuss", message="Happy to talk it through.")

    before = _architect_payload(env, discuss)
    # The discussion reply is the turn's only write (it would reach the second
    # payload's ``conversation``); remove it so the deck is as it was.
    with env.engine.begin() as conn:
        conn.execute(text("DELETE FROM session_messages"))
    _add_assets(env)
    after = _architect_payload(env, discuss)

    assert set(after) == OLD_ARCHITECT_KEYS, "a top-level architect payload key changed"
    assert set(after["deck_style_context"]) == {"design_tokens", "template_classes", "logos"}
    assert after["deck_style_context"]["design_tokens"] == EXPECTED_TOKENS
    assert after["deck_style_context"]["template_classes"] == EXPECTED_CLASSES
    assert after["deck_style_context"]["logos"] == EXPECTED_LOGOS
    assert before["deck_style_context"]["logos"] == []
    assert _without_logos(after) == _without_logos(before)


def test_the_projection_keeps_the_nested_logos():
    """A22: ``model_payload_for`` passes ``deck_style_context.logos`` through untouched."""
    payload = {key: f"value of {key}" for key in sorted(OLD_ARCHITECT_KEYS)}
    payload["previous_deck_review"] = None
    payload["deck_style_context"] = {
        "design_tokens": EXPECTED_TOKENS,
        "template_classes": EXPECTED_CLASSES,
        "logos": EXPECTED_LOGOS,
    }
    assert model_payload_for("architect", payload) == payload


# ---------------------------------------------------------------------------
# The Meridian fake asset index (RA6) and the eval derivation (A9)
# ---------------------------------------------------------------------------


def _meridian_assets() -> List[Dict[str, Any]]:
    from evals.harness import case

    path = case.MERIDIAN_DIR / "assets.json"
    assert path.is_file(), f"{path} is missing"
    rows = json.loads(path.read_text())
    assert isinstance(rows, list), "assets.json is a JSON list of asset rows"
    return rows


def _has_marker(filename: str) -> bool:
    low = filename.lower()
    return any(marker in low for marker in MARKERS)


def test_meridian_asset_index_has_logos_a_lockup_and_product_icons():
    from src.services.design_system_service import _infer_asset_kind

    rows = _meridian_assets()
    for row in rows:
        assert {"handle", "filename", "kind"} <= set(row), row
        assert DS_ASSET_PLACEHOLDER_PATTERN.fullmatch(row["handle"]), row
        # The filename classifies to its kind as a bundle import would classify it.
        assert _infer_asset_kind(row["filename"]) == row["kind"], row
    handles = [row["handle"] for row in rows]
    assert len(handles) == len(set(handles)), "asset handles are not unique"

    logos = [row for row in rows if row["kind"] == "logo"]
    lockups = [row for row in rows if row["kind"] == "lockup"]
    icons = [row for row in rows if row["kind"] == "icon"]
    assert len(logos) >= 2, logos
    assert any(not _has_marker(r["filename"]) for r in logos), "no default-ground logo"
    assert any(_has_marker(r["filename"]) for r in logos), "no reverse / dark-ground logo"
    assert len(lockups) >= 1, "no lockup"
    assert len(icons) >= 4, icons


def test_meridian_context_logos_are_the_ranked_index_logos():
    from evals.harness import case

    rows = _meridian_assets()
    ctx = case.meridian_deck_style_context()

    assert set(ctx) == {"design_tokens", "template_classes", "logos"}
    logos = ctx["logos"]
    # The shared ranking function, over the same rows the fake search index serves.
    assert logos == _rank(rows)
    brand_marks = {(r["handle"], r["filename"]) for r in rows if r["kind"] in ("logo", "lockup")}
    assert {(r["handle"], r["filename"]) for r in logos} == brand_marks
    icon_handles = {r["handle"] for r in rows if r["kind"] == "icon"}
    assert not icon_handles & {r["handle"] for r in logos}, "an icon reached logos"
    by_handle = {r["handle"]: r for r in rows}
    first = by_handle[logos[0]["handle"]]
    assert first["kind"] == "logo" and not _has_marker(first["filename"]), first
    assert any(_has_marker(r["filename"]) for r in logos), "the reverse logo is not offered"
    # The tokens and classes are untouched by the logos.
    assert ctx["design_tokens"].get("--brand-core-primary") == "#0F766E"
    assert {"slide", "stat-value"} <= set(ctx["template_classes"])

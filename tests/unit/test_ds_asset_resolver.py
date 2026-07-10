"""Unit tests for the {{ds-asset:ID}} placeholder resolver (Phase 3).

The resolver is a sibling of ``image_utils.substitute_image_placeholders`` but a
DISTINCT namespace: ``design_system_asset`` ids and ``image_assets`` ids are
independent sequences, so the two must never touch each other's placeholders.

All fixtures are SYNTHETIC — no real brand content.
"""
import base64

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import src.database.models  # noqa: F401 - register models with Base.metadata
from src.core.database import Base


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    with Session(engine) as s:
        yield s
    engine.dispose()


def _make_asset(session, *, data=b"<svg/>", mime="image/svg+xml", kind="logo", name="Acme DS"):
    from src.database.models.design_system import DesignSystem, DesignSystemAsset

    ds = DesignSystem(name=name)  # name is UNIQUE — vary it when a test makes >1
    ds.assets.append(
        DesignSystemAsset(
            kind=kind, filename="logo.svg", mime=mime, data=data, size_bytes=len(data)
        )
    )
    session.add(ds)
    session.commit()
    session.refresh(ds)
    return ds.assets[0]


def _make_ds_with_assets(session, specs, *, name="Acme DS"):
    """Create ONE design system holding several assets; return (ds_id, [assets]).

    Resolution is scoped to a single design system, so any test that resolves
    multiple assets in one deck must put them all in the SAME system.
    ``specs`` is a list of ``dict(data=, mime=, kind=)``.
    """
    from src.database.models.design_system import DesignSystem, DesignSystemAsset

    ds = DesignSystem(name=name)
    for spec in specs:
        ds.assets.append(
            DesignSystemAsset(
                kind=spec.get("kind", "logo"),
                filename=spec.get("filename", "asset.bin"),
                mime=spec["mime"],
                data=spec["data"],
                size_bytes=len(spec["data"]),
            )
        )
    session.add(ds)
    session.commit()
    session.refresh(ds)
    return ds.id, list(ds.assets)


class TestSubstituteDsAssetPlaceholders:
    def test_replaces_placeholder_with_data_uri(self, session):
        from src.utils.ds_asset_utils import substitute_ds_asset_placeholders

        asset = _make_asset(session, data=b"<svg>logo</svg>", mime="image/svg+xml")
        html = f'<img src="{{{{ds-asset:{asset.id}}}}}" alt="logo" />'
        out = substitute_ds_asset_placeholders(
            html, session, design_system_id=asset.design_system_id
        )

        expected_b64 = base64.b64encode(b"<svg>logo</svg>").decode()
        assert f"data:image/svg+xml;base64,{expected_b64}" in out
        assert "{{ds-asset:" not in out

    def test_does_not_touch_image_placeholder(self, session):
        """The ds-asset resolver must leave {{image:ID}} untouched (orthogonal)."""
        from src.utils.ds_asset_utils import substitute_ds_asset_placeholders

        asset = _make_asset(session)
        html = f'<img src="{{{{ds-asset:{asset.id}}}}}"><img src="{{{{image:1}}}}">'
        out = substitute_ds_asset_placeholders(
            html, session, design_system_id=asset.design_system_id
        )

        assert "{{ds-asset:" not in out
        assert "{{image:1}}" in out  # untouched

    def test_foreign_design_system_asset_id_left_in_place(self, session):
        """Confused-deputy guard at the resolver: an id that belongs to a
        DIFFERENT design system than the one in scope must NOT resolve to that
        system's bytes — it is left in place exactly like an unknown id."""
        from src.utils.ds_asset_utils import substitute_ds_asset_placeholders

        victim = _make_asset(
            session, data=b"<svg>victim-secret</svg>", name="Victim DS"
        )
        attacker_id, _ = _make_ds_with_assets(
            session, [{"data": b"<svg>attacker</svg>", "mime": "image/svg+xml"}],
            name="Attacker DS",
        )
        html = f'<img src="{{{{ds-asset:{victim.id}}}}}">'
        out = substitute_ds_asset_placeholders(
            html, session, design_system_id=attacker_id
        )

        victim_b64 = base64.b64encode(b"<svg>victim-secret</svg>").decode()
        assert victim_b64 not in out  # foreign bytes never served
        assert out == html  # handle left in place, not resolved

    def test_unknown_asset_id_left_in_place(self, session):
        from src.utils.ds_asset_utils import substitute_ds_asset_placeholders

        html = "background: url('{{ds-asset:987654}}')"
        out = substitute_ds_asset_placeholders(html, session, design_system_id=1)
        assert out == html  # unresolved placeholder preserved, not crashed

    def test_none_scope_resolves_nothing(self, session):
        """Fail-closed: with no active design system in scope, no handle resolves
        (a deck with no design system must not embed any brand asset by bare id)."""
        from src.utils.ds_asset_utils import substitute_ds_asset_placeholders

        asset = _make_asset(session, data=b"<svg>logo</svg>", mime="image/svg+xml")
        html = f'<img src="{{{{ds-asset:{asset.id}}}}}">'
        out = substitute_ds_asset_placeholders(html, session, design_system_id=None)
        assert out == html  # left in place; nothing embedded

    def test_unknown_asset_id_is_logged_not_silent(self, session, caplog):
        """Phase-2 reset (section D): with brand images now fetched via the
        search_brand_assets tool, a model COULD still fabricate an id. Verify the
        resolver does NOT fail silently — it logs a warning naming the id and
        leaves the placeholder in place (never raises). The resolver itself is
        UNCHANGED (section F); this locks in that "at least log it" behavior."""
        import logging

        from src.utils.ds_asset_utils import substitute_ds_asset_placeholders

        html = '<img src="{{ds-asset:987654}}">'
        with caplog.at_level(logging.WARNING, logger="src.utils.ds_asset_utils"):
            out = substitute_ds_asset_placeholders(html, session, design_system_id=1)

        assert out == html  # left in place, never raises
        warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert any("987654" in m for m in warnings), "fabricated id must be logged, not silent"

    def test_noop_when_no_placeholder(self, session):
        from src.utils.ds_asset_utils import substitute_ds_asset_placeholders

        html = "<div>no placeholders here</div>"
        assert substitute_ds_asset_placeholders(html, session, design_system_id=1) is html


class TestSubstituteDeckDictDsAssets:
    def test_substitutes_across_slides_and_html_content(self, session):
        from src.utils.ds_asset_utils import substitute_deck_dict_ds_assets

        asset = _make_asset(session, data=b"BYTES", mime="image/png")
        deck = {
            "slides": [
                {"html": f'<img src="{{{{ds-asset:{asset.id}}}}}">'},
                {"html": "<p>no placeholder</p>"},
            ],
            "html_content": f'<div style="background:url({{{{ds-asset:{asset.id}}}}})"></div>',
        }
        out = substitute_deck_dict_ds_assets(
            deck, session, design_system_id=asset.design_system_id
        )

        b64 = base64.b64encode(b"BYTES").decode()
        assert f"data:image/png;base64,{b64}" in out["slides"][0]["html"]
        assert "{{ds-asset:" not in out["slides"][0]["html"]
        assert "{{ds-asset:" not in out["html_content"]
        assert out["slides"][1]["html"] == "<p>no placeholder</p>"

    def test_substitutes_deck_top_level_css_font_and_background(self, session):
        """Deck top-level ``css`` resolves {{ds-asset:ID}} in @font-face src
        url() (fonts) and background-image url() (backgrounds).

        Regression: slide ``html`` and ``html_content`` were substituted but the
        deck-level stylesheet was not, so brand fonts/backgrounds referenced via
        ``@font-face { src: url('{{ds-asset:ID}}') }`` and
        ``background-image: url('{{ds-asset:ID}}')`` leaked as unresolved
        placeholders.
        """
        from src.utils.ds_asset_utils import substitute_deck_dict_ds_assets

        # Font and background must live in the SAME design system (resolution is
        # scoped to one system), mirroring a real bundle's assets.
        ds_id, (font, bg) = _make_ds_with_assets(
            session,
            [
                {"data": b"synthetic-font-bytes", "mime": "font/woff2", "kind": "font"},
                {"data": b"synthetic-bg-bytes", "mime": "image/png", "kind": "background"},
            ],
            name="Acme DS Fonts+Backgrounds",
        )
        # Build placeholders via the compiler's own convention to avoid f-string
        # brace collisions with the surrounding CSS braces.
        font_ph = "{{ds-asset:%d}}" % font.id
        bg_ph = "{{ds-asset:%d}}" % bg.id
        deck = {
            "slides": [{"html": "<p>no placeholder</p>"}],
            "css": (
                "@font-face { font-family: 'Brand'; "
                "src: url('" + font_ph + "') format('woff2'); }\n"
                ".hero { background-image: url('" + bg_ph + "'); }"
            ),
        }
        out = substitute_deck_dict_ds_assets(deck, session, design_system_id=ds_id)

        font_b64 = base64.b64encode(b"synthetic-font-bytes").decode()
        bg_b64 = base64.b64encode(b"synthetic-bg-bytes").decode()
        assert f"data:font/woff2;base64,{font_b64}" in out["css"]
        assert f"data:image/png;base64,{bg_b64}" in out["css"]
        assert "{{ds-asset:" not in out["css"]
        # Slides without placeholders are untouched.
        assert out["slides"][0]["html"] == "<p>no placeholder</p>"

    def test_empty_deck_is_noop(self, session):
        from src.utils.ds_asset_utils import substitute_deck_dict_ds_assets

        assert substitute_deck_dict_ds_assets({}, session, design_system_id=None) == {}
        assert substitute_deck_dict_ds_assets(
            {"slides": []}, session, design_system_id=None
        ) == {"slides": []}


class TestChatServiceCallerGate:
    """Caller-level gate: ``ChatService._substitute_images_for_response`` must
    invoke the ds-asset resolver when the ONLY ``{{ds-asset:ID}}`` reference is
    in the deck's top-level ``css``.

    Regression for the caller-gate gap: the utility resolves ``css``, but the
    caller previously gated the resolver on slide ``html`` / ``html_content``
    only. A deck whose brand font/background placeholder lived solely in the
    deck stylesheet therefore skipped substitution and returned
    ``{{ds-asset:ID}}`` unresolved to the client (all response paths route
    through this one method).
    """

    def test_resolves_ds_asset_when_only_in_deck_css(self, session):
        from contextlib import contextmanager
        from unittest.mock import patch

        from src.api.services.chat_service import ChatService

        asset = _make_asset(
            session, data=b"synthetic-bg-bytes", mime="image/png", kind="background"
        )
        placeholder = "{{ds-asset:%d}}" % asset.id
        deck = {
            "slides": [{"html": "<p>x</p>"}],  # no placeholder in slide html
            "css": ".hero{background:url('" + placeholder + "')}",
        }

        @contextmanager
        def _fake_db():
            yield session

        service = ChatService()
        # The method does ``from src.core.database import get_db_session`` at call
        # time, so patch it at its source module. Scope resolution is stubbed to
        # the asset's own design system (the session's active system).
        with patch("src.core.database.get_db_session", _fake_db), patch(
            "src.api.services.chat_service.resolve_active_design_system_id",
            return_value=asset.design_system_id,
        ):
            out_deck, _ = service._substitute_images_for_response(
                deck, session_id="sess-1"
            )

        bg_b64 = base64.b64encode(b"synthetic-bg-bytes").decode()
        assert f"data:image/png;base64,{bg_b64}" in out_deck["css"]
        assert "{{ds-asset:" not in out_deck["css"]

"""Unit tests for ``design_system_service.search_assets`` (Phase 2 reset).

The read helper backing the ``search_brand_assets`` tool: it returns a design
system's brand IMAGE assets (logo/lockup/icon/illustration/background), filtered
by kind and/or a case-insensitive filename substring, RANKED by brand importance.
Fonts (wired inline via @font-face) and template_shot (reference-only) are never
surfaced. All fixtures are SYNTHETIC — no real brand content.
"""
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


def _make_ds(session, *, name, assets):
    from src.database.models.design_system import DesignSystem, DesignSystemAsset

    ds = DesignSystem(name=name)
    for a in assets:
        ds.assets.append(DesignSystemAsset(**a))
    session.add(ds)
    session.commit()
    session.refresh(ds)
    return ds


def _asset(kind, filename):
    return {
        "kind": kind,
        "filename": filename,
        "mime": "image/svg+xml" if filename.endswith(".svg") else "image/png",
        "data": b"<svg/>",
        "size_bytes": 6,
    }


# Deliberately UNSORTED, mixed-kind (+ font + template_shot to exclude).
_ASSETS = [
    _asset("icon", "icon-b.svg"),
    _asset("logo", "logo-b.svg"),
    _asset("icon", "icon-a.svg"),
    _asset("logo", "acme-logo-a.svg"),
    _asset("illustration", "art.png"),
    _asset("background", "hero-bg.png"),
    _asset("lockup", "lockup.svg"),
    {"kind": "font", "filename": "acme.woff2", "mime": "font/woff2",
     "data": b"font", "size_bytes": 4},
    {"kind": "template_shot", "filename": "shot.png", "mime": "image/png",
     "data": b"png", "size_bytes": 3},
]


class TestSearchAssets:
    def test_returns_only_image_assets_by_default(self, session):
        from src.services.design_system_service import search_assets

        ds = _make_ds(session, name="Acme", assets=_ASSETS)
        rows = search_assets(session, ds.id)
        names = {a.filename for a in rows}
        # image kinds present
        assert "logo-b.svg" in names
        assert "icon-a.svg" in names
        assert "art.png" in names
        assert "hero-bg.png" in names
        assert "lockup.svg" in names
        # font + template_shot excluded
        assert "acme.woff2" not in names
        assert "shot.png" not in names

    def test_no_query_fallback_ranked_by_importance(self, session):
        """Neither query nor kind → a RANKED default set: logo > lockup > icon >
        illustration > background (so a loose call yields useful assets)."""
        from src.services.design_system_service import search_assets

        ds = _make_ds(session, name="Acme", assets=_ASSETS)
        kinds = [a.kind for a in search_assets(session, ds.id)]
        # first appearance of each kind follows importance order
        importance = ("logo", "lockup", "icon", "illustration", "background")
        first = {k: kinds.index(k) for k in importance}
        assert (
            first["logo"] < first["lockup"] < first["icon"]
            < first["illustration"] < first["background"]
        )

    def test_ranked_ties_sorted_by_filename(self, session):
        from src.services.design_system_service import search_assets

        ds = _make_ds(session, name="Acme", assets=_ASSETS)
        logos = [a.filename for a in search_assets(session, ds.id) if a.kind == "logo"]
        assert logos == ["acme-logo-a.svg", "logo-b.svg"]  # sorted within kind

    def test_filter_by_kind(self, session):
        from src.services.design_system_service import search_assets

        ds = _make_ds(session, name="Acme", assets=_ASSETS)
        rows = search_assets(session, ds.id, kind="icon")
        assert {a.filename for a in rows} == {"icon-a.svg", "icon-b.svg"}

    def test_filter_by_kind_case_insensitive(self, session):
        from src.services.design_system_service import search_assets

        ds = _make_ds(session, name="Acme", assets=_ASSETS)
        rows = search_assets(session, ds.id, kind="ICON")
        assert {a.filename for a in rows} == {"icon-a.svg", "icon-b.svg"}

    def test_filter_by_query_filename_substring_case_insensitive(self, session):
        from src.services.design_system_service import search_assets

        ds = _make_ds(session, name="Acme", assets=_ASSETS)
        rows = search_assets(session, ds.id, query="LOGO")
        assert {a.filename for a in rows} == {"logo-b.svg", "acme-logo-a.svg"}

    def test_filter_by_kind_and_query_combined(self, session):
        from src.services.design_system_service import search_assets

        ds = _make_ds(session, name="Acme", assets=_ASSETS)
        rows = search_assets(session, ds.id, kind="logo", query="acme")
        assert {a.filename for a in rows} == {"acme-logo-a.svg"}

    def test_query_never_returns_excluded_font_even_if_matched(self, session):
        """The font is excluded even when the query would match its filename."""
        from src.services.design_system_service import search_assets

        ds = _make_ds(session, name="Acme", assets=_ASSETS)
        rows = search_assets(session, ds.id, query="acme")
        assert "acme.woff2" not in {a.filename for a in rows}

    def test_kind_font_returns_nothing(self, session):
        """Fonts are never tool-surfaced (delivered via @font-face)."""
        from src.services.design_system_service import search_assets

        ds = _make_ds(session, name="Acme", assets=_ASSETS)
        assert search_assets(session, ds.id, kind="font") == []

    def test_scoped_to_design_system(self, session):
        from src.services.design_system_service import search_assets

        ds1 = _make_ds(session, name="Acme", assets=[_asset("logo", "acme.svg")])
        ds2 = _make_ds(session, name="Other", assets=[_asset("logo", "other.svg")])
        assert {a.filename for a in search_assets(session, ds1.id)} == {"acme.svg"}
        assert {a.filename for a in search_assets(session, ds2.id)} == {"other.svg"}

    def test_empty_design_system_returns_empty(self, session):
        from src.services.design_system_service import search_assets

        ds = _make_ds(session, name="Empty", assets=[])
        assert search_assets(session, ds.id) == []

    def test_unknown_kind_returns_empty(self, session):
        from src.services.design_system_service import search_assets

        ds = _make_ds(session, name="Acme", assets=_ASSETS)
        assert search_assets(session, ds.id, kind="does-not-exist") == []

    def test_deterministic_regardless_of_insertion_order(self, session):
        from src.services.design_system_service import search_assets

        ds1 = _make_ds(session, name="A", assets=_ASSETS)
        ds2 = _make_ds(session, name="B", assets=list(reversed(_ASSETS)))
        names1 = [a.filename for a in search_assets(session, ds1.id)]
        names2 = [a.filename for a in search_assets(session, ds2.id)]
        assert names1 == names2

    def test_unknown_image_kind_still_surfaced_last(self, session):
        """A brand image of an unknown kind is still returned (denylist, not
        allowlist), ranked after the known importance kinds."""
        from src.services.design_system_service import search_assets

        ds = _make_ds(session, name="Acme", assets=[
            _asset("logo", "logo.svg"),
            _asset("photo", "product.png"),  # unknown-but-image kind
        ])
        rows = [a.filename for a in search_assets(session, ds.id)]
        assert rows == ["logo.svg", "product.png"]  # logo ranked first, unknown last

"""API tests for the design-system source-file browser endpoints (v1 Phase 6).

Two endpoints on the Design System settings router:

- ``GET /{ds_id}/files``           — the file tree as METADATA ONLY (path, kind,
                                     mime, size_bytes), combining source rows and
                                     asset/font reference rows; bytes never leave
                                     the serve endpoint.
- ``GET /{ds_id}/files/{path}``    — serve ONE stored file's content SECURELY:
                                     text sources (md/css/html/js/json/svg) are
                                     forced to ``text/plain`` so user-uploaded
                                     markup can never execute in the app origin;
                                     everything ships with ``Content-Disposition:
                                     attachment`` + ``X-Content-Type-Options:
                                     nosniff``. Path traversal is rejected and
                                     lookups are ownership-scoped (404 otherwise).

Uses a real in-memory SQLite DB via a get_db dependency override, mirroring
``test_design_systems_routes.py``. All fixtures are SYNTHETIC (fake "Acme"
brand) per public-repo hygiene.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.main import app
from src.core.database import Base, get_db
from tests.unit.conftest_design_system import (
    COLORS_AND_TYPE_CSS,
    SVG_LOGO,
    SYNTHETIC_README,
    SYNTHETIC_TEMPLATE_HTML,
    make_bundle_zip,
    png_bytes,
    templated_bundle_files,
    templated_manifest,
)


@pytest.fixture(scope="function")
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture(scope="function")
def db_session(db_engine):
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
    session = session_local()
    yield session
    session.close()


@pytest.fixture(scope="function")
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


BASE = "/api/settings/design-systems"

# Content types that would let user-uploaded markup render or execute if a
# response were opened same-origin — the serve endpoint must NEVER emit these.
EXECUTABLE_CONTENT_TYPES = {
    "text/html",
    "application/xhtml+xml",
    "image/svg+xml",
    "text/javascript",
    "application/javascript",
    "application/ecmascript",
}

# The default synthetic bundle's retained file tree (see make_bundle_zip):
# source rows (readme/skill/css/template) + asset/font reference rows. The
# skipped entries (ds-base.js, title-shot.png, assets/preview.png) never land.
DEFAULT_TREE = {
    "README.md": "readme",
    "SKILL.md": "skill",
    "assets/backgrounds/hero-bg.png": "asset",
    "assets/logo.svg": "asset",
    "colors_and_type.css": "css",
    "fonts/acme-sans.woff2": "font",
    "templates/corporate/index.html": "template",
}


def _import(client, name=None, **bundle_kwargs):
    zip_bytes = make_bundle_zip(**bundle_kwargs)
    resp = client.post(
        f"{BASE}/import",
        files={"file": ("acme.zip", zip_bytes, "application/zip")},
        data={"name": name} if name else None,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# ---------------------------------------------------------------------------
# File tree listing
# ---------------------------------------------------------------------------


class TestListFiles:
    def test_list_returns_metadata_only_tree_sorted_by_path(self, client):
        ds_id = _import(client)
        resp = client.get(f"{BASE}/{ds_id}/files")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] == len(DEFAULT_TREE)
        paths = [f["path"] for f in body["files"]]
        assert paths == sorted(DEFAULT_TREE)
        for entry in body["files"]:
            # Metadata only — bytes never appear in a listing.
            assert set(entry) == {"path", "kind", "mime", "size_bytes"}
            assert entry["size_bytes"] > 0
            assert entry["mime"]

    def test_list_maps_stored_kinds(self, client):
        ds_id = _import(client)
        body = client.get(f"{BASE}/{ds_id}/files").json()
        assert {f["path"]: f["kind"] for f in body["files"]} == DEFAULT_TREE

    def test_list_excludes_unretained_bundle_junk(self, client):
        ds_id = _import(client)
        paths = {f["path"] for f in client.get(f"{BASE}/{ds_id}/files").json()["files"]}
        assert "templates/corporate/ds-base.js" not in paths
        assert "templates/title-shot.png" not in paths
        assert "assets/preview.png" not in paths

    def test_list_includes_template_preview_reference_row(self, client):
        ds_id = _import(
            client, manifest=templated_manifest(), files=templated_bundle_files()
        )
        body = client.get(f"{BASE}/{ds_id}/files").json()
        by_path = {f["path"]: f for f in body["files"]}
        preview = by_path["templates/corporate/preview.png"]
        assert preview["kind"] == "asset"
        assert preview["mime"] == "image/png"

    def test_list_unknown_design_system_returns_404(self, client):
        assert client.get(f"{BASE}/4242/files").status_code == 404

    def test_list_design_system_without_files_is_empty(self, client):
        resp = client.post(BASE, json={"name": "Acme Structured"})
        assert resp.status_code == 201, resp.text
        ds_id = resp.json()["id"]
        resp = client.get(f"{BASE}/{ds_id}/files")
        assert resp.status_code == 200
        assert resp.json() == {"files": [], "total": 0}

    def test_list_is_scoped_to_the_design_system(self, client):
        ds_a = _import(client)
        files_b = {
            "assets/only-b.png": png_bytes(4, 4),
            "README.md": SYNTHETIC_README,
        }
        ds_b = _import(client, name="Acme B", files=files_b)
        paths_a = {f["path"] for f in client.get(f"{BASE}/{ds_a}/files").json()["files"]}
        paths_b = {f["path"] for f in client.get(f"{BASE}/{ds_b}/files").json()["files"]}
        assert "assets/only-b.png" not in paths_a
        assert "assets/only-b.png" in paths_b
        assert "SKILL.md" not in paths_b  # bundle B never shipped one


# ---------------------------------------------------------------------------
# Secure single-file serving
# ---------------------------------------------------------------------------


def _assert_safe_text_response(resp, expected_body: bytes):
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "text/plain; charset=utf-8"
    assert resp.headers["content-disposition"] == "attachment"
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.content == expected_body


class TestServeFile:
    def test_readme_served_as_plain_text_attachment(self, client):
        ds_id = _import(client)
        resp = client.get(f"{BASE}/{ds_id}/files/README.md")
        _assert_safe_text_response(resp, SYNTHETIC_README)

    def test_css_served_as_plain_text(self, client):
        ds_id = _import(client)
        resp = client.get(f"{BASE}/{ds_id}/files/colors_and_type.css")
        _assert_safe_text_response(resp, COLORS_AND_TYPE_CSS.encode("utf-8"))

    def test_template_html_never_served_as_html(self, client):
        ds_id = _import(client)
        resp = client.get(f"{BASE}/{ds_id}/files/templates/corporate/index.html")
        _assert_safe_text_response(resp, SYNTHETIC_TEMPLATE_HTML)
        assert "html" not in resp.headers["content-type"]

    def test_svg_served_as_source_text_not_image(self, client):
        """SVG can carry script — as a *source file* it ships as text/plain,
        with its bytes resolved through the asset reference row."""
        ds_id = _import(client)
        resp = client.get(f"{BASE}/{ds_id}/files/assets/logo.svg")
        _assert_safe_text_response(resp, SVG_LOGO)

    def test_json_and_js_sources_served_as_plain_text(self, client, db_session):
        """Stored rows with json/js content types are text sources, never
        executable. (The importer doesn't currently retain these kinds, so the
        rows are seeded directly.)"""
        from src.database.models.design_system import DesignSystemFile

        ds_id = _import(client)
        db_session.add_all(
            [
                DesignSystemFile(
                    design_system_id=ds_id,
                    path="data/sample-config.json",
                    kind="asset",
                    mime="application/json",
                    data=b'{"sample": true}',
                    size_bytes=16,
                ),
                DesignSystemFile(
                    design_system_id=ds_id,
                    path="scripts/sample-util.js",
                    kind="asset",
                    mime="text/javascript",
                    data=b"console.log('sample');",
                    size_bytes=22,
                ),
            ]
        )
        db_session.commit()
        resp = client.get(f"{BASE}/{ds_id}/files/data/sample-config.json")
        _assert_safe_text_response(resp, b'{"sample": true}')
        resp = client.get(f"{BASE}/{ds_id}/files/scripts/sample-util.js")
        _assert_safe_text_response(resp, b"console.log('sample');")

    def test_png_served_as_binary_attachment(self, client):
        ds_id = _import(client)
        resp = client.get(f"{BASE}/{ds_id}/files/assets/backgrounds/hero-bg.png")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/png"
        assert resp.headers["content-disposition"] == "attachment"
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert resp.content == png_bytes(16, 16)

    def test_font_served_as_binary_attachment(self, client):
        ds_id = _import(client)
        resp = client.get(f"{BASE}/{ds_id}/files/fonts/acme-sans.woff2")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "font/woff2"
        assert resp.headers["content-disposition"] == "attachment"
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert resp.content == b"OTTO synthetic-font-bytes"

    def test_every_listed_file_is_served_and_never_executable(self, client):
        """Sweep the whole tree (incl. the template preview screenshot): every
        listed path serves 200 as an attachment with nosniff, and no response
        carries a renderable/executable content type."""
        ds_id = _import(
            client, manifest=templated_manifest(), files=templated_bundle_files()
        )
        files = client.get(f"{BASE}/{ds_id}/files").json()["files"]
        assert files
        for entry in files:
            resp = client.get(f"{BASE}/{ds_id}/files/{entry['path']}")
            assert resp.status_code == 200, entry["path"]
            assert resp.headers["content-disposition"] == "attachment", entry["path"]
            assert resp.headers["x-content-type-options"] == "nosniff", entry["path"]
            content_type = resp.headers["content-type"].split(";")[0].strip()
            assert content_type not in EXECUTABLE_CONTENT_TYPES, entry["path"]

    def test_unknown_path_returns_404(self, client):
        ds_id = _import(client)
        assert client.get(f"{BASE}/{ds_id}/files/README.md").status_code == 200
        assert client.get(f"{BASE}/{ds_id}/files/no-such-file.md").status_code == 404

    def test_path_owned_by_another_design_system_returns_404(self, client):
        ds_a = _import(client)
        ds_b = _import(
            client, name="Acme No Readme", files={"assets/only-b.png": png_bytes(4, 4)}
        )
        # SKILL.md exists in system A only — B must not be able to read it.
        assert client.get(f"{BASE}/{ds_a}/files/SKILL.md").status_code == 200
        assert client.get(f"{BASE}/{ds_b}/files/SKILL.md").status_code == 404

    def test_missing_readme_bundle_still_lists_and_serves(self, client):
        ds_id = _import(
            client, name="Acme No Readme 2", files={"assets/only.png": png_bytes(4, 4)}
        )
        body = client.get(f"{BASE}/{ds_id}/files").json()
        assert "README.md" not in {f["path"] for f in body["files"]}
        assert client.get(f"{BASE}/{ds_id}/files/README.md").status_code == 404
        assert client.get(f"{BASE}/{ds_id}/files/assets/only.png").status_code == 200

    def test_unknown_design_system_returns_404(self, client):
        _import(client)
        assert client.get(f"{BASE}/4242/files/README.md").status_code == 404

    @pytest.mark.parametrize(
        "encoded_path",
        [
            "..%2fREADME.md",  # decodes to ../README.md
            "%2e%2e%2fREADME.md",  # decodes to ../README.md (dot-encoded)
            "assets%2f..%2f..%2fREADME.md",  # decodes to assets/../../README.md
            "assets%5clogo.svg",  # decodes to assets\logo.svg (backslash)
            "%2fetc%2fpasswd",  # decodes to /etc/passwd (absolute)
            "assets//logo.svg",  # empty segment
            "%252e%252e%2fREADME.md",  # double-encoded: lingering %2e after decode
            # NUL must be rejected BEFORE the DB lookup: SQLite would mask it as
            # a no-match 404, but PostgreSQL/psycopg2 refuses NUL in a bound
            # parameter (ValueError -> generic 500), breaking the uniform-404
            # contract in production.
            "foo%00bar.md",  # decodes to foo\x00bar.md (embedded NUL)
            "%00README.md",  # decodes to \x00README.md (leading NUL)
        ],
    )
    def test_traversal_attempts_rejected(self, client, encoded_path):
        ds_id = _import(client)
        # The legit sibling serves fine — so the 404 below proves rejection,
        # not a missing route.
        assert client.get(f"{BASE}/{ds_id}/files/README.md").status_code == 200
        assert client.get(f"{BASE}/{ds_id}/files/{encoded_path}").status_code == 404

    def test_empty_path_returns_404(self, client):
        ds_id = _import(client)
        assert client.get(f"{BASE}/{ds_id}/files/").status_code == 404

    def test_reference_row_with_missing_asset_returns_404(self, client, db_session):
        """Defensive: a dangling asset reference row must 404, not 500."""
        from src.database.models.design_system import DesignSystemAsset, DesignSystemFile

        ds_id = _import(client)
        row = (
            db_session.query(DesignSystemFile)
            .filter(
                DesignSystemFile.design_system_id == ds_id,
                DesignSystemFile.path == "assets/logo.svg",
            )
            .one()
        )
        db_session.query(DesignSystemAsset).filter(
            DesignSystemAsset.id == row.asset_id
        ).delete()
        row.asset_id = None
        db_session.commit()
        assert client.get(f"{BASE}/{ds_id}/files/assets/logo.svg").status_code == 404


# ---------------------------------------------------------------------------
# Path validation (pure function)
# ---------------------------------------------------------------------------


class TestValidatedFilePath:
    @pytest.mark.parametrize(
        "path",
        [
            "README.md",
            "colors_and_type.css",
            "templates/corporate/index.html",
            "assets/backgrounds/hero-bg.png",
            "a-b_c.1/ok.css",
        ],
    )
    def test_accepts_canonical_relative_paths(self, path):
        from src.api.routes.settings.design_systems import _validated_file_path

        assert _validated_file_path(path) == path

    @pytest.mark.parametrize(
        "path",
        [
            "",
            ".",
            "..",
            "../README.md",
            "a/../b.css",
            "a/..",
            "/etc/passwd",
            "C:evil.css",
            "C:/evil.css",
            "a//b.css",  # empty segment
            "a/./b.css",  # '.' segment
            "a\\b.css",  # backslash
            "trailing/",  # empty final segment
            "%2e%2e/b.css",  # lingering percent-encoded dot (double-encoding)
            "a%2fb.css",  # lingering percent-encoded slash
            "a%5cb.css",  # lingering percent-encoded backslash
            "a%2E%2e/b.css",  # mixed-case percent-encoding
            # NUL / C0 control characters: never in a legitimate path, and NUL
            # in particular breaks psycopg2 parameter adaptation (500, not 404).
            "foo\x00bar.md",  # embedded NUL
            "\x00README.md",  # leading NUL
            "foo\x1fbar.md",  # other C0 control
            "a\tb.css",  # tab (C0)
        ],
    )
    def test_rejects_traversal_and_non_canonical_paths(self, path):
        from src.api.routes.settings.design_systems import _validated_file_path

        assert _validated_file_path(path) is None

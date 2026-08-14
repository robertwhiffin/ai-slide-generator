"""Unit tests for the Design System bundle importer + asset retrieval (Phase 3).

The importer accepts a ``.zip`` design-system project (``_ds_manifest.json`` +
``colors_and_type.css`` + ``fonts/`` + ``assets/**``), validates it, stores the
design system + tokens + assets in Lakebase, and compiles the prompt artifact.

All fixtures are SYNTHETIC (fake "Acme" brand, dummy hex, placeholder bytes) —
no real brand content, per the public-repo hygiene rule.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import src.database.models  # noqa: F401 - register models with Base.metadata
from src.core.database import Base
from tests.unit.conftest_design_system import (
    MANIFEST_FILENAME,
    SVG_LOGO,
    SYNTHETIC_README,
    make_bundle_zip,
    make_declared_size_bundle_zip,
    webp_bytes,
)


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


# ---------------------------------------------------------------------------
# Happy path: end-to-end import -> store -> recompute
# ---------------------------------------------------------------------------


class TestImportHappyPath:
    def test_import_creates_design_system(self, session):
        from src.services.design_system_service import import_bundle

        ds = import_bundle(session, zip_bytes=make_bundle_zip(), user="tester@example.com")

        assert ds.id is not None
        assert ds.name == "Acme Design System"
        assert ds.created_by == "tester@example.com"
        assert ds.is_active is True
        assert ds.published is False
        assert ds.is_default is False
        # The bundle's semantic version is preserved in the manifest.
        assert ds.manifest_json["version"] == "1.0.0"

    def test_import_stores_tokens_from_manifest_and_css(self, session):
        from src.database.models.design_system import DesignSystemToken
        from src.services.design_system_service import import_bundle

        ds = import_bundle(session, zip_bytes=make_bundle_zip(), user="u")

        tokens = session.query(DesignSystemToken).filter_by(design_system_id=ds.id).all()
        by_key = {(t.group, t.name): t.value for t in tokens}
        # From _ds_manifest.json tokens[]
        assert by_key[("core", "primary")] == "#123456"
        assert by_key[("spacing", "md")] == "16px"
        # From colors_and_type.css :root vars (the --brand-<group>-<name> convention)
        assert by_key[("accents", "lava")] == "#EB4A34"
        # A non-prefixed type var lands in the 'type' group.
        assert ("type", "heading-font") in by_key

    def test_import_stores_binary_assets_and_skips_preview_and_template_shot(self, session):
        from src.database.models.design_system import DesignSystemAsset
        from src.services.design_system_service import import_bundle

        ds = import_bundle(session, zip_bytes=make_bundle_zip(), user="u")

        assets = session.query(DesignSystemAsset).filter_by(design_system_id=ds.id).all()
        by_name = {a.filename: a for a in assets}
        # fonts/ -> kind=font, bytes stored
        assert by_name["acme-sans.woff2"].kind == "font"
        assert by_name["acme-sans.woff2"].data == b"OTTO synthetic-font-bytes"
        # assets/logo.svg -> image asset
        assert by_name["logo.svg"].kind == "logo"
        assert by_name["logo.svg"].mime == "image/svg+xml"
        # backgrounds/hero-bg.png -> background, with intrinsic dimensions
        assert by_name["hero-bg.png"].kind == "background"
        assert by_name["hero-bg.png"].width == 16
        # template screenshots and previews are NOT stored
        assert "title-shot.png" not in by_name
        assert "preview.png" not in by_name

    def test_import_populates_compiled_style_content(self, session):
        from src.database.models.design_system import DesignSystemAsset
        from src.services.design_system_service import import_bundle

        ds = import_bundle(session, zip_bytes=make_bundle_zip(), user="u")

        assert ds.compiled_style_content
        assert "SLIDE VISUAL STYLE:" in ds.compiled_style_content
        assert "--brand-core-primary: #123456;" in ds.compiled_style_content
        # Brand IMAGE assets are fetched on demand via the search_brand_assets tool
        # (the compiled prompt carries the contract), NOT enumerated by id.
        assert "search_brand_assets" in ds.compiled_style_content
        logo = session.query(DesignSystemAsset).filter_by(
            design_system_id=ds.id, filename="logo.svg"
        ).one()
        assert f"{{{{ds-asset:{logo.id}}}}}" not in ds.compiled_style_content
        # Fonts ARE wired inline via @font-face, referenced by their real DB id.
        font = session.query(DesignSystemAsset).filter_by(
            design_system_id=ds.id, filename="acme-sans.woff2"
        ).one()
        assert f"{{{{ds-asset:{font.id}}}}}" in ds.compiled_style_content
        # Uses the ds-asset namespace, never the unrelated image namespace.
        assert "{{image:" not in ds.compiled_style_content

    def test_import_handles_wrapping_root_folder(self, session):
        """A bundle zipped with a top-level directory still imports."""
        from src.services.design_system_service import import_bundle

        zip_bytes = make_bundle_zip(root_prefix="acme-bundle/")
        ds = import_bundle(session, zip_bytes=zip_bytes, user="u")
        assert ds.name == "Acme Design System"
        assert len(ds.tokens) >= 3
        assert len(ds.assets) >= 3

    def test_name_override_wins_over_manifest(self, session):
        from src.services.design_system_service import import_bundle

        ds = import_bundle(
            session, zip_bytes=make_bundle_zip(), user="u", name_override="Renamed DS"
        )
        assert ds.name == "Renamed DS"


# ---------------------------------------------------------------------------
# Validation / malformed bundles -> clear errors
# ---------------------------------------------------------------------------


class TestImportValidation:
    def test_not_a_zip_raises_import_error(self, session):
        from src.services.design_system_service import DesignSystemImportError, import_bundle

        with pytest.raises(DesignSystemImportError):
            import_bundle(session, zip_bytes=b"this is not a zip", user="u")

    def test_missing_manifest_raises_import_error(self, session):
        from src.services.design_system_service import DesignSystemImportError, import_bundle

        zip_bytes = make_bundle_zip(include_manifest=False)
        with pytest.raises(DesignSystemImportError) as exc:
            import_bundle(session, zip_bytes=zip_bytes, user="u")
        assert "_ds_manifest.json" in str(exc.value)

    def test_invalid_manifest_json_raises_import_error(self, session):
        from src.services.design_system_service import DesignSystemImportError, import_bundle

        zip_bytes = make_bundle_zip(manifest="{not valid json")
        with pytest.raises(DesignSystemImportError):
            import_bundle(session, zip_bytes=zip_bytes, user="u")

    def test_per_asset_size_limit_enforced(self, session):
        from src.database.models.design_system import MAX_ASSET_SIZE_BYTES
        from src.services.design_system_service import DesignSystemImportError, import_bundle

        # DECLARED oversize (cheap zip), so this does not allocate MAX_ASSET_SIZE_BYTES
        # in the test process just because the cap was raised.
        zip_bytes = make_declared_size_bundle_zip(
            {"assets/huge.png": MAX_ASSET_SIZE_BYTES + 1}
        )
        with pytest.raises(DesignSystemImportError) as exc:
            import_bundle(session, zip_bytes=zip_bytes, user="u")
        assert "too large" in str(exc.value).lower()

    def test_per_bundle_size_limit_enforced(self, session):
        from src.database.models.design_system import (
            MAX_ASSET_SIZE_BYTES,
            MAX_BUNDLE_SIZE_BYTES,
        )
        from src.services.design_system_service import DesignSystemImportError, import_bundle

        # Several individually-legal assets whose sum exceeds the bundle cap.
        chunk = MAX_ASSET_SIZE_BYTES - 1
        count = (MAX_BUNDLE_SIZE_BYTES // chunk) + 2
        zip_bytes = make_declared_size_bundle_zip(
            {f"assets/img-{i}.png": chunk for i in range(count)}
        )
        with pytest.raises(DesignSystemImportError) as exc:
            import_bundle(session, zip_bytes=zip_bytes, user="u")
        assert "bundle" in str(exc.value).lower()

    def test_oversized_manifest_rejected_before_read(self, session):
        """Decompression-bomb guard: a manifest whose declared uncompressed size
        exceeds the per-asset limit is rejected BEFORE zf.read materialises it."""
        from src.database.models.design_system import MAX_ASSET_SIZE_BYTES
        from src.services.design_system_service import DesignSystemImportError, import_bundle

        # Oversized (and never even parsed — the size guard fires first).
        zip_bytes = make_declared_size_bundle_zip(
            {MANIFEST_FILENAME: MAX_ASSET_SIZE_BYTES + 1}, manifest=None
        )
        with pytest.raises(DesignSystemImportError) as exc:
            import_bundle(session, zip_bytes=zip_bytes, user="u")
        assert "too large" in str(exc.value).lower()

    def test_oversized_css_rejected_before_read(self, session):
        """Decompression-bomb guard: an oversized globalCssPaths/colors_and_type.css
        entry is rejected BEFORE zf.read materialises it."""
        from src.database.models.design_system import MAX_ASSET_SIZE_BYTES
        from src.services.design_system_service import DesignSystemImportError, import_bundle

        zip_bytes = make_declared_size_bundle_zip(
            {"colors_and_type.css": MAX_ASSET_SIZE_BYTES + 1}, css=None
        )
        with pytest.raises(DesignSystemImportError) as exc:
            import_bundle(session, zip_bytes=zip_bytes, user="u")
        assert "too large" in str(exc.value).lower()

    def test_asset_declaring_over_100mb_is_rejected_not_materialised(self, session):
        """The per-asset guard still bites at the RAISED 100 MB boundary.

        Pinned to the concrete cap (not just ``MAX_ASSET_SIZE_BYTES + 1``) so a future
        cap change cannot make this pass vacuously. The entry DECLARES >100 MB in its
        zip header but is kilobytes on disk, so the assertion is that the guard reads
        the declared size and refuses — never allocating 100 MB, never OOMing, and
        never silently dropping the entry.
        """
        import zipfile as zipfile_mod

        from src.services.design_system_service import DesignSystemImportError, import_bundle

        over_100mb = 100 * 1024 * 1024 + 1
        zip_bytes = make_declared_size_bundle_zip({"assets/bomb.png": over_100mb})

        reads: list[str] = []
        original_read = zipfile_mod.ZipFile.read

        def spy_read(self, name, *args, **kwargs):
            reads.append(getattr(name, "filename", name))
            return original_read(self, name, *args, **kwargs)

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(zipfile_mod.ZipFile, "read", spy_read)
        try:
            with pytest.raises(DesignSystemImportError) as exc:
                import_bundle(session, zip_bytes=zip_bytes, user="u")
        finally:
            monkeypatch.undo()

        # VISIBLE + ACTIONABLE: names the offending entry and the limit it broke.
        message = str(exc.value)
        assert "assets/bomb.png" in message
        assert str(over_100mb) in message
        assert str(100 * 1024 * 1024) in message
        assert "too large" in message.lower()
        # PRE-MATERIALISATION: the bomb's bytes were never handed to zf.read.
        assert "assets/bomb.png" not in reads

    def test_cumulative_bundle_guard_still_trips_above_500mb(self, session):
        """The cumulative guard still bites at the RAISED 500 MB boundary.

        Individually-legal entries (each under the 100 MB per-asset cap) whose DECLARED
        sizes sum past 500 MB must be refused by the running total that spans manifest +
        CSS + assets — proving the bundle cap is still cumulative, not per-entry.
        """
        from src.services.design_system_service import DesignSystemImportError, import_bundle

        per_entry = 90 * 1024 * 1024  # legal on its own (< 100 MB)
        entries = {f"assets/img-{i}.png": per_entry for i in range(6)}  # 540 MB declared
        assert sum(entries.values()) > 500 * 1024 * 1024
        assert max(entries.values()) < 100 * 1024 * 1024  # none trips the per-asset cap

        zip_bytes = make_declared_size_bundle_zip(entries)
        with pytest.raises(DesignSystemImportError) as exc:
            import_bundle(session, zip_bytes=zip_bytes, user="u")

        message = str(exc.value)
        assert "bundle" in message.lower()
        assert str(500 * 1024 * 1024) in message

    def test_duplicate_name_raises_conflict(self, session):
        from src.services.design_system_service import (
            DesignSystemNameConflictError,
            import_bundle,
        )

        import_bundle(session, zip_bytes=make_bundle_zip(), user="u")
        with pytest.raises(DesignSystemNameConflictError):
            import_bundle(session, zip_bytes=make_bundle_zip(), user="u")


# ---------------------------------------------------------------------------
# Dotfile handling: a NARROW allowlist, not a relaxed skip
#
# A template folder's ``.thumbnail`` screenshot is the ONE dot-prefixed shape the
# importer stores. The allowlist is keyed on the whole normalized path
# (``templates/<one-segment>/`` + a thumbnail basename), so every other dotfile —
# anywhere in the bundle — stays skipped exactly as before.
# ---------------------------------------------------------------------------


class TestDotfileAllowlistIsNarrow:
    def _stored(self, session, files):
        from src.services.design_system_service import import_bundle

        ds = import_bundle(
            session, zip_bytes=make_bundle_zip(files=files), user="u"
        )
        return {a.filename for a in ds.assets}, {f.path for f in ds.files}

    @pytest.mark.parametrize(
        "arcname",
        [
            ".env",
            ".npmrc",
            ".DS_Store",
            ".git/config",
            ".git/HEAD",
            "assets/.env",
            "assets/.DS_Store",
            "assets/.hidden-logo.png",
            "fonts/.env",
            "__MACOSX/._logo.svg",
            "__MACOSX/assets/._logo.svg",
            "templates/corporate/.env",
            "templates/corporate/.DS_Store",
            "templates/corporate/.git/config",
        ],
        ids=lambda name: name.replace("/", "_"),
    )
    def test_non_thumbnail_dotfiles_and_os_junk_are_never_stored(
        self, session, arcname
    ):
        files = {
            "assets/logo.svg": SVG_LOGO,
            "README.md": SYNTHETIC_README,
            arcname: b"SECRET=should-never-be-stored",
        }
        filenames, paths = self._stored(session, files)
        assert arcname not in paths
        assert arcname.rsplit("/", 1)[-1] not in filenames
        # The legitimate asset still imported, so this is not a vacuous pass.
        assert "assets/logo.svg" in paths

    @pytest.mark.parametrize(
        "arcname",
        [
            ".thumbnail",  # bundle root, not a template folder
            "assets/.thumbnail",  # inside the brand-asset tree
            "fonts/.thumbnail",
            "templates/.thumbnail",  # no template folder segment
            "templates/corporate/nested/.thumbnail",  # two segments deep
            "templates/corporate/.thumbnail.bak",  # not a bare thumbnail basename
            "templates/corporate/.thumbnails",
        ],
        ids=lambda name: name.replace("/", "_"),
    )
    def test_thumbnail_outside_the_allowed_shape_is_not_stored(self, session, arcname):
        """Real WebP bytes at the wrong path are still refused — the allowlist is
        keyed on the PATH shape, so valid image content cannot smuggle a dotfile
        past it."""
        files = {
            "assets/logo.svg": SVG_LOGO,
            "README.md": SYNTHETIC_README,
            arcname: webp_bytes(),
        }
        filenames, paths = self._stored(session, files)
        assert arcname not in paths
        assert "assets/logo.svg" in paths


class TestThumbnailPathsAreStillZipSlipChecked:
    @pytest.mark.parametrize(
        "arcname",
        [
            "../.thumbnail",
            "templates/../../.thumbnail",
            "templates/corporate/../../../.thumbnail",
            "/etc/templates/corporate/.thumbnail",
        ],
        ids=lambda name: name.replace("/", "_"),
    )
    def test_traversal_thumbnail_rejects_the_whole_bundle(self, session, arcname):
        from src.services.design_system_service import DesignSystemImportError, import_bundle

        files = {"assets/logo.svg": SVG_LOGO, arcname: webp_bytes()}
        with pytest.raises(DesignSystemImportError) as exc:
            import_bundle(session, zip_bytes=make_bundle_zip(files=files), user="u")
        message = str(exc.value).lower()
        assert "unsafe" in message or "traversal" in message

    def test_iterator_itself_refuses_a_traversal_thumbnail(self):
        """The entry iterator raises on its own, not only via the up-front global
        path scan — a dot-prefixed thumbnail must not be able to skip the check by
        being allowlisted."""
        import io
        import zipfile

        from src.services.design_system_service import (
            DesignSystemImportError,
            _iter_safe_entries,
        )

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("templates/corporate/../../../.thumbnail", webp_bytes())
        with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as zf:
            with pytest.raises(DesignSystemImportError):
                list(_iter_safe_entries(zf, ""))

    def test_iterator_still_yields_a_legitimate_dot_thumbnail(self):
        """Positive control for the test above: the same iterator DOES surface a
        well-formed template thumbnail, so the rejection above is about the path,
        not about dot-prefixed names in general."""
        import io
        import zipfile

        from src.services.design_system_service import _iter_safe_entries

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("templates/corporate/.thumbnail", webp_bytes())
            zf.writestr("templates/corporate/.env", b"SECRET=x")
        with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as zf:
            yielded = [rel for _, rel in _iter_safe_entries(zf, "")]
        assert yielded == ["templates/corporate/.thumbnail"]


# ---------------------------------------------------------------------------
# A bundle path is CANONICAL or it is refused — never laundered into one
# ---------------------------------------------------------------------------
#
# Normalization used to run BEFORE the junk/dotfile decision, so a segment that
# made an entry junk could be erased on the way to that decision:
# ``assets/innocent/.`` normalized to ``assets/innocent``, whose basename is no
# longer dot-prefixed, and the entry was STORED under a path that was not its own
# name. Two entries could also collapse onto one identity (``assets/./x`` and
# ``assets/x``), leaving which bytes win to zip ordering.
#
# The fix is to refuse a non-canonical path outright instead of rewriting it into
# an acceptable one, and to make BOTH gates that look at bundle paths reach that
# verdict through the SAME classifier, so they cannot disagree by construction.
# ---------------------------------------------------------------------------

#: Path shapes that are not canonical and must therefore be REFUSED outright.
#: Every one of these was previously either stored under a laundered name or
#: silently collapsed onto another entry's identity.
NON_CANONICAL_ARCNAMES = [
    "assets/innocent/.",
    "fonts/x/.",
    "assets/./x",
    "assets/x/.",
    "templates/x/.",
    ".",
    "..",
    "assets/..",
    "assets//x",
    "./assets/logo2.svg",
]

#: Trailing junk on the ALLOWLISTED thumbnail shape. ``$`` matches before a single
#: trailing newline in Python, so ``templates/x/.thumbnail\n`` satisfied a ``$``
#: anchored allowlist and was stored; the rest are control characters that never
#: belong in a path.
CONTROL_CHAR_ARCNAMES = [
    "templates/x/.thumbnail\n",
    "templates/x/.thumbnail\r\n",
    "templates/x/.thumbnail\r",
    "templates/x/.thumbnail\t",
    "templates/x/preview\n",
    "templates/x/preview.png\n",
]


class TestNonCanonicalPathsAreRefused:
    def test_all_shapes_refuse_the_whole_bundle(self, session):
        """Every non-canonical shape refuses the import rather than storing
        SOMETHING under a name that is not the entry's own."""
        from src.services.design_system_service import DesignSystemImportError, import_bundle
        from tests.unit.conftest_design_system import default_manifest

        survived = []
        for index, arcname in enumerate(NON_CANONICAL_ARCNAMES + CONTROL_CHAR_ARCNAMES):
            # A distinct name per iteration: the unique index on a LIVE name would
            # otherwise 409 on the second import and mask the real outcome.
            manifest = default_manifest()
            manifest["name"] = f"Acme Shape {index}"
            files = {"assets/logo.svg": SVG_LOGO, arcname: webp_bytes()}
            try:
                ds = import_bundle(
                    session,
                    zip_bytes=make_bundle_zip(manifest=manifest, files=files),
                    user="u",
                )
            except DesignSystemImportError:
                continue
            survived.append((arcname, sorted(f.path for f in ds.files)))
        assert survived == [], f"non-canonical paths reached storage: {survived}"

    @pytest.mark.parametrize(
        "arcname", NON_CANONICAL_ARCNAMES + CONTROL_CHAR_ARCNAMES, ids=repr
    )
    def test_both_gates_agree_by_construction(self, arcname):
        """The up-front whole-bundle scan and the per-entry iterator must reach the
        SAME verdict on the same shape. The regression was exactly a disagreement:
        the scan refused ``assets/innocent/.`` on its RAW basename while the
        iterator accepted the same entry on its NORMALIZED one."""
        import io
        import zipfile

        from src.services.design_system_service import (
            DesignSystemImportError,
            _assert_bundle_paths_safe,
            _iter_safe_entries,
        )

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(arcname, webp_bytes())
        raw = buf.getvalue()

        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            with pytest.raises(DesignSystemImportError):
                _assert_bundle_paths_safe(zf)
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            with pytest.raises(DesignSystemImportError):
                list(_iter_safe_entries(zf, ""))

    @pytest.mark.parametrize(
        "rel_path",
        NON_CANONICAL_ARCNAMES
        + CONTROL_CHAR_ARCNAMES
        + [
            # A NUL cannot survive ``zipfile`` (it truncates the arcname on write),
            # so it is unreachable end-to-end — the predicate still refuses it
            # rather than relying on a stdlib detail for that property.
            "templates/x/.thumbnail\x00",
            "assets/lo\x00go.svg",
            "",
            "/etc/passwd",
            "C:/Windows/x",
        ],
        ids=repr,
    )
    def test_safe_relpath_refuses_rather_than_rewrites(self, rel_path):
        from src.services.design_system_service import _safe_relpath

        assert _safe_relpath(rel_path) is None

    @pytest.mark.parametrize(
        "rel_path", ["assets/logo.svg", "templates/x/.thumbnail", "a/b/c.png"]
    )
    def test_canonical_paths_pass_through_unchanged(self, rel_path):
        """Positive control: a canonical path is returned as-is, so the refusals
        above are about non-canonical shapes, not about rejecting everything."""
        from src.services.design_system_service import _safe_relpath

        assert _safe_relpath(rel_path) == rel_path

    def test_directory_entries_are_skipped_not_refused(self, session):
        """A trailing-slash directory entry is never STORED, but it must not refuse
        the bundle either — every real zip carries directory entries."""
        import io
        import zipfile

        from src.services.design_system_service import _iter_safe_entries, import_bundle

        files = {
            "assets/": b"",
            "assets/sub/": b"",
            "fonts/": b"",
            "assets/logo.svg": SVG_LOGO,
        }
        ds = import_bundle(session, zip_bytes=make_bundle_zip(files=files), user="u")
        paths = {f.path for f in ds.files}
        assert "assets/logo.svg" in paths
        assert not any(p.rstrip("/") in ("assets", "assets/sub", "fonts") for p in paths)

        # And the iterator yields nothing for a bare directory entry.
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("assets/dir/", b"")
        with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as zf:
            assert [rel for _, rel in _iter_safe_entries(zf, "")] == []

    def test_traversal_directory_entry_is_still_refused(self):
        """Skipping directory entries must not become a way to smuggle a traversal
        path past the scan."""
        import io
        import zipfile

        from src.services.design_system_service import (
            DesignSystemImportError,
            _assert_bundle_paths_safe,
        )

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("../evil/", b"")
        with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as zf:
            with pytest.raises(DesignSystemImportError):
                _assert_bundle_paths_safe(zf)


class TestThumbnailAllowlistAnchoring:
    """``$`` accepts a terminal newline in Python, so a ``$``-anchored allowlist on
    a PATH accepts ``<allowed shape>\\n``. Every allowlist predicate on a path or
    filename must reject trailing junk, not just the documented shapes."""

    @pytest.mark.parametrize(
        "rel_path",
        [
            "templates/x/.thumbnail\n",
            "templates/x/.thumbnail\r\n",
            "templates/x/.thumbnail\r",
            "templates/x/.thumbnail\t",
            "templates/x/.thumbnail ",
            "templates/x/.thumbnail\x00",
            "templates/x/thumbnail\n",
            "templates/x/preview\n",
        ],
        ids=repr,
    )
    def test_thumbnail_recognizers_reject_trailing_junk(self, rel_path):
        from src.services.design_system_service import (
            _is_template_preview,
            _is_template_thumbnail,
        )

        assert _is_template_thumbnail(rel_path) is False
        assert _is_template_preview(rel_path) is False

    @pytest.mark.parametrize(
        "rel_path",
        [
            "templates/x/preview.png\n",
            "templates/x/preview.webp\n",
            "templates/x/preview.png\t",
            "templates/x/preview.png ",
            "templates/x/preview.png\x00",
        ],
        ids=repr,
    )
    def test_preview_recognizer_rejects_trailing_junk(self, rel_path):
        """The SIBLING regex has the same ``$`` anchor and the same defect class."""
        from src.services.design_system_service import _is_template_preview

        assert _is_template_preview(rel_path) is False

    @pytest.mark.parametrize(
        "rel_path",
        ["templates/x/.thumbnail", "templates/x/preview.png", "templates/x/preview"],
    )
    def test_legitimate_shapes_still_recognized(self, rel_path):
        """Positive control for the anchoring tests above."""
        from src.services.design_system_service import _is_template_preview

        assert _is_template_preview(rel_path) is True

    @pytest.mark.parametrize(
        "basename",
        [
            ".thumbnail\n",
            ".thumbnail\r\n",
            ".thumbnail\r",
            ".thumbnail\t",
            ".thumbnail\x00",
            "preview\n",
        ],
        ids=repr,
    )
    def test_template_thumbnail_lookup_rejects_control_characters(self, basename):
        """The THIRD gate on the same file (``design_system_templates``) picks the
        row that becomes ``thumbnail_url``. Defence in depth: stored paths can no
        longer carry a control character, and this predicate no longer depends on
        the importer for that."""
        from src.services.design_system_templates import _is_thumbnail_basename

        assert _is_thumbnail_basename(basename) is False

    @pytest.mark.parametrize("basename", [".thumbnail", "thumbnail", "preview.png"])
    def test_template_thumbnail_lookup_still_matches_real_basenames(self, basename):
        from src.services.design_system_templates import _is_thumbnail_basename

        assert _is_thumbnail_basename(basename) is True


# ---------------------------------------------------------------------------
# Asset retrieval (used by the {{ds-asset:ID}} resolver + serve endpoint)
# ---------------------------------------------------------------------------


class TestGetAssetBase64:
    def test_returns_base64_and_mime(self, session):
        import base64

        from src.database.models.design_system import DesignSystemAsset
        from src.services.design_system_service import get_asset_base64, import_bundle

        ds = import_bundle(session, zip_bytes=make_bundle_zip(), user="u")
        logo = session.query(DesignSystemAsset).filter_by(
            design_system_id=ds.id, filename="logo.svg"
        ).one()

        b64, mime = get_asset_base64(session, logo.id, design_system_id=ds.id)
        assert mime == "image/svg+xml"
        assert base64.b64decode(b64) == logo.data

    def test_missing_asset_raises(self, session):
        from src.services.design_system_service import get_asset_base64

        with pytest.raises(ValueError):
            get_asset_base64(session, 999999, design_system_id=1)

    def test_foreign_design_system_id_raises_not_found(self, session):
        """Confused-deputy guard: an asset id fetched under the WRONG design
        system id must be reported not-found (never returns the other system's
        bytes)."""
        from src.database.models.design_system import DesignSystemAsset
        from src.services.design_system_service import get_asset_base64, import_bundle

        ds = import_bundle(session, zip_bytes=make_bundle_zip(), user="u")
        logo = session.query(DesignSystemAsset).filter_by(
            design_system_id=ds.id, filename="logo.svg"
        ).one()

        with pytest.raises(ValueError):
            get_asset_base64(session, logo.id, design_system_id=ds.id + 1)

    def test_none_design_system_id_raises_not_found(self, session):
        """Fail-closed: a None scope resolves NO asset (the column is NOT NULL,
        so the IS NULL filter matches nothing)."""
        from src.database.models.design_system import DesignSystemAsset
        from src.services.design_system_service import get_asset_base64, import_bundle

        ds = import_bundle(session, zip_bytes=make_bundle_zip(), user="u")
        logo = session.query(DesignSystemAsset).filter_by(
            design_system_id=ds.id, filename="logo.svg"
        ).one()

        with pytest.raises(ValueError):
            get_asset_base64(session, logo.id, design_system_id=None)


class TestDefaultNamePrecedence:
    """Default name: override -> manifest name -> README H1 -> zip filename ->
    bundle root folder -> constant. All fixtures SYNTHETIC."""

    def _manifest_without_name(self):
        from tests.unit.conftest_design_system import default_manifest

        manifest = default_manifest()
        manifest.pop("name", None)
        return manifest

    def test_manifest_name_wins_over_readme_h1(self, session):
        from src.services.design_system_service import import_bundle

        ds = import_bundle(
            session,
            zip_bytes=make_bundle_zip(),  # manifest name + README H1 both present
            user="u",
            source_filename="acme-bundle.zip",
        )
        assert ds.name == "Acme Design System"  # manifest name

    def test_readme_h1_used_when_manifest_has_no_name(self, session):
        from tests.unit.conftest_design_system import SYNTHETIC_SKILL

        files = {
            "README.md": b"# Acme Brand Kit\n\nSynthetic readme.\n",
            "SKILL.md": SYNTHETIC_SKILL,
        }
        from src.services.design_system_service import import_bundle

        ds = import_bundle(
            session,
            zip_bytes=make_bundle_zip(manifest=self._manifest_without_name(), files=files),
            user="u",
            source_filename="whatever.zip",
        )
        assert ds.name == "Acme Brand Kit"

    def test_zip_filename_used_when_no_manifest_name_and_no_h1(self, session):
        files = {"README.md": b"No heading here, just prose.\n"}
        from src.services.design_system_service import import_bundle

        ds = import_bundle(
            session,
            zip_bytes=make_bundle_zip(manifest=self._manifest_without_name(), files=files),
            user="u",
            source_filename="acme-export-2026.zip",
        )
        assert ds.name == "acme-export-2026"

    def test_constant_fallback_when_nothing_available(self, session):
        from src.services.design_system_service import import_bundle

        ds = import_bundle(
            session,
            zip_bytes=make_bundle_zip(manifest=self._manifest_without_name(), files={}),
            user="u",
        )
        assert ds.name == "Imported Design System"

    def test_override_still_wins_over_everything(self, session):
        from src.services.design_system_service import import_bundle

        ds = import_bundle(
            session,
            zip_bytes=make_bundle_zip(),
            user="u",
            name_override="Explicit Name",
            source_filename="acme.zip",
        )
        assert ds.name == "Explicit Name"


# ---------------------------------------------------------------------------
# Long token NAMES must not fail the whole bundle import
# ---------------------------------------------------------------------------
#
# The user requirement is ZERO brand-token loss. The compiler stopped dropping
# names, but the STORAGE/VALIDATION layers still rejected them: TokenIn capped
# name at 100 chars and design_system_token.name was VARCHAR(100). That is worse
# than a silent drop — one long token name rejected the ENTIRE import, so a
# bundle with 400 good tokens and one 120-char name imported nothing.
#
# Both layers are widened to 255. All fixtures SYNTHETIC.

# NOTE: deliberately NOT prefixed "brand-". ``_normalize_token_ident`` strips that
# namespace by design so manifest tokens dedup against CSS ``:root`` vars, which
# would change the stored name and make these assertions test the wrong thing.
_LONG_120 = "display-heading-size-token-" + "x" * 93
_LONG_200 = "semantic-surface-elevated-interactive-hover-token-" + "y" * 150


class TestLongTokenNamesImportSuccessfully:
    def test_token_in_accepts_a_120_and_200_char_name(self):
        """The API-layer validator must not be the thing that loses brand data."""
        from src.api.routes.settings.design_systems import TokenIn

        assert len(_LONG_120) == 120
        assert len(_LONG_200) == 200
        for name in (_LONG_120, _LONG_200):
            token = TokenIn(group="type", name=name, value="64px")
            assert token.name == name

    def test_bundle_with_long_token_names_imports_and_compiles(self, session):
        """End to end: a bundle carrying both long names imports SUCCESSFULLY and
        both names reach the compiled artifact."""
        from src.services.design_system_compiler import compile_design_system
        from src.services.design_system_service import import_bundle
        from tests.unit.conftest_design_system import default_manifest

        manifest = default_manifest()
        manifest["name"] = "Acme Long Token Names"
        manifest["tokens"] = [
            {"group": "type", "name": _LONG_120, "value": "64px"},
            {"group": "type", "name": _LONG_200, "value": "40px"},
            {"group": "core", "name": "primary", "value": "#123456"},
        ]

        ds = import_bundle(
            session,
            zip_bytes=make_bundle_zip(manifest=manifest),
            user="creator@test.com",
        )
        session.commit()

        stored = {token.name for token in ds.tokens}
        assert _LONG_120 in stored, "120-char token name was not persisted"
        assert _LONG_200 in stored, "200-char token name was not persisted"

        compiled = compile_design_system(ds)
        assert _LONG_120 in compiled
        assert _LONG_200 in compiled

    def test_one_long_name_does_not_reject_the_other_tokens(self):
        """The failure mode that made this BLOCKING: a single long name used to
        take the whole bundle down with it."""
        from src.api.routes.settings.design_systems import TokenIn

        tokens = [
            TokenIn(group="core", name="primary", value="#123456"),
            TokenIn(group="type", name=_LONG_120, value="64px"),
            TokenIn(group="core", name="secondary", value="#234567"),
        ]
        assert [t.name for t in tokens][1] == _LONG_120

    def test_there_is_no_upper_boundary_on_a_brand_token_name(self):
        """SUPERSEDES ``test_255_is_the_boundary_and_beyond_it_still_validates``.

        That test asserted 256 characters were REJECTED, which was the defect: a
        bundle import is one request, so rejecting one long token failed the whole
        import and cost every other token in the bundle. Two rounds raised the
        boundary (100 -> 255) and a longer real string reopened it each time,
        because the number was never the problem.

        Free-form brand text is now UNCAPPED at both the validator and the column,
        so this asserts the absence of a boundary — a strictly stronger property
        than "the boundary sits at 255", and one no future length can defeat.
        """
        from src.api.routes.settings.design_systems import TokenIn

        for length in (255, 256, 1000, 10_000):
            token = TokenIn(group="type", name="z" * length, value="1px")
            assert len(token.name) == length, (
                f"a {length}-character brand token name was altered or rejected"
            )


class TestTokenNameColumnWidthMigration:
    """The hand-rolled idempotent migration (there is no Alembic in this repo).

    On Postgres the widening is a real ``ALTER COLUMN TYPE VARCHAR(255)``, which
    is safe and non-rewriting. On SQLite ``VARCHAR(n)`` length is NOT enforced at
    all, so the migration is deliberately a NO-OP there rather than faking a
    table rebuild — asserted below so nobody "fixes" it into one.
    """

    def test_migration_is_idempotent_run_twice(self):
        """Running the whole migration set twice must not error."""
        from sqlalchemy import create_engine
        from sqlalchemy.pool import StaticPool

        from src.core.database import Base, _run_migrations

        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=engine)
        _run_migrations(engine)
        _run_migrations(engine)  # second pass must be a clean no-op
        engine.dispose()

    def test_widen_helper_is_a_noop_on_sqlite(self):
        """SQLite does not enforce VARCHAR length, so there is nothing to do —
        and attempting an ALTER COLUMN TYPE there would raise."""
        from sqlalchemy import create_engine, inspect, text
        from sqlalchemy.pool import StaticPool

        from src.core.database import Base, _migrate_widen_token_name

        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=engine)
        with engine.begin() as conn:
            inspector = inspect(conn)
            _migrate_widen_token_name(
                conn, inspector, None, lambda t: f'"{t}"', True
            )
            # A 200-char name round-trips regardless (length is unenforced here).
            conn.execute(text(
                "INSERT INTO design_system "
                "(name, version, published, is_active, is_default, created_at, updated_at) "
                "VALUES ('Acme Width', 1, 0, 1, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ))
            ds_id = conn.execute(text("SELECT id FROM design_system")).scalar()
            conn.execute(
                text(
                    "INSERT INTO design_system_token (design_system_id, \"group\", name, value) "
                    "VALUES (:ds, 'type', :name, '64px')"
                ),
                {"ds": ds_id, "name": "w" * 200},
            )
            got = conn.execute(text("SELECT name FROM design_system_token")).scalar()
        assert got == "w" * 200
        engine.dispose()

    def test_orm_column_is_declared_uncapped(self):
        """SUPERSEDES ``test_orm_column_is_declared_255``. The ORM declaration is
        what ``create_all()`` uses for FRESH databases, so it must match the
        migration for existing ones — and the target is now NO cap at all, not a
        wider one. Asserting the absence of a length is strictly stronger than
        asserting a specific width."""
        from sqlalchemy import Text

        from src.database.models.design_system import DesignSystemToken

        column = DesignSystemToken.__table__.c.name
        assert column.type.length is None
        assert isinstance(column.type, Text)


class TestTokenGroupWidth:
    """BLOCKING 4a (round 5, cross-review): a 51-character GROUP name was rejected
    at the API validator with ``string_too_long``, so a bundle carrying one long
    group name failed to import — turning a token away for the NAME OF ITS GROUP,
    which the zero-token-loss requirement rules out. Worse than the silent drop the
    compiler stopped doing: one long group name cost every other token in the
    bundle.

    ``design_system_token.group`` is widened 50 -> 255 to match ``name`` and
    ``value``, with the same hand-rolled idempotent ALTER used for ``name``.

    All fixtures SYNTHETIC.
    """

    def test_api_validator_accepts_a_200_char_group(self):
        from src.api.routes.settings.design_systems import TokenIn

        token = TokenIn(group="g" * 200, name="tok", value="#123456")
        assert token.group == "g" * 200

    def test_orm_group_column_is_declared_uncapped(self):
        """SUPERSEDES ``test_orm_group_column_is_declared_255`` — same reasoning as
        the token NAME column: ``create_all()`` uses this declaration for fresh
        databases, and the target is now no cap at all."""
        from sqlalchemy import Text

        from src.database.models.design_system import DesignSystemToken

        column = DesignSystemToken.__table__.c.group
        assert column.type.length is None
        assert isinstance(column.type, Text)

    def test_a_200_char_group_compiles_and_keeps_its_tokens(self):
        """End to end: the long group must reach the compiled artifact, not just be
        storable."""
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session
        from sqlalchemy.pool import StaticPool

        from src.core.database import Base
        from src.database.models.design_system import DesignSystem, DesignSystemToken
        from src.services.design_system_compiler import compile_design_system

        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=engine)
        long_group = "g" * 200
        with Session(engine) as session:
            ds = DesignSystem(name="Acme Width DS", version=1)
            ds.tokens.append(
                DesignSystemToken(group=long_group, name="tok-long", value="#0A0B0C")
            )
            session.add(ds)
            session.commit()
            session.refresh(ds)
            out = compile_design_system(ds)
        engine.dispose()

        assert "tok-long: #0A0B0C" in out, "token with a 200-char group was dropped"

    def test_widen_group_helper_is_a_noop_on_sqlite(self):
        """Same dialect contract as the name widening: SQLite does not enforce
        VARCHAR length, so the helper returns early rather than attempting an
        ALTER COLUMN TYPE that SQLite cannot run."""
        from sqlalchemy import create_engine, inspect, text
        from sqlalchemy.pool import StaticPool

        from src.core.database import Base, _migrate_widen_token_group

        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=engine)
        with engine.begin() as conn:
            inspector = inspect(conn)
            _migrate_widen_token_group(conn, inspector, None, lambda t: f'"{t}"', True)
            conn.execute(text(
                "INSERT INTO design_system "
                "(name, version, published, is_active, is_default, created_at, updated_at) "
                "VALUES ('Acme Group Width', 1, 0, 1, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ))
            ds_id = conn.execute(text("SELECT id FROM design_system")).scalar()
            conn.execute(
                text(
                    "INSERT INTO design_system_token (design_system_id, \"group\", name, value) "
                    "VALUES (:ds, :grp, 'tok', '64px')"
                ),
                {"ds": ds_id, "grp": "g" * 200},
            )
            got = conn.execute(text('SELECT "group" FROM design_system_token')).scalar()
        assert got == "g" * 200
        engine.dispose()

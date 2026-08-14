"""Unit tests for the Design System bundle importer + asset retrieval (Phase 3).

The importer accepts a ``.zip`` design-system project (``_ds_manifest.json`` +
``colors_and_type.css`` + ``fonts/`` + ``assets/**``), validates it, stores the
design system + tokens + assets in Lakebase, and compiles the prompt artifact.

All fixtures are SYNTHETIC (fake "Acme" brand, dummy hex, placeholder bytes) —
no real brand content, per the public-repo hygiene rule.
"""

import contextlib
import io
import json
import os
import shutil
import subprocess
import zipfile

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import src.database.models  # noqa: F401 - register models with Base.metadata
from src.core.database import Base
from src.services.design_system_service import _basename
from tests.unit.conftest_design_system import (
    COLORS_AND_TYPE_CSS,
    MANIFEST_FILENAME,
    SVG_LOGO,
    SYNTHETIC_README,
    SYNTHETIC_TEMPLATE_HTML,
    default_manifest,
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
        from src.services.design_system_service import _iter_safe_entries

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("templates/corporate/.thumbnail", webp_bytes())
            zf.writestr("templates/corporate/.env", b"SECRET=x")
        with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as zf:
            yielded = [rel for _, rel in _iter_safe_entries(zf, "")]
        assert yielded == ["templates/corporate/.thumbnail"]


# ---------------------------------------------------------------------------
# A bundle path is VALIDATED, never rewritten — and a duplicate claim on ONE
# stored path is refused instead of resolved by zip order
# ---------------------------------------------------------------------------
#
# The rule is the one f83fc2e shipped: an entry is already spelled as the plain
# relative path of the file it names, or the bundle is REFUSED. Nothing is
# normalized into an acceptable form, for two measured reasons.
#
# (i) Rewriting changes the very string the rules downstream are about to judge.
# ``assets/innocent/.`` normalized to ``assets/innocent``, losing the ``.``
# basename that made it a directory reference, and the entry was stored under a
# name that was not its own.
#
# (ii) Rewriting collapses DISTINCT entries onto ONE identity — ``assets/./x``,
# ``assets//x`` and ``assets/x`` all become ``assets/x`` — leaving which bytes
# get stored to zip member ordering.
#
# The ONE tolerance, kept exactly as f83fc2e kept it, is folding ``\`` to ``/``:
# zips written on Windows use it as the separator, and a fold can neither erase a
# segment nor change a basename's junk-ness the way the collapses above do.
# Because it IS still a way for two entries to claim one stored path
# (``assets\x`` and ``assets/x``), that collision is DETECTED and refused rather
# than resolved by order.
#
# A ``./``-prefixed archive — what ``bsdtar -a -cf bundle.zip -C <dir> .`` writes
# for every member, plus a bare ``./`` for the root — is therefore refused, and
# that is deliberate rather than a cost being absorbed. Measured over the real
# exports on hand (777, 777, 868 and 872 entries): ZERO non-canonical entries — no
# leading ``./``, no ``//``, no backslash, no ``.`` segment — every entry of all
# four classified as a storable file. The ``./`` prefix is an artifact of
# re-archiving an unpacked bundle with a tar-family tool, not of the product's
# export, so the refusal costs no real bundle; and it names the re-archive as the
# likely cause so a user who hit it can fix it.
# ---------------------------------------------------------------------------

#: Spellings that are NOT the plain relative form of the file they name. Each
#: refuses the whole bundle: this importer validates, it does not launder. The
#: ``.``-suffixed entries are the laundering route itself — ``assets/innocent/.``
#: must never arrive as the FILE ``assets/innocent``.
NON_CANONICAL_ARCNAMES = [
    "./assets/logo2.svg",
    "assets/./logo2.svg",
    "assets//logo2.svg",
    "./assets/./sub//logo2.svg",
    "./templates/corporate/.thumbnail",
    ".",
    "./",
    "assets/.",
    "assets/./",
    "assets//",
    "assets/innocent/.",
    "fonts/x/.",
    "templates/x/.",
]

#: ``(raw arcname, stored path)`` for the ONE tolerated fold. Folding cannot
#: erase a segment or change a basename, so it launders nothing past a later
#: rule — which is what separates it from the collapses refused above.
BACKSLASH_ARCNAMES = [
    ("assets\\logo2.svg", "assets/logo2.svg"),
    ("assets\\sub\\logo2.svg", "assets/sub/logo2.svg"),
    ("templates\\corporate\\.thumbnail", "templates/corporate/.thumbnail"),
]

#: Directory markers naming a legitimate path. Never stored, and never refused —
#: a real archive carries them, and the path a marker names is canonical.
DIRECTORY_ARCNAMES = ["assets/", "assets/sub/", "assets\\sub\\"]

#: Shapes that change WHICH FILE the path names. Refused outright — and the whole
#: bundle with them, because an archive containing one is not a bundle we can
#: interpret. A directory marker gets no exemption: ``../evil/`` names a
#: directory outside the bundle.
UNSAFE_ARCNAMES = [
    "..",
    "../evil.png",
    "../evil/",
    "assets/..",
    "assets/../evil.png",
    "assets/../../evil.png",
    "templates/x/../../../.thumbnail",
    "/etc/passwd",
    "/etc/templates/corporate/.thumbnail",
    "/abs/dir/",
    "C:/Windows/x",
    "C:\\Windows\\x",
    "//server/share/x",
    "..\\evil.png",
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

#: Pairs of DISTINCT arcnames that are each individually ACCEPTABLE yet claim ONE
#: stored path, by way of the tolerated ``\`` fold. Whichever of the two the
#: archive happens to list first would otherwise decide the stored bytes. These
#: are the collisions strict validation cannot reach — refusing non-canonical
#: shapes does nothing about them, which is why the collision check is separate.
FOLD_COLLIDING_ARCNAME_PAIRS = [
    ("assets/mixed.svg", "assets\\mixed.svg"),
    ("assets/sub/mixed.svg", "assets\\sub\\mixed.svg"),
    ("templates/x/.thumbnail", "templates\\x\\.thumbnail"),
]

#: Bytes that differ between the two members of a colliding pair, so "which entry
#: won" is directly readable from what got stored.
COLLIDING_FIRST_BYTES = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1">'
    b"<!--FIRST-MEMBER--></svg>"
)
COLLIDING_SECOND_BYTES = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="2" height="2">'
    b"<!--SECOND-MEMBER--></svg>"
)


@contextlib.contextmanager
def _isolated_session():
    """A private, empty database per import.

    The order-independence tests below import the SAME bundle name twice and must
    not have the second import see the first one's rows — a 409 name conflict
    would look exactly like the refusal they are trying to measure.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    with Session(engine) as isolated:
        yield isolated
    engine.dispose()


def _import_outcome(files):
    """``("refused", message)`` or ``("stored", [(stored_path, bytes), ...])``.

    Keyed on the STORED PATH — which is what a collision is about — and carrying the
    BYTES, so a test that compares two member orderings fails with the differing
    content in its message rather than with an opaque boolean.
    """
    from src.services.design_system_service import DesignSystemImportError, import_bundle

    with _isolated_session() as isolated:
        try:
            ds = import_bundle(
                isolated, zip_bytes=make_bundle_zip(files=files), user="u"
            )
        except DesignSystemImportError as exc:
            return "refused", str(exc)
        stored = [
            (f.path, bytes(f.data if f.data is not None else f.asset.data))
            for f in ds.files
        ]
        return "stored", sorted(stored)


class TestNonCanonicalShapesRefuseTheWholeBundle:
    """A non-canonical spelling refuses the bundle; it is never rewritten into an
    acceptable one. Normalizing first is what let an entry reach storage under a
    name that was not its own, so the fix is to validate and stop."""

    @pytest.mark.parametrize("arcname", NON_CANONICAL_ARCNAMES, ids=repr)
    def test_refused(self, session, arcname):
        from src.services.design_system_service import DesignSystemImportError, import_bundle

        files = {
            "assets/logo.svg": SVG_LOGO,
            "README.md": SYNTHETIC_README,
            arcname: webp_bytes(),
        }
        with pytest.raises(DesignSystemImportError) as exc:
            import_bundle(session, zip_bytes=make_bundle_zip(files=files), user="u")
        assert "unsafe" in str(exc.value).lower()

    @pytest.mark.parametrize("arcname", NON_CANONICAL_ARCNAMES, ids=repr)
    def test_nothing_at_all_reaches_storage(self, arcname):
        """Refusal is what makes "not stored under a rewritten name" structural
        rather than a property of whichever rule happens to run first: the import
        aborts before a single row is created."""
        verdict, detail = _import_outcome(
            {
                "assets/logo.svg": SVG_LOGO,
                "README.md": SYNTHETIC_README,
                arcname: webp_bytes(),
            }
        )
        assert verdict == "refused", (
            f"{arcname!r} is not a canonical path but the import succeeded and "
            f"stored {detail!r}"
        )


class TestTrailingDotIsNeverStoredAsItsParentName:
    """``assets/innocent/.`` must NEVER end up stored as ``assets/innocent``.

    This is the exact laundering the strict rule exists to prevent: normalizing
    before the junk/dotfile decision dropped the ``.`` basename, and the entry was
    stored under its parent's name. Pinned on the import path AND on the database,
    because "the returned object has no such row" would still pass if the row were
    written and then not attached.
    """

    ARCNAME = "assets/innocent/."
    SECRET = b"SECRET=should-never-be-stored"

    def _files(self):
        return {
            "assets/logo.svg": SVG_LOGO,
            "README.md": SYNTHETIC_README,
            self.ARCNAME: self.SECRET,
        }

    def test_the_bundle_is_refused_and_names_the_entry(self, session):
        from src.services.design_system_service import DesignSystemImportError, import_bundle

        with pytest.raises(DesignSystemImportError) as exc:
            import_bundle(
                session, zip_bytes=make_bundle_zip(files=self._files()), user="u"
            )
        assert repr(self.ARCNAME) in str(exc.value)

    def test_no_row_exists_at_the_parent_path_afterwards(self):
        from src.database.models.design_system import DesignSystemFile
        from src.services.design_system_service import DesignSystemImportError, import_bundle

        with _isolated_session() as isolated:
            with pytest.raises(DesignSystemImportError):
                import_bundle(
                    isolated, zip_bytes=make_bundle_zip(files=self._files()), user="u"
                )
            isolated.rollback()
            stored = [
                f.path
                for f in isolated.query(DesignSystemFile).all()
            ]
            assert stored == [], f"a refused bundle still stored {stored!r}"


class TestBackslashSeparatorsAreFolded:
    """The ONE tolerance f83fc2e kept, kept unchanged: a Windows zip writes ``\\``
    as its separator, and folding it can neither erase a segment nor change a
    basename — so it cannot launder anything past a later rule."""

    @pytest.mark.parametrize("raw,stored", BACKSLASH_ARCNAMES, ids=lambda v: repr(v))
    def test_stored_under_the_forward_slash_spelling(self, session, raw, stored):
        from src.services.design_system_service import import_bundle

        payload = webp_bytes() if stored.endswith(".thumbnail") else SVG_LOGO
        files = {
            "assets/logo.svg": SVG_LOGO,
            "README.md": SYNTHETIC_README,
            raw: payload,
        }
        ds = import_bundle(session, zip_bytes=make_bundle_zip(files=files), user="u")
        paths = {f.path for f in ds.files}
        assert stored in paths, f"{raw!r} did not reach storage as {stored!r}"
        assert raw not in paths

    def test_a_dotfile_reached_through_a_backslash_path_is_still_a_dotfile(
        self, session
    ):
        """The fold happens before the junk/dotfile decision, so that decision must
        still see the dot: ``assets\\.npmrc`` is a dotfile, not brand content."""
        from src.services.design_system_service import import_bundle

        files = {
            "assets/logo.svg": SVG_LOGO,
            "README.md": SYNTHETIC_README,
            "assets\\.npmrc": b"//registry/:_authToken=nope",
            "assets\\.DS_Store": b"junk",
        }
        ds = import_bundle(session, zip_bytes=make_bundle_zip(files=files), user="u")
        paths = {f.path for f in ds.files}
        assert "assets/logo.svg" in paths  # not a vacuous pass
        assert not any(_basename(p).startswith(".") for p in paths)


class TestDirectoryMarkersAreSkippedNotRefused:
    """A directory marker is not a file and is never stored — but a real archive
    carries them, so a marker naming a canonical path must not refuse the bundle."""

    @pytest.mark.parametrize("arcname", DIRECTORY_ARCNAMES, ids=repr)
    def test_skipped_while_the_bundle_still_imports(self, session, arcname):
        from src.services.design_system_service import import_bundle

        files = {
            "assets/logo.svg": SVG_LOGO,
            "README.md": SYNTHETIC_README,
            arcname: b"",
        }
        ds = import_bundle(session, zip_bytes=make_bundle_zip(files=files), user="u")
        paths = {f.path for f in ds.files}
        assert "assets/logo.svg" in paths  # the bundle was NOT refused
        assert arcname not in paths
        named = arcname.replace("\\", "/").rstrip("/")
        assert named not in paths, (
            f"{arcname!r} names a directory but was stored as the FILE {named!r}"
        )


class TestUnsafeShapesRefuseTheWholeBundle:
    @pytest.mark.parametrize(
        "arcname", UNSAFE_ARCNAMES + CONTROL_CHAR_ARCNAMES, ids=repr
    )
    def test_refused(self, session, arcname):
        from src.services.design_system_service import DesignSystemImportError, import_bundle

        files = {"assets/logo.svg": SVG_LOGO, arcname: webp_bytes()}
        with pytest.raises(DesignSystemImportError) as exc:
            import_bundle(session, zip_bytes=make_bundle_zip(files=files), user="u")
        assert "unsafe" in str(exc.value).lower()

    @pytest.mark.parametrize(
        "arcname",
        UNSAFE_ARCNAMES + CONTROL_CHAR_ARCNAMES + NON_CANONICAL_ARCNAMES,
        ids=repr,
    )
    def test_the_refusal_is_actionable_without_reading_the_source(
        self, session, arcname
    ):
        """A refusal has to name the entry, say what is wrong with it, and say what
        to do about it. "non-canonical" alone names a category a user who has never
        seen this code cannot map to anything they can change."""
        from src.services.design_system_service import DesignSystemImportError, import_bundle

        files = {"assets/logo.svg": SVG_LOGO, arcname: webp_bytes()}
        with pytest.raises(DesignSystemImportError) as exc:
            import_bundle(session, zip_bytes=make_bundle_zip(files=files), user="u")
        message = str(exc.value)
        # WHICH entry. ``!r`` so a control character is visible rather than acted on
        # by whatever renders the message.
        assert repr(arcname) in message
        # WHAT to do about it: upload the export as-is, or re-zip with `zip -r`
        # rather than with a tar-family tool.
        lowered = message.lower()
        assert "re-create the archive" in lowered
        assert "zip -r" in lowered
        assert "export" in lowered


class TestOnePathClaimedTwiceIsRefusedNotDecidedByZipOrder:
    """Strict validation does not close identity collapse on its own.

    The tolerated ``\\`` fold is still a route to two DISTINCT entries claiming one
    stored path, and a zip may legally carry the same arcname twice. Both are
    caught by detecting the duplicate CLAIM, which covers every route rather than
    the shapes someone thought of.
    """

    @staticmethod
    def _pair_files(first, second, *, reverse=False):
        """The same two entries, carrying the SAME bytes, in either archive order.

        The payload stays bound to the arcname — swapping the bytes along with the
        order would make an order-dependent importer look order-independent, since
        whichever entry came first would always carry the same content.
        """
        payload = {first: COLLIDING_FIRST_BYTES, second: COLLIDING_SECOND_BYTES}
        files = {"assets/logo.svg": SVG_LOGO, "README.md": SYNTHETIC_README}
        for arcname in ([second, first] if reverse else [first, second]):
            files[arcname] = payload[arcname]
        return files

    @pytest.mark.parametrize(
        "first,second", FOLD_COLLIDING_ARCNAME_PAIRS, ids=lambda v: repr(v)
    )
    def test_zip_member_order_does_not_change_the_outcome(self, first, second):
        forward = _import_outcome(self._pair_files(first, second))
        reverse = _import_outcome(self._pair_files(first, second, reverse=True))
        assert forward == reverse, (
            f"reversing the zip member order of {first!r} / {second!r} changed the "
            f"outcome: forward={forward!r} reverse={reverse!r}"
        )

    @pytest.mark.parametrize(
        "first,second", FOLD_COLLIDING_ARCNAME_PAIRS, ids=lambda v: repr(v)
    )
    def test_the_pair_is_refused_rather_than_silently_deduplicated(self, first, second):
        verdict, detail = _import_outcome(self._pair_files(first, second))
        assert verdict == "refused", (
            f"{first!r} and {second!r} name one stored path, but the import "
            f"succeeded and kept {detail!r}"
        )
        assert repr(first) in detail and repr(second) in detail
        assert "re-create the archive" in detail.lower()

    def test_the_same_arcname_twice_is_refused(self):
        """A zip may legally list one name twice, and then nothing but member order
        decides which bytes a reader gets. No path rule can see this — both spellings
        are identical and canonical — so only the duplicate-claim check catches it."""
        from src.services.design_system_service import (
            DesignSystemImportError,
            import_bundle,
        )

        buf = io.BytesIO()
        with pytest.warns(UserWarning, match="Duplicate name"):
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr(MANIFEST_FILENAME, json.dumps(default_manifest()).encode())
                zf.writestr("colors_and_type.css", COLORS_AND_TYPE_CSS)
                zf.writestr("README.md", SYNTHETIC_README)
                zf.writestr("assets/mixed.svg", COLLIDING_FIRST_BYTES)
                zf.writestr("assets/mixed.svg", COLLIDING_SECOND_BYTES)

        with _isolated_session() as isolated:
            with pytest.raises(DesignSystemImportError) as exc:
                import_bundle(isolated, zip_bytes=buf.getvalue(), user="u")
        assert "assets/mixed.svg" in str(exc.value)

    def test_a_bundle_without_a_collision_still_imports(self):
        """Positive control: two entries sharing a BASENAME but canonicalizing to
        different paths are not a collision, and both are stored with their own
        bytes."""
        verdict, detail = _import_outcome(
            {
                "assets/logo.svg": SVG_LOGO,
                "README.md": SYNTHETIC_README,
                "assets/mixed.svg": COLLIDING_FIRST_BYTES,
                "assets/sub/mixed.svg": COLLIDING_SECOND_BYTES,
            }
        )
        assert verdict == "stored", detail
        stored = dict(detail)
        assert stored["assets/mixed.svg"] == COLLIDING_FIRST_BYTES
        assert stored["assets/sub/mixed.svg"] == COLLIDING_SECOND_BYTES


def _dot_rooted_members():
    """The member list ``bsdtar`` writes for an archive rooted at ``.``.

    ``bsdtar -a -cf b.zip -C <dir> .`` prefixes EVERY member with ``./`` and leads
    with a bare ``./`` for the root directory itself. That is the shape of a
    RE-ARCHIVE of an unpacked bundle, not of the product's export: measured over the
    real exports on hand (777, 777, 868 and 872 entries) not one entry is
    ``./``-prefixed, doubled-slashed, backslashed or ``.``-segmented.
    """
    return {
        "./": b"",
        "./" + MANIFEST_FILENAME: json.dumps(default_manifest()).encode(),
        "./colors_and_type.css": COLORS_AND_TYPE_CSS.encode(),
        "./README.md": SYNTHETIC_README,
        "./assets/": b"",
        "./assets/logo.svg": SVG_LOGO,
        "./fonts/": b"",
        "./fonts/acme-sans.woff2": b"OTTO synthetic-font-bytes",
        "./templates/": b"",
        "./templates/corporate/": b"",
        "./templates/corporate/index.html": SYNTHETIC_TEMPLATE_HTML,
        "./templates/corporate/.thumbnail": webp_bytes(),
    }


class TestDotRootedArchiveIsRefused:
    """A ``./``-rooted archive is refused, and the refusal explains itself.

    Accepting it would mean rewriting every entry before judging it — the
    laundering ``assets/innocent/.`` exploited — so the shape is turned away
    instead. The cost is bounded and was measured: no real export carries the
    shape, it only appears when someone re-archives an unpacked bundle with a
    tar-family tool, and the message says exactly that.
    """

    def _dot_rooted_zip(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for arcname, payload in _dot_rooted_members().items():
                zf.writestr(arcname, payload)
        return buf.getvalue()

    def test_a_dot_rooted_bundle_is_refused(self, session):
        """The member SHAPE, built with ``zipfile`` so the property is pinned even
        where ``bsdtar`` is not installed."""
        from src.services.design_system_service import DesignSystemImportError, import_bundle

        with pytest.raises(DesignSystemImportError) as exc:
            import_bundle(session, zip_bytes=self._dot_rooted_zip(), user="u")
        assert "unsafe" in str(exc.value).lower()

    def test_the_refusal_points_at_the_re_archive_that_caused_it(self, session):
        """A user who re-zipped with ``bsdtar`` has to be able to tell, from the
        message alone, that the archiver is the problem and what to do instead."""
        from src.services.design_system_service import DesignSystemImportError, import_bundle

        with pytest.raises(DesignSystemImportError) as exc:
            import_bundle(session, zip_bytes=self._dot_rooted_zip(), user="u")
        message = str(exc.value).lower()
        assert "zip -r" in message
        assert "export" in message
        assert "bsdtar" in message

    def test_a_real_bsdtar_archive_is_refused(self, session, tmp_path):
        """The same shape from the actual tool, so the fixture above cannot drift
        away from what ``bsdtar`` really writes."""
        from src.services.design_system_service import DesignSystemImportError, import_bundle

        bsdtar = shutil.which("bsdtar") or (
            "/usr/bin/bsdtar" if os.path.exists("/usr/bin/bsdtar") else None
        )
        if bsdtar is None:
            pytest.skip("bsdtar (libarchive) is not installed on this machine")

        tree = tmp_path / "bundle"
        for arcname, payload in _dot_rooted_members().items():
            if arcname.endswith("/"):
                continue
            target = tree / arcname[2:]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)

        archive = tmp_path / "bundle.zip"
        subprocess.run(
            [bsdtar, "-a", "-cf", str(archive), "-C", str(tree), "."], check=True
        )
        members = zipfile.ZipFile(archive).namelist()
        # Guard the guard: if a future bsdtar stops emitting './' this test would
        # otherwise silently stop testing the thing it exists for.
        assert all(m.startswith("./") for m in members), members
        assert "./" in members

        with pytest.raises(DesignSystemImportError) as exc:
            import_bundle(session, zip_bytes=archive.read_bytes(), user="u")
        assert "unsafe" in str(exc.value).lower()

    def test_the_same_tree_re_zipped_with_zip_r_imports(self, session, tmp_path):
        """The positive control that makes the refusal above a statement about the
        ARCHIVER rather than about the bundle: the identical file tree, zipped the
        way the refusal message tells the user to, imports with its thumbnail."""
        from src.services.design_system_service import import_bundle

        zip_cmd = shutil.which("zip")
        if zip_cmd is None:
            pytest.skip("the 'zip' CLI is not installed on this machine")

        tree = tmp_path / "bundle"
        for arcname, payload in _dot_rooted_members().items():
            if arcname.endswith("/"):
                continue
            target = tree / arcname[2:]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)

        archive = tmp_path / "bundle.zip"
        subprocess.run(
            [zip_cmd, "-r", "-q", str(archive), "."], cwd=str(tree), check=True
        )
        members = zipfile.ZipFile(archive).namelist()
        assert not any(m.startswith("./") for m in members), members

        ds = import_bundle(session, zip_bytes=archive.read_bytes(), user="u")
        paths = {f.path for f in ds.files}
        assert "assets/logo.svg" in paths
        assert "fonts/acme-sans.woff2" in paths
        assert "templates/corporate/.thumbnail" in paths
        assert ds.tokens, "the re-zipped bundle must still yield its tokens"


# ---------------------------------------------------------------------------
# The two gates must reach the SAME verdict — measured as DIVERGENCE
# ---------------------------------------------------------------------------
#
# The regression this suite exists for was a DISAGREEMENT between the up-front
# whole-bundle scan and the per-entry iterator: the scan refused
# ``assets/innocent/.`` on its raw basename while the iterator accepted the same
# entry on its normalized one, and the permissive gate was the one that reached
# storage.
#
# A test that feeds both gates only shapes both REFUSE cannot see that class of
# defect — it passes whatever the gates do on everything else. So the corpus below
# is generated to straddle every rule, and a companion test asserts the corpus
# really does land on all three verdicts, which is what keeps the agreement test
# from going vacuous.
#
# NOTE ON WHAT THIS DOES AND DOES NOT PIN: it pins AGREEMENT across a broad
# corpus, which is the property the regression violated. It does not pin that the
# two gates SHARE one classifier function — two independent implementations that
# happen to agree on every shape here would pass. Sharing one classifier is a
# maintainability property (a new rule cannot be added to one gate and forgotten
# in the other), not a behaviourally-pinned one, and it is not honest to claim a
# test enforces it.
# ---------------------------------------------------------------------------


def _gate_corpus():
    """Path shapes straddling every rule the classifier applies.

    Generated rather than listed so the corpus cannot quietly shrink to only the
    shapes that were on someone's mind.
    """
    heads = ["", "./", ".//", "/", "C:/", "../", ".\\"]
    middles = [
        "assets/",
        "assets/./",
        "assets//",
        "assets/../",
        "assets\\",
        "fonts/",
        "templates/x/",
        "",
    ]
    tails = ["logo.svg", ".thumbnail", ".env", "preview.png", "", ".", ".."]
    shapes = {
        head + middle + tail
        for head in heads
        for middle in middles
        for tail in tails
    }
    return sorted(shapes - {""})


class TestBothGatesReachTheSameVerdict:
    @staticmethod
    def _verdicts(arcname):
        """``(scan_refused, iterator_verdict)`` for one arcname, from the real gates."""
        from src.services.design_system_service import (
            DesignSystemImportError,
            _assert_bundle_paths_safe,
            _iter_safe_entries,
        )

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(arcname, webp_bytes())
        raw = buf.getvalue()
        # zipfile truncates an arcname at a NUL and rejects nothing else, so read
        # back what the archive ACTUALLY contains rather than what we asked for.
        stored_name = zipfile.ZipFile(io.BytesIO(raw)).namelist()[0]

        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            try:
                _assert_bundle_paths_safe(zf)
                scan_refused = False
            except DesignSystemImportError:
                scan_refused = True
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            try:
                yielded = [rel for _, rel in _iter_safe_entries(zf, "")]
                iterator = ("stored", yielded[0]) if yielded else ("skipped", None)
            except DesignSystemImportError:
                iterator = ("refused", None)
        return stored_name, scan_refused, iterator

    def test_no_shape_in_the_corpus_makes_the_gates_disagree(self):
        divergences = []
        for arcname in _gate_corpus():
            stored_name, scan_refused, iterator = self._verdicts(arcname)
            if scan_refused != (iterator[0] == "refused"):
                divergences.append(
                    {
                        "arcname": stored_name,
                        "scan_refused": scan_refused,
                        "iterator": iterator[0],
                    }
                )
        assert divergences == [], (
            f"the two gates disagree on {len(divergences)} shapes: {divergences}"
        )

    def test_the_corpus_lands_on_all_three_verdicts(self):
        """Keeps the agreement test above from passing vacuously. If every shape in
        the corpus were refused, agreement would be trivial and the test would not
        detect the divergence it exists to detect."""
        seen = {"refused": 0, "skipped": 0, "stored": 0}
        for arcname in _gate_corpus():
            _, _, iterator = self._verdicts(arcname)
            seen[iterator[0]] += 1
        assert all(count > 0 for count in seen.values()), seen

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

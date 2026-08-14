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
import struct
import subprocess
import zipfile
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import src.database.models  # noqa: F401 - register models with Base.metadata
from src.core.database import Base
from src.database.models.design_system import DesignSystem
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
    make_zip64_header_offset_archive,
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

#: Backslash-separated names. REFUSED — this was the last surviving rewrite in the
#: validator, and it was not free. ``\`` is not a separator in a .zip at all, so a
#: fold is an interpretation; meanwhile root discovery and the ``startswith``
#: scoping match RAW names, so the folded and raw forms disagreed about which entry
#: a path was (see TestBackslashUnderAWrappedRootIsNotSilentlyDropped). Measured,
#: the fold bought nothing: 0 backslash entries across all four real exports.
BACKSLASH_ARCNAMES = [
    "assets\\logo2.svg",
    "assets\\sub\\logo2.svg",
    "templates\\corporate\\.thumbnail",
    "assets\\sub\\",
    "assets\\.npmrc",
    "assets/mixed\\x.svg",
]

#: Directory markers naming a legitimate path. Never stored, and never refused —
#: a real archive carries them, and the path a marker names is canonical.
DIRECTORY_ARCNAMES = ["assets/", "assets/sub/"]

#: Characters that can never appear in a bundle path. ``U+0085`` and the rest of the
#: C1 range were accepted by an ``ord(ch) < 0x20 or ord(ch) == 0x7F`` test, which is
#: C0 + DEL only; ``U+202E`` makes a name RENDER as a different one than it is.
FORBIDDEN_CHARACTER_ARCNAMES = [
    "assets/logo\x85.svg",       # NEL - C1, and a line break to several parsers
    "assets/logo\x80.svg",       # first C1 code point
    "assets/logo\x9f.svg",       # last C1 code point
    "assets/logo\u202egnp.svg",  # RTL OVERRIDE - renders as though it ended ".svg"
    "assets/logo\u200f.svg",     # RIGHT-TO-LEFT MARK
    "assets/logo\u061c.svg",     # ARABIC LETTER MARK - the omission that shipped
    "assets/logo\u2066.svg",     # LEFT-TO-RIGHT ISOLATE
    "templates/x/.thumbnail\x85",
]

#: Category-Cf characters that are NOT refused, deliberately: they occur in
#: legitimate filenames in Persian, Arabic and Indic scripts and carry no
#: display-spoofing power, so refusing all of Cf would fail a real bundle to
#: close nothing.
PERMITTED_FORMAT_CHARACTER_ARCNAMES = [
    "assets/logo\u200c.svg",  # ZERO WIDTH NON-JOINER
    "assets/logo\u200d.svg",  # ZERO WIDTH JOINER
    "assets/logo\u00ad.svg",  # SOFT HYPHEN
]

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

#: Arcnames that claim one stored path WITHOUT any path rule being able to see it.
#: Now that no rewrite is left in the validator, the only remaining route to a
#: collision is a zip carrying the same name twice — both spellings identical, both
#: perfectly canonical, and only member order deciding which bytes a reader gets.
DUPLICATE_CLAIM_ARCNAMES = [
    "assets/mixed.svg",
    "templates/x/.thumbnail",
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


class TestBackslashSeparatorsAreRefused:
    """``\\`` is refused outright — the LAST rewrite removed from the validator.

    A zip has exactly one separator, ``/``. Folding ``\\`` into it is an
    interpretation, and it was the one remaining place where the string validation
    judged differed from the string the rest of the importer used.
    """

    @pytest.mark.parametrize("arcname", BACKSLASH_ARCNAMES, ids=repr)
    def test_refused(self, session, arcname):
        from src.services.design_system_service import DesignSystemImportError, import_bundle

        files = {
            "assets/logo.svg": SVG_LOGO,
            "README.md": SYNTHETIC_README,
            arcname: webp_bytes(),
        }
        with pytest.raises(DesignSystemImportError) as exc:
            import_bundle(session, zip_bytes=make_bundle_zip(files=files), user="u")
        message = str(exc.value)
        assert repr(arcname) in message
        # The reason names the separator, not a generic "non-canonical".
        assert "separator" in message.lower()

    def test_no_backslash_entry_reaches_storage_under_any_spelling(self, session):
        from src.services.design_system_service import DesignSystemImportError, import_bundle

        files = {
            "assets/logo.svg": SVG_LOGO,
            "README.md": SYNTHETIC_README,
            "assets\\logo2.svg": SVG_LOGO,
        }
        with pytest.raises(DesignSystemImportError):
            import_bundle(session, zip_bytes=make_bundle_zip(files=files), user="u")


class TestBackslashUnderAWrappedRootIsNotSilentlyDropped:
    """The concrete bug the fold caused, pinned.

    Root discovery and the in-scope check match RAW names, but classification folded
    first. In a bundle wrapped in ``safe/``, ``safe\\templates\\x\\.thumbnail`` folded
    to the same logical path as ``safe/templates/x/.thumbnail`` — yet failed the raw
    ``startswith("safe/")`` test, so it was SKIPPED rather than colliding with its
    twin. Measured before the fix: the import SUCCEEDED, the 99x99 thumbnail vanished
    without a word, and the collision check was never reached. An entry that should
    refuse the bundle must never be silently dropped instead.
    """

    #: The entry that used to vanish: a backslash twin of a wrapped thumbnail.
    BACKSLASH_TWIN = "safe\\templates\\x\\.thumbnail"

    @staticmethod
    def _wrapped_zip():
        manifest = default_manifest()
        manifest["templates"] = [
            {
                "name": "X",
                "description": "Synthetic layout.",
                "folder": "templates/x",
                "entryPath": "templates/x/index.html",
            }
        ]
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("safe/" + MANIFEST_FILENAME, json.dumps(manifest).encode())
            zf.writestr("safe/colors_and_type.css", COLORS_AND_TYPE_CSS)
            zf.writestr("safe/README.md", SYNTHETIC_README)
            zf.writestr("safe/assets/logo.svg", SVG_LOGO)
            zf.writestr("safe/templates/x/index.html", SYNTHETIC_TEMPLATE_HTML)
            zf.writestr("safe/templates/x/.thumbnail", webp_bytes(10, 6))
            zf.writestr(
                TestBackslashUnderAWrappedRootIsNotSilentlyDropped.BACKSLASH_TWIN,
                webp_bytes(99, 99),
            )
        return buf.getvalue()

    def test_the_bundle_is_refused_rather_than_quietly_losing_the_entry(self):
        from src.services.design_system_service import DesignSystemImportError, import_bundle

        with _isolated_session() as isolated:
            with pytest.raises(DesignSystemImportError) as exc:
                import_bundle(isolated, zip_bytes=self._wrapped_zip(), user="u")
        message = str(exc.value)
        # The refusal names the offending entry — the one that used to disappear.
        assert repr(self.BACKSLASH_TWIN) in message
        assert "separator" in message.lower()

    def test_before_the_fix_this_entry_was_dropped_without_a_word(self):
        """States what the old behaviour WAS, so the regression this pins is legible:
        the 99x99 twin was skipped, the 10x6 one stored, the import reported success,
        and the collision check never ran. Anything other than a refusal — storing
        either thumbnail, or succeeding with a warning — fails here."""
        from src.services.design_system_service import DesignSystemImportError, import_bundle

        with _isolated_session() as isolated:
            with pytest.raises(DesignSystemImportError):
                import_bundle(isolated, zip_bytes=self._wrapped_zip(), user="u")
            isolated.rollback()
            from src.database.models.design_system import DesignSystemAsset

            assert isolated.query(DesignSystemAsset).all() == []

    def test_the_forward_slash_twin_alone_still_imports(self):
        """Positive control: the wrapped bundle without the backslash entry imports
        and keeps its thumbnail, so the refusal is about the backslash and the
        root-prefix stripping still works."""
        from src.services.design_system_service import import_bundle

        raw = self._wrapped_zip()
        buf = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(raw)) as src:
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as out:
                for info in src.infolist():
                    if "\\" in info.filename:
                        continue
                    out.writestr(info.filename, src.read(info.filename))
        with _isolated_session() as isolated:
            ds = import_bundle(isolated, zip_bytes=buf.getvalue(), user="u")
            paths = {f.path for f in ds.files}
            assert "templates/x/.thumbnail" in paths
            assert "assets/logo.svg" in paths
            shots = [a for a in ds.assets if a.kind == "template_shot"]
            assert [(a.width, a.height) for a in shots] == [(10, 6)]


class TestSkippedDotfilesAreReportedNotSilent:
    """A non-allowlisted dotfile is SKIPPED and the user is TOLD.

    A DELIBERATE, DOCUMENTED DEVIATION from the acceptance battery's B8 wording,
    which lists dotfiles among the shapes to refuse. The tradeoff, on measured
    evidence: the real export ships FOUR dotfiles and all four are ``.thumbnail``
    files, so wholesale dotfile refusal is untested against any real bundle — while
    ``.DS_Store`` is created invisibly and ubiquitously by macOS Finder, so refusing
    would fail a user's upload over a file they cannot see they have. Skipping is
    already safe (a dotfile is never stored); the only gap was that the user was not
    TOLD, and a non-fatal warning closes exactly that gap. Do not "fix" this into a
    refusal without new evidence about real bundles.
    """

    DOTFILES = {
        "assets/.DS_Store": b"macos junk",
        "assets/.env": b"SECRET=should-never-be-stored",
        ".npmrc": b"//registry/:_authToken=nope",
    }

    def _import(self, session):
        from src.services.design_system_service import BundleImportWarning, import_bundle

        files = {"assets/logo.svg": SVG_LOGO, "README.md": SYNTHETIC_README}
        files.update(self.DOTFILES)
        collected: list[BundleImportWarning] = []
        ds = import_bundle(
            session,
            zip_bytes=make_bundle_zip(files=files),
            user="u",
            warnings=collected,
        )
        return ds, collected

    def test_the_bundle_imports_and_no_dotfile_is_stored(self, session):
        ds, _ = self._import(session)
        paths = {f.path for f in ds.files}
        assert "assets/logo.svg" in paths  # not a vacuous pass
        assert not any(_basename(p).startswith(".") for p in paths)
        assert not any(
            bytes(a.data) == self.DOTFILES["assets/.env"] for a in ds.assets
        )

    def test_every_skipped_dotfile_is_named_in_a_warning(self, session):
        _, collected = self._import(session)
        assert {w.path for w in collected} == set(self.DOTFILES), (
            f"skipped dotfiles were not all reported: {[w.path for w in collected]}"
        )

    def test_the_warning_says_why_and_that_the_import_continued(self, session):
        _, collected = self._import(session)
        reason = next(w.reason for w in collected if w.path == "assets/.DS_Store")
        assert "dot-prefixed" in reason
        assert "ignored" in reason

    def test_an_allowlisted_thumbnail_is_not_warned_about(self, session):
        """Positive control: the ONE dot-prefixed shape that IS stored must not be
        reported as skipped, or every real bundle would warn about its thumbnails."""
        from src.services.design_system_service import BundleImportWarning, import_bundle

        manifest = default_manifest()
        manifest["templates"] = [
            {
                "name": "X",
                "description": "Synthetic layout.",
                "folder": "templates/x",
                "entryPath": "templates/x/index.html",
            }
        ]
        files = {
            "assets/logo.svg": SVG_LOGO,
            "README.md": SYNTHETIC_README,
            "templates/x/index.html": SYNTHETIC_TEMPLATE_HTML,
            "templates/x/.thumbnail": webp_bytes(),
        }
        collected: list[BundleImportWarning] = []
        ds = import_bundle(
            session,
            zip_bytes=make_bundle_zip(manifest=manifest, files=files),
            user="u",
            warnings=collected,
        )
        assert "templates/x/.thumbnail" in {f.path for f in ds.files}
        assert collected == []

    def test_directory_markers_do_not_produce_warnings(self, session):
        """Skips with no user-actionable content stay silent: a real archive carries
        one directory marker per folder, and warning about each would bury the
        dotfile warnings that matter."""
        from src.services.design_system_service import BundleImportWarning, import_bundle

        files = {
            "assets/logo.svg": SVG_LOGO,
            "README.md": SYNTHETIC_README,
            "assets/": b"",
            "assets/sub/": b"",
        }
        collected: list[BundleImportWarning] = []
        import_bundle(
            session,
            zip_bytes=make_bundle_zip(files=files),
            user="u",
            warnings=collected,
        )
        assert collected == []


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


#: ``(arcname, a phrase that must appear in the stated reason)``. Checking that a
#: refusal merely mentions the entry and offers generic advice does not check the
#: part a user actually reads to understand WHY — and a stated reason can be plainly
#: untrue while every such test passes. ``'..'`` is the case in point: the message
#: used to claim a parent-directory segment "would place the file outside the
#: bundle", which is false for ``assets/../logo.svg`` — it resolves back inside.
REFUSAL_REASON_PHRASES = [
    ("assets/../logo.svg", "resolving the path"),
    ("../evil.png", "resolving the path"),
    ("/etc/passwd", "absolute path"),
    ("C:/Windows/x", "drive letter"),
    ("C:\\Windows\\x", "drive letter"),
    ("assets\\logo.svg", "separator"),
    ("./assets/logo.svg", "leading './'"),
    ("assets//logo.svg", "empty segment"),
    ("assets/innocent/.", "'.' (current-directory) segment"),
    ("templates/x/.thumbnail\n", "control character"),
    ("assets/logo\x85.svg", "control character"),
    ("assets/logo\u202egnp.svg", "bidirectional text control"),
]


class TestTheStatedReasonIsTrue:
    """A refusal's REASON has to be accurate, not merely present.

    ``assets/../logo.svg`` resolves back INSIDE the bundle, so "would place the file
    outside the bundle" was simply false — and no test noticed, because the
    actionability test only checked that the message named the entry and offered
    advice. Refusal is still right; the reason now states the true defect (which file
    the name refers to can only be worked out by resolving it).
    """

    @pytest.mark.parametrize("arcname,phrase", REFUSAL_REASON_PHRASES, ids=lambda v: repr(v))
    def test_the_reason_names_the_actual_defect(self, session, arcname, phrase):
        from src.services.design_system_service import DesignSystemImportError, import_bundle

        files = {"assets/logo.svg": SVG_LOGO, arcname: webp_bytes()}
        with pytest.raises(DesignSystemImportError) as exc:
            import_bundle(session, zip_bytes=make_bundle_zip(files=files), user="u")
        assert phrase in str(exc.value), (
            f"the refusal for {arcname!r} does not state the real reason: {exc.value}"
        )

    def test_a_traversal_that_stays_inside_the_bundle_is_not_described_as_escaping(
        self, session
    ):
        """The specific inaccuracy, pinned so it cannot come back: this path does NOT
        escape the bundle, so the message must not say it does."""
        from src.services.design_system_service import DesignSystemImportError, import_bundle

        files = {"assets/logo.svg": SVG_LOGO, "assets/../logo2.svg": webp_bytes()}
        with pytest.raises(DesignSystemImportError) as exc:
            import_bundle(session, zip_bytes=make_bundle_zip(files=files), user="u")
        reason = str(exc.value).split(". ")[0]
        assert "would place the file outside the bundle" not in reason

    def test_a_name_mismatch_with_no_nul_is_not_blamed_on_nul_truncation(self):
        """The reason for ``orig_filename != filename`` used to attribute EVERY such
        case to NUL truncation, which a Unicode Path extra field falsifies: central
        ``assets/cafe.svg`` plus a record declaring ``assets/caf\\u00e9.svg`` makes the
        two names differ with no NUL anywhere. Refusal is the right identity policy;
        the reason has to describe the identity conflict generically rather than name a
        cause this entry does not have.
        """
        from src.services.design_system_service import DesignSystemImportError, import_bundle

        central = "assets/cafe.svg"
        zip_bytes = _bundle_with_extra_field(
            central,
            _unicode_path_extra(central, "assets/café.svg"),
            SVG_LOGO,
        )
        with _isolated_session() as isolated:
            with pytest.raises(DesignSystemImportError) as exc:
                import_bundle(isolated, zip_bytes=zip_bytes, user="u")
        message = str(exc.value)
        # The stdlib DID rewrite the name here, with no NUL involved — which is exactly
        # why the reason may not present NUL truncation as the explanation.
        assert "does not match the name the zip reader resolves" in message
        assert "TWO identities" in message
        # Still actionable, like every other path refusal.
        assert "re-create the archive" in message.lower()


class TestForbiddenCharactersAreRefused:
    """Character classes that must never appear in a stored path.

    The previous test was ``ord(ch) < 0x20 or ord(ch) == 0x7F`` — C0 plus DEL — which
    let the ENTIRE C1 range through, ``U+0085`` (NEL) included. Bidi controls are
    refused for a different reason: they make a name RENDER as a different name than
    it is, and these paths are shown back to users in the file browser.
    """

    @pytest.mark.parametrize("arcname", FORBIDDEN_CHARACTER_ARCNAMES, ids=repr)
    def test_refused(self, session, arcname):
        from src.services.design_system_service import DesignSystemImportError, import_bundle

        files = {"assets/logo.svg": SVG_LOGO, arcname: webp_bytes()}
        with pytest.raises(DesignSystemImportError) as exc:
            import_bundle(session, zip_bytes=make_bundle_zip(files=files), user="u")
        assert "unsafe" in str(exc.value).lower()

    @pytest.mark.parametrize("arcname", FORBIDDEN_CHARACTER_ARCNAMES, ids=repr)
    def test_nothing_is_stored(self, arcname):
        verdict, detail = _import_outcome(
            {
                "assets/logo.svg": SVG_LOGO,
                "README.md": SYNTHETIC_README,
                arcname: webp_bytes(),
            }
        )
        assert verdict == "refused", f"{arcname!r} was stored: {detail!r}"

    def test_an_unpaired_surrogate_is_refused(self):
        """Not reachable through a real zip, but the validator is also called on
        manifest-declared paths, which are arbitrary JSON strings."""
        from src.services.design_system_service import _safe_relpath

        assert _safe_relpath("assets/logo\ud800.svg") is None

    def test_the_refused_set_is_exactly_unicodes_bidi_control_property(self):
        """The whole point of deriving the set instead of hand-listing it.

        ``U+061C`` ARABIC LETTER MARK is a Unicode Bidi_Control and was MISSING from the
        hand-written list, so it was accepted while the policy said otherwise. This
        asserts, over the entire code space, that the predicate matches precisely the
        twelve characters carrying the Bidi_Control property (PropList.txt) — no
        omission and no over-capture. Nine are derived from their bidi class; if a
        future Unicode release adds another embedding-style control it is picked up
        automatically, and if it adds another implicit mark this test fails instead of
        the omission shipping.
        """
        import unicodedata

        from src.services.design_system_service import _is_bidi_control

        bidi_control = {
            0x061C, 0x200E, 0x200F,                          # implicit marks
            0x202A, 0x202B, 0x202C, 0x202D, 0x202E,          # embeddings + overrides
            0x2066, 0x2067, 0x2068, 0x2069,                  # isolates
        }
        refused = {cp for cp in range(0x110000) if _is_bidi_control(chr(cp))}
        assert refused == bidi_control, {
            "missing": sorted(hex(c) for c in bidi_control - refused),
            "over-captured": sorted(hex(c) for c in refused - bidi_control),
            "unidata_version": unicodedata.unidata_version,
        }

    @pytest.mark.parametrize(
        "code_point",
        [0x070F, 0x110BD, 0x13430],
        ids=["syriac-abbreviation-mark", "kaithi-number-sign", "egyptian-hieroglyph"],
    )
    def test_near_miss_format_characters_are_not_over_captured(self, code_point):
        """Precision, not just coverage. These are category Cf with a bidi class of L
        or AL — the same classes the implicit marks carry — so a looser derivation
        ("Cf and bidi in {L,R,AL}") would refuse all of them. They are not
        Bidi_Control and carry no spoofing power, so they must not be refused."""
        from src.services.design_system_service import _is_bidi_control

        assert _is_bidi_control(chr(code_point)) is False

    @pytest.mark.parametrize(
        "arcname", PERMITTED_FORMAT_CHARACTER_ARCNAMES, ids=repr
    )
    def test_legitimate_format_characters_are_not_refused(self, session, arcname):
        """The deliberate limit on the rule. ZWNJ/ZWJ/SOFT HYPHEN are category Cf and
        appear in real Persian, Arabic and Indic filenames; refusing all of Cf would
        fail a real bundle while closing nothing, since none of them can disguise
        what a name says."""
        from src.services.design_system_service import import_bundle

        files = {
            "assets/logo.svg": SVG_LOGO,
            "README.md": SYNTHETIC_README,
            arcname: SVG_LOGO,
        }
        ds = import_bundle(session, zip_bytes=make_bundle_zip(files=files), user="u")
        assert arcname in {f.path for f in ds.files}


def _unicode_path_extra(central_name, declared_name, *, version=1, name_crc=None):
    """A real Info-ZIP Unicode Path extra field (tag ``0x7075``).

    Layout: ``tag`` u16, ``size`` u16, ``version`` u8, ``crc32`` of the CENTRAL name
    u32, then the declared name as UTF-8. The CRC has to match the central name or
    CPython ignores the record, so it is computed here rather than faked — the point of
    these tests is a record the stdlib really acts on.
    """
    from binascii import crc32

    if name_crc is None:
        name_crc = crc32(central_name.encode("utf-8"))
    body = struct.pack("<BL", version, name_crc) + declared_name.encode("utf-8")
    return struct.pack("<HH", 0x7075, len(body)) + body


def _bundle_with_extra_field(central_name, extra, payload):
    """A complete, otherwise-valid bundle whose one extra entry carries ``extra``.

    ``ZipInfo.extra`` is written into BOTH the local header and the central directory,
    so the record is present exactly as a real archiver would emit it.

    SYMMETRY IS THE LIMIT OF THIS HELPER, and it is why the central-directory-only
    inspection went unnoticed for a round: every archive it builds carries the same
    record in both headers, so a check reading either one passes. Use
    :func:`_bundle_with_asymmetric_extra_fields` for the shapes that tell them apart.
    """
    return _bundle_with_asymmetric_extra_fields(
        central_name, local_extra=extra, central_extra=extra, payload=payload
    )


def _bundle_with_asymmetric_extra_fields(
    central_name, *, local_extra, central_extra, payload
):
    """A bundle whose entry carries DIFFERENT extra fields in its two headers.

    A .zip records every entry twice — once in the local file header that precedes its
    bytes, once in the central directory at the end — and nothing makes the two agree.
    CPython parses only the central copy, so an archive can show a clean central record
    to Python and a name-rewriting one to any reader that trusts the local header.

    Built without patching bytes: ``ZipFile`` emits the local header during
    ``writestr`` and the central directory at ``close``, both reading ``zinfo.extra``
    when they run. Mutating the attribute between the two therefore hands each header
    its own record, with all lengths and offsets computed by ``zipfile`` itself.
    """
    manifest = default_manifest()
    manifest["templates"] = [
        {
            "name": "X",
            "description": "Synthetic layout.",
            "folder": "templates/x",
            "entryPath": "templates/x/index.html",
        }
    ]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(MANIFEST_FILENAME, json.dumps(manifest).encode())
        zf.writestr("colors_and_type.css", COLORS_AND_TYPE_CSS)
        zf.writestr("README.md", SYNTHETIC_README)
        zf.writestr("assets/logo.svg", SVG_LOGO)
        zf.writestr("templates/x/index.html", SYNTHETIC_TEMPLATE_HTML)
        info = zipfile.ZipInfo(central_name)
        info.extra = local_extra
        zf.writestr(info, payload)
        # Written by ``_write_end_record`` at close, from this same object.
        info.extra = central_extra
    return buf.getvalue()


def _local_header_of(raw, central_name):
    """``(offset, name_bytes, extra_bytes)`` of ``central_name``'s LOCAL file header.

    Parsed from the archive bytes the way a non-CPython unzip would, so the tests
    assert on what the local header REALLY says rather than on what was intended.
    """
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        info = next(i for i in zf.infolist() if i.filename == central_name)
    offset = info.header_offset
    header = raw[offset : offset + 30]
    assert header[:4] == b"PK\x03\x04", "not a local file header"
    name_len, extra_len = struct.unpack_from("<HH", header, 26)
    name_at = offset + 30
    extra_at = name_at + name_len
    return offset, raw[name_at:extra_at], raw[extra_at : extra_at + extra_len]


class TestUnicodePathExtraFieldCannotRewriteAName:
    """A ``0x7075`` extra field declares a name for an entry OTHER than the central
    directory's — and CPython acts on it.

    ``ZipInfo._decodeExtra`` runs ``self.filename = _sanitize_filename(declared)`` for
    this record and never touches ``orig_filename``. So the NUL bypass comes straight
    back in a form the "recorded name == read name" invariant cannot see: put the CLEAN
    name ``templates/x/.thumbnail`` in the central directory and the NUL-bearing
    ``templates/x/.thumbnail\\x00.exe`` in the extra field, and the sanitizer strips the
    NUL back out, leaving ``orig_filename == filename`` and the invariant satisfied.

    The guard therefore parses the RAW extra bytes rather than trusting any
    stdlib-processed attribute — which is the whole premise of this commit series
    applied one layer further down.
    """

    CENTRAL = "templates/x/.thumbnail"
    DECLARED_NUL = "templates/x/.thumbnail\x00.exe"

    def _zip(self, declared=None, *, extra=None, central=None, payload=None):
        central = self.CENTRAL if central is None else central
        if extra is None:
            extra = _unicode_path_extra(
                central, self.DECLARED_NUL if declared is None else declared
            )
        return _bundle_with_extra_field(
            central, extra, webp_bytes() if payload is None else payload
        )

    def test_the_stdlib_really_does_act_on_the_record_and_hide_it(self):
        """Guard the guard. If CPython stopped honouring ``0x7075``, or stopped
        sanitizing the declared name, every test below would keep passing while the
        bypass they exist for had ceased to exist — or worse, changed shape.

        Asserted on what the SINK consumes: the two attributes the old invariant
        compared come back EQUAL, so the entry looks perfectly ordinary.
        """
        with zipfile.ZipFile(io.BytesIO(self._zip())) as zf:
            info = next(i for i in zf.infolist() if i.filename == self.CENTRAL)
        assert info.orig_filename == self.CENTRAL
        assert info.filename == self.CENTRAL
        assert info.orig_filename == info.filename, (
            "the 0x7075 route is only interesting because these are EQUAL"
        )
        # The record really is present in the parsed extra bytes...
        assert struct.pack("<H", 0x7075) in info.extra
        # ...and the name the stdlib resolved is the allowlisted thumbnail shape, which
        # is what made this storable rather than merely untidy.
        from src.services.design_system_service import _is_template_preview

        assert _is_template_preview(info.filename) is True

    def test_the_bundle_is_refused(self):
        from src.services.design_system_service import DesignSystemImportError, import_bundle

        with _isolated_session() as isolated:
            with pytest.raises(DesignSystemImportError) as exc:
                import_bundle(isolated, zip_bytes=self._zip(), user="u")
        assert "0x7075" in str(exc.value) or "extra field" in str(exc.value).lower()

    def test_nothing_is_stored_as_a_thumbnail(self):
        from src.database.models.design_system import (
            DesignSystemAsset,
            DesignSystemFile,
        )
        from src.services.design_system_service import DesignSystemImportError, import_bundle

        with _isolated_session() as isolated:
            with pytest.raises(DesignSystemImportError):
                import_bundle(isolated, zip_bytes=self._zip(), user="u")
            isolated.rollback()
            assert isolated.query(DesignSystemFile).all() == []
            assert isolated.query(DesignSystemAsset).all() == []

    def test_the_iterator_refuses_it_too_not_only_the_up_front_scan(self):
        from src.services.design_system_service import (
            DesignSystemImportError,
            _iter_safe_entries,
        )

        with zipfile.ZipFile(io.BytesIO(self._zip())) as zf:
            with pytest.raises(DesignSystemImportError):
                list(_iter_safe_entries(zf, ""))

    @pytest.mark.parametrize(
        "declared",
        [
            "templates/x/.thumbnail\x00.exe",
            "templates/x/.thumbnail\x85",
            "templates\\x\\.thumbnail",
            "../../../etc/passwd",
            "/etc/passwd",
            "templates/x/./.thumbnail",
            "assets/other.svg",
            "",
        ],
        ids=repr,
    )
    def test_any_disagreeing_declared_name_is_refused(self, declared):
        """Not only the NUL spelling. Whatever the second name is — a traversal, an
        absolute path, a backslash path, or simply a DIFFERENT valid name — the entry
        has two identities and one of them would reach storage unvalidated."""
        from src.services.design_system_service import DesignSystemImportError, import_bundle

        with _isolated_session() as isolated:
            with pytest.raises(DesignSystemImportError):
                import_bundle(isolated, zip_bytes=self._zip(declared), user="u")

    @pytest.mark.parametrize(
        "extra_kwargs",
        [{"version": 2}, {"name_crc": 0xDEADBEEF}],
        ids=["ignored-version", "non-matching-crc"],
    )
    def test_a_record_the_stdlib_ignores_is_still_refused(self, extra_kwargs):
        """CPython only applies the record when the version is 1 AND the name CRC
        matches, so these two are inert TODAY. They are refused anyway: matching the
        stdlib's acceptance condition would make this guard depend on the internals it
        exists to distrust, and an entry declaring two names is ambiguous regardless of
        which one a given reader picks."""
        from src.services.design_system_service import DesignSystemImportError, import_bundle

        extra = _unicode_path_extra(
            self.CENTRAL, self.DECLARED_NUL, **extra_kwargs
        )
        with _isolated_session() as isolated:
            with pytest.raises(DesignSystemImportError):
                import_bundle(isolated, zip_bytes=self._zip(extra=extra), user="u")

    def test_a_truncated_record_never_imports(self):
        """A record whose declared ``size`` overruns the extra field must not import.

        THIS shape is caught one layer lower: CPython validates extra-field framing
        while building the ZipFile and raises ``BadZipFile``, which surfaces as "not a
        valid .zip bundle". So this asserts the OUTCOME rather than a message this code
        owns. Do not generalise that to every malformed record — an invalid-UTF-8
        payload is NOT screened; see
        :meth:`test_the_parser_reports_unframeable_records_rather_than_raising` for the
        split.
        """
        from src.services.design_system_service import DesignSystemImportError, import_bundle

        # Declares 40 bytes of payload but supplies 2.
        extra = struct.pack("<HH", 0x7075, 40) + b"\x01\x02"
        with _isolated_session() as isolated:
            with pytest.raises(DesignSystemImportError):
                import_bundle(isolated, zip_bytes=self._zip(extra=extra), user="u")

    #: An invalid-UTF-8 0x7075 payload that CPython does NOT screen, because the
    #: version byte is not 1 and so the decode it would have raised on never runs:
    #: ``if up_version == 1 and up_name_crc == filename_crc: ...decode('utf-8')``.
    #: The archive opens normally and the record reaches this module's parser.
    ARCHIVE_REACHABLE_BAD_UTF8 = (
        struct.pack("<HH", 0x7075, 7) + b"\x02" + struct.pack("<L", 0) + b"\xff\xfe"
    )

    def test_an_invalid_utf8_record_is_refused_through_a_real_archive(self):
        """The malformed shape that is genuinely archive-reachable, pinned end to end.

        CPython only decodes the declared name when the record's version is 1 AND its
        name CRC matches, so a payload of invalid UTF-8 behind a version byte of 2 is
        never decoded by the stdlib and raises nothing: the ``ZipFile`` opens and the
        entry looks ordinary. Refusing it is therefore this module's job alone, and
        this asserts it happens for a real upload rather than only for a directly
        constructed ``ZipInfo``.
        """
        from src.services.design_system_service import (
            _REASON_CORRUPT_EXTRA,
            DesignSystemImportError,
            import_bundle,
        )

        zip_bytes = self._zip(extra=self.ARCHIVE_REACHABLE_BAD_UTF8)
        # Guard the guard: CPython really does open this, so the refusal below is ours.
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            assert self.CENTRAL in zf.namelist()

        with _isolated_session() as isolated:
            with pytest.raises(DesignSystemImportError) as exc:
                import_bundle(isolated, zip_bytes=zip_bytes, user="u")
        assert _REASON_CORRUPT_EXTRA in str(exc.value)

    @pytest.mark.parametrize(
        "extra",
        [
            struct.pack("<HH", 0x7075, 40) + b"\x01\x02",     # size overruns the field
            struct.pack("<HH", 0x7075, 3) + b"\x01\x02\x03",  # body shorter than 5
        ],
        ids=["overrun", "short-body"],
    )
    def test_the_parser_reports_unframeable_records_rather_than_raising(self, extra):
        """Unit-level, because THESE two shapes really are unreachable through an
        archive — unlike the invalid-UTF-8 case above.

        The distinction matters and was previously stated wrongly here, so it is worth
        being exact about which category each shape is in:

          * ARCHIVE-REACHABLE — an invalid-UTF-8 payload the stdlib never decodes
            (version != 1, or a non-matching name CRC). Pinned end-to-end by
            :meth:`test_an_invalid_utf8_record_is_refused_through_a_real_archive`.
          * CPYTHON-SCREENED — the two below. ``_decodeExtra`` validates extra-field
            FRAMING unconditionally while the ``ZipFile`` is built: an overrunning
            ``size`` raises ``BadZipFile("Corrupt extra field 7075")`` and a body
            shorter than the 5-byte header raises ``BadZipFile("Corrupt unicode path
            extra field (0x7075)")``. Both surface as "not a valid .zip bundle" before
            this module sees the entry, so an archive-level test could not tell
            "handled here" from "never called".

        Tested directly anyway: the parser reads attacker-controlled bytes and must not
        depend on another layer having screened them first, which is the premise of this
        whole series applied to its own dependency.
        """
        from src.services.design_system_service import (
            _REASON_CORRUPT_EXTRA,
            _extra_field_name_refusal,
        )

        assert (
            _extra_field_name_refusal(extra, "assets/logo.svg")
            == _REASON_CORRUPT_EXTRA
        )

    @pytest.mark.parametrize(
        "extra,opens",
        [
            (struct.pack("<HH", 0x7075, 40) + b"\x01\x02", False),
            (struct.pack("<HH", 0x7075, 3) + b"\x01\x02\x03", False),
            (ARCHIVE_REACHABLE_BAD_UTF8, True),
        ],
        ids=["overrun-screened", "short-body-screened", "invalid-utf8-reachable"],
    )
    def test_the_documented_reachability_of_each_malformed_shape_is_accurate(
        self, extra, opens
    ):
        """Pins the CLAIM the docstrings above make, so it cannot rot into a
        confidently false reading of which layer catches what.

        A security-path comment that misstates reachability is worse than no comment:
        it tells the next reader a branch is dead when it is live. This asserts the
        classification directly against CPython.
        """
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            info = zipfile.ZipInfo("assets/logo.svg")
            info.extra = extra
            zf.writestr(info, SVG_LOGO)

        try:
            with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as zf:
                zf.namelist()
            actually_opens = True
        except zipfile.BadZipFile:
            actually_opens = False

        assert actually_opens is opens, (
            f"reachability documented for {extra.hex()} is wrong: CPython "
            f"{'opens' if actually_opens else 'rejects'} this archive"
        )

    def test_the_parser_walks_past_other_records_to_find_a_later_one(self):
        """Extra fields are a SEQUENCE. A name-rewriting record placed after an
        unrelated one must still be found, or the guard is bypassed by prepending any
        unknown tag."""
        from src.services.design_system_service import (
            _REASON_NAME_MISMATCH,
            _extra_field_name_refusal,
        )

        timestamp = struct.pack("<HH", 0x5455, 5) + b"\x03\x00\x00\x00\x00"
        unicode_path = _unicode_path_extra("assets/logo.svg", "assets/evil.svg")
        assert (
            _extra_field_name_refusal(timestamp + unicode_path, "assets/logo.svg")
            == _REASON_NAME_MISMATCH
        )

    def test_a_record_that_agrees_with_the_central_name_is_accepted(self):
        """The limit of the rule, and the reason the real exports are unaffected: a
        0x7075 record is only a problem when it DISAGREES. One that declares exactly
        the central name adds no second identity, so the entry imports normally and the
        guard is not a blanket refusal of extra fields."""
        from src.services.design_system_service import import_bundle

        extra = _unicode_path_extra(self.CENTRAL, self.CENTRAL)
        with _isolated_session() as isolated:
            ds = import_bundle(isolated, zip_bytes=self._zip(extra=extra), user="u")
            assert self.CENTRAL in {f.path for f in ds.files}
            shots = [a for a in ds.assets if a.kind == "template_shot"]
            assert len(shots) == 1

    def test_an_unrelated_extra_field_is_left_alone(self):
        """Only name-rewriting records are this module's business. An unknown tag —
        here a plausible-looking timestamp record — must not refuse the bundle."""
        from src.services.design_system_service import import_bundle

        extra = struct.pack("<HH", 0x5455, 5) + b"\x03\x00\x00\x00\x00"
        with _isolated_session() as isolated:
            ds = import_bundle(isolated, zip_bytes=self._zip(extra=extra), user="u")
            assert self.CENTRAL in {f.path for f in ds.files}

    #: The 0x7075 TAG and nothing else: two bytes, with no ``size`` field and no body.
    #: Too short to be a header, so a walk that only steps while four or more bytes
    #: remain never looks at it — and reports the entry as clean.
    HEADERLESS_FRAGMENT = b"\x75\x70"

    def test_a_fragment_too_short_to_be_a_header_is_refused(self):
        """An extra field of exactly ``b"\\x75\\x70"`` must be REFUSED, not ignored.

        The walk steps record by record and used to stop as soon as fewer than four
        bytes remained, treating the leftover as padding. That is the wrong reading of
        a trailing fragment: the extra field is a sequence of records with no padding
        in it, so bytes that cannot be a complete header mean the field is malformed —
        and here they are the first half of the very record this guard exists to read.
        Whatever name that record meant to declare is unreadable, which is exactly the
        condition the overrun and short-body cases already refuse.

        CPython opens such an archive without complaint (its own walk has the same
        four-byte floor), so refusing it is this module's job alone.
        """
        from src.services.design_system_service import (
            _REASON_CORRUPT_EXTRA,
            DesignSystemImportError,
            import_bundle,
        )

        zip_bytes = self._zip(extra=self.HEADERLESS_FRAGMENT)
        # Guard the guard: the refusal below is ours, not a BadZipFile from the stdlib.
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            info = next(i for i in zf.infolist() if i.filename == self.CENTRAL)
            assert info.extra == self.HEADERLESS_FRAGMENT

        with _isolated_session() as isolated:
            with pytest.raises(DesignSystemImportError) as exc:
                import_bundle(isolated, zip_bytes=zip_bytes, user="u")
        assert _REASON_CORRUPT_EXTRA in str(exc.value)

    @pytest.mark.parametrize(
        "extra",
        [
            b"\x75\x70",
            b"\x75",
            b"\x75\x70\x20",
            struct.pack("<HH", 0x5455, 5) + b"\x03\x00\x00\x00\x00" + b"\x75\x70",
        ],
        ids=["tag-only", "one-byte", "three-bytes", "after-a-valid-record"],
    )
    def test_the_parser_refuses_every_trailing_fragment(self, extra):
        """Any leftover, wherever it falls. A fragment following a well-formed record
        is the shape that matters most: the walk reaches it having already parsed
        something successfully, which is precisely when "stop, we are done" looks
        reasonable and is wrong."""
        from src.services.design_system_service import (
            _REASON_CORRUPT_EXTRA,
            _extra_field_name_refusal,
        )

        assert (
            _extra_field_name_refusal(extra, "assets/logo.svg")
            == _REASON_CORRUPT_EXTRA
        )

    def test_an_extra_field_that_ends_exactly_on_a_record_is_still_accepted(self):
        """The limit of the rule. A field whose records tile it exactly has no
        fragment, and must not be refused — otherwise every ordinary archive with a
        timestamp record fails."""
        from src.services.design_system_service import _extra_field_name_refusal

        extra = struct.pack("<HH", 0x5455, 5) + b"\x03\x00\x00\x00\x00"
        assert _extra_field_name_refusal(extra, "assets/logo.svg") is None
        assert _extra_field_name_refusal(b"", "assets/logo.svg") is None


class TestTheLocalFileHeaderIsInspectedToo:
    """A .zip states every entry's identity TWICE, and CPython reads only one copy.

    Each entry is described by a local file header immediately before its bytes and
    again by a central directory record at the end of the archive. Nothing in the
    format makes the two agree, and CPython's reader builds ``ZipInfo`` purely from
    the central copy: ``ZipInfo.extra`` is the CENTRAL extra, and the local extra is
    never parsed at all.

    So a guard reading ``info.extra`` alone can be walked straight past. Give the
    central directory a clean name and an EMPTY extra, and put the name-rewriting
    ``0x7075`` record — version 1, matching CRC, declaring
    ``templates/x/.thumbnail\\x00.exe`` — in the local header only. CPython reports an
    ordinary entry, the guard finds nothing to object to, and the archive is stored
    under the clean thumbnail identity while presenting the other name to any unzip
    that reads local headers. That is the same one-archive-two-identities problem the
    central-extra refusal exists to prevent, expressed in the copy that was not being
    read.

    Both copies are therefore inspected, and a DISAGREEMENT between them is itself a
    refusal: there is no single name such an entry can be said to have.
    """

    CENTRAL = "templates/x/.thumbnail"
    DECLARED_NUL = "templates/x/.thumbnail\x00.exe"

    def _zip(self, *, local_extra=None, central_extra=b"", declared=None):
        if local_extra is None:
            local_extra = _unicode_path_extra(
                self.CENTRAL, self.DECLARED_NUL if declared is None else declared
            )
        return _bundle_with_asymmetric_extra_fields(
            self.CENTRAL,
            local_extra=local_extra,
            central_extra=central_extra,
            payload=webp_bytes(),
        )

    def test_the_two_headers_really_do_disagree_in_the_crafted_archive(self):
        """NON-VACUITY, and the whole reason this class exists. If the record leaked
        into the central directory, every refusal below would pass through the
        central-extra path and prove nothing about the local one.

        Pinned on both sides: the central extra is EMPTY, the local extra carries the
        0x7075 record, and CPython opens the archive and resolves the clean,
        allowlisted thumbnail name — the state in which the bypass was measured.
        """
        from src.services.design_system_service import _is_template_preview

        raw = self._zip()
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            info = next(i for i in zf.infolist() if i.filename == self.CENTRAL)
        assert info.extra == b"", "the central directory must carry NO extra field"
        assert info.orig_filename == info.filename == self.CENTRAL
        assert _is_template_preview(info.filename) is True

        _, local_name, local_extra = _local_header_of(raw, self.CENTRAL)
        assert local_name == self.CENTRAL.encode()
        assert struct.pack("<H", 0x7075) in local_extra
        assert self.DECLARED_NUL.encode() in local_extra

    def test_the_central_extra_walk_alone_reports_nothing(self):
        """The second half of the non-vacuity proof: the parser reading the CENTRAL
        extra is silent on this archive. Any refusal therefore comes from the local
        header, which is the code path under test."""
        from src.services.design_system_service import _extra_field_name_refusal

        with zipfile.ZipFile(io.BytesIO(self._zip())) as zf:
            info = next(i for i in zf.infolist() if i.filename == self.CENTRAL)
        assert _extra_field_name_refusal(info.extra, self.CENTRAL) is None

    def test_the_bundle_is_refused_for_the_two_identities(self):
        from src.services.design_system_service import (
            _REASON_NAME_MISMATCH,
            DesignSystemImportError,
            import_bundle,
        )

        with _isolated_session() as isolated:
            with pytest.raises(DesignSystemImportError) as exc:
                import_bundle(isolated, zip_bytes=self._zip(), user="u")
        assert _REASON_NAME_MISMATCH in str(exc.value)

    def test_nothing_is_stored_as_a_thumbnail(self):
        """The consequence that made this blocking rather than untidy: the entry was
        reaching the template-thumbnail allowlist and being stored under the clean
        name, which is the identity the guard was supposed to make impossible."""
        from src.database.models.design_system import (
            DesignSystemAsset,
            DesignSystemFile,
        )
        from src.services.design_system_service import (
            DesignSystemImportError,
            import_bundle,
        )

        with _isolated_session() as isolated:
            with pytest.raises(DesignSystemImportError):
                import_bundle(isolated, zip_bytes=self._zip(), user="u")
            isolated.rollback()
            assert isolated.query(DesignSystemFile).all() == []
            assert isolated.query(DesignSystemAsset).all() == []

    def test_the_iterator_refuses_it_too_not_only_the_up_front_scan(self):
        """Both gates share one judgement, so neither can be left behind."""
        from src.services.design_system_service import (
            DesignSystemImportError,
            _iter_safe_entries,
        )

        with zipfile.ZipFile(io.BytesIO(self._zip())) as zf:
            with pytest.raises(DesignSystemImportError):
                list(_iter_safe_entries(zf, ""))

    @pytest.mark.parametrize(
        "declared",
        [
            "templates/x/.thumbnail\x00.exe",
            "templates\\x\\.thumbnail",
            "../../../etc/passwd",
            "assets/other.svg",
        ],
        ids=repr,
    )
    def test_any_disagreeing_local_declaration_is_refused(self, declared):
        """Not only the NUL spelling: whatever second name the local header declares,
        the entry has two identities."""
        from src.services.design_system_service import (
            _REASON_NAME_MISMATCH,
            DesignSystemImportError,
            import_bundle,
        )

        with _isolated_session() as isolated:
            with pytest.raises(DesignSystemImportError) as exc:
                import_bundle(isolated, zip_bytes=self._zip(declared=declared), user="u")
        assert _REASON_NAME_MISMATCH in str(exc.value)

    def test_a_malformed_record_in_the_local_extra_alone_is_refused(self):
        """The two findings compose: a fragment too short to be a header, in the copy
        that was not being read. Neither guard alone catches this."""
        from src.services.design_system_service import (
            _REASON_CORRUPT_EXTRA,
            DesignSystemImportError,
            import_bundle,
        )

        zip_bytes = self._zip(local_extra=b"\x75\x70")
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            info = next(i for i in zf.infolist() if i.filename == self.CENTRAL)
            assert info.extra == b"", "central must stay clean or this proves nothing"

        with _isolated_session() as isolated:
            with pytest.raises(DesignSystemImportError) as exc:
                import_bundle(isolated, zip_bytes=zip_bytes, user="u")
        assert _REASON_CORRUPT_EXTRA in str(exc.value)

    def test_a_local_extra_that_agrees_with_the_central_name_is_accepted(self):
        """The limit of the rule, and what keeps the real exports importable: reading
        the local header is not a refusal of archives that HAVE one. A record
        declaring exactly the central name adds no second identity, so the thumbnail
        imports and is bound to its template as usual."""
        from src.services.design_system_service import import_bundle

        zip_bytes = self._zip(local_extra=_unicode_path_extra(self.CENTRAL, self.CENTRAL))
        with _isolated_session() as isolated:
            ds = import_bundle(isolated, zip_bytes=zip_bytes, user="u")
            assert self.CENTRAL in {f.path for f in ds.files}
            assert len([a for a in ds.assets if a.kind == "template_shot"]) == 1

    def test_a_local_filename_that_disagrees_is_refused_before_any_read(self):
        """The other way the two copies can differ: not the extra field but the NAME
        recorded beside it.

        Patched to an equal-length name so every length and offset in the archive
        stays valid — CPython opens it and lists the central name happily. Its own
        local/central comparison exists but runs inside ``ZipFile.open``, i.e. only
        when an entry's bytes are actually read, and it raises ``BadZipFile`` — a
        corrupt-archive error, not an explanation. Refusing at the path gate covers
        every entry whether or not the importer ever reads it, and tells the user what
        is wrong with their upload.
        """
        from src.services.design_system_service import (
            _REASON_NAME_MISMATCH,
            DesignSystemImportError,
            import_bundle,
        )

        raw = bytearray(self._zip(local_extra=b""))
        offset, local_name, _ = _local_header_of(bytes(raw), self.CENTRAL)
        other = b"templates/y/.thumbnail"
        assert len(other) == len(local_name), "equal length keeps the archive framed"
        raw[offset + 30 : offset + 30 + len(local_name)] = other

        with zipfile.ZipFile(io.BytesIO(bytes(raw))) as zf:
            assert self.CENTRAL in zf.namelist()

        with _isolated_session() as isolated:
            with pytest.raises(DesignSystemImportError) as exc:
                import_bundle(isolated, zip_bytes=bytes(raw), user="u")
        assert _REASON_NAME_MISMATCH in str(exc.value)

    def test_an_unreadable_local_header_is_refused(self):
        """Fail closed. If the local header is not there to be read, the entry's
        second identity is unknown rather than absent, and an importer that cannot
        check must not accept."""
        from src.services.design_system_service import (
            _REASON_LOCAL_HEADER,
            DesignSystemImportError,
            import_bundle,
        )

        raw = bytearray(self._zip(local_extra=b""))
        offset, _, _ = _local_header_of(bytes(raw), self.CENTRAL)
        raw[offset : offset + 4] = b"PK\xff\xff"

        with zipfile.ZipFile(io.BytesIO(bytes(raw))) as zf:
            assert self.CENTRAL in zf.namelist()

        with _isolated_session() as isolated:
            with pytest.raises(DesignSystemImportError) as exc:
                import_bundle(isolated, zip_bytes=bytes(raw), user="u")
        assert _REASON_LOCAL_HEADER in str(exc.value)

    def test_an_ordinary_bundle_with_no_extra_fields_still_imports(self):
        """The regression this whole check must not cause: reading local headers is
        added work on EVERY entry of every upload, so the plain path is pinned here."""
        from src.services.design_system_service import import_bundle

        with _isolated_session() as isolated:
            ds = import_bundle(isolated, zip_bytes=self._zip(local_extra=b""), user="u")
            assert self.CENTRAL in {f.path for f in ds.files}
            assert len([a for a in ds.assets if a.kind == "template_shot"]) == 1


class TestAHostileZip64OffsetIsRefusedRatherThanCrashing:
    """The local-header read is driven by an offset the ARCHIVE supplies, and the
    archive is the attacker's.

    ``info.header_offset`` looks like a number the zip reader vouched for, and it is
    not: a central directory record may carry the legacy sentinel ``0xffffffff`` plus a
    ZIP64 extra field holding a 64-bit replacement, and ``ZipInfo._decodeExtra``
    substitutes it verbatim without ever comparing it to the size of the file. So an
    archive of 146 bytes can present an entry whose local header begins at
    ``2**64 - 1``.

    Seeking there does not raise ``OSError`` or ``ValueError`` — the two the guard
    caught. ``BytesIO.seek`` cannot convert the value to a C ``ssize_t`` at all and
    raises ``OverflowError``, which walked straight out of the helper, out of
    ``import_bundle``, past the route's ``DesignSystemImportError`` handler and into
    the generic 500. A hostile upload must not be able to choose the status code, and
    "the local header could not be read" is exactly the condition
    :data:`_REASON_LOCAL_HEADER` already exists to refuse.

    So the offset is bound-checked against the real size of the archive BEFORE the
    seek, and the guard is widened to ``OverflowError`` so no later arithmetic
    surprise can escape either. Both, not one: the bound check is the fix, and the
    widened guard is the backstop for the next value nobody predicted.
    """

    #: 2**64 - 1, the offset CPython reports for the crafted pair.
    HOSTILE_OFFSET = 18446744073709551615

    def test_cpython_really_exposes_the_out_of_range_offset(self):
        """NON-VACUITY. If CPython stopped honouring the ZIP64 offset substitution, or
        started sanity-checking it, every test below would keep passing while the crash
        they exist for had ceased to exist.

        Pinned on the three facts that make the crash reachable: the archive OPENS, the
        offset is astronomically past the end of it, and the entry is otherwise
        completely ordinary.
        """
        raw = make_zip64_header_offset_archive()
        assert len(raw) == 146, "a 146-byte archive is the whole attack"
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            (info,) = zf.infolist()
        assert info.header_offset == self.HOSTILE_OFFSET
        assert info.header_offset > len(raw), "the offset must be past EOF to matter"
        assert info.filename == info.orig_filename == MANIFEST_FILENAME

    def test_the_unpatched_guard_would_not_have_caught_it(self):
        """WHY the guard had to be widened rather than only bound-checked: the
        exception a raw seek to this offset raises is not in the caught set.

        Asserted against ``BytesIO`` directly — the exact object ``import_bundle``
        wraps the upload in — so this pins the stdlib behaviour the fix is a response
        to, independently of the helper.
        """
        with pytest.raises(OverflowError):
            io.BytesIO(b"small").seek(self.HOSTILE_OFFSET)
        assert not issubclass(OverflowError, (OSError, ValueError))

    def test_the_helper_reports_an_unreadable_header_instead_of_raising(self):
        from src.services.design_system_service import _local_header_identity

        with zipfile.ZipFile(io.BytesIO(make_zip64_header_offset_archive())) as zf:
            (info,) = zf.infolist()
            assert _local_header_identity(zf, info) is None

    def test_the_bundle_is_refused_with_the_unreadable_header_reason(self):
        """Fail CLOSED, on the path that already exists for a header that cannot be
        read — not with a new error shape and not with a 500."""
        from src.services.design_system_service import (
            _REASON_LOCAL_HEADER,
            DesignSystemImportError,
            import_bundle,
        )

        with _isolated_session() as isolated:
            with pytest.raises(DesignSystemImportError) as exc:
                import_bundle(
                    isolated, zip_bytes=make_zip64_header_offset_archive(), user="u"
                )
        assert _REASON_LOCAL_HEADER in str(exc.value)

    @pytest.mark.parametrize(
        "offset",
        [
            b"\xff" * 8,  # 2**64 - 1: unconvertible to a C ssize_t
            struct.pack("<Q", 2**63),  # the first value above the ssize_t ceiling
            struct.pack("<Q", 2**63 - 1),  # the ceiling itself: converts, seeks past EOF
            struct.pack("<Q", 146),  # exactly EOF
            struct.pack("<Q", 147),  # one byte past EOF
        ],
        ids=["2**64-1", "2**63", "2**63-1", "at-EOF", "past-EOF"],
    )
    def test_every_offset_at_or_beyond_the_end_of_the_archive_is_refused(self, offset):
        """The bound check is what makes this uniform. An offset that OVERFLOWS the
        seek and one that merely lands past the last byte are the same defect — the
        local header is not there — and only a size comparison treats them alike.
        Without it, the three largest values raise and the two smallest fall through to
        a short read, which happened to return ``None`` by luck rather than by rule.
        """
        from src.services.design_system_service import (
            _REASON_LOCAL_HEADER,
            DesignSystemImportError,
            import_bundle,
        )

        with _isolated_session() as isolated:
            with pytest.raises(DesignSystemImportError) as exc:
                import_bundle(
                    isolated,
                    zip_bytes=make_zip64_header_offset_archive(offset),
                    user="u",
                )
        assert _REASON_LOCAL_HEADER in str(exc.value)

    def test_reading_a_local_header_leaves_the_file_position_where_it_found_it(self):
        """Defensive hygiene, pinned so it stays. The helper seeks a file pointer it
        does not own; every reader that shares it re-seeks before reading, which is why
        this was never a bug, but restoring the position costs one call and removes the
        need to know that."""
        from src.services.design_system_service import _local_header_identity

        with zipfile.ZipFile(io.BytesIO(make_bundle_zip())) as zf:
            info = next(i for i in zf.infolist() if i.filename == "assets/logo.svg")
            zf.fp.seek(7)
            assert _local_header_identity(zf, info) is not None
            assert zf.fp.tell() == 7


class TestAnEmptyCentralNameIsRefusedRatherThanLaundered:
    """``orig_filename or filename`` replaces an EMPTY recorded name with the REWRITTEN
    one — the one laundering left in a module whose whole premise is not to launder.

    An empty central-directory name is attacker-controlled data with meaning, and
    truthiness cannot tell it apart from the attribute being ABSENT. The consequence is
    not cosmetic: a ``0x7075`` record whose CRC matches the empty central name (CRC-32
    of ``b""``, which is 0) makes CPython assign ``filename = "slides/benign.bin"``
    while ``orig_filename`` stays ``""``. The ``or`` then hands every gate the rewritten
    name, so route 1 of :func:`_entry_identity_refusal` (``orig_filename !=
    filename``) compares the rewritten name against itself and the local-name
    comparison compares the local header against the rewritten name too. Both agree,
    and an entry carrying two raw header identities imports.

    Measured before the fix: the scan raised nothing and the iterator yielded
    ``slides/benign.bin`` as a file to store.

    Two changes, because either alone leaves a hole. ``None`` is distinguished from
    ``""`` so the raw name is the raw name; and an empty raw name is REFUSED, because
    no legitimate archive member has one and an entry with no recorded name has no
    identity for the gate to establish.
    """

    TARGET = "slides/benign.bin"

    def _zip(self, *, central_name="", declared=None, local_name=None):
        """A valid bundle plus one entry whose two headers record DIFFERENT names.

        No byte patching. ``ZipFile`` writes the local header during ``writestr`` and
        the central directory at ``close``, both reading ``zinfo.filename`` and
        ``zinfo.extra`` when they run, so mutating the object in between gives each
        header its own name and its own extra field with every length computed by
        ``zipfile`` itself.
        """
        declared = self.TARGET if declared is None else declared
        local_name = self.TARGET if local_name is None else local_name
        manifest = default_manifest()
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(MANIFEST_FILENAME, json.dumps(manifest).encode())
            zf.writestr("colors_and_type.css", COLORS_AND_TYPE_CSS)
            zf.writestr("README.md", SYNTHETIC_README)
            zf.writestr("assets/logo.svg", SVG_LOGO)
            info = zipfile.ZipInfo(local_name)
            info.extra = _unicode_path_extra(local_name, declared)
            zf.writestr(info, b"synthetic-payload")
            # Re-read from this same object by ``_write_end_record`` at close, so the
            # CENTRAL record gets the empty name and its own matching-CRC record.
            info.filename = central_name
            info.extra = _unicode_path_extra(central_name, declared)
        return buf.getvalue()

    def test_cpython_really_launders_the_empty_name_into_a_usable_one(self):
        """NON-VACUITY, and the reason an empty name is worth attacking with. The
        central directory records NO name; CPython resolves a perfectly ordinary
        storable one and leaves the two attributes DIFFERENT — which is precisely the
        divergence route 1 exists to catch and which the ``or`` hid from it."""
        with zipfile.ZipFile(io.BytesIO(self._zip())) as zf:
            info = next(i for i in zf.infolist() if i.filename == self.TARGET)
        assert info.orig_filename == "", "the central name must really be EMPTY"
        assert info.filename == self.TARGET
        assert info.orig_filename != info.filename

    def test_the_raw_name_is_the_empty_one_the_archive_records(self):
        """The laundering itself, at the one line that does it. Everything else in this
        class is a consequence of this function's answer."""
        from src.services.design_system_service import _raw_entry_name

        with zipfile.ZipFile(io.BytesIO(self._zip())) as zf:
            info = next(i for i in zf.infolist() if i.filename == self.TARGET)
        assert _raw_entry_name(info) == ""

    def test_an_absent_attribute_still_falls_back_to_the_filename(self):
        """The distinction the fix turns on, and the case the ``or`` got right: ABSENT
        is not EMPTY. A ``ZipInfo`` without the attribute at all must still report a
        name, so the fallback stays — it is only truthiness that goes."""
        from src.services.design_system_service import _raw_entry_name

        info = zipfile.ZipInfo("assets/logo.svg")
        del info.orig_filename
        assert not hasattr(info, "orig_filename")
        assert _raw_entry_name(info) == "assets/logo.svg"

    def test_the_shared_judgement_refuses_the_entry(self):
        """The judgement BOTH gates read, so neither can be left behind."""
        from src.services.design_system_service import (
            _ENTRY_REFUSE,
            _REASON_EMPTY_RECORDED_NAME,
            _entry_verdict_for_info,
        )

        with zipfile.ZipFile(io.BytesIO(self._zip())) as zf:
            info = next(i for i in zf.infolist() if i.filename == self.TARGET)
            verdict = _entry_verdict_for_info(zf, info)
        assert verdict.kind == _ENTRY_REFUSE
        assert verdict.reason == _REASON_EMPTY_RECORDED_NAME

    def test_the_bundle_is_refused(self):
        from src.services.design_system_service import (
            _REASON_EMPTY_RECORDED_NAME,
            DesignSystemImportError,
            import_bundle,
        )

        with _isolated_session() as isolated:
            with pytest.raises(DesignSystemImportError) as exc:
                import_bundle(isolated, zip_bytes=self._zip(), user="u")
        assert _REASON_EMPTY_RECORDED_NAME in str(exc.value)

    def test_the_iterator_refuses_it_rather_than_skipping_it(self):
        """The gate that decides what gets STORED, asserted as a REFUSAL.

        Before the fix it yielded ``slides/benign.bin`` — an entry with two raw header
        identities, on its way to a row. "Not yielded" was too weak an assertion to
        replace that with: this entry's recorded name is ``""``, which strips to nothing
        under every root prefix, so the iterator's ``if not rel_raw: continue`` SKIPPED
        it silently and satisfied a not-yielded assertion while judging it not at all.
        Refusing is the property that matters, because a skip leaves the entry's second
        identity unremarked and leans entirely on the up-front scan having run.
        """
        from src.services.design_system_service import (
            _REASON_EMPTY_RECORDED_NAME,
            DesignSystemImportError,
            _iter_safe_entries,
        )

        with zipfile.ZipFile(io.BytesIO(self._zip())) as zf:
            with pytest.raises(DesignSystemImportError) as exc:
                list(_iter_safe_entries(zf, ""))
        assert _REASON_EMPTY_RECORDED_NAME in str(exc.value)

    def test_the_iterator_refuses_it_out_of_scope_too(self):
        """The same refusal under a root prefix the entry does not sit under.

        An empty recorded name is hostile wherever it sits: there is no root prefix that
        makes "the archive records no name for this entry" acceptable. Pinned separately
        from the case above because the two failed for DIFFERENT reasons — in scope the
        empty remainder swallowed it, out of scope the ``startswith`` did — and a fix
        that only reordered one of them would leave the other.
        """
        from src.services.design_system_service import (
            _REASON_EMPTY_RECORDED_NAME,
            DesignSystemImportError,
            _iter_safe_entries,
        )

        with zipfile.ZipFile(io.BytesIO(self._zip())) as zf:
            with pytest.raises(DesignSystemImportError) as exc:
                list(_iter_safe_entries(zf, "no-such-root/"))
        assert _REASON_EMPTY_RECORDED_NAME in str(exc.value)

    def test_nothing_is_stored(self):
        from src.database.models.design_system import (
            DesignSystemAsset,
            DesignSystemFile,
        )
        from src.services.design_system_service import (
            DesignSystemImportError,
            import_bundle,
        )

        with _isolated_session() as isolated:
            with pytest.raises(DesignSystemImportError):
                import_bundle(isolated, zip_bytes=self._zip(), user="u")
            isolated.rollback()
            assert isolated.query(DesignSystemFile).all() == []
            assert isolated.query(DesignSystemAsset).all() == []

    def test_a_directory_entry_is_still_accepted_as_an_identity_and_skipped(self):
        """THE LIMIT OF THE RULE, and the thing an over-broad emptiness check breaks. A
        trailing-slash directory entry records a real, non-empty name; it is judged as
        having one identity and then skipped as a directory, exactly as before. Pinned
        with a bundle that imports, so a regression here fails loudly rather than
        dropping a folder."""
        from src.services.design_system_service import import_bundle

        files = {
            "assets/": b"",
            "assets/logo.svg": SVG_LOGO,
            "README.md": SYNTHETIC_README,
        }
        with _isolated_session() as isolated:
            ds = import_bundle(
                isolated, zip_bytes=make_bundle_zip(files=files), user="u"
            )
            stored = {f.path for f in ds.files}
            assert "assets/logo.svg" in stored
            assert "assets/" not in stored

    def test_an_ordinary_bundle_still_imports(self):
        """The plain path, pinned: the new refusal must cost nothing to a real upload
        whose every entry records its own name."""
        from src.services.design_system_service import import_bundle

        with _isolated_session() as isolated:
            ds = import_bundle(isolated, zip_bytes=make_bundle_zip(), user="u")
            assert "assets/logo.svg" in {f.path for f in ds.files}


class TestIdentityIsJudgedBeforeScopeSoTheIteratorRefusesOnItsOwn:
    """TWO GATES, and either one alone must refuse a hostile entry.

    Every entry is judged twice — by the up-front whole-bundle scan
    (:func:`_assert_bundle_paths_safe`) and again by the per-entry iterator
    (:func:`_iter_safe_entries`) — and the point of the second gate is that it does not
    depend on the first having run. The iterator had quietly dropped to ONE gate: it
    filtered by SCOPE first (``startswith(root_prefix)``, then a non-empty remainder)
    and only asked for a verdict afterwards, so any entry the scope filter dropped was
    never judged at all. Its identity — whether the archive gives it one name or two —
    went unexamined.

    Nothing was exploitable. The only production caller reaches the iterator through
    ``_collect_assets_and_files``, and :func:`import_bundle` runs the scan first, before
    root discovery and before any read; there is no MCP, retry, streaming or alternate
    caller. So the hole was latent — and a latent hole in the second of two gates is
    exactly the thing that becomes live the day someone adds a third caller.

    THE DISTINCTION THE FIX TURNS ON: a safety/identity verdict is not a scoping
    decision. Where an entry sits decides whether THIS import stores it; whether the
    archive gives it one name decides whether the archive is acceptable at all. So the
    identity verdict is evaluated for EVERY member before the scope filter runs, and the
    scope filter is unchanged behind it — see
    :meth:`test_a_safe_out_of_scope_entry_is_still_skipped_silently` for the half that
    must NOT change.

    Every test here calls the iterator DIRECTLY with NO prior
    ``_assert_bundle_paths_safe``, and hands it a ``root_prefix`` the hostile entry does
    not sit under, so a refusal cannot be coming from the other gate and cannot be
    coming from the path rules either — out of scope, those are never reached.
    """

    CENTRAL = "templates/x/.thumbnail"

    #: A prefix no entry of any archive below starts with, so every entry is OUT OF
    #: SCOPE and the pre-fix iterator skipped the lot without a verdict.
    OUT_OF_SCOPE_ROOT = "no-such-root/"

    @staticmethod
    def _mismatched_local_name_zip():
        """A bundle whose entry's two headers record DIFFERENT NAMES.

        The local name is patched to an equal-length one so every length and offset in
        the archive stays valid and CPython opens it happily — the same recipe as
        :meth:`TestTheLocalFileHeaderIsInspectedToo.test_a_local_filename_that_disagrees_is_refused_before_any_read`,
        which pins this shape through ``import_bundle``. Here it is the iterator's turn.
        """
        central = TestIdentityIsJudgedBeforeScopeSoTheIteratorRefusesOnItsOwn.CENTRAL
        raw = bytearray(
            _bundle_with_asymmetric_extra_fields(
                central, local_extra=b"", central_extra=b"", payload=webp_bytes()
            )
        )
        offset, local_name, _ = _local_header_of(bytes(raw), central)
        other = b"templates/y/.thumbnail"
        assert len(other) == len(local_name), "equal length keeps the archive framed"
        raw[offset + 30 : offset + 30 + len(local_name)] = other
        return bytes(raw)

    def _refusal_out_of_scope(self, zip_bytes):
        """The iterator's own refusal message for an archive it is asked to scope AWAY.

        Fails with the yielded list rather than a bare ``DidNotRaise`` if nothing is
        refused, because "the iterator skipped it" is the regression being guarded and
        it is worth reading that in the failure.
        """
        from src.services.design_system_service import (
            DesignSystemImportError,
            _iter_safe_entries,
        )

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            try:
                yielded = [path for _, path in _iter_safe_entries(zf, self.OUT_OF_SCOPE_ROOT)]
            except DesignSystemImportError as exc:
                return str(exc)
        pytest.fail(
            f"the iterator did not refuse the entry; it yielded {yielded!r} and "
            "skipped the hostile member silently"
        )

    def test_the_crafted_archives_really_are_out_of_scope_and_otherwise_ordinary(self):
        """NON-VACUITY, on the two facts every test below depends on: CPython opens each
        archive, and NO entry in it starts with the root prefix the iterator is given —
        so the pre-fix iterator reached its ``continue`` for every member and the
        refusals below are genuinely coming from the hoisted identity check."""
        archives = {
            "mismatched-local-name": self._mismatched_local_name_zip(),
            "corrupt-extra": _bundle_with_extra_field(
                self.CENTRAL, b"\x75\x70", webp_bytes()
            ),
            "unreadable-local-header": make_zip64_header_offset_archive(),
        }
        for label, raw in archives.items():
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                names = zf.namelist()
            assert names, f"{label}: the archive must open and list its entries"
            assert not any(
                name.startswith(self.OUT_OF_SCOPE_ROOT) for name in names
            ), f"{label}: every entry must be OUT of scope or the test proves nothing"

    def test_a_local_name_disagreeing_with_the_central_one_is_refused(self):
        """Identity route 3 — the two headers record different names — out of scope."""
        from src.services.design_system_service import _REASON_NAME_MISMATCH

        assert _REASON_NAME_MISMATCH in self._refusal_out_of_scope(
            self._mismatched_local_name_zip()
        )

    @pytest.mark.parametrize(
        "fragment",
        [b"\x75", b"\x75\x70", b"\x75\x70\x20"],
        ids=["one-byte", "tag-only", "three-bytes"],
    )
    def test_a_trailing_extra_field_fragment_is_refused(self, fragment):
        """An extra field ending in bytes too short to be a record header: the name the
        record meant to declare cannot be read, so the entry's identity cannot be
        established. CPython opens such an archive without complaint (its own walk has
        the same four-byte floor), so this gate is the only one that sees it."""
        from src.services.design_system_service import _REASON_CORRUPT_EXTRA

        raw = _bundle_with_extra_field(self.CENTRAL, fragment, webp_bytes())
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            info = next(i for i in zf.infolist() if i.filename == self.CENTRAL)
            assert info.extra == fragment, "the fragment must survive into the archive"

        assert _REASON_CORRUPT_EXTRA in self._refusal_out_of_scope(raw)

    def test_an_unreadable_local_header_is_refused(self):
        """The hostile ZIP64 offset: the local header is not where the central directory
        says it is, so the entry's second name is unknown rather than absent. Fail
        closed, out of scope as well as in."""
        from src.services.design_system_service import _REASON_LOCAL_HEADER

        assert _REASON_LOCAL_HEADER in self._refusal_out_of_scope(
            make_zip64_header_offset_archive()
        )

    def test_a_safe_out_of_scope_entry_is_still_skipped_silently(self):
        """THE HALF THAT MUST NOT CHANGE, and the reason identity was hoisted rather
        than the whole verdict.

        Scoping is this iterator's contract: it yields the entries THIS import stores,
        and an entry outside the discovered root is simply not one of them. A safe
        neighbour must therefore still be passed over without a word — no refusal and no
        warning — exactly as before. Hoisting the full verdict instead of the identity
        half would have turned this into a refusal and widened the iterator from "the
        entries this import stores" to "every entry in the archive".
        """
        from src.services.design_system_service import _iter_safe_entries

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("safe/assets/logo.svg", SVG_LOGO)
            zf.writestr("outside/logo.svg", SVG_LOGO)
        warnings = []
        with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as zf:
            yielded = [path for _, path in _iter_safe_entries(zf, "safe/", warnings)]
        assert yielded == ["assets/logo.svg"]
        assert warnings == [], "an out-of-scope neighbour is not the user's problem"

    def test_an_unsafe_path_out_of_scope_is_still_the_scans_business_not_this_gates(self):
        """The line, drawn deliberately and pinned so it is not crossed by accident.

        A ``..`` entry outside the root is refused by the WHOLE-BUNDLE SCAN, which
        judges paths globally — that is where an unsafe path outside the import scope
        belongs, and it is why the bundle below cannot be imported. This iterator still
        skips it, because deciding that an out-of-scope PATH refuses the bundle is the
        scan's judgement to make and duplicating it here would change what this
        generator is for.

        Identity is different in kind, which is the whole distinction: "the archive
        gives this entry two names" is a fact about the archive, true wherever the entry
        sits, and no root prefix makes it acceptable.
        """
        from src.services.design_system_service import (
            DesignSystemImportError,
            _assert_bundle_paths_safe,
            _iter_safe_entries,
        )

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("safe/assets/logo.svg", SVG_LOGO)
            zf.writestr("../evil.png", webp_bytes())
        raw = buf.getvalue()
        assert "../evil.png" in zipfile.ZipFile(io.BytesIO(raw)).namelist()

        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            yielded = [path for _, path in _iter_safe_entries(zf, "safe/")]
        assert yielded == ["assets/logo.svg"]

        # ...and the gate that DOES own it refuses the bundle, so nothing is lost.
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            with pytest.raises(DesignSystemImportError):
                _assert_bundle_paths_safe(zf)


class TestStdlibRewrittenNamesAreRefused:
    """Python's zip reader TRUNCATES ``ZipInfo.filename`` at a NUL byte and keeps the
    real central-directory name only in ``orig_filename``.

    So an entry recorded as ``templates/x/.thumbnail\\x00.exe`` is READ as
    ``templates/x/.thumbnail`` — which matches the template-thumbnail allowlist and
    is stored if its bytes sniff as an image. Every gate validating ``info.filename``
    was validating a string the stdlib had rewritten: exactly the laundering this
    module refuses to do, performed one layer down where the refusal could not see it.

    The fix is the invariant "the archive's name IS the read name", which covers NUL
    and anything else the stdlib may quietly change.
    """

    #: A same-length placeholder, so swapping the bytes needs no offset fixups.
    PLACEHOLDER = "templates/x/.thumbnail@.exe"
    REAL = "templates/x/.thumbnail\x00.exe"

    def _nul_zip(self):
        """A bundle whose central directory REALLY records a NUL-bearing name.

        ``zipfile`` truncates an arcname at a NUL when WRITING too, so the name cannot
        simply be passed to ``writestr`` — it has to be patched into the finished
        archive bytes, in both the local header and the central directory.
        """
        assert len(self.PLACEHOLDER) == len(self.REAL)
        manifest = default_manifest()
        manifest["templates"] = [
            {
                "name": "X",
                "description": "Synthetic layout.",
                "folder": "templates/x",
                "entryPath": "templates/x/index.html",
            }
        ]
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(MANIFEST_FILENAME, json.dumps(manifest).encode())
            zf.writestr("colors_and_type.css", COLORS_AND_TYPE_CSS)
            zf.writestr("README.md", SYNTHETIC_README)
            zf.writestr("assets/logo.svg", SVG_LOGO)
            zf.writestr("templates/x/index.html", SYNTHETIC_TEMPLATE_HTML)
            zf.writestr(self.PLACEHOLDER, webp_bytes())
        return buf.getvalue().replace(
            self.PLACEHOLDER.encode(), self.REAL.encode()
        )

    def test_the_fixture_really_carries_a_nul_name_that_the_stdlib_truncates(self):
        """Guard the guard, asserted on what the SINK consumes. If the NUL did not
        survive into the archive, or a future stdlib stopped truncating, every test
        below would pass while testing nothing."""
        with zipfile.ZipFile(io.BytesIO(self._nul_zip())) as zf:
            info = next(i for i in zf.infolist() if i.orig_filename != i.filename)
        assert info.orig_filename == self.REAL
        assert info.filename == "templates/x/.thumbnail"
        # ...and the truncated form is exactly the allowlisted thumbnail shape, which
        # is what made this exploitable rather than merely untidy.
        from src.services.design_system_service import _is_template_preview

        assert _is_template_preview(info.filename) is True

    def test_the_bundle_is_refused(self):
        from src.services.design_system_service import DesignSystemImportError, import_bundle

        with _isolated_session() as isolated:
            with pytest.raises(DesignSystemImportError) as exc:
                import_bundle(isolated, zip_bytes=self._nul_zip(), user="u")
        assert "nul" in str(exc.value).lower()

    def test_nothing_is_stored_under_the_truncated_name(self):
        from src.database.models.design_system import DesignSystemFile
        from src.services.design_system_service import DesignSystemImportError, import_bundle

        with _isolated_session() as isolated:
            with pytest.raises(DesignSystemImportError):
                import_bundle(isolated, zip_bytes=self._nul_zip(), user="u")
            isolated.rollback()
            assert isolated.query(DesignSystemFile).all() == []

    def test_the_iterator_refuses_it_too_not_only_the_up_front_scan(self):
        """Both gates, so the entry cannot reach storage through the iterator if the
        up-front scan is ever bypassed or reordered."""
        from src.services.design_system_service import (
            DesignSystemImportError,
            _iter_safe_entries,
        )

        with zipfile.ZipFile(io.BytesIO(self._nul_zip())) as zf:
            with pytest.raises(DesignSystemImportError):
                list(_iter_safe_entries(zf, ""))


class TestOnePathClaimedTwiceIsRefusedNotDecidedByZipOrder:
    """Strict validation does not close identity collapse on its own.

    With no rewrite left in the validator, the surviving route is a zip that carries
    the SAME arcname twice: both names identical, both perfectly canonical, nothing
    for a path rule to object to, and only member order deciding which bytes a reader
    gets. That is why the duplicate-CLAIM check stays — it catches collisions by their
    effect rather than by any shape someone anticipated.
    """

    @staticmethod
    def _duplicate_zip(arcname, *, reverse=False):
        """One bundle carrying ``arcname`` twice, with differing bytes.

        The two payloads are distinguishable so "which member won" would be readable
        from what got stored, and ``reverse`` swaps their order so an order-dependent
        importer cannot look order-independent.
        """
        manifest = default_manifest()
        manifest["templates"] = [
            {
                "name": "X",
                "description": "Synthetic layout.",
                "folder": "templates/x",
                "entryPath": "templates/x/index.html",
            }
        ]
        payloads = [COLLIDING_FIRST_BYTES, COLLIDING_SECOND_BYTES]
        if reverse:
            payloads.reverse()
        buf = io.BytesIO()
        with pytest.warns(UserWarning, match="Duplicate name"):
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr(MANIFEST_FILENAME, json.dumps(manifest).encode())
                zf.writestr("colors_and_type.css", COLORS_AND_TYPE_CSS)
                zf.writestr("README.md", SYNTHETIC_README)
                zf.writestr("assets/logo.svg", SVG_LOGO)
                zf.writestr("templates/x/index.html", SYNTHETIC_TEMPLATE_HTML)
                for payload in payloads:
                    zf.writestr(arcname, payload)
        return buf.getvalue()

    @staticmethod
    def _outcome(zip_bytes):
        from src.services.design_system_service import DesignSystemImportError, import_bundle

        with _isolated_session() as isolated:
            try:
                ds = import_bundle(isolated, zip_bytes=zip_bytes, user="u")
            except DesignSystemImportError as exc:
                return "refused", str(exc)
            return "stored", sorted(
                (f.path, bytes(f.data if f.data is not None else f.asset.data))
                for f in ds.files
            )

    @pytest.mark.parametrize("arcname", DUPLICATE_CLAIM_ARCNAMES, ids=repr)
    def test_the_same_arcname_twice_is_refused(self, arcname):
        verdict, detail = self._outcome(self._duplicate_zip(arcname))
        assert verdict == "refused", (
            f"{arcname!r} appears twice, but the import succeeded and kept {detail!r}"
        )
        assert arcname in detail
        assert "re-create the archive" in detail.lower()

    @pytest.mark.parametrize("arcname", DUPLICATE_CLAIM_ARCNAMES, ids=repr)
    def test_zip_member_order_does_not_change_the_outcome(self, arcname):
        forward = self._outcome(self._duplicate_zip(arcname))
        reverse = self._outcome(self._duplicate_zip(arcname, reverse=True))
        assert forward == reverse, (
            f"reversing the two {arcname!r} members changed the outcome: "
            f"forward={forward!r} reverse={reverse!r}"
        )

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
    def _verdicts(arcname, root_prefix=""):
        """``(stored_name, scan_refused, iterator_verdict)`` from the real gates.

        With a ``root_prefix``, the archive entry is ``root_prefix + arcname`` and the
        iterator is asked to strip it — which is how a wrapped bundle is really
        imported.
        """
        from src.services.design_system_service import (
            DesignSystemImportError,
            _assert_bundle_paths_safe,
            _iter_safe_entries,
        )

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(root_prefix + arcname, webp_bytes())
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
                yielded = [rel for _, rel in _iter_safe_entries(zf, root_prefix)]
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

    def test_under_a_wrapped_root_the_iterator_is_never_more_permissive(self):
        """The corpus run with a NON-EMPTY root_prefix — the case that was never
        exercised, and the one the backslash bypass lived in.

        The property asserted here is deliberately the SAFETY DIRECTION rather than
        strict equality, because with a prefix the two gates judge different strings
        by design: the scan sees ``safe/<shape>`` while the iterator sees ``<shape>``,
        and two rules are position-anchored (a drive letter at position 0, the
        ``templates/`` thumbnail allowlist at position 0). So ``safe/C:/x`` is an
        ordinary relative path to the scan and a drive-letter path to the iterator —
        a legitimate difference, and it fails CLOSED.

        What must never happen is the reverse: an entry the whole-bundle scan refuses
        going on to be STORED by the iterator. That direction is what the original
        regression did, and it is what this pins.
        """
        violations = []
        for arcname in _gate_corpus():
            stored_name, scan_refused, iterator = self._verdicts(
                arcname, root_prefix="safe/"
            )
            if scan_refused and iterator[0] == "stored":
                violations.append({"arcname": stored_name, "stored_as": iterator[1]})
        assert violations == [], (
            f"the iterator stored {len(violations)} entries the whole-bundle scan "
            f"refuses: {violations}"
        )

    def test_the_wrapped_corpus_run_is_not_vacuous(self):
        """The test above would pass trivially if nothing were ever stored under a
        prefix, or if the scan refused everything."""
        seen = {"refused": 0, "skipped": 0, "stored": 0}
        scan_refusals = 0
        for arcname in _gate_corpus():
            _, scan_refused, iterator = self._verdicts(arcname, root_prefix="safe/")
            seen[iterator[0]] += 1
            scan_refusals += int(scan_refused)
        assert all(count > 0 for count in seen.values()), seen
        assert scan_refusals > 0

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


# ---------------------------------------------------------------------------
# Concurrent same-name import: a CONFLICT, never an opaque server error
# ---------------------------------------------------------------------------


class TestConcurrentSameNameImportIsAConflict:
    """Two importers racing for one name: the loser gets the same 409 the
    sequential path returns, not an opaque 500.

    The fail-fast name check is a SELECT taken before all the expensive
    collect/compile work, and the partial unique index
    ``uq_design_system_name_active`` is what actually decides. Two overlapping
    importers both pass the SELECT, so the loser meets the index only at its
    write — measured live as ``HTTP 500 {"detail":"Failed to import design
    system"}`` while the sequential path returns a precise 409 naming the
    winner. No data-integrity bug (the index held, the rollback held); a wrong
    status code and an unactionable message on a race a user hits by
    double-clicking Import.
    """

    def _bootstrap_db(self, tmp_path):
        url = f"sqlite:///{tmp_path}/design_systems.db"
        bootstrap = create_engine(url)
        Base.metadata.create_all(bind=bootstrap)
        bootstrap.dispose()
        return url

    def test_two_concurrent_imports_of_one_name_give_one_success_one_conflict(
        self, tmp_path
    ):
        """DETERMINISTIC by construction, not by timing.

        A barrier holds BOTH importers between their pre-check SELECT and their
        first write, so the TOCTOU window is provably open; the writes are then
        strictly ordered so the loser's INSERT meets a COMMITTED row. Nothing
        here depends on how fast either thread runs.

        Writes must be ordered rather than merely concurrent because SQLite
        refuses a write-after-read lock upgrade with SQLITE_BUSY, which would
        make the test flake on lock contention instead of exercising the index.
        """
        import threading

        from src.database.models.design_system import (
            DesignSystemAsset,
            DesignSystemFile,
            DesignSystemTemplate,
            DesignSystemToken,
        )
        from src.services import design_system_service
        from src.services.design_system_service import (
            DesignSystemNameConflictError,
            import_bundle,
        )

        url = self._bootstrap_db(tmp_path)
        both_prechecked = threading.Barrier(2)
        first_committed = threading.Event()
        real_collect = design_system_service._collect_assets_and_files
        outcomes: dict[str, str] = {}
        conflict_messages: list[str] = []

        def _collect_then_sequence(*args, **kwargs):
            result = real_collect(*args, **kwargs)
            # Reached AFTER the fail-fast name SELECT and BEFORE any write.
            both_prechecked.wait(timeout=30)
            if threading.current_thread().name == "importer-second":
                first_committed.wait(timeout=30)
            return result

        def _run(tag):
            engine = create_engine(url, connect_args={"timeout": 30})
            try:
                with Session(engine) as db:
                    try:
                        import_bundle(
                            db,
                            zip_bytes=make_bundle_zip(),
                            user="racer@example.com",
                            name_override="Race Me",
                        )
                        outcomes[tag] = "created"
                    except DesignSystemNameConflictError as exc:
                        db.rollback()
                        outcomes[tag] = "conflict"
                        conflict_messages.append(str(exc))
                    except Exception as exc:  # noqa: BLE001 - recorded, then asserted on
                        db.rollback()
                        outcomes[tag] = f"{type(exc).__name__}: {exc}"
            finally:
                if tag == "first":
                    first_committed.set()
                engine.dispose()

        with patch.object(
            design_system_service,
            "_collect_assets_and_files",
            _collect_then_sequence,
        ):
            threads = [
                threading.Thread(target=_run, args=(tag,), name=f"importer-{tag}")
                for tag in ("first", "second")
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=60)
            assert not any(t.is_alive() for t in threads), "importer thread hung"

        assert sorted(outcomes.values()) == ["conflict", "created"], outcomes
        # Actionable, and it names the name the caller must change.
        assert "Race Me" in conflict_messages[0]
        assert "already exists" in conflict_messages[0]

        # ZERO ORPHAN ROWS: the loser's rollback left nothing behind, so the
        # winner owns every child row in the database.
        verify = create_engine(url)
        with Session(verify) as db:
            systems = db.query(DesignSystem).all()
            assert len(systems) == 1, [(s.id, s.name) for s in systems]
            winner_id = systems[0].id
            for model in (
                DesignSystemToken,
                DesignSystemAsset,
                DesignSystemFile,
                DesignSystemTemplate,
            ):
                rows = db.query(model).all()
                assert all(r.design_system_id == winner_id for r in rows), (
                    f"orphan {model.__name__} rows survived the loser's rollback"
                )
            # Non-vacuity for the sweep above: the winner really did write child
            # rows, so "no orphans" is not just an empty database. (The default
            # synthetic manifest declares no templates[], so DesignSystemTemplate
            # is legitimately empty and is checked for orphans only.)
            for model in (DesignSystemToken, DesignSystemAsset, DesignSystemFile):
                assert db.query(model).count() > 0, (
                    f"{model.__name__} should carry the winner's rows"
                )
        verify.dispose()

    def test_the_precheck_still_wins_when_there_is_no_race(self, tmp_path):
        """Non-vacuity: without the barrier the SEQUENTIAL path is what answers,
        so the test above is measuring the race and not the pre-check."""
        from src.services.design_system_service import (
            DesignSystemNameConflictError,
            import_bundle,
        )

        url = self._bootstrap_db(tmp_path)
        engine = create_engine(url, connect_args={"timeout": 30})
        with Session(engine) as db:
            first = import_bundle(
                db, zip_bytes=make_bundle_zip(), user="u", name_override="Race Me"
            )
            with pytest.raises(DesignSystemNameConflictError) as excinfo:
                import_bundle(
                    db, zip_bytes=make_bundle_zip(), user="u", name_override="Race Me"
                )
        # The sequential message can name the winner's id; the race one cannot.
        assert f"id={first.id}" in str(excinfo.value)
        engine.dispose()


class TestTranslateNameConflictError:
    """The translator matches THIS index and nothing else."""

    def _integrity_error(self, orig):
        from sqlalchemy.exc import IntegrityError

        return IntegrityError(
            "INSERT INTO design_system (name) VALUES (?)", {}, orig
        )

    def _pg_error(self, sqlstate, constraint_name, message):
        class _Diag:
            pass

        diag = _Diag()
        diag.constraint_name = constraint_name

        class _PgError(Exception):
            pass

        err = _PgError(message)
        err.pgcode = sqlstate
        err.diag = diag
        return err

    def test_translates_a_unique_violation_on_the_active_name_index(self):
        from src.services.design_system_service import (
            DesignSystemNameConflictError,
            translate_name_conflict_error,
        )

        exc = self._integrity_error(
            self._pg_error(
                "23505",
                "uq_design_system_name_active",
                'duplicate key value violates unique constraint '
                '"uq_design_system_name_active"\nDETAIL:  Key (name)=(Acme) already exists.',
            )
        )
        with pytest.raises(DesignSystemNameConflictError) as excinfo:
            translate_name_conflict_error(exc, name="Acme")
        assert "Acme" in str(excinfo.value)

    def test_translates_the_sqlite_form_of_the_same_index(self):
        """SQLite names the COLUMN rather than the index, and it is the same rule
        (this is the only unique index over design_system.name)."""
        import sqlite3

        from src.services.design_system_service import (
            DesignSystemNameConflictError,
            translate_name_conflict_error,
        )

        exc = self._integrity_error(
            sqlite3.IntegrityError("UNIQUE constraint failed: design_system.name")
        )
        with pytest.raises(DesignSystemNameConflictError):
            translate_name_conflict_error(exc, name="Acme")

    @pytest.mark.parametrize(
        "orig_factory,label",
        [
            # A unique violation on a DIFFERENT constraint must keep its own
            # identity — reporting it as a name conflict would send the caller
            # off to rename something that is not the problem.
            (
                lambda self: self._pg_error(
                    "23505",
                    "uq_session_lock",
                    'duplicate key value violates unique constraint "uq_session_lock"',
                ),
                "other unique constraint",
            ),
            # NOT NULL, foreign key, check: all IntegrityError, none a conflict.
            (
                lambda self: self._pg_error(
                    "23502", None, 'null value in column "name" violates not-null constraint'
                ),
                "not-null violation",
            ),
            (
                lambda self: self._pg_error(
                    "23503",
                    "design_system_asset_design_system_id_fkey",
                    "insert or update on table violates foreign key constraint",
                ),
                "foreign key violation",
            ),
            (
                lambda self: __import__("sqlite3").IntegrityError(
                    "UNIQUE constraint failed: design_system_template.name"
                ),
                "unique violation on another table",
            ),
            (
                lambda self: __import__("sqlite3").IntegrityError(
                    "NOT NULL constraint failed: design_system.name"
                ),
                "sqlite not-null violation",
            ),
        ],
    )
    def test_leaves_every_other_integrity_error_alone(self, orig_factory, label):
        from src.services.design_system_service import translate_name_conflict_error

        exc = self._integrity_error(orig_factory(self))
        # Returns without raising: the caller's own `raise` then surfaces the
        # real error instead of a misleading 409.
        translate_name_conflict_error(exc, name="Acme")

    def test_leaves_an_unrelated_exception_alone(self):
        from src.services.design_system_service import translate_name_conflict_error

        translate_name_conflict_error(
            ValueError("some entirely unrelated failure"), name="Acme"
        )

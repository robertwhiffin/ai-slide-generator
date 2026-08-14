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
        info.extra = extra
        zf.writestr(info, payload)
    return buf.getvalue()


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
        """A malformed record must not import. It happens to be caught one layer lower
        — CPython validates extra-field framing while building the ZipFile and raises
        ``BadZipFile``, which surfaces as "not a valid .zip bundle" — so this asserts
        the OUTCOME rather than a message this code owns.
        """
        from src.services.design_system_service import DesignSystemImportError, import_bundle

        # Declares 40 bytes of payload but supplies 2.
        extra = struct.pack("<HH", 0x7075, 40) + b"\x01\x02"
        with _isolated_session() as isolated:
            with pytest.raises(DesignSystemImportError):
                import_bundle(isolated, zip_bytes=self._zip(extra=extra), user="u")

    @pytest.mark.parametrize(
        "extra",
        [
            struct.pack("<HH", 0x7075, 40) + b"\x01\x02",       # size overruns the field
            struct.pack("<HH", 0x7075, 3) + b"\x01\x02\x03",    # body shorter than 5
            struct.pack("<HH", 0x7075, 7) + b"\x01\x00\x00\x00\x00\xff\xfe",  # bad UTF-8
        ],
        ids=["overrun", "short-body", "invalid-utf8"],
    )
    def test_the_parser_reports_malformed_records_rather_than_raising(self, extra):
        """Unit-level, deliberately: every malformed shape above is rejected by the
        stdlib before this function is reached through a real archive, so an
        archive-level test could not distinguish "handled" from "never called".

        Tested directly anyway, because the parser reads attacker-controlled bytes and
        must not depend on another layer having screened them first — the premise of
        this whole series is not trusting what a lower layer did with a name.
        """
        from src.services.design_system_service import (
            _REASON_CORRUPT_EXTRA,
            _extra_field_name_refusal,
        )

        info = zipfile.ZipInfo("assets/logo.svg")
        info.extra = extra
        assert _extra_field_name_refusal(info) == _REASON_CORRUPT_EXTRA

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
        info = zipfile.ZipInfo("assets/logo.svg")
        info.extra = timestamp + unicode_path
        assert _extra_field_name_refusal(info) == _REASON_NAME_MISMATCH

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

"""The IMPORTER must persist a token group exactly as the brand authored it.

Round 10 taught the COMPILER to show an author-invented group label with its
authored whitespace intact (``tests/unit/test_design_system_compiler_group_labels.py``
:class:`TestTheLabelIsTheBrandsOwnSpelling`). That fix was real and is still green —
and it was UNOBSERVABLE in production, because every one of those tests builds its
``DesignSystemToken`` rows directly and hands them to ``compile_design_system``.
The real upload path does not. It goes through
:func:`src.services.design_system_service.import_bundle`, which called
``_canonicalize_token`` — and that returned ``group.strip()`` for an unrecognized
group, destroying the authored padding BEFORE any row was ever written. The
compiler was preserving whitespace that no longer existed by the time it ran.

A runtime probe through ``import_bundle`` with the groups ``" Brand Semantic "`` and
``" brand-type "`` showed the loss in both display positions at once::

    stored groups: ["'Brand Semantic'", "'brand-type'"]
    '- Grouped by the brand as: "Brand Semantic"'
    '  (grouped by the brand as: "brand-type")'

So the label the brand is shown is not the label the brand wrote, in the generic
section AND in the re-homed font-size attribution.

That is why every test here runs a REAL BUNDLE IMPORT. A hand-built ORM object
cannot fail this way; the defect lives precisely in the step those tests skip. The
assertions are deliberately doubled — the STORED value and the COMPILED artifact —
because either alone would have passed at some point in this defect's life: storage
was intact before the label was ever displayed, and display was correct in tests
while storage was already lossy.

The split the fix applies is the same one Round 10 applied inside the compiler:
strip for the LOOKUP KEY and the EMPTINESS CHECK, never for the STORED VALUE.

All fixtures SYNTHETIC (invented "Acme" brand, dummy hex).
"""

import itertools
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import src.database.models  # noqa: F401 - register models with Base.metadata
from src.core.database import Base
from src.services.design_system_compiler import (
    _GROUP_LABEL_LINE_PREFIX,
    _RE_HOMED_GROUP_ATTRIBUTION_PREFIX,
)
from tests.unit.conftest_design_system import default_manifest, make_bundle_zip

#: ``design_system.name`` is UNIQUE, so each import within a session needs a name.
_ds_counter = itertools.count()


@pytest.fixture
def session():
    """In-memory SQLite session (StaticPool keeps one connection alive)."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    with Session(engine) as s:
        yield s
    engine.dispose()


def _import_with_tokens(session, tokens):
    """Import a real synthetic bundle whose manifest carries exactly *tokens*.

    The bundle is built and zipped by the shared fixture helper and read back
    through the production importer, so the manifest-token path — the one the
    upload endpoint uses — is what runs. ``css=None`` keeps the bundle's declared
    CSS from contributing extra ``:root`` tokens, so the assertions below concern
    only the tokens the test named.
    """
    from src.services.design_system_service import import_bundle

    manifest = default_manifest()
    manifest["name"] = f"Acme Imported DS {next(_ds_counter)}"
    manifest["tokens"] = tokens
    manifest["globalCssPaths"] = []
    return import_bundle(
        session, zip_bytes=make_bundle_zip(manifest=manifest, css=None), user="u"
    )


def _stored_group(design_system, token_name):
    """The group value PERSISTED for *token_name* — the thing the fix is about."""
    matches = [t for t in design_system.tokens if t.name == token_name]
    assert len(matches) == 1, f"expected one {token_name!r} row, got {matches!r}"
    return matches[0].group


def _label_line(label):
    """The generic section's data line for *label* (``json.dumps``-quoted)."""
    return f"{_GROUP_LABEL_LINE_PREFIX}{json.dumps(label, ensure_ascii=False)}"


def _attribution_line(label):
    """The re-homed font-size attribution note for *label*."""
    return (
        f"{_RE_HOMED_GROUP_ATTRIBUTION_PREFIX}"
        f"{json.dumps(label, ensure_ascii=False)})"
    )


class TestAPaddedUnknownGroupSurvivesTheImport:
    """(a) A padded author-invented group, shown in the generic section."""

    #: Real padding shapes a brand can author in a manifest. Every character here
    #: is a SPACE or a printable glyph — see ``test_a_tab_is_stored_verbatim_and
    #: _sanitized_only_for_display`` for why a TAB is stored but not displayed.
    _PADDED = (
        pytest.param(" Brand Semantic ", id="both-sides"),
        pytest.param(" leading", id="leading"),
        pytest.param("trailing ", id="trailing"),
        pytest.param("  two both  ", id="both-doubled"),
        pytest.param(" 意味論 ", id="padded-cjk"),
    )

    @pytest.mark.parametrize("group", _PADDED)
    def test_the_authored_padding_reaches_storage(self, session, group):
        """The importer must write the group the brand wrote, byte for byte."""
        ds = _import_with_tokens(
            session, [{"group": group, "name": "tok-one", "value": "#123456"}]
        )

        assert _stored_group(ds, "tok-one") == group, (
            "the importer altered the brand's group before storing it; the "
            "compiler's whitespace fidelity is unobservable in production"
        )

    @pytest.mark.parametrize("group", _PADDED)
    def test_the_authored_padding_reaches_the_artifact(self, session, group):
        """And the compiled artifact shows that same spelling."""
        ds = _import_with_tokens(
            session, [{"group": group, "name": "tok-one", "value": "#123456"}]
        )

        assert _label_line(group) in ds.compiled_style_content, (
            "the label in the artifact is not the label the brand authored"
        )

    def test_a_tab_is_stored_verbatim_and_sanitized_only_for_display(self, session):
        """A TAB separates the two layers, and both behaviours are correct.

        A tab is Unicode category ``Cc`` — a C0 CONTROL, not a space. The compiler
        drops C0/C1 characters at every interpolation point on purpose: that is what
        makes the type-scale region sentinels unforgeable, and the group-label suite
        already classes ``"\\t"`` with the controls rather than with the whitespace it
        preserves. So DISPLAY must keep dropping it.

        STORAGE is a different question, and it is this item's question: the importer
        has no business editing the brand's string on its way to the database. The tab
        is persisted exactly as authored, and sanitization stays where it belongs — at
        the interpolation boundary, applied by the compiler, once.

        Pinning both halves in one test keeps a future round from "fixing" the display
        side by weakening the control-stripping guard.
        """
        group = "\tbrand-tabbed\t"
        ds = _import_with_tokens(
            session, [{"group": group, "name": "tok-one", "value": "#123456"}]
        )

        assert _stored_group(ds, "tok-one") == group, (
            "the importer edited a control character out of the stored brand text"
        )
        assert _label_line("brand-tabbed") in ds.compiled_style_content, (
            "the tab must be dropped at DISPLAY by the compiler's control filter"
        )

    def test_the_token_itself_still_lands(self, session):
        """Preserving the group must not disturb the token it belongs to."""
        ds = _import_with_tokens(
            session, [{"group": " Brand Semantic ", "name": "tok-one", "value": "#0A0B0C"}]
        )

        assert "- tok-one: #0A0B0C" in ds.compiled_style_content


class TestAPaddedGroupSurvivesWhenItsOnlyTokenIsReHomed:
    """(b) The group's ONLY token is a font size, so the label appears as the
    re-homed attribution note instead of a generic-section label line.

    This is the second display position Round 10 built, and it reads the same stored
    string — so the importer's strip broke both at once. Asserted separately because
    the two positions are produced by different code paths in the compiler, and a
    fix that only satisfied one would be a partial fix.
    """

    _PADDED = (
        pytest.param(" brand-type ", id="both-sides"),
        pytest.param(" marketing-scale", id="leading"),
        pytest.param("display-sizes ", id="trailing"),
        pytest.param(" ブランド型 ", id="padded-cjk"),
    )

    @pytest.mark.parametrize("group", _PADDED)
    def test_the_authored_padding_reaches_storage(self, session, group):
        ds = _import_with_tokens(
            session, [{"group": group, "name": "fs-hero", "value": "64px"}]
        )

        assert _stored_group(ds, "fs-hero") == group, (
            "the importer altered the brand's group before storing it"
        )

    @pytest.mark.parametrize("group", _PADDED)
    def test_the_authored_padding_reaches_the_attribution(self, session, group):
        ds = _import_with_tokens(
            session, [{"group": group, "name": "fs-hero", "value": "64px"}]
        )

        assert _attribution_line(group) in ds.compiled_style_content, (
            "the re-homed attribution shows a group label the brand did not write"
        )

    def test_the_lone_re_homed_group_emits_no_generic_label_line(self, session):
        """The control for (b): there IS no generic section to carry the label.

        Pins WHY the attribution position exists — if a generic label line appeared
        here too, the test above would be passing for the wrong reason.
        """
        ds = _import_with_tokens(
            session, [{"group": " brand-type ", "name": "fs-hero", "value": "64px"}]
        )

        assert _GROUP_LABEL_LINE_PREFIX not in ds.compiled_style_content
        assert "- fs-hero: 64px" in ds.compiled_style_content


class TestTheExistingNormalisationIsUnchanged:
    """Preserving the stored value must not cost any behaviour that already held.

    Each of these passed BEFORE the fix and must still pass after it: the fix is a
    split between the lookup key and the stored value, not a removal of
    normalisation. Run through ``import_bundle`` for the same reason as above.
    """

    @pytest.mark.parametrize(
        "authored,canonical",
        [
            pytest.param("  CORE ", "core", id="padded-upper-core"),
            pytest.param(" Type ", "type", id="padded-title-type"),
            pytest.param("SPACING", "spacing", id="upper-spacing"),
            pytest.param(" shadow ", "shadow", id="padded-shadow"),
            pytest.param(" Accents ", "accents", id="padded-accents"),
        ],
    )
    def test_a_recognised_group_still_maps_to_its_canonical_spelling(
        self, session, authored, canonical
    ):
        """A RECOGNISED group is this app's own vocabulary, so it still normalises.

        The author's padding/casing identifies which canonical group they meant; the
        canonical spelling is what the purpose-built emitters require.
        """
        ds = _import_with_tokens(
            session, [{"group": authored, "name": "tok-one", "value": "#123456"}]
        )

        assert _stored_group(ds, "tok-one") == canonical

    def test_a_colour_subgroup_encoded_in_the_name_is_unaffected(self, session):
        """Rule 2 (no explicit group): the name's leading segment still decides."""
        ds = _import_with_tokens(
            session, [{"name": "--brand-accents-lava", "value": "#EB4A34"}]
        )

        assert _stored_group(ds, "lava") == "accents"

    @pytest.mark.parametrize(
        "kind,expected",
        [
            pytest.param("color", "core", id="color"),
            pytest.param("font", "type", id="font"),
            pytest.param("spacing", "spacing", id="spacing"),
            pytest.param("shadow", "shadow", id="shadow"),
        ],
    )
    def test_the_manifest_kind_path_is_unaffected(self, session, kind, expected):
        """Rule 3 (no explicit group): ``kind`` still decides, padding and all."""
        ds = _import_with_tokens(
            session,
            [{"name": "--tok-one", "value": "#123456", "kind": f"  {kind.upper()} "}],
        )

        assert _stored_group(ds, "tok-one") == expected

    def test_padding_variants_still_collapse_into_one_labelled_section(self, session):
        """The grouping guarantee, now proven through the importer.

        Two tokens whose groups differ ONLY in padding must share ONE section with
        ONE label — the compiler's normalised lookup key does that, and storing the
        verbatim value must not undo it. This is the assertion that would fail if the
        fix had simply removed the strip everywhere.
        """
        ds = _import_with_tokens(
            session,
            [
                {"group": " brand-pad ", "name": "tok-a", "value": "#123456"},
                {"group": "brand-pad", "name": "tok-b", "value": "#654321"},
            ],
        )

        compiled = ds.compiled_style_content
        assert compiled.count(_GROUP_LABEL_LINE_PREFIX) == 1, (
            "padding variants must collapse into ONE labelled section"
        )
        assert "- tok-a: #123456" in compiled
        assert "- tok-b: #654321" in compiled

    def test_casing_variants_still_collapse_into_one_labelled_section(self, session):
        """The same guarantee for casing, also through the importer."""
        ds = _import_with_tokens(
            session,
            [
                {"group": "Brand-Semantic", "name": "tok-a", "value": "#123456"},
                {"group": "brand-semantic", "name": "tok-b", "value": "#654321"},
            ],
        )

        compiled = ds.compiled_style_content
        assert compiled.count(_GROUP_LABEL_LINE_PREFIX) == 1, (
            "casing variants must collapse into ONE labelled section"
        )
        assert "- tok-a: #123456" in compiled
        assert "- tok-b: #654321" in compiled

    @pytest.mark.parametrize(
        "group",
        [
            pytest.param(" ", id="single-space"),
            pytest.param("   ", id="several-spaces"),
            pytest.param("\t", id="tab"),
            pytest.param("\n", id="newline-only"),
        ],
    )
    def test_a_whitespace_only_group_is_still_treated_as_absent(self, session, group):
        """The EMPTINESS CHECK keeps stripping — that half of the split stays.

        A group that is nothing but whitespace expresses no grouping intent, so the
        importer must fall through to inference exactly as it does for no group at
        all (here: value-inferred ``core`` for a hex). Storing ``"   "`` verbatim
        would invent a group the brand never named.
        """
        ds = _import_with_tokens(
            session, [{"group": group, "name": "tok-one", "value": "#123456"}]
        )

        assert _stored_group(ds, "tok-one") == "core"
        assert _GROUP_LABEL_LINE_PREFIX not in ds.compiled_style_content


class TestTheSameClassElsewhereInTheImporter:
    """The audit that follows from the group defect: the SAME shape, other fields.

    The group bug was not "a stray ``.strip()``" — it was a boundary that edited
    brand text on the way to storage while believing it was normalising a key. So
    every other free-prose brand string the importer persists is checked for it here.

    IN CLASS (fixed, asserted below): the design-system NAME, the DESCRIPTION, and a
    manifest TEMPLATE's name/description. All are free-form prose displayed back to
    the brand and to the model; none is a lookup key, a path, or an identifier; each
    was being ``.strip()``-ed into storage.

    OUT OF CLASS (deliberately unchanged, and pinned by the tests in the last two
    methods so a later round does not "tidy" them):

    * a token NAME — normalised by ``_strip_token_ident`` into a CSS-identifier-shaped
      key that must dedup a manifest ``--brand-core-primary`` against a CSS
      ``primary``. It is an identifier, not prose.
    * a token VALUE — a CSS declaration value, where surrounding whitespace is not
      meaningful and the parsed CSS form is the point.
    * a font FAMILY — joined across ``fonts[]`` and ``brandFonts[]`` on the family
      string, so it is a genuine join key; CSS family matching is itself
      whitespace/case-insensitive (``design_system_templates._font_face_families``).
    * an asset FILENAME — already stored verbatim (probed), because it comes from the
      zip entry name rather than from a normalising branch.
    """

    def test_a_padded_design_system_name_is_stored_as_authored(self, session):
        """The name is the brand's title for its own system — prose, not a key.

        It is compared for uniqueness, but an exact comparison of verbatim values is
        what the UNIQUE index already does, and the PUT/rename path
        (``routes/settings/design_systems.py``) ALREADY assigns ``request.name``
        unstripped. The importer was the inconsistent boundary: the same name typed
        into rename was preserved and imported was edited.
        """
        ds = _import_with_tokens(session, [{"group": "core", "name": "t", "value": "#123456"}])
        # The helper names the system itself, so re-import under a padded override.
        from src.services.design_system_service import import_bundle

        manifest = default_manifest()
        manifest["name"] = "  Padded Manifest Name  "
        manifest["globalCssPaths"] = []
        manifest["tokens"] = [{"group": "core", "name": "t", "value": "#123456"}]
        imported = import_bundle(
            session, zip_bytes=make_bundle_zip(manifest=manifest, css=None), user="u"
        )

        assert imported.name == "  Padded Manifest Name  ", (
            "the importer edited the brand's own name for its design system"
        )
        assert ds is not None  # the first import is only here to prove no clash

    def test_a_padded_name_override_is_stored_as_authored(self, session):
        """The override is text a human typed into the upload form."""
        from src.services.design_system_service import import_bundle

        manifest = default_manifest()
        manifest["name"] = "Unused Manifest Name"
        manifest["globalCssPaths"] = []
        manifest["tokens"] = [{"group": "core", "name": "t", "value": "#123456"}]
        imported = import_bundle(
            session,
            zip_bytes=make_bundle_zip(manifest=manifest, css=None),
            user="u",
            name_override="  Padded Override  ",
        )

        assert imported.name == "  Padded Override  "

    #: Padding shapes for a README H1, one per Unicode whitespace class a brand can
    #: actually type into a heading. EM SPACE is the reviewer's reproducer; the ASCII
    #: space and the NO-BREAK SPACE are here because the fix must be about the
    #: WHITESPACE CLASS, not about one code point that happened to be reported.
    _PADDED_H1 = (
        pytest.param(" ", id="em-space"),
        pytest.param(" ", id="ascii-space"),
        pytest.param(" ", id="no-break-space"),
        pytest.param("　", id="ideographic-space"),
    )

    @pytest.mark.parametrize("pad", _PADDED_H1)
    def test_a_padded_readme_h1_name_is_stored_as_authored(self, session, pad):
        """The README H1 is the brand's own title for its system, in its own file.

        THE LAST NAME CANDIDATE STILL EDITED ON INGRESS. The previous round fixed the
        manifest-name and the upload-form override, but the H1 reaches ``_resolve_name``
        already normalised — ``_read_readme_h1`` matched on ``line.strip()``, and its
        regex ate the padding via ``\\s+``/``\\s*`` before ``.strip()``-ing the captured
        group a third time. So the candidate ``_resolve_name`` faithfully returns
        verbatim was never the authored text, and the loss is PERMANENT: the padding is
        gone from the database, not merely from a display.

        A heading's MARKDOWN DELIMITERS are syntax and are correctly removed (the
        leading ``#`` run, the optional closing ``#`` run). Its CONTENT is prose.
        """
        from src.services.design_system_service import import_bundle
        from tests.unit.conftest_design_system import SVG_LOGO

        authored = f"{pad} README Brand {pad}"
        manifest = default_manifest()
        # The H1 must be the ONLY name source, so the earlier candidates are absent:
        # no override argument, and no manifest ``name`` key at all.
        manifest.pop("name")
        manifest["globalCssPaths"] = []
        manifest["tokens"] = [{"group": "core", "name": "t", "value": "#123456"}]
        imported = import_bundle(
            session,
            zip_bytes=make_bundle_zip(
                manifest=manifest,
                css=None,
                files={
                    # ``# `` is the markdown delimiter — the hash plus the ONE space
                    # that makes the line a heading. Everything after it is the
                    # brand's authored heading content, padding included.
                    "README.md": f"# {authored}\n\nSynthetic body prose.\n".encode(),
                    "assets/logo.svg": SVG_LOGO,
                },
            ),
            user="u",
        )

        assert imported.name == authored, (
            "the importer edited the brand's README heading before storing it as the "
            "design system's name"
        )

    def test_a_whitespace_only_readme_h1_still_falls_through(self, session):
        """The EMPTINESS half of the split, for the H1 candidate.

        A heading that is nothing but whitespace states no title, so naming must fall
        through to the next candidate exactly as it does when there is no README at
        all — here the zip filename. Only the emptiness CHECK may normalise; what gets
        stored is what the brand wrote.
        """
        from src.services.design_system_service import import_bundle
        from tests.unit.conftest_design_system import SVG_LOGO

        manifest = default_manifest()
        manifest.pop("name")
        manifest["globalCssPaths"] = []
        manifest["tokens"] = [{"group": "core", "name": "t", "value": "#123456"}]
        imported = import_bundle(
            session,
            zip_bytes=make_bundle_zip(
                manifest=manifest,
                css=None,
                files={
                    "README.md": "#     \n\nSynthetic body prose.\n".encode(),
                    "assets/logo.svg": SVG_LOGO,
                },
            ),
            user="u",
            source_filename="acme-fallthrough-bundle.zip",
        )

        assert imported.name == "acme-fallthrough-bundle", (
            "a whitespace-only heading was treated as a usable name"
        )

    def test_a_padded_description_is_stored_as_authored(self, session):
        """The description is free prose, emitted as the artifact's caption."""
        from src.services.design_system_service import import_bundle

        manifest = default_manifest()
        manifest["name"] = "Acme Padded Description DS"
        manifest["description"] = "  padded brand description  "
        manifest["globalCssPaths"] = []
        manifest["tokens"] = [{"group": "core", "name": "t", "value": "#123456"}]
        imported = import_bundle(
            session, zip_bytes=make_bundle_zip(manifest=manifest, css=None), user="u"
        )

        assert imported.description == "  padded brand description  ", (
            "the importer edited the brand's description before storing it"
        )

    def test_a_whitespace_only_description_is_still_absent(self, session):
        """The emptiness half of the split, for the description."""
        from src.services.design_system_service import import_bundle

        manifest = default_manifest()
        manifest["name"] = "Acme Blank Description DS"
        manifest["description"] = "   "
        manifest["globalCssPaths"] = []
        manifest["tokens"] = [{"group": "core", "name": "t", "value": "#123456"}]
        imported = import_bundle(
            session, zip_bytes=make_bundle_zip(manifest=manifest, css=None), user="u"
        )

        assert imported.description is None

    def test_a_padded_template_name_and_description_are_stored_as_authored(self, session):
        """A materialized template carries the brand's own words for the layout."""
        from src.services.design_system_service import import_bundle
        from tests.unit.conftest_design_system import (
            SVG_LOGO,
            SYNTHETIC_README,
            TEMPLATED_TEMPLATE_HTML,
        )

        manifest = default_manifest()
        manifest["name"] = "Acme Padded Template DS"
        manifest["globalCssPaths"] = []
        manifest["tokens"] = [{"group": "core", "name": "t", "value": "#123456"}]
        manifest["templates"] = [
            {
                "name": "  Padded Template  ",
                "description": "  padded layout description  ",
                "folder": "templates/corporate",
                "entryPath": "templates/corporate/index.html",
            }
        ]
        imported = import_bundle(
            session,
            zip_bytes=make_bundle_zip(
                manifest=manifest,
                css=None,
                files={
                    "templates/corporate/index.html": TEMPLATED_TEMPLATE_HTML,
                    "assets/logo.svg": SVG_LOGO,
                    "README.md": SYNTHETIC_README,
                },
            ),
            user="u",
        )

        assert len(imported.templates) == 1
        template = imported.templates[0]
        assert template.name == "  Padded Template  ", (
            "the importer edited the brand's template name before storing it"
        )
        assert template.description == "  padded layout description  "

    def test_a_whitespace_only_template_name_is_still_skipped(self, session):
        """The emptiness half of the split, for a template name.

        A nameless template entry names no layout, so it is still not materialized —
        that check keeps using the stripped form.
        """
        from src.services.design_system_service import import_bundle
        from tests.unit.conftest_design_system import (
            SVG_LOGO,
            SYNTHETIC_README,
            TEMPLATED_TEMPLATE_HTML,
        )

        manifest = default_manifest()
        manifest["name"] = "Acme Blank Template DS"
        manifest["globalCssPaths"] = []
        manifest["tokens"] = [{"group": "core", "name": "t", "value": "#123456"}]
        manifest["templates"] = [
            {
                "name": "   ",
                "folder": "templates/corporate",
                "entryPath": "templates/corporate/index.html",
            }
        ]
        imported = import_bundle(
            session,
            zip_bytes=make_bundle_zip(
                manifest=manifest,
                css=None,
                files={
                    "templates/corporate/index.html": TEMPLATED_TEMPLATE_HTML,
                    "assets/logo.svg": SVG_LOGO,
                    "README.md": SYNTHETIC_README,
                },
            ),
            user="u",
        )

        assert imported.templates == []

    def test_a_token_name_is_still_normalised_into_an_identifier(self, session):
        """OUT OF CLASS, pinned: a token name is a CSS identifier, not prose.

        ``_strip_token_ident`` exists so a manifest ``--brand-core-primary`` and a CSS
        ``primary`` reduce to ONE token rather than two. Preserving padding here would
        break that dedup, which is a data-loss bug of its own (duplicated tokens).
        """
        ds = _import_with_tokens(
            session, [{"group": "brand-x", "name": "  spaced-name  ", "value": "#123456"}]
        )

        assert _stored_group(ds, "spaced-name") == "brand-x"

    def test_a_token_value_is_still_normalised(self, session):
        """OUT OF CLASS, pinned: a CSS declaration value's padding is not meaningful."""
        ds = _import_with_tokens(
            session, [{"group": "brand-x", "name": "tok-one", "value": "  #123456  "}]
        )

        stored = [t for t in ds.tokens if t.name == "tok-one"][0]
        assert stored.value == "#123456"

    def test_an_asset_filename_is_already_stored_verbatim(self, session):
        """OUT OF CLASS because it was never broken — asserted so it stays that way."""
        from src.services.design_system_service import import_bundle
        from tests.unit.conftest_design_system import SVG_LOGO, SYNTHETIC_README

        manifest = default_manifest()
        manifest["name"] = "Acme Padded Filename DS"
        manifest["globalCssPaths"] = []
        manifest["tokens"] = [{"group": "core", "name": "t", "value": "#123456"}]
        imported = import_bundle(
            session,
            zip_bytes=make_bundle_zip(
                manifest=manifest,
                css=None,
                files={
                    "assets/ padded logo .svg": SVG_LOGO,
                    "README.md": SYNTHETIC_README,
                },
            ),
            user="u",
        )

        filenames = [a.filename for a in imported.assets]
        assert " padded logo .svg" in filenames

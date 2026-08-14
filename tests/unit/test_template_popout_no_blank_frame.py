"""WN-01: the template pop-out must never show a blank WHITE frame.

MECHANISM (measured, not inferred): assigning `srcDoc` is a FULL Chromium document
navigation, and a navigating frame shows its pre-paint WHITE canvas until the
megabyte document parses — CDP screencast per click reads white -> uniform dark ->
painted. The pager is PARENT state, so it is already correct during that window,
which is exactly the reported symptom: "Slide 2 of 6" over a white rectangle.
Measured at 4x CPU throttle: 217 ms of pure white on a cold open, 75-85 ms per
next-click, 32/32 pages blank for at least one frame. The SETTLED state is fine on
all 32 pages (0 blank / 383 samples) — the defect lives only in the unsettled
window, which is why a screenshot-stability harness misses it.

Ruled out by measurement, so do not re-diagnose: the frame contract is correct
(exactly one `section` 1280x720@0,0 on all 32 pages), a no-shim control renders
UNIFORM DARK rather than white, missing token CSS still renders dark, and there are
zero unresolved `{{ds-asset:}}` handles. WHITE MEANS NO DOCUMENT IS IN THE FRAME.

These are SOURCE-LEVEL assertions on the wiring, in the same idiom as
``test_export_csp.py`` (which regex-reads slideDocument.ts to pin a shared
constant): the frontend has no unit runner, and the real proof is a CDP frame
timeline, which is deferred to the post-deploy re-run (0 white frames across 32/32
pages, exactly ONE navigation per open, under 4x throttle). What IS pinned here is
every structural property that fix depends on — so it cannot be silently undone,
and so the fix can never be replaced by the cosmetic dark-background variant that
merely HIDES the bug.
"""
from pathlib import Path

import pytest

_FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "src" / "components" / "config"
_THUMBNAIL = _FRONTEND / "TemplateThumbnail.tsx"
_MODAL = _FRONTEND / "TemplateViewerModal.tsx"
_PREVIEW_DOC = _FRONTEND / "templatePreviewDoc.ts"
_DETAIL_PANEL = _FRONTEND / "DesignSystemDetailPanel.tsx"


def _src(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def thumbnail() -> str:
    return _src(_THUMBNAIL)


@pytest.fixture(scope="module")
def preview_doc() -> str:
    return _src(_PREVIEW_DOC)


class TestOneNavigationPerOpen:
    """11.1 — the viewer used to build TWO documents per open."""

    def test_slide_index_is_passed_unconditionally(self):
        """`slideIndex={isPaginated ? index : undefined}` made phase A build the
        FULL multi-megabyte document (slideCount starts at 0, so isPaginated is
        false) and phase B rebuild the isolated one: two navigations, two white
        windows, every open. The builder already falls through to the full document
        for a layout with 0 or 1 slide sections, so passing it unconditionally is
        semantically identical."""
        source = _src(_MODAL)
        assert "slideIndex={index}" in source
        assert "isPaginated ? index" not in source
        assert "slideIndex={isPaginated" not in source

    def test_the_pager_still_only_renders_when_paginated(self):
        """Non-vacuity: `isPaginated` is still what gates the pager CHROME, so the
        change above is about the frame's props and nothing else."""
        source = _src(_MODAL)
        assert "{isPaginated && (" in source


class TestDocumentIsDerivedNotEffectStored:
    """11.3 — an effect-stored document can mount one render behind its props."""

    def test_doc_is_derived_with_use_memo(self, thumbnail):
        assert "const doc = useMemo(" in thumbnail
        assert "renderTemplatePreview(prepared, slideIndex)" in thumbnail

    def test_no_state_setter_holds_the_document(self, thumbnail):
        """The old shape was `const [doc, setDoc] = useState(...)` written from an
        effect keyed on [source, slideIndex], so the iframe could render with a
        document built from the PREVIOUS index."""
        assert "setDoc(" not in thumbnail
        assert "useState<string | null>(null)" not in thumbnail


class TestSourceIsParsedOnce:
    """11.4 — repeated multi-megabyte parses are what widened the white window."""

    def test_prepare_is_memoized_on_the_source_alone(self, thumbnail):
        assert "const prepared = useMemo(" in thumbnail
        assert "prepareTemplatePreview(source.layout_html, source.token_css)" in thumbnail

    def test_the_slide_count_comes_off_that_same_parse(self, thumbnail):
        """It used to come from `countTemplateSlides`, a SECOND full parse of the
        same layout, run on every open purely to size the pager."""
        assert "onSlideCount(prepared.slideCount)" in thumbnail
        assert "countTemplateSlides" not in thumbnail

    def test_the_second_parsing_counter_is_gone(self, preview_doc):
        assert "export function countTemplateSlides" not in preview_doc

    def test_there_is_exactly_one_dom_parser_call_site(self, preview_doc):
        """One `new DOMParser()`, reached only through `parseLayout`, which only
        `prepareTemplatePreview` calls — so a page change cannot re-parse."""
        assert preview_doc.count("new DOMParser()") == 1
        assert preview_doc.count("parseLayout(") == 2  # the definition + one call

    def test_paging_clones_instead_of_mutating_the_shared_parse(self, preview_doc):
        """Isolating a slide must not destroy the shared Document for every other
        page, and must keep REMOVING the other sections rather than hiding them
        with injected CSS (which would fight the template's own cascade)."""
        assert "cloneNode(true)" in preview_doc
        assert "export function renderTemplatePreview" in preview_doc
        assert "export function prepareTemplatePreview" in preview_doc

    def test_the_legacy_entry_point_still_exists(self, preview_doc):
        """`buildTemplatePreviewDoc` is imported by a Playwright spec, so it stays
        as a thin wrapper over prepare+render."""
        assert "export function buildTemplatePreviewDoc" in preview_doc
        assert "renderTemplatePreview(prepareTemplatePreview(" in preview_doc


class TestDoubleBufferedFrames:
    """11.2 — the old frame stays visible until the new one has painted."""

    def test_two_buffers_exist_and_swap_on_load(self, thumbnail):
        assert "const [buffers, setBuffers] = useState<{" in thumbnail
        assert "active: 'a' | 'b'" in thumbnail
        assert "onLoad={() => handleBufferLoad(slot)}" in thumbnail
        assert "renderBuffer('a')" in thumbnail
        assert "renderBuffer('b')" in thumbnail

    def test_a_new_document_goes_to_the_idle_buffer(self, thumbnail):
        """Never to the frame the user is looking at — that is the whole defect."""
        assert "const idle = prev.active === 'a' ? 'b' : 'a'" in thumbnail

    def test_the_idle_buffer_still_paints_so_load_can_fire(self, thumbnail):
        """`display: none` would suppress layout and the load event with it, so the
        idle buffer is transparent instead."""
        assert "opacity: isActive ? 1 : 0" in thumbnail
        assert "display: 'none'" not in thumbnail

    def test_only_the_active_frame_carries_the_test_id(self, thumbnail):
        """Two frames sharing one test id would break every strict-mode locator in
        the Playwright specs."""
        assert "data-testid={isActive ? testId ?? 'template-live-preview' : undefined}" in thumbnail

    def test_the_fix_is_not_the_cosmetic_variant(self, thumbnail):
        """A dark parent-side background would HIDE the white frame rather than
        remove it. The buffer swap is what must be present."""
        assert "handleBufferLoad" in thumbnail


class TestSandboxAndCspAreNotWeakened:
    """The double buffer needs the element-level `load` event, which fires for a
    `sandbox=""` srcdoc frame while `contentDocument` stays blocked — so no
    capability is traded for the signal."""

    def test_the_preview_iframe_is_fully_sandboxed(self, thumbnail):
        """Both buffers render through ONE `<iframe>` element in a helper, so there
        is a single place the sandbox could be weakened."""
        assert thumbnail.count("<iframe") == 1
        start = thumbnail.index("<iframe")
        iframe = thumbnail[start : thumbnail.index("/>", start)]
        assert 'sandbox=""' in iframe
        assert 'sandbox="allow' not in thumbnail

    def test_the_frame_never_reaches_into_the_document(self, thumbnail):
        """Property-access form: the prose above mentions contentDocument by name
        precisely because it must stay unreachable."""
        assert ".contentDocument" not in thumbnail
        assert ".contentWindow" not in thumbnail

    def test_the_preview_csp_is_unchanged(self, preview_doc):
        assert (
            "\"default-src 'none'; style-src 'unsafe-inline'; "
            "img-src data: blob:; font-src data:;\"" in preview_doc
        )

    def test_the_csp_meta_is_still_the_first_fetch_capable_byte(self, preview_doc):
        """The guard block leads the synthesized head, ahead of the template's own
        head content, so nothing the template declares can fetch before the policy
        is in force."""
        assert "${prepared.guard}${prepared.head}${PREVIEW_STAGE_SHIM}" in preview_doc


class TestSmallHardenings:
    """11.5 — two latent teardown paths."""

    def test_a_zero_measurement_never_reaches_the_scale(self, thumbnail):
        """scale === 0 unmounts the iframe, which tears down an in-flight document
        load; a transient zero measurement must not be able to do that."""
        assert "if (!el.offsetWidth) return;" in thumbnail

    def test_the_viewer_modal_is_keyed_by_template(self):
        source = _src(_DETAIL_PANEL)
        modal = source[source.index("<TemplateViewerModal") :]
        assert "key={viewerTemplate.id}" in modal[:400]

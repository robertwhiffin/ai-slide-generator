import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { Button } from '@/ui/button';
import type { Slide } from '../../types/slide';
import { useViewer } from '../../contexts/ViewerContext';
import { buildSlideDocument } from '../../services/slideDocument';

interface SlideStageProps {
  slides: Slide[];
  css: string;
  externalScripts: string[];
}

/** Slides author against a fixed 1280x720 canvas (same constants as SlideTile). */
const SLIDE_WIDTH = 1280;
const SLIDE_HEIGHT = 720;
/** Never enlarge past 1:1 — upscaling a 720p slide just blurs it. */
const MAX_SCALE = 1;

/**
 * One discrete slide change per gesture (spec §4.1).
 *
 * The threshold exists to stop a single trackpad flick — which fires a burst of
 * events over ~100-300ms — from skipping several slides. It must NOT be used to
 * filter out small deltas: a mouse wheel reports deltaY of roughly 3-5 per notch,
 * so a threshold of 40 silently ignored every mouse user (measured: notches of
 * 3, 4, 5, 10 and 39 all did nothing). The cooldown is what enforces one slide
 * per gesture; the threshold only needs to reject sub-pixel noise.
 */
const WHEEL_THRESHOLD = 2;
const WHEEL_COOLDOWN_MS = 350;

export const SlideStage: React.FC<SlideStageProps> = ({ slides, css, externalScripts }) => {
  const { currentIndex, next, prev } = useViewer();
  const lastWheelRef = useRef(0);
  const fitRef = useRef<HTMLDivElement | null>(null);
  const [scale, setScale] = useState(1);

  // Fit the 1280x720 slide inside the stage, preserving aspect ratio. The iframe
  // must lay out at its intrinsic size and be transform-scaled (the approach
  // SlideTile and ThumbnailRibbon already use): sizing the iframe element itself
  // does NOT scale its content, it just crops it — which is what shipped, and the
  // slide overflowed the viewport on both sides. Unlike SlideTile (width-only fit,
  // scrolls vertically) the stage is a fixed pane, so fit on BOTH axes.
  useEffect(() => {
    const el = fitRef.current;
    if (!el) return;
    const update = () => {
      const { width, height } = el.getBoundingClientRect();
      if (width === 0 || height === 0) return;
      setScale(Math.min(width / SLIDE_WIDTH, height / SLIDE_HEIGHT, MAX_SCALE));
    };
    update();
    // ResizeObserver, not window.resize: the stage also changes size when the
    // drawer is resized or either side panel collapses, with no window event.
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const handleWheel = useCallback(
    (e: React.WheelEvent) => {
      if (Math.abs(e.deltaY) < WHEEL_THRESHOLD) return;
      const now = Date.now();
      if (now - lastWheelRef.current < WHEEL_COOLDOWN_MS) return;
      lastWheelRef.current = now;
      if (e.deltaY > 0) next();
      else prev();
    },
    [next, prev],
  );

  const slide = slides[currentIndex];

  const srcDoc = useMemo(() => {
    if (!slide) return '';
    return buildSlideDocument(slide.html, {
      css,
      externalScripts,
      scripts: slide.scripts || '',
    });
  }, [slide, css, externalScripts]);

  if (!slide) {
    return (
      <div
        data-testid="slide-stage-empty"
        className="flex flex-1 items-center justify-center"
      >
        {/* Matches the SlideViewer empty state, which preserves the wording the
            pre-viewer SlidePanel used. */}
        <div className="text-center text-muted-foreground">
          <p className="text-lg font-medium">No slides yet</p>
          <p className="mt-2 text-sm">Send a message to generate slides</p>
        </div>
      </div>
    );
  }

  return (
    <div
      data-testid="slide-stage"
      className="relative flex flex-1 items-center justify-center overflow-hidden bg-muted/30 p-4"
      onWheel={handleWheel}
    >
      <Button
        variant="outline"
        size="icon"
        aria-label="Previous slide"
        data-testid="stage-prev"
        onClick={prev}
        disabled={currentIndex === 0}
        className="absolute left-2 z-10"
      >
        <ChevronLeft className="size-4" />
      </Button>

      {/* Measured fit box: fills the stage so the ResizeObserver above can compute
          the scale, and clips anything the slide paints outside its canvas. */}
      <div ref={fitRef} className="relative flex size-full items-center justify-center overflow-hidden">
        <div
          // The scaled slide's painted size. Giving the wrapper the post-scale
          // dimensions keeps the flex centring honest — a transform alone does not
          // affect layout, so without this the box would still claim 1280x720.
          className="relative bg-white shadow-lg"
          style={{ width: SLIDE_WIDTH * scale, height: SLIDE_HEIGHT * scale }}
        >
          {/* pointer-events: none so wheel and click land on the stage container,
              not inside the sandboxed iframe. Without this the iframe covers the
              stage and wheel events over the slide are dispatched in the iframe's
              own browsing context — never reaching the onWheel handler above, so
              scroll-to-page (spec §4.1) only worked in a margin no user aims at.
              ThumbnailRibbon does the same for its preview iframes. Slides are
              non-interactive today; the inline editor (workstream 8) will need
              its own hit target layered on top. */}
          <iframe
            key={slide.slide_id}
            title={`Slide ${currentIndex + 1}`}
            data-testid="slide-stage-frame"
            /* Keyboard focus must not enter the iframe either: pointer-events:none
               only blocks the mouse. A Tab into it silently kills keyboard paging
               (events fire in the iframe context) with no Escape recovery, since
               the iframe is inside stageRef. PresentationMode does the same. */
            tabIndex={-1}
            sandbox="allow-scripts"
            srcDoc={srcDoc}
            className="absolute left-0 top-0 border-0"
            style={{
              // Intrinsic canvas size + transform is what actually scales the
              // CONTENT. Sizing the element instead only crops it.
              width: SLIDE_WIDTH,
              height: SLIDE_HEIGHT,
              transform: `scale(${scale})`,
              transformOrigin: 'top left',
              pointerEvents: 'none',
            }}
          />
        </div>
      </div>

      <Button
        variant="outline"
        size="icon"
        aria-label="Next slide"
        data-testid="stage-next"
        onClick={next}
        disabled={currentIndex >= slides.length - 1}
        className="absolute right-2 z-10"
      >
        <ChevronRight className="size-4" />
      </Button>

      <div
        data-testid="stage-position"
        className="absolute bottom-2 rounded bg-background/80 px-2 py-1 text-xs text-muted-foreground"
      >
        {currentIndex + 1} / {slides.length}
      </div>
    </div>
  );
};

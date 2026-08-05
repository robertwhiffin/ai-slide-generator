import React, { useCallback, useMemo, useRef } from 'react';
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

/** One discrete slide change per gesture, so a trackpad flick cannot skip slides (spec §4.1). */
const WHEEL_THRESHOLD = 40;
const WHEEL_COOLDOWN_MS = 350;

export const SlideStage: React.FC<SlideStageProps> = ({ slides, css, externalScripts }) => {
  const { currentIndex, next, prev } = useViewer();
  const lastWheelRef = useRef(0);

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

      <div className="aspect-video h-full max-h-full w-full max-w-full bg-white shadow-lg">
        {/* pointer-events: none so wheel and click land on the stage container,
            not inside the sandboxed iframe. Without this the iframe covers all
            but a ~16px frame of the stage, and wheel events over the slide are
            dispatched in the iframe's own browsing context — never reaching the
            onWheel handler above, so scroll-to-page (spec §4.1) only worked in
            a margin no user aims at. ThumbnailRibbon does the same for its
            preview iframes. Slides are non-interactive today; the inline editor
            (workstream 8) will need its own hit target layered on top. */}
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
          className="size-full border-0"
          style={{ pointerEvents: 'none' }}
        />
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

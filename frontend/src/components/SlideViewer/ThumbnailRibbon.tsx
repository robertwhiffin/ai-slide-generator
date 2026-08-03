import React, { useEffect, useMemo, useRef } from 'react';
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core';
import {
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import type { SlideDeck } from '../../types/slide';
import { useViewer } from '../../contexts/ViewerContext';
import { buildSlideDocument } from '../../services/slideDocument';

// Thumbnail scale: ribbon is w-40 (160px). The clip boundary for the iframe
// is 160 − 16 (ribbon p-2, 8px each side) − 2 (button border, 1px each side)
// − 8 (button p-1, 4px each side) = 134px.
// Scale = 134 / 1280 ≈ 0.1047 so the 1280-wide document fits exactly.
// Container uses padding-top: 56.25% (16:9) to reserve the right height.
const PREVIEW_SCALE = 134 / 1280;

interface ThumbnailRibbonProps {
  slideDeck: SlideDeck;
  unseenSlideIndices: Set<number>;
  onReorder: (from: number, to: number) => void;
}

interface ThumbProps {
  id: string;
  index: number;
  slideHtml: string;
  previewDocument: (html: string) => string;
  isCurrent: boolean;
  hasUnseen: boolean;
  onSelect: (index: number) => void;
}

const Thumb: React.FC<ThumbProps> = ({
  id,
  index,
  slideHtml,
  previewDocument,
  isCurrent,
  hasUnseen,
  onSelect,
}) => {
  // useSortable provides setNodeRef for dnd-kit (droppable+draggable combined ref).
  const { attributes, listeners, setNodeRef, transform, transition } = useSortable({ id });

  // Separate ref for scroll-into-view, attached to the same DOM node via the
  // callback ref pattern below — both setNodeRef and scrollRef end up pointing
  // at the same button element without one overwriting the other.
  const scrollRef = useRef<HTMLButtonElement | null>(null);

  // Auto-reveal: when this entry becomes current, scroll it into view (spec §4).
  useEffect(() => {
    if (isCurrent) {
      scrollRef.current?.scrollIntoView({ block: 'nearest' });
    }
  }, [isCurrent]);

  const slideDoc = useMemo(
    // previewDocument is already memoised on deck-level inputs; slideHtml changes per edit.
    () => previewDocument(slideHtml),
    [slideHtml, previewDocument],
  );

  return (
    <button
      ref={(node) => {
        // Attach both refs to the same element without losing either.
        setNodeRef(node);
        scrollRef.current = node;
      }}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      {...attributes}
      {...listeners}
      type="button"
      data-testid={`ribbon-thumb-${index}`}
      data-current={isCurrent ? 'true' : 'false'}
      aria-current={isCurrent ? 'true' : undefined}
      onClick={() => onSelect(index)}
      className={[
        'relative flex w-full flex-col gap-1 rounded-md border p-1 text-left transition',
        isCurrent
          ? 'border-[#3b82f6] bg-[#3b82f6]/10 shadow-sm ring-1 ring-[#3b82f6]'
          : 'border-border hover:bg-muted/50',
      ].join(' ')}
    >
      {/* Scaled slide preview: 1280×720 iframe shrunk to fit the ribbon width. */}
      <div
        className="relative w-full overflow-hidden rounded-sm bg-white"
        style={{ paddingTop: '56.25%' }}
      >
        <iframe
          title={`Slide ${index + 1} preview`}
          srcDoc={slideDoc}
          scrolling="no"
          sandbox="allow-scripts"
          style={{
            position: 'absolute',
            top: 0,
            left: 0,
            width: '1280px',
            height: '720px',
            border: 0,
            background: '#ffffff',
            transform: `scale(${PREVIEW_SCALE})`,
            transformOrigin: 'top left',
            // pointer-events: none so clicks and dnd-kit drag listeners on the
            // parent <button> are not swallowed by the interactive iframe.
            pointerEvents: 'none',
          }}
        />
      </div>

      {/* Slide label row with unseen indicator. */}
      <div className="flex items-center gap-1 px-1">
        <span className="truncate text-xs text-muted-foreground">Slide {index + 1}</span>
        {hasUnseen && (
          // Unseen dot: amber to avoid colour collision with the blue current-slide border.
          <span
            data-testid={`ribbon-unseen-${index}`}
            aria-label="Unread AI feedback"
            className="ml-auto size-2 shrink-0 rounded-full bg-amber-500"
          />
        )}
      </div>
    </button>
  );
};

export const ThumbnailRibbon: React.FC<ThumbnailRibbonProps> = ({
  slideDeck,
  unseenSlideIndices,
  onReorder,
}) => {
  const { currentIndex, setCurrentIndex } = useViewer();

  // Mirror SlidePanel.tsx:83-88 exactly: PointerSensor + KeyboardSensor with
  // sortableKeyboardCoordinates. No modifiers in SlidePanel, so none here either.
  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    }),
  );

  // Memoise the document builder on deck-level inputs (css, external_scripts,
  // scripts), matching SlideSelection.tsx:40-67. Rebuilding only when those
  // change keeps thumbnail renders cheap across slide navigation.
  const previewDocument = useMemo(() => {
    const inlineScripts = slideDeck.scripts
      ? `
      try {
        ${slideDeck.scripts}
      } catch (error) {
        console.debug('Chart initialization skipped for missing canvas:', error.message);
      }`
      : '';

    const resetStyle = `
      * { box-sizing: border-box; }
      body {
        margin: 0;
        width: 1280px;
        height: 720px;
        background: #ffffff;
        font-family: 'Inter', 'Segoe UI', system-ui, -apple-system, sans-serif;
      }`;

    return (slideHtml: string) =>
      buildSlideDocument(slideHtml, {
        css: slideDeck.css,
        externalScripts: slideDeck.external_scripts ?? undefined,
        extraHeadStyle: resetStyle,
        scripts: inlineScripts,
        // Do NOT pass includeKeyBridge — thumbnails don't drive navigation.
      });
  }, [slideDeck.css, slideDeck.external_scripts, slideDeck.scripts]);

  const ids = slideDeck.slides.map((s) => s.slide_id);

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const from = ids.indexOf(String(active.id));
    const to = ids.indexOf(String(over.id));
    if (from !== -1 && to !== -1) {
      // Report only — the parent owns the deck state. Do NOT call the API here.
      onReorder(from, to);
    }
  };

  return (
    // No wheel handler: wheel events here scroll the thumbnail list only (spec §4.1).
    // Attaching a wheel listener that calls setCurrentIndex would violate that rule.
    <div
      data-testid="thumbnail-ribbon"
      className="flex h-full w-40 shrink-0 flex-col gap-2 overflow-y-auto border-r border-border bg-card p-2"
    >
      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        onDragEnd={handleDragEnd}
      >
        <SortableContext items={ids} strategy={verticalListSortingStrategy}>
          {slideDeck.slides.map((slide, index) => (
            <Thumb
              key={slide.slide_id}
              id={slide.slide_id}
              index={index}
              slideHtml={slide.html}
              previewDocument={previewDocument}
              isCurrent={index === currentIndex}
              hasUnseen={unseenSlideIndices.has(index)}
              onSelect={setCurrentIndex}
            />
          ))}
        </SortableContext>
      </DndContext>
    </div>
  );
};

import React, { useMemo, useRef, useState, useEffect } from 'react';
import { useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { GripVertical, Edit3, Trash2, MessageSquare, Maximize2, Loader2, User, Clock } from 'lucide-react';
import { Button } from '@/ui/button';
import { Tooltip } from '../common/Tooltip';
import type { Slide, SlideDeck } from '../../types/slide';
import type { VerificationResult } from '../../types/verification';
import { HTMLEditorModal } from './HTMLEditorModal';
import { useSelection } from '../../contexts/SelectionContext';
import { VerificationBadge } from './VerificationBadge';
import { api } from '../../services/api';

function formatRelativeTime(iso: string): string {
  const date = new Date(iso);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMin = Math.floor(diffMs / 60_000);
  if (diffMin < 1) return 'just now';
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDays = Math.floor(diffHr / 24);
  if (diffDays < 7) return `${diffDays}d ago`;
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

interface SlideTileProps {
  slide: Slide;
  slideDeck: SlideDeck;
  index: number;
  sessionId: string;
  onDelete: () => void;
  onUpdate: (html: string) => Promise<void>;
  onVerificationUpdate: (verification: VerificationResult | null) => Promise<void>;
  isAutoVerifying?: boolean;
  onOptimize?: () => void;
  isOptimizing?: boolean;
  readOnly?: boolean;
}

const SLIDE_WIDTH = 1280;
const SLIDE_HEIGHT = 720;
const MAX_SCALE = 1.0;

export const SlideTile: React.FC<SlideTileProps> = ({
  slide,
  slideDeck,
  index,
  sessionId,
  onDelete,
  onUpdate,
  onVerificationUpdate,
  isAutoVerifying = false,
  onOptimize,
  isOptimizing = false,
  readOnly = false,
}) => {
  const [isEditing, setIsEditing] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [scale, setScale] = useState(1);
  const [contentHeight, setContentHeight] = useState<number>(SLIDE_HEIGHT);
  const { selectedIndices, setSelection } = useSelection();
  
  const [verificationResult, setVerificationResult] = useState<VerificationResult | undefined>(
    slide.verification
  );
  const [isManualVerifying, setIsManualVerifying] = useState(false);
  const [isStale, setIsStale] = useState(false);

  const isVerifying = isManualVerifying || isAutoVerifying;

  useEffect(() => {
    setVerificationResult(slide.verification);
    setIsStale(false);
  }, [slide.verification]);

  const handleVerify = async () => {
    if (!sessionId || isVerifying) return;
    
    setIsManualVerifying(true);
    try {
      const result = await api.verifySlide(sessionId, index);
      const verification: VerificationResult = {
        ...result,
        rating: result.rating as VerificationResult['rating'],
        timestamp: new Date().toISOString(),
      };
      
      console.log(`[Verification] Slide ${index + 1} verified:`, {
        score: verification.score,
        rating: verification.rating,
        trace_id: verification.trace_id,
        content_hash: slide.content_hash,
      });
      
      setVerificationResult(verification);
      setIsStale(false);
      await onVerificationUpdate(verification);
    } catch (error) {
      console.error('Verification failed:', error);
      const errorResult: VerificationResult = {
        score: 0,
        rating: 'error',
        explanation: error instanceof Error ? error.message : 'Verification failed',
        issues: [],
        duration_ms: 0,
        error: true,
        error_message: error instanceof Error ? error.message : 'Unknown error',
      };
      setVerificationResult(errorResult);
    } finally {
      setIsManualVerifying(false);
    }
  };

  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: slide.slide_id });

  useEffect(() => {
    const updateScale = () => {
      if (containerRef.current) {
        const containerWidth = containerRef.current.offsetWidth;
        const calculatedScale = Math.min(containerWidth / SLIDE_WIDTH, MAX_SCALE);
        setScale(calculatedScale);
      }
    };

    updateScale();

    window.addEventListener('resize', updateScale);
    return () => window.removeEventListener('resize', updateScale);
  }, []);

  const slideHTML = useMemo(() => {
    const slideScripts = slide.scripts || '';
    const slideId = slide.slide_id.replace(/'/g, "\\'");
    return `
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  ${slideDeck.external_scripts.map(src => 
    `<script src="${src}"></script>`
  ).join('\n  ')}
  <style>${slideDeck.css}</style>
</head>
<body>
  ${slide.html}
  ${slideScripts ? `<script>${slideScripts}</script>` : ''}
  <script>
(function() {
  function sendHeight() {
    var h = Math.max(document.documentElement.scrollHeight, document.documentElement.offsetHeight, document.body.scrollHeight, document.body.offsetHeight);
    try { window.parent.postMessage({ type: 'slideHeight', slideId: '${slideId}', height: h }, '*'); } catch (e) {}
  }
  if (document.readyState === 'complete') sendHeight(); else window.addEventListener('load', sendHeight);
  setTimeout(sendHeight, 100);
  setTimeout(sendHeight, 500);
})();
</script>
</body>
</html>
    `.trim();
  }, [slide.html, slide.scripts, slide.slide_id, slideDeck.css, slideDeck.external_scripts]);

  useEffect(() => {
    const onMessage = (e: MessageEvent) => {
      const d = e.data;
      if (d?.type === 'slideHeight' && d?.slideId === slide.slide_id && typeof d?.height === 'number')
        setContentHeight(Math.max(SLIDE_HEIGHT, d.height));
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [slide.slide_id]);

  useEffect(() => {
    setContentHeight(SLIDE_HEIGHT);
  }, [slide.html]);

  const displayHeight = Math.max(SLIDE_HEIGHT, contentHeight);
  const scaledHeight = displayHeight * scale;

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };

  const isSelected = selectedIndices.includes(index);
  const containerClassName = `bg-white rounded-lg overflow-hidden ${
    isSelected ? 'ring-2 ring-blue-500' : ''
  }`;

  return (
    <>
      <div
        ref={setNodeRef}
        style={style}
        className={containerClassName}
      >
        {/* Slide Header with Actions */}
      <div className="flex items-center gap-2 border-b border-border bg-card px-3 py-2" data-testid="slide-tile-header">
          <div className="flex items-center gap-2 flex-1">
            {!readOnly && (
              <Tooltip text="Drag to reorder">
                <button
                  {...attributes}
                  {...listeners}
                  className="cursor-grab active:cursor-grabbing text-muted-foreground hover:text-foreground"
                >
                  <GripVertical className="size-4" />
                </button>
              </Tooltip>
            )}

            <span className="text-sm font-medium text-foreground">
              Slide {index + 1}
            </span>
          </div>

          {/* Action Buttons */}
          <div className="flex items-center gap-1">
            <VerificationBadge
              slideIndex={index}
              sessionId={sessionId}
              verificationResult={verificationResult}
              isVerifying={isVerifying}
              onVerify={handleVerify}
              isStale={isStale}
            />

            {!readOnly && (
              <Tooltip text={isSelected ? 'Selected for editing' : 'Add to chat context'}>
                <Button
                  variant={isSelected ? "secondary" : "ghost"}
                  size="icon"
                  onClick={() => setSelection([index], [slide])}
                  className="h-7 w-7"
                  aria-pressed={isSelected}
                >
                  <MessageSquare className="size-3.5" />
                </Button>
              </Tooltip>
            )}

            {!readOnly && onOptimize && (
              <Tooltip text={isOptimizing ? 'Optimizing layout...' : 'Optimize layout'}>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={onOptimize}
                  disabled={isOptimizing}
                  className="h-7 w-7"
                >
                  {isOptimizing ? (
                    <Loader2 className="size-3.5 animate-spin" />
                  ) : (
                    <Maximize2 className="size-3.5" />
                  )}
                </Button>
              </Tooltip>
            )}

            {!readOnly && (
              <>
                <Tooltip text="Edit slide HTML">
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => setIsEditing(true)}
                    className="h-7 w-7"
                    aria-label="Edit"
                  >
                    <Edit3 className="size-3.5" />
                  </Button>
                </Tooltip>

                <Tooltip text="Delete slide" align="end">
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={onDelete}
                    className="h-7 w-7 text-destructive hover:text-destructive"
                    aria-label="Delete"
                  >
                    <Trash2 className="size-3.5" />
                  </Button>
                </Tooltip>
              </>
            )}
          </div>
      </div>

      {/* Slide Preview */}
      <div
        ref={containerRef}
        className="relative bg-muted/20 overflow-hidden"
        style={{ height: `${scaledHeight}px`, minHeight: `${SLIDE_HEIGHT * scale}px` }}
      >
        <iframe
          ref={iframeRef}
          srcDoc={slideHTML}
          title={`Slide ${index + 1}`}
          className="absolute top-0 left-0 border-0"
          sandbox="allow-scripts"
          style={{
            width: `${SLIDE_WIDTH}px`,
            height: `${displayHeight}px`,
            transform: `scale(${scale})`,
            transformOrigin: 'top left',
          }}
        />
      </div>

      {/* Slide Metadata Footer */}
      <div className="px-3 py-1.5 bg-gray-50 border-t text-xs text-gray-500 flex flex-wrap items-center gap-x-3 gap-y-0.5">
        <span className="inline-flex items-center gap-1 whitespace-nowrap">
          <User className="size-2.5 text-gray-400" />
          <span className="text-gray-400">Created by</span>
          <span className="text-gray-700 font-medium">{slide.created_by || '—'}</span>
        </span>
        <span className="inline-flex items-center gap-1 whitespace-nowrap">
          <Clock className="size-2.5 text-gray-400" />
          <span className="text-gray-400">Created</span>
          <span className="text-gray-700" title={slide.created_at ? new Date(slide.created_at).toLocaleString() : ''}>
            {slide.created_at ? formatRelativeTime(slide.created_at) : '—'}
          </span>
        </span>
        <span className="text-gray-300">|</span>
        <span className="inline-flex items-center gap-1 whitespace-nowrap">
          <User className="size-2.5 text-gray-400" />
          <span className="text-gray-400">Last modified by</span>
          <span className="text-gray-700 font-medium">{slide.modified_by || '—'}</span>
        </span>
        <span className="inline-flex items-center gap-1 whitespace-nowrap">
          <Clock className="size-2.5 text-gray-400" />
          <span className="text-gray-400">Modified</span>
          <span className="text-gray-700" title={slide.modified_at ? new Date(slide.modified_at).toLocaleString() : ''}>
            {slide.modified_at ? formatRelativeTime(slide.modified_at) : '—'}
          </span>
        </span>
      </div>

    </div>

      {/* HTML Editor Modal */}
      {isEditing && (
        <HTMLEditorModal
          html={slide.html}
          slideDeck={slideDeck}
          slide={slide}
          onSave={async (newHtml) => {
            await onUpdate(newHtml);
            
            if (verificationResult) {
              setVerificationResult(undefined);
              setIsStale(false);
              await onVerificationUpdate(null);
            }
            setIsEditing(false);
          }}
          onCancel={() => setIsEditing(false)}
        />
      )}
    </>
  );
};

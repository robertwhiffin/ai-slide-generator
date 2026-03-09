import React, { useMemo, useRef, useState, useEffect } from 'react';
import { useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { FiEdit, FiTrash2, FiMove, FiMessageSquare, FiMessageCircle, FiDatabase, FiMaximize2, FiUser, FiClock } from 'react-icons/fi';
import { Tooltip } from '../common/Tooltip';
import type { Slide, SlideDeck } from '../../types/slide';
import type { VerificationResult } from '../../types/verification';
import { HTMLEditorModal } from './HTMLEditorModal';
import { CommentThread } from './CommentThread';
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
  isAutoVerifying?: boolean;  // True when auto-verification is running for this slide
  onOptimize?: () => void;
  isOptimizing?: boolean;
  readOnly?: boolean;  // When true, hide edit/delete/reorder controls
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
  const [showComments, setShowComments] = useState(false);
  const [commentCount, setCommentCount] = useState<number | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(1);
  const { selectedIndices, setSelection } = useSelection();
  
  // Verification state - initialize from persisted slide.verification
  const [verificationResult, setVerificationResult] = useState<VerificationResult | undefined>(
    slide.verification
  );
  const [isManualVerifying, setIsManualVerifying] = useState(false);
  const [isStale, setIsStale] = useState(false);
  const [isLoadingGenieLink, setIsLoadingGenieLink] = useState(false);
  
  // Combined verifying state (manual or auto)
  const isVerifying = isManualVerifying || isAutoVerifying;

  // Handle opening Genie conversation link
  const handleOpenGenieLink = async () => {
    if (isLoadingGenieLink) return;
    
    setIsLoadingGenieLink(true);
    try {
      const link = await api.getGenieLink(sessionId);
      if (link.url) {
        window.open(link.url, '_blank');
      } else {
        alert(link.message || 'No Genie conversation available');
      }
    } catch (error) {
      console.error('Failed to get Genie link:', error);
      alert('Failed to get Genie conversation link');
    } finally {
      setIsLoadingGenieLink(false);
    }
  };

  // Fetch comment count on mount and when comments panel closes
  useEffect(() => {
    if (!sessionId || !slide.slide_id) return;
    let cancelled = false;
    api.listComments(sessionId, slide.slide_id).then(({ count }) => {
      if (!cancelled) setCommentCount(count);
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [sessionId, slide.slide_id, showComments]);

  // Sync verification state when slide.verification changes (e.g., session restore)
  useEffect(() => {
    setVerificationResult(slide.verification);
    setIsStale(false);  // Reset stale when verification is loaded
  }, [slide.verification]);

  // Handle manual verification (user clicks verify button)
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
      
      // Log trace_id for easy access
      console.log(`[Verification] Slide ${index + 1} verified:`, {
        score: verification.score,
        rating: verification.rating,
        trace_id: verification.trace_id,
        content_hash: slide.content_hash,
      });
      
      setVerificationResult(verification);
      setIsStale(false);
      
      // Note: Backend now saves verification automatically by content hash
      // This call updates local state for the parent component
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
      // Don't persist error results
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

  // Calculate scale based on container width
  useEffect(() => {
    const updateScale = () => {
      if (containerRef.current) {
        const containerWidth = containerRef.current.offsetWidth;
        // Scale to fit width, but cap at MAX_SCALE (1.5x)
        const calculatedScale = Math.min(containerWidth / SLIDE_WIDTH, MAX_SCALE);
        setScale(calculatedScale);
      }
    };

    // Initial calculation
    updateScale();

    // Update on window resize
    window.addEventListener('resize', updateScale);
    return () => window.removeEventListener('resize', updateScale);
  }, []);

  // Build complete HTML for iframe using slide-specific scripts
  // Each slide is rendered in its own iframe, so no IIFE wrapping needed
  const slideHTML = useMemo(() => {
    const slideScripts = slide.scripts || '';
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
</body>
</html>
    `.trim();
  }, [slide.html, slide.scripts, slideDeck.css, slideDeck.external_scripts]);

  // Calculate scaled dimensions
  const scaledHeight = SLIDE_HEIGHT * scale;

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };

  const isSelected = selectedIndices.includes(index);
  const containerClassName = `bg-white rounded-lg shadow-md overflow-hidden ${
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
      <div className="px-4 py-2 bg-gray-100 border-b flex items-center justify-between">
          <div className="flex items-center space-x-2">
            {/* Drag Handle - hidden in readOnly mode */}
            {!readOnly && (
              <Tooltip text="Drag to reorder">
                <button
                  {...attributes}
                  {...listeners}
                  className="cursor-grab active:cursor-grabbing text-gray-500 hover:text-gray-700"
                >
                  <FiMove size={18} />
                </button>
              </Tooltip>
            )}
            
        <span className="text-sm font-medium text-gray-700">
          Slide {index + 1}
        </span>
          </div>

          {/* Action Buttons */}
          <div className="flex items-center space-x-1">
            {/* Verification Badge/Button */}
            <VerificationBadge
              slideIndex={index}
              sessionId={sessionId}
              verificationResult={verificationResult}
              isVerifying={isVerifying}
              onVerify={handleVerify}
              isStale={isStale}
            />
            
            {/* Genie Source Data Link */}
            <Tooltip text="View source data">
              <button
                onClick={handleOpenGenieLink}
                disabled={isLoadingGenieLink}
                className="p-1 text-purple-600 hover:bg-purple-50 rounded disabled:opacity-50"
              >
                <FiDatabase size={16} />
              </button>
            </Tooltip>

            {/* Comments toggle */}
            <Tooltip text={showComments ? 'Hide comments' : 'Comments'}>
              <button
                onClick={() => setShowComments((v) => !v)}
                className={`relative p-1 rounded ${
                  showComments
                    ? 'text-orange-700 bg-orange-50'
                    : 'text-orange-600 hover:bg-orange-50'
                }`}
              >
                <FiMessageCircle size={16} />
                {commentCount != null && commentCount > 0 && (
                  <span className="absolute -top-1 -right-1 bg-orange-500 text-white text-[10px] leading-none font-bold rounded-full min-w-[16px] h-4 flex items-center justify-center px-0.5">
                    {commentCount}
                  </span>
                )}
              </button>
            </Tooltip>
            
            {/* Selection for chat context - hidden in readOnly mode */}
            {!readOnly && (
              <Tooltip text={isSelected ? 'Selected for editing' : 'Add to chat context'}>
                <button
                  onClick={() => setSelection([index], [slide])}
                  className={`p-1 rounded ${
                    isSelected
                      ? 'text-blue-700 bg-blue-50'
                      : 'text-indigo-600 hover:bg-indigo-50'
                  }`}
                  aria-pressed={isSelected}
                >
                  <FiMessageSquare size={16} />
                </button>
              </Tooltip>
            )}
            
            {/* Optimize button - hidden in readOnly mode */}
            {!readOnly && onOptimize && (
              <Tooltip text={isOptimizing ? 'Optimizing layout...' : 'Optimize layout'}>
                <button
                  onClick={onOptimize}
                  disabled={isOptimizing}
                  className={`p-1 rounded ${
                    isOptimizing
                      ? 'text-gray-400 cursor-not-allowed'
                      : 'text-purple-600 hover:bg-purple-50'
                  }`}
                >
                  {isOptimizing ? (
                    <div className="animate-spin rounded-full h-4 w-4 border-2 border-purple-600 border-t-transparent"></div>
                  ) : (
                    <FiMaximize2 size={16} />
                  )}
                </button>
              </Tooltip>
            )}
            
            {/* Edit button - hidden in readOnly mode */}
            {!readOnly && (
              <Tooltip text="Edit slide HTML">
                <button
                  onClick={() => setIsEditing(true)}
                  className="p-1 text-blue-600 hover:bg-blue-50 rounded"
                >
                  <FiEdit size={16} />
                </button>
              </Tooltip>
            )}
            
            {/* Delete button - hidden in readOnly mode */}
            {!readOnly && (
              <Tooltip text="Delete slide" align="end">
                <button
                  onClick={onDelete}
                  className="p-1 text-red-600 hover:bg-red-50 rounded"
                >
                  <FiTrash2 size={16} />
                </button>
              </Tooltip>
            )}
          </div>
      </div>

      {/* Slide Preview */}
      <div 
        ref={containerRef}
        className="relative bg-gray-200 overflow-hidden"
        style={{ height: `${scaledHeight}px` }}
      >
        <iframe
          srcDoc={slideHTML}
          title={`Slide ${index + 1}`}
          className="absolute top-0 left-0 border-0"
          sandbox="allow-scripts"
          style={{
            width: `${SLIDE_WIDTH}px`,
            height: `${SLIDE_HEIGHT}px`,
            transform: `scale(${scale})`,
            transformOrigin: 'top left',
          }}
        />
      </div>

      {/* Slide Metadata Footer */}
      {(slide.created_by || slide.modified_by) && (
        <div className="px-4 py-1.5 bg-gray-50 border-t text-xs text-gray-500 flex items-center justify-between">
          {slide.created_by && (
            <span className="flex items-center gap-1">
              <FiUser size={12} />
              {slide.created_by}
              {slide.created_at && (
                <Tooltip text={new Date(slide.created_at).toLocaleString()}>
                  <span className="text-gray-400 cursor-default">
                    &middot; created {formatRelativeTime(slide.created_at)}
                  </span>
                </Tooltip>
              )}
            </span>
          )}
          {slide.modified_by && slide.modified_at && slide.modified_at !== slide.created_at && (
            <span className="flex items-center gap-1">
              <FiClock size={12} />
              edited by {slide.modified_by}
              <Tooltip text={new Date(slide.modified_at).toLocaleString()}>
                <span className="text-gray-400 cursor-default">
                  {formatRelativeTime(slide.modified_at)}
                </span>
              </Tooltip>
            </span>
          )}
        </div>
      )}

      {/* Comments Panel */}
      {showComments && (
        <CommentThread sessionId={sessionId} slideId={slide.slide_id} />
      )}
    </div>

      {/* HTML Editor Modal */}
      {isEditing && (
        <HTMLEditorModal
          html={slide.html}
          slideDeck={slideDeck}
          slide={slide}
          onSave={async (newHtml) => {
            await onUpdate(newHtml);
            
            // Clear verification when slide is edited
            if (verificationResult) {
              setVerificationResult(undefined);
              setIsStale(false);
              // Persist the cleared verification
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

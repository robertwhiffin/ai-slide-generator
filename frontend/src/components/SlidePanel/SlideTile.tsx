import React, { useMemo, useRef, useState, useEffect } from 'react';
import { useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { FiEdit, FiCopy, FiTrash2, FiMove, FiMessageSquare } from 'react-icons/fi';
import type { Slide, SlideDeck } from '../../types/slide';
import type { VerificationResult } from '../../types/verification';
import { HTMLEditorModal } from './HTMLEditorModal';
import { useSelection } from '../../contexts/SelectionContext';
import { VerificationBadge } from './VerificationBadge';
import { api } from '../../services/api';

interface SlideTileProps {
  slide: Slide;
  slideDeck: SlideDeck;
  index: number;
  sessionId: string;
  onDelete: () => void;
  onDuplicate: () => void;
  onUpdate: (html: string) => Promise<void>;
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
  onDuplicate,
  onUpdate,
}) => {
  const [isEditing, setIsEditing] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(1);
  const { selectedIndices, setSelection } = useSelection();
  
  // Verification state
  const [verificationResult, setVerificationResult] = useState<VerificationResult | undefined>();
  const [isVerifying, setIsVerifying] = useState(false);
  const [lastVerifiedAt, setLastVerifiedAt] = useState<string | undefined>();
  const [lastEditedAt, setLastEditedAt] = useState<string | undefined>();

  // Handle verification
  const handleVerify = async () => {
    if (!sessionId || isVerifying) return;
    
    setIsVerifying(true);
    try {
      const result = await api.verifySlide(sessionId, index);
      setVerificationResult({
        ...result,
        rating: result.rating as VerificationResult['rating'],
        timestamp: new Date().toISOString(),
      });
      setLastVerifiedAt(new Date().toISOString());
    } catch (error) {
      console.error('Verification failed:', error);
      setVerificationResult({
        score: 0,
        rating: 'error',
        explanation: error instanceof Error ? error.message : 'Verification failed',
        issues: [],
        duration_ms: 0,
        error: true,
        error_message: error instanceof Error ? error.message : 'Unknown error',
      });
    } finally {
      setIsVerifying(false);
    }
  };

  // Check if verification is stale (slide edited after verification)
  const isStale = !!(lastVerifiedAt && lastEditedAt && new Date(lastEditedAt) > new Date(lastVerifiedAt));

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
            {/* Drag Handle */}
            <button
              {...attributes}
              {...listeners}
              className="cursor-grab active:cursor-grabbing text-gray-500 hover:text-gray-700"
              title="Drag to reorder"
            >
              <FiMove size={18} />
            </button>
            
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
            
            <button
              onClick={() => setSelection([index], [slide])}
              className={`p-1 rounded ${
                isSelected
                  ? 'text-blue-700 bg-blue-50'
                  : 'text-indigo-600 hover:bg-indigo-50'
              }`}
              aria-pressed={isSelected}
              title={isSelected ? 'Selected for editing' : 'Add to chat context'}
            >
              <FiMessageSquare size={16} />
            </button>
            <button
              onClick={() => setIsEditing(true)}
              className="p-1 text-blue-600 hover:bg-blue-50 rounded"
              title="Edit HTML"
            >
              <FiEdit size={16} />
            </button>
            
            <button
              onClick={onDuplicate}
              className="p-1 text-green-600 hover:bg-green-50 rounded"
              title="Duplicate"
            >
              <FiCopy size={16} />
            </button>
            
            <button
              onClick={onDelete}
              className="p-1 text-red-600 hover:bg-red-50 rounded"
              title="Delete"
            >
              <FiTrash2 size={16} />
            </button>
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
    </div>

      {/* HTML Editor Modal */}
      {isEditing && (
        <HTMLEditorModal
          html={slide.html}
          onSave={async (newHtml) => {
            await onUpdate(newHtml);
            setLastEditedAt(new Date().toISOString());  // Mark as edited for stale verification
            setIsEditing(false);
          }}
          onCancel={() => setIsEditing(false)}
        />
      )}
    </>
  );
};

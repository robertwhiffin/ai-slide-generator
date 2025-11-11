import React, { useEffect, useMemo, useRef, useState, useCallback } from 'react';
import styled from 'styled-components';

interface SlideViewerProps {
  slides: string[];
  isRefreshing: boolean;
}

const ViewerContainer = styled.div`
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', sans-serif;
  font-weight: 400;
`;

const SlideArea = styled.div`
  flex: 1;
  display: flex;
  gap: 16px;
  min-height: 0;
`;

const SlideListPanel = styled.div`
  width: 200px;
  min-width: 180px;
  max-width: 220px;
  background: #FFFFFF;
  border: 1px solid #e5e7eb;
  border-radius: 16px;
  padding: 8px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
`;

const SlideList = styled.div`
  overflow-y: auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
`;

const SlideListItem = styled.button<{ $active?: boolean }>`
  text-align: left;
  border: 1px solid ${props => (props.$active ? '#ff3b2e' : '#e5e7eb')};
  background: ${props => (props.$active ? 'rgba(255, 59, 46, 0.06)' : '#fafafa')};
  color: #111827;
  border-radius: 8px;
  padding: 6px 6px 8px 6px;
  cursor: pointer;
  transition: background-color .15s, border-color .15s;
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 4px;
  &:hover { background: #f3f4f6; }
  &:focus, &:focus-visible { outline: none; box-shadow: none; }
`;

const SlideIndex = styled.span`
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  font-size: 10px;
  font-weight: 600;
  color: #1F2937;
  background: #E5E7EB;
  border-radius: 4px;
`;

const SlideTitleRow = styled.div`
  display: flex;
  align-items: center;
  gap: 6px;
`;

const SlideTitle = styled.div`
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
`;

const ThumbBox = styled.div`
  width: 120px;
  height: 68px; /* 16:9 */
  border-radius: 6px;
  overflow: hidden;
  background: #ffffff;
  border: 1px solid #e5e7eb;
  flex: 0 0 auto;
`;

const ThumbFrame = styled.iframe`
  width: 800px;   /* virtual size before scale */
  height: 450px;  /* 16:9 */
  border: 0;
  transform: scale(0.15); /* 800*0.15=120px, 450*0.15=67.5px */
  transform-origin: top left;
  pointer-events: none; /* preview only */
  background: white;
`;

const SlideDisplay = styled.div`
  flex: 1;
  display: flex;
  justify-content: center;
  align-items: center;
  padding: 16px;
  margin-bottom: 16px;
  position: relative;
  min-height: 0;
`;

const SlideFrame = styled.div`
  width: 98%;
  max-width: 99%;
  aspect-ratio: 16/9;
  border: 2px solid #d1d5db;
  border-radius: 12px;
  overflow: hidden;
  background: white;
  box-shadow: 0 8px 25px rgba(0, 0, 0, 0.15);
  position: relative;
  
  @media (min-width: 1200px) {
    width: 99%;
  }
  
  @media (min-width: 1600px) {
    width: 99%;
  }
  
  @media (max-width: 768px) {
    width: 97%;
  }
`;

const IFrame = styled.iframe`
  width: 1280px;
  height: 720px;
  border: none;
  background: white;
  transform: scale(var(--scale-factor, 1));
  transform-origin: top left;
  position: absolute;
  top: 0;
  left: 0;
`;


const EmptyState = styled.div`
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #9ca3af;
  text-align: center;
  padding: 40px;
`;

const EmptyStateIcon = styled.div`
  font-size: 4rem;
  margin-bottom: 16px;
`;

const EmptyStateText = styled.div`
  font-size: 1.1rem;
  font-weight: 600;
  margin-bottom: 8px;
`;

const EmptyStateSubtext = styled.div`
  font-size: 0.9rem;
  color: #6b7280;
`;

const LoadingOverlay = styled.div`
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(255, 255, 255, 0.8);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.1rem;
  color: #667eea;
  border-radius: 12px;
  z-index: 10;
`;

// Thumbnail component that updates only when clicked
const ThumbnailFrame = React.memo<{
  slideIndex: number;
  html: string;
  isActive: boolean;
  onRefresh: number;
}>(({ slideIndex, html, isActive, onRefresh }) => {
  const [thumbnailContent, setThumbnailContent] = useState<string>('');
  const [isLoading, setIsLoading] = useState(false);

  // Generate thumbnail content
  const generateThumbnailContent = useCallback(() => {
    return `<html><head><style>html,body{margin:0;height:100%;overflow:hidden}</style></head><body>${html}</body></html>`;
  }, [html]);

  // Update thumbnail when refresh is requested
  useEffect(() => {
    if (typeof onRefresh === 'number' && onRefresh > 0) {
      setIsLoading(true);
      // Small delay to show loading state
      setTimeout(() => {
        setThumbnailContent(generateThumbnailContent());
        setIsLoading(false);
      }, 100);
    }
  }, [onRefresh, generateThumbnailContent]);

  // Initial load
  useEffect(() => {
    if (!thumbnailContent) {
      setThumbnailContent(generateThumbnailContent());
    }
  }, [thumbnailContent, generateThumbnailContent]);

  return (
    <ThumbBox style={{ position: 'relative' }}>
      {isLoading && (
        <div style={{
          position: 'absolute',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          background: 'rgba(255,255,255,0.8)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: '10px',
          color: '#666',
          zIndex: 1
        }}>
          ⟳
        </div>
      )}
      <ThumbFrame
        srcDoc={thumbnailContent}
        sandbox="allow-scripts allow-same-origin"
      />
    </ThumbBox>
  );
});

ThumbnailFrame.displayName = 'ThumbnailFrame';

// Memoized slide list item to prevent unnecessary re-renders
const SlideListItemMemo = React.memo<{
  slide: { index: number; title: string };
  activeIndex: number;
  html: string;
  onGotoSlide: (index: number) => void;
}>(({ slide, activeIndex, html, onGotoSlide }) => {
  const [refreshTrigger, setRefreshTrigger] = useState(0);

  const handleSlideClick = () => {
    // Refresh thumbnail when slide is clicked
    setRefreshTrigger(prev => prev + 1);
    // Navigate to the clicked slide
    onGotoSlide(slide.index);
  };

  return (
    <SlideListItem $active={slide.index === activeIndex} onClick={handleSlideClick}>
      <SlideTitleRow>
        <SlideIndex>{slide.index + 1}</SlideIndex>
        <SlideTitle>{slide.title}</SlideTitle>
      </SlideTitleRow>
      <ThumbnailFrame
        slideIndex={slide.index}
        html={html}
        isActive={slide.index === activeIndex}
        onRefresh={refreshTrigger}
      />
    </SlideListItem>
  );
});

SlideListItemMemo.displayName = 'SlideListItemMemo';

const SlideViewer: React.FC<SlideViewerProps> = ({ slides, isRefreshing }) => {
  const hasSlides = slides && slides.length > 0;

  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const slideFrameRef = useRef<HTMLDivElement | null>(null);
  const [activeIndex, setActiveIndex] = useState(0);

  const calculateScaleFactor = () => {
    if (!slideFrameRef.current || !iframeRef.current) return;
    
    const frameRect = slideFrameRef.current.getBoundingClientRect();
    // Use full frame dimensions for maximum content visibility
    const availableWidth = frameRect.width;
    const availableHeight = frameRect.height;
    
    const scaleX = availableWidth / 1280;
    const scaleY = availableHeight / 720;
    const scale = Math.min(scaleX, scaleY);
    
    iframeRef.current.style.setProperty('--scale-factor', scale.toString());
  };

  // Stable slide metadata that only updates when slide count changes
  const [slidesMeta, setSlidesMeta] = useState<{ index: number; title: string }[]>([]);
  const [lastSlideCount, setLastSlideCount] = useState(0);

  // Update slides metadata only when slide count changes
  useEffect(() => {
    if (!hasSlides) {
      setSlidesMeta([]);
      setLastSlideCount(0);
      return;
    }

    try {
      const currentSlideCount = slides.length;
      
      // Only update if slide count changed
      if (currentSlideCount !== lastSlideCount) {
        const newSlidesMeta = slides.map((slideHtml, i) => {
          const parser = new DOMParser();
          const doc = parser.parseFromString(slideHtml, 'text/html');
          const heading = doc.querySelector('h1, h2, h3');
          const title = (heading?.textContent || '').trim() || `Slide ${i + 1}`;
          return { index: i, title };
        });
        setSlidesMeta(newSlidesMeta);
        setLastSlideCount(currentSlideCount);
      }
    } catch {
      setSlidesMeta([]);
      setLastSlideCount(0);
    }
  }, [slides, hasSlides, lastSlideCount]);

  useEffect(() => {
    const onMessage = (e: MessageEvent) => {
      const data = e?.data as any;
      if (!data || typeof data !== 'object') return;
      if (data.type === 'SLIDE_CHANGED') {
        if (typeof data.index === 'number') setActiveIndex(data.index);
      }
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [activeIndex]);

  // Calculate scale factor when component mounts or resizes
  useEffect(() => {
    if (!hasSlides) return;
    
    const handleResize = () => {
      setTimeout(calculateScaleFactor, 100);
    };
    
    calculateScaleFactor();
    window.addEventListener('resize', handleResize);
    
    return () => window.removeEventListener('resize', handleResize);
  }, [hasSlides, slides]);

  const gotoSlide = useCallback((index: number) => {
    // Only update if the index is different from current active index
    if (index !== activeIndex) {
      setActiveIndex(index);
    }
  }, [activeIndex]);

  // Only reset to first slide when slides are first created, not on every update
  useEffect(() => {
    if (!hasSlides) return;
    
    // Only reset to first slide if we don't have any slides yet or if this is a completely new deck
    if (slidesMeta.length === 0) {
      setActiveIndex(0);
    }
    
    // If the current active index is beyond the available slides, reset to last slide
    if (activeIndex >= slidesMeta.length && slidesMeta.length > 0) {
      const newIndex = slidesMeta.length - 1;
      setActiveIndex(newIndex);
    }
  }, [hasSlides, slidesMeta.length, activeIndex]);

  return (
    <ViewerContainer>
      {hasSlides ? (
        <SlideArea>
          <SlideListPanel>
            <SlideList>
              {slidesMeta.map(s => (
                <SlideListItemMemo
                  key={s.index}
                  slide={s}
                  activeIndex={activeIndex}
                  html={slides[s.index] || ''}
                  onGotoSlide={gotoSlide}
                />
              ))}
            </SlideList>
          </SlideListPanel>
          <SlideDisplay>
            <SlideFrame ref={slideFrameRef}>
              {isRefreshing && (
                <LoadingOverlay>🔄 Refreshing slides...</LoadingOverlay>
              )}
              <IFrame
                ref={iframeRef}
                srcDoc={slides[activeIndex] || ''}
                title="Generated Slides"
                sandbox="allow-scripts allow-same-origin"
                onLoad={() => {
                  // Calculate scale after iframe loads
                  setTimeout(calculateScaleFactor, 100);
                }}
              />
            </SlideFrame>
          </SlideDisplay>
        </SlideArea>
      ) : (
        <SlideDisplay>
          <EmptyState>
            <EmptyStateIcon>📊</EmptyStateIcon>
            <EmptyStateText>No slides generated yet</EmptyStateText>
            <EmptyStateSubtext>Start a conversation to create your presentation</EmptyStateSubtext>
          </EmptyState>
        </SlideDisplay>
      )}
    </ViewerContainer>
  );
};

export default SlideViewer;


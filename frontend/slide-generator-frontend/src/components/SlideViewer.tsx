import React from 'react';
import styled from 'styled-components';

interface SlideViewerProps {
  html: string;
  onRefresh: () => void;
  onReset: () => void;
  onExport: () => void;
  isRefreshing: boolean;
}

const ViewerContainer = styled.div`
  display: flex;
  flex-direction: column;
  height: 100%;
  flex: 1;
  max-height: calc(100vh - 120px);
`;

const SlideDisplay = styled.div`
  flex: 1;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  overflow: hidden;
  background: white;
  position: relative;
  height: calc(100vh - 200px);
  max-height: calc(100vh - 200px);
`;

const IFrame = styled.iframe`
  width: 100%;
  height: 100%;
  border: none;
  background: white;
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
`;

const NavigationHint = styled.div`
  position: absolute;
  top: 16px;
  right: 16px;
  background: rgba(0, 0, 0, 0.8);
  color: white;
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 500;
  z-index: 10;
  display: flex;
  align-items: center;
  gap: 6px;
  backdrop-filter: blur(4px);
`;

const SlideViewer: React.FC<SlideViewerProps> = ({
  html,
  onRefresh,
  onReset,
  onExport,
  isRefreshing
}) => {
  const hasSlides = html && html.trim().length > 0;


  return (
    <ViewerContainer>
      <SlideDisplay>
        {isRefreshing && (
          <LoadingOverlay>
            🔄 Refreshing slides...
          </LoadingOverlay>
        )}
        
        {hasSlides && (
          <NavigationHint>
            Use arrow keys to navigate
          </NavigationHint>
        )}
        
        {hasSlides ? (
          <IFrame
            srcDoc={html}
            title="Generated Slides"
            sandbox="allow-scripts allow-same-origin"
          />
        ) : (
          <EmptyState>
            <EmptyStateIcon>📊</EmptyStateIcon>
            <EmptyStateText>No slides generated yet</EmptyStateText>
            <EmptyStateSubtext>Start a conversation to create your presentation</EmptyStateSubtext>
          </EmptyState>
        )}
      </SlideDisplay>
    </ViewerContainer>
  );
};

export default SlideViewer;

import React, { useState, useEffect } from 'react';
import styled from 'styled-components';
import ChatInterface from './components/ChatInterface';
import SlideViewer from './components/SlideViewer';
import './App.css';

const AppContainer = styled.div`
  min-height: 100vh;
  background: #f8fafc;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', sans-serif;
  display: flex;
  flex-direction: column;
`;

const TopRibbon = styled.header`
  background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%);
  color: white;
  padding: 12px 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
  position: sticky;
  top: 0;
  z-index: 100;
`;

const BrandSection = styled.div`
  display: flex;
  align-items: center;
  gap: 12px;
`;


const BrandText = styled.h1`
  margin: 0;
  font-size: 20px;
  font-weight: 600;
`;

const ActionButtons = styled.div`
  display: flex;
  align-items: center;
  gap: 12px;
`;

const StatusIndicator = styled.div`
  display: flex;
  align-items: center;
  gap: 6px;
  background: rgba(16, 185, 129, 0.2);
  border: 1px solid rgba(16, 185, 129, 0.3);
  border-radius: 20px;
  padding: 4px 12px;
  font-size: 14px;
`;

const StatusDot = styled.div`
  width: 8px;
  height: 8px;
  background: #10b981;
  border-radius: 50%;
`;

const RibbonButton = styled.button`
  background: rgba(255, 255, 255, 0.15);
  border: none;
  color: white;
  border-radius: 10px;
  padding: 10px 16px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 500;
  min-width: 44px;
  height: 40px;
  transition: all 0.2s ease;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);

  &:hover {
    background: rgba(255, 255, 255, 0.25);
    transform: translateY(-1px);
    box-shadow: 0 4px 8px rgba(0, 0, 0, 0.15);
  }

  &:active {
    transform: translateY(0);
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.1);
  }

  &:disabled {
    opacity: 0.4;
    cursor: not-allowed;
    transform: none;
    box-shadow: none;
  }
`;

const MainContent = styled.div`
  display: grid;
  grid-template-columns: 580px 1fr;
  flex: 1;
  min-height: calc(100vh - 60px);
  
  @media (max-width: 1200px) {
    grid-template-columns: 500px 1fr;
  }
  
  @media (max-width: 1024px) {
    grid-template-columns: 1fr;
    grid-template-rows: 500px 1fr;
  }
`;

const ChatSection = styled.div`
  background: white;
  border-right: 1px solid #e5e7eb;
  display: flex;
  flex-direction: column;
  padding: 32px;
  gap: 20px;
  max-height: calc(100vh - 60px);
  overflow: hidden;
`;

const SlideSection = styled.div`
  background: #f9fafb;
  display: flex;
  flex-direction: column;
  padding: 24px;
  position: relative;
  overflow: hidden;
  max-height: calc(100vh - 60px);
`;

const SectionTitle = styled.h2`
  margin: 0 0 20px 0;
  font-size: 18px;
  font-weight: 600;
  color: #374151;
  display: flex;
  align-items: center;
  gap: 10px;
`;


const App: React.FC = () => {
  const [slidesHtml, setSlidesHtml] = useState<string>('');
  const [isRefreshing, setIsRefreshing] = useState(false);

  const refreshSlides = async () => {
    setIsRefreshing(true);
    try {
      const response = await fetch('http://localhost:8000/slides/html');
      const data = await response.json();
      setSlidesHtml(data.html);
    } catch (error) {
      console.error('Error refreshing slides:', error);
    } finally {
      setIsRefreshing(false);
    }
  };

  const resetSlides = async () => {
    try {
      await fetch('http://localhost:8000/slides/reset', { method: 'POST' });
      await refreshSlides();
    } catch (error) {
      console.error('Error resetting slides:', error);
    }
  };

  const exportSlides = async () => {
    try {
      const response = await fetch('http://localhost:8000/slides/export', { method: 'POST' });
      const data = await response.json();
      alert(data.message);
    } catch (error) {
      console.error('Error exporting slides:', error);
    }
  };

  useEffect(() => {
    refreshSlides();
  }, []);

  return (
    <AppContainer>
      <TopRibbon>
        <BrandSection>
          <BrandText>EY Slide Generator</BrandText>
        </BrandSection>
        
        <ActionButtons>
          <StatusIndicator>
            <StatusDot />
            Connected
          </StatusIndicator>
          <RibbonButton onClick={refreshSlides} disabled={isRefreshing} title="Refresh Slides">
            {isRefreshing ? (
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M23 4v6h-6"/>
                <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
              </svg>
            ) : (
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M23 4v6h-6"/>
                <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
              </svg>
            )}
          </RibbonButton>
          <RibbonButton onClick={exportSlides} title="Download Slides">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
              <polyline points="7,10 12,15 17,10"/>
              <line x1="12" y1="15" x2="12" y2="3"/>
            </svg>
          </RibbonButton>
          <RibbonButton onClick={resetSlides} title="Reset All Slides">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="3,6 5,6 21,6"/>
              <path d="M19,6v14a2,2 0 0,1 -2,2H7a2,2 0 0,1 -2,-2V6m3,0V4a2,2 0 0,1 2,-2h4a2,2 0 0,1 2,2v2"/>
              <line x1="10" y1="11" x2="10" y2="17"/>
              <line x1="14" y1="11" x2="14" y2="17"/>
            </svg>
          </RibbonButton>
        </ActionButtons>
      </TopRibbon>
      
      <MainContent>
        <ChatSection>
          <div>
            <SectionTitle>💬 Slide Creation Assistant</SectionTitle>
            <p style={{color: '#6b7280', fontSize: '14px', margin: 0, lineHeight: '1.5'}}>
              Describe what slides you'd like to create, and I'll generate them for you!
            </p>
          </div>
          
          <div style={{flex: 1, display: 'flex', flexDirection: 'column'}}>
            <ChatInterface onSlideUpdate={refreshSlides} />
          </div>
        </ChatSection>
        
        <SlideSection>
          <SectionTitle>🎯 Generated Slides</SectionTitle>
          <p style={{color: '#6b7280', fontSize: '14px', marginBottom: '20px'}}>
            Your slides will appear here as you create them
          </p>
          <SlideViewer 
            html={slidesHtml} 
            onRefresh={() => {}} // Handled by ribbon now
            onReset={() => {}}   // Handled by ribbon now  
            onExport={() => {}}  // Handled by ribbon now
            isRefreshing={isRefreshing}
          />
        </SlideSection>
      </MainContent>
    </AppContainer>
  );
};

export default App;
import React, { useState, useEffect, useRef } from 'react';
import styled from 'styled-components';
import ChatInterface from './components/ChatInterface';
import SlideViewer from './components/SlideViewer';
import './App.css';

// EY palette
const EY_YELLOW = '#FFE600';
const EY_BLUE = '#1A9AFA';
const EY_GREY1 = '#747480';
const EY_GREY2 = '#C4C4CD';
const EY_BLACK = '#2E2E38';
const EY_WHITE = '#FFFFFF';
const DARK_GRAY = '#333333';
// Ribbon color (aligned with screenshot)
const RIBBON_BG = '#1F333B';

const AppContainer = styled.div`
  height: 100vh;
  background: ${EY_WHITE};
  padding: 10px;
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', sans-serif;
  font-weight: 400;
  display: flex;
  flex-direction: column;
  overflow: hidden;
`;

const ContentWrapper = styled.div`
  flex: 1;
  background: ${EY_WHITE};
  border-radius: 12px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  min-height: 0;
`;

const Header = styled.div`
  background: ${RIBBON_BG};
  color: ${EY_WHITE};
  padding: 12px 20px 8px 20px;
  text-align: left;
  flex-shrink: 0;
`;

const Ribbon = styled.div`
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
`;

const Brand = styled.div`
  display: flex;
  align-items: center;
  gap: 18px; /* add spacing between databricks logo and title */
`;

const LogoBox = styled.div`
  height: 28px;
  display: flex;
  align-items: center;
  svg { height: 100%; width: auto; display: block; }
`;

const EYParthenonLogo: React.FC = () => (
  <svg className="cmp-logo__image cmp-logo__image--parthenon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 171 55" aria-hidden="true">
    <defs>
      <style>
        {`.cmp-logo__image--parthenon { transition: all 0.3s ease-out; } .cls-1 { fill: #1a9afa; } .cls-2 { fill: #ffe600; } .cls-3 { fill: #fff; }`}
      </style>
    </defs>
    <g>
      <g>
        <path className="cls-1" d="M64.7,41.72a3.7,3.7,0,0,0-.24-1.38,2.64,2.64,0,0,0-1.67-1.65,4.05,4.05,0,0,0-1.34-.21H56.37V45h5.08a3.17,3.17,0,0,0,2.44-.87,3.38,3.38,0,0,0,.81-2.4m2.89,0a6.62,6.62,0,0,1-.47,2.57,5,5,0,0,1-1.29,1.85,5.51,5.51,0,0,1-2,1.13,8.09,8.09,0,0,1-2.53.38h-5V54.7H53.58V35.8H61.5a7.53,7.53,0,0,1,2.42.38,5.34,5.34,0,0,1,1.93,1.11,5,5,0,0,1,1.27,1.85,6.67,6.67,0,0,1,.47,2.58"></path>
        <path className="cls-1" d="M77.31,48.65a5.17,5.17,0,0,0-.71-.28,6.36,6.36,0,0,0-.66-.18c-.23,0-.5-.08-.82-.11s-.67,0-1.05,0a3.54,3.54,0,0,0-2.13.57,1.78,1.78,0,0,0-.79,1.54,2.2,2.2,0,0,0,.23,1.07,1.94,1.94,0,0,0,.56.72,2.59,2.59,0,0,0,.81.42,4.18,4.18,0,0,0,1.13.13A3.79,3.79,0,0,0,75,52.33a4.89,4.89,0,0,0,1-.42,4.39,4.39,0,0,0,.81-.58,3.51,3.51,0,0,0,.59-.65Zm0,6.05V53.3a7.64,7.64,0,0,1-.89.73c-.24.16-.49.3-.74.44a5.5,5.5,0,0,1-1,.37,5.18,5.18,0,0,1-1.29.16,6.15,6.15,0,0,1-1.73-.26A4.31,4.31,0,0,1,69,52.43a5,5,0,0,1-.45-2.21,4.49,4.49,0,0,1,.43-2,3.91,3.91,0,0,1,1.18-1.43,5.15,5.15,0,0,1,1.8-.84,8.87,8.87,0,0,1,2.24-.27,10,10,0,0,1,1.88.15,5.56,5.56,0,0,1,1.28.39V45.12a2.26,2.26,0,0,0-.68-1.78,2.9,2.9,0,0,0-2-.62,8.59,8.59,0,0,0-2,.21,7.06,7.06,0,0,0-1.71.67l-1.08-2.09a8.36,8.36,0,0,1,2.18-1,10.29,10.29,0,0,1,2.67-.32,7.7,7.7,0,0,1,2.17.29,4.61,4.61,0,0,1,1.69.88,4.12,4.12,0,0,1,1.09,1.49,5.25,5.25,0,0,1,.39,2.1V54.7Z"></path>
        <path className="cls-1" d="M90.45,43.47a4.1,4.1,0,0,0-1-.38A4.52,4.52,0,0,0,88.32,43a2.48,2.48,0,0,0-2.06.91,4.37,4.37,0,0,0-.72,2.74V54.7H82.75V40.53h2.79v1.35a3.27,3.27,0,0,1,.58-.66,4.63,4.63,0,0,1,.76-.52,4.71,4.71,0,0,1,.89-.35,4,4,0,0,1,1-.12,5.27,5.27,0,0,1,1.43.16,3.71,3.71,0,0,1,1,.43Z"></path>
        <path className="cls-1" d="M100.75,54.34a5.56,5.56,0,0,1-1.2.48A6.12,6.12,0,0,1,98,55a3.76,3.76,0,0,1-1.27-.2,2.92,2.92,0,0,1-1-.65A2.71,2.71,0,0,1,95.07,53a5.56,5.56,0,0,1-.24-1.75V43.06h-2V40.53h2v-4L97.56,35v5.5h3.51v2.53H97.56v7.7a3.1,3.1,0,0,0,.09.82,1.11,1.11,0,0,0,.26.52,1,1,0,0,0,.45.28,2.59,2.59,0,0,0,.66.08,3.94,3.94,0,0,0,1.11-.17,4.91,4.91,0,0,0,.94-.4Z"></path>
        <path className="cls-1" d="M112.28,54.7v-8a5,5,0,0,0-.7-2.93,2.56,2.56,0,0,0-2.22-1,3.27,3.27,0,0,0-1.19.21,2.14,2.14,0,0,0-.94.7,3.52,3.52,0,0,0-.59,1.14,5.55,5.55,0,0,0-.19,1.56V54.7h-2.79V36.49L106.45,35v6.85a3,3,0,0,1,.64-.69,3.87,3.87,0,0,1,.85-.52,4.61,4.61,0,0,1,1-.33,5.49,5.49,0,0,1,1.08-.11,5.6,5.6,0,0,1,2.22.41,4.14,4.14,0,0,1,1.58,1.2,5.46,5.46,0,0,1,1,2,11.46,11.46,0,0,1,.31,2.71V54.7Z"></path>
        <path className="cls-1" d="M126.52,46.3a6,6,0,0,0-.26-1.37,3.42,3.42,0,0,0-.61-1.13,2.8,2.8,0,0,0-1-.77,3.47,3.47,0,0,0-1.47-.28,3.24,3.24,0,0,0-1.3.24,2.7,2.7,0,0,0-1,.69,3.81,3.81,0,0,0-.65,1.1,5.86,5.86,0,0,0-.35,1.52Zm2.81,1c0,.26,0,.49,0,.71s0,.41-.05.56h-9.38a6,6,0,0,0,.45,1.76,3.93,3.93,0,0,0,.8,1.2,3,3,0,0,0,1.08.7,3.49,3.49,0,0,0,1.24.22,4.43,4.43,0,0,0,1.66-.31c.25-.11.47-.22.67-.33s.44-.27.75-.49l1.65,1.78a7.46,7.46,0,0,1-1,.81,6.84,6.84,0,0,1-1,.55,5.66,5.66,0,0,1-1.28.38,8.45,8.45,0,0,1-1.57.13a5.75,5.75,0,0,1-1.73-.26,5.48,5.48,0,0,1-1.42-.67,6.05,6.05,0,0,1-1.12-1,6.41,6.41,0,0,1-.94-1.37,7.54,7.54,0,0,1-.69-1.87,10,10,0,0,1-.24-2.26,10.22,10.22,0,0,1,.46-3.17,6.54,6.54,0,0,1,1.27-2.32,5.24,5.24,0,0,1,2-1.42,6.5,6.5,0,0,1,2.52-.48,5.77,5.77,0,0,1,2.64.57,5.49,5.49,0,0,1,1.86,1.54A6.91,6.91,0,0,1,129,44.6a9.78,9.78,0,0,1,.37,2.73"></path>
        <path className="cls-1" d="M140,54.7v-8a5.06,5.06,0,0,0-.69-2.91,2.54,2.54,0,0,0-2.23-1,3.15,3.15,0,0,0-1.24.24,2.2,2.2,0,0,0-1,.73,3.13,3.13,0,0,0-.55,1.18,5.73,5.73,0,0,0-.18,1.46V54.7H131.4V40.53h2.78v1.35a3.27,3.27,0,0,1,.65-.69,3.87,3.87,0,0,1,.85-.52,4.35,4.35,0,0,1,1-.33,5.68,5.68,0,0,1,1.09-.11,5.43,5.43,0,0,1,2.22.42,4,4,0,0,1,1.57,1.19,5.35,5.35,0,0,1,1,2,10.93,10.93,0,0,1,.31,2.78V54.7Z"></path>
        <path className="cls-1" d="M154.72,47.62a7.32,7.32,0,0,0-.25-1.95,4.55,4.55,0,0,0-.72-1.5,3.48,3.48,0,0,0-1.14-1,3.43,3.43,0,0,0-1.52-.33,3,3,0,0,0-1.42.33,3.13,3.13,0,0,0-1.07.95,4.53,4.53,0,0,0-.68,1.47,7.08,7.08,0,0,0-.24,1.91,7.6,7.6,0,0,0,.26,2.07,4.2,4.2,0,0,0,.73,1.5,3.12,3.12,0,0,0,1.12.93,3.24,3.24,0,0,0,1.44.31,2.75,2.75,0,0,0,1.43-.37,3.44,3.44,0,0,0,1.1-1,5.08,5.08,0,0,0,.71-1.5,6.87,6.87,0,0,0,.25-1.84m2.81-.08a9.3,9.3,0,0,1-.49,3.15A6.93,6.93,0,0,1,155.69,53a5.64,5.64,0,0,1-2,1.46,6.45,6.45,0,0,1-2.53.5,5.82,5.82,0,0,1-4.47-2,7.05,7.05,0,0,1-1.31-2.33,10,10,0,0,1,0-6.14,6.94,6.94,0,0,1,1.34-2.32,5.65,5.65,0,0,1,2-1.46,6.24,6.24,0,0,1,2.5-.5,6,6,0,0,1,2.51.52,5.83,5.83,0,0,1,2,1.48,7.09,7.09,0,0,1,1.33,2.3,9,9,0,0,1,.48,3"></path>
        <path className="cls-1" d="M168.22,54.7v-8a5.06,5.06,0,0,0-.69-2.91,2.54,2.54,0,0,0-2.23-1,3.15,3.15,0,0,0-1.24.24,2.2,2.2,0,0,0-.95.73,3.31,3.31,0,0,0-.56,1.18,6.22,6.22,0,0,0-.17,1.46V54.7H159.6V40.53h2.78v1.35a3,3,0,0,1,.65-.69,3.81,3.81,0,0,1,.84-.52,4.61,4.61,0,0,1,1-.33,5.57,5.57,0,0,1,1.08-.11,5.44,5.44,0,0,1,2.23.42,4,4,0,0,1,1.57,1.19,5.19,5.19,0,0,1,.94,2,10.9,10.9,0,0,1,.32,2.78V54.7Z"></path>
      </g>
      <g>
        <polygon className="cls-2" points="53.58 0 0 19.52 53.58 10.07 53.58 0 53.58 0"></polygon>
        <path className="cls-3" d="M36.11,27.64l-4.6,8.83-4.59-8.83h-9L27.4,44V54.7h8.1V44L45,27.64ZM0,27.64V54.7H21.68V48.47H8.13V44h9.8V38.33H8.13V33.86H19l-3.6-6.22Z"></path>
      </g>
    </g>
  </svg>
);

const Title = styled.h1`
  margin: 0;
  font-size: 1.6rem; /* larger, like the screenshot */
  font-weight: 600;  /* semi-bold */
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', sans-serif;
  letter-spacing: 0.2px;
  margin-left: 0; /* align flush left like screenshot */
`;

const Actions = styled.div`
  display: flex;
  align-items: center;
  gap: 10px;
`;

const PartnerLogo = styled.img`
  height: 24px; /* slightly larger for the white one-color wordmark */
  display: block;
  max-width: 140px;
`;

const PrimaryButton = styled.button`
  appearance: none;
  border: none;
  background: transparent;
  color: #E6EDF1; /* light grey text like Databricks */
  padding: 8px 12px;
  border-radius: 8px;
  font-size: 0.95rem;
  font-weight: 500;
  cursor: pointer;
  transition: background-color 0.15s ease-in-out, color 0.15s ease-in-out, transform 0.06s ease-in-out;
  outline: none;
  box-shadow: none;
  -webkit-tap-highlight-color: transparent;

  &:hover {
    background: rgba(255, 255, 255, 0.08); /* subtle hover chip */
    color: #F1F5F9;
  }

  &:active {
    background: rgba(255, 255, 255, 0.14);
    color: #FFFFFF;
    transform: translateY(1px);
  }

  &:focus, &:focus-visible {
    outline: none;
    box-shadow: none;
  }
`;

const LinkButtonBlue = styled.button`
  appearance: none;
  border: 1px solid ${EY_BLUE};
  background: transparent;
  color: ${EY_BLUE};
  padding: 8px 12px;
  border-radius: 8px;
  font-size: 0.9rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s ease-in-out;
  &:hover {
    background: ${EY_BLUE};
    color: ${EY_WHITE};
  }
`;


const MainContent = styled.div`
  display: grid;
  grid-template-columns: 0.85fr 2.15fr; /* widen slide column a bit more */
  gap: 0;
  flex: 1;
  overflow: hidden;

  @media (max-width: 1024px) {
    grid-template-columns: 1fr;
  }
`;

const ChatSection = styled.div`
  padding: 20px;
  border-right: 1px solid ${EY_GREY2};
  background: #F6F6FA;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-height: 0;
  border-radius: 16px;
  margin: 8px;

  @media (max-width: 1024px) {
    border-right: none;
    border-bottom: 1px solid #e0e7ff;
  }
`;

const SlideSection = styled.div`
  padding: 8px; /* tighter to maximize viewport */
  background: #F6F6FA;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-height: 0;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04), 0 1px 3px rgba(0, 0, 0, 0.06);
  border-radius: 16px;
  margin: 8px; /* align with colleague's uniform margin */
`;

const SectionTitle = styled.h2`
  margin: 0 0 15px 0;
  font-size: 1.2rem;
  font-weight: 600;
  color: ${EY_BLACK};
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
`;


const App: React.FC = () => {
  const [slidesHtml, setSlidesHtml] = useState<string[]>([]);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const refreshAbortRef = useRef<AbortController | null>(null);
  const refreshDebounceRef = useRef<any>(null);
  const [refreshTick, setRefreshTick] = useState(0);

  const runRefresh = async () => {
    // cancel any in-flight request
    try { refreshAbortRef.current?.abort(); } catch {}
    const controller = new AbortController();
    refreshAbortRef.current = controller;
    setIsRefreshing(true);
    // safety clear in case of long network hang
    const safety = setTimeout(() => setIsRefreshing(false), 5000);
    try {
      const response = await fetch('http://localhost:8000/slides/html', { signal: controller.signal });
      const data = await response.json();
      if (data?.slides !== undefined) setSlidesHtml(data.slides);
    } catch (error) {
      if ((error as any)?.name !== 'AbortError') {
        console.error('Error refreshing slides:', error);
      }
    } finally {
      clearTimeout(safety);
      setIsRefreshing(false);
      setRefreshTick(prev => prev + 1); // notify ChatInterface to sync messages
    }
  };

  const refreshSlides = () => {
    if (refreshDebounceRef.current) clearTimeout(refreshDebounceRef.current);
    refreshDebounceRef.current = setTimeout(runRefresh, 300);
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
      const res = await fetch('http://localhost:8000/slides/export/pptx');
      if (!res.ok) throw new Error(`Export failed: ${res.status}`);
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      // Try to infer filename from response headers, else fallback
      const cd = res.headers.get('Content-Disposition');
      const match = cd && cd.match(/filename="?([^";]+)"?/i);
      a.download = match ? match[1] : 'slides_export.pptx';
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch (error) {
      console.error('Error exporting slides:', error);
    }
  };

  useEffect(() => {
    refreshSlides();
  }, []);

  return (
    <AppContainer>
      <ContentWrapper>
        <Header>
          <Ribbon>
            <Brand>
              <PartnerLogo
                src="https://cdn.bfldr.com/9AYANS2F/at/n8vj68cs4fwqfh3x363vsc/primary-lockup-one-color-white-rgb.svg?auto=webp"
                alt="Databricks"
                onError={(e) => (e.currentTarget.style.display = 'none')}
              />
              <Title>AI Slide Generator</Title>
            </Brand>
            <Actions>
              <PrimaryButton onClick={refreshSlides}>Refresh</PrimaryButton>
              <PrimaryButton onClick={exportSlides}>Download</PrimaryButton>
              <PrimaryButton onClick={resetSlides}>Reset</PrimaryButton>
            </Actions>
          </Ribbon>
        </Header>
        
        <MainContent>
          <ChatSection>
            <SectionTitle>Slide Creation Assistant</SectionTitle>
            <ChatInterface onSlideUpdate={refreshSlides} refreshTick={refreshTick} />
          </ChatSection>
          
          <SlideSection>
            <SectionTitle>Generated Slides</SectionTitle>
            <SlideViewer 
              slides={slidesHtml} 
              isRefreshing={isRefreshing}
            />
          </SlideSection>
        </MainContent>
      </ContentWrapper>
    </AppContainer>
  );
};

export default App;
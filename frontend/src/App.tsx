import { Routes, Route, useLocation } from 'react-router-dom';
import { AppLayout } from './components/Layout/AppLayout';
import './index.css';
import { SelectionProvider } from './contexts/SelectionContext';
import { ProfileProvider } from './contexts/ProfileContext';
import { SessionProvider } from './contexts/SessionContext';
import { GenerationProvider } from './contexts/GenerationContext';

function AppRoutes() {
  // Use location key to force remount when route changes
  const location = useLocation();

  return (
    <Routes>
      <Route path="/" element={<AppLayout key="help" initialView="help" />} />
      <Route path="/help" element={<AppLayout key="help" initialView="help" />} />
      <Route path="/profiles" element={<AppLayout key="profiles" initialView="profiles" />} />
      <Route path="/deck-prompts" element={<AppLayout key="deck_prompts" initialView="deck_prompts" />} />
      <Route path="/slide-styles" element={<AppLayout key="slide_styles" initialView="slide_styles" />} />
      <Route path="/images" element={<AppLayout key="images" initialView="images" />} />
      <Route path="/history" element={<AppLayout key="history" initialView="history" />} />
      <Route path="/sessions/:sessionId/edit" element={<AppLayout key={`edit-${location.pathname}`} initialView="main" />} />
      <Route path="/sessions/:sessionId/view" element={<AppLayout key={`view-${location.pathname}`} initialView="main" viewOnly={true} />} />
    </Routes>
  );
}

function App() {
  return (
    <ProfileProvider>
      <SessionProvider>
        <GenerationProvider>
          <SelectionProvider>
            <AppRoutes />
          </SelectionProvider>
        </GenerationProvider>
      </SessionProvider>
    </ProfileProvider>
  );
}

export default App;

import { useState, useEffect } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { AppLayout } from './components/Layout/AppLayout';
import { AdminPage } from './components/Admin/AdminPage';
import { WelcomeSetup } from './components/Setup';
import './index.css';
import { SelectionProvider } from './contexts/SelectionContext';
import { ProfileProvider } from './contexts/ProfileContext';
import { SessionProvider } from './contexts/SessionContext';
import { GenerationProvider } from './contexts/GenerationContext';
import { ToastProvider } from './contexts/ToastContext';

function AppRoutes() {
  // Single stable key so AppLayout (and sidebar / Recent Decks) stays mounted when
  // switching between help, profiles, deck-prompts, sessions/… — only the main
  // content area updates via initialView sync. Avoids refetching Recent Decks on
  // every nav and keeps partial rendering.
  const layoutKey = "app-layout";

  return (
    <Routes>
      <Route path="/" element={<AppLayout key={layoutKey} initialView="help" />} />
      <Route path="/help" element={<AppLayout key={layoutKey} initialView="help" />} />
      <Route path="/profiles" element={<AppLayout key={layoutKey} initialView="profiles" />} />
      <Route path="/deck-prompts" element={<AppLayout key={layoutKey} initialView="deck_prompts" />} />
      <Route path="/slide-styles" element={<AppLayout key={layoutKey} initialView="slide_styles" />} />
      <Route path="/images" element={<AppLayout key={layoutKey} initialView="images" />} />
      <Route path="/history" element={<AppLayout key={layoutKey} initialView="history" />} />
      <Route path="/admin" element={<AdminPage />} />
      <Route path="/feedback" element={<Navigate to="/admin" replace />} />
      <Route path="/sessions/:sessionId/edit" element={<AppLayout key={layoutKey} initialView="main" />} />
      <Route path="/sessions/:sessionId/view" element={<AppLayout key={layoutKey} initialView="main" viewOnly={true} />} />
      <Route path="*" element={<Navigate to="/help" replace />} />
    </Routes>
  );
}

function App() {
  const [isConfigured, setIsConfigured] = useState<boolean | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    // Check if the app is configured on load
    const checkSetupStatus = async () => {
      try {
        const response = await fetch('/api/setup/status');
        if (response.ok) {
          const data = await response.json();
          setIsConfigured(data.configured);
        } else {
          // If the endpoint doesn't exist (old version), assume configured
          setIsConfigured(true);
        }
      } catch (error) {
        // Network error or endpoint not available, assume configured
        // This handles the case where the backend is the old version
        console.warn('Setup status check failed, assuming configured:', error);
        setIsConfigured(true);
      } finally {
        setIsLoading(false);
      }
    };

    checkSetupStatus();
  }, []);

  const handleSetupComplete = () => {
    setIsConfigured(true);
  };

  // Show loading state while checking configuration
  if (isLoading) {
    return (
      <div style={{ 
        minHeight: '100vh', 
        display: 'flex', 
        alignItems: 'center', 
        justifyContent: 'center',
        background: '#1a1a2e'
      }}>
        <div style={{ color: 'white' }}>Loading...</div>
      </div>
    );
  }

  // Show setup screen if not configured
  if (!isConfigured) {
    return <WelcomeSetup onSetupComplete={handleSetupComplete} />;
  }

  // Show main app if configured
  return (
    <ProfileProvider>
      <SessionProvider>
        <GenerationProvider>
          <SelectionProvider>
            <ToastProvider>
              <AppRoutes />
            </ToastProvider>
          </SelectionProvider>
        </GenerationProvider>
      </SessionProvider>
    </ProfileProvider>
  );
}

export default App;

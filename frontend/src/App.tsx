import { useState, useEffect } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { AppLayout } from './components/Layout/AppLayout';
import { AdminPage } from './components/Admin/AdminPage';
import { useCurrentUser } from './hooks/useCurrentUser';
import { WelcomeSetup } from './components/Setup';
import './index.css';
import { SelectionProvider } from './contexts/SelectionContext';
import { AgentConfigProvider } from './contexts/AgentConfigContext';
import { SessionProvider } from './contexts/SessionContext';
import { GenerationProvider } from './contexts/GenerationContext';
import { ToastProvider } from './contexts/ToastContext';
import { TourProvider } from './contexts/TourContext';
import { AppTour } from './components/Tour/AppTour';
import { WelcomeModal } from './components/Tour/WelcomeModal';

/**
 * Renders the admin page only for admins; sends everyone else to "/".
 *
 * UX gate ONLY — it hides a page a non-admin cannot use anyway. The admin API
 * routes each enforce their own server-side admin check, and those 403s are the
 * real protection; nothing here is trusted for authorization.
 *
 * While identity is still resolving the verdict is UNKNOWN, so this renders
 * nothing: showing the page would flash admin content at a non-admin, and
 * redirecting would bounce a genuine admin off their own page.
 */
function RequireAdmin({ children }: { children: React.ReactNode }) {
  const { isAdmin, loading } = useCurrentUser();

  if (loading) return null;
  if (!isAdmin) return <Navigate to="/" replace />;
  return <>{children}</>;
}

function AppRoutes() {
  // Single stable key so AppLayout (and sidebar / Recent Decks) stays mounted when
  // switching between help, profiles, deck-prompts, sessions/… — only the main
  // content area updates via initialView sync. Avoids refetching Recent Decks on
  // every nav and keeps partial rendering.
  const layoutKey = "app-layout";

  return (
    <Routes>
      <Route path="/" element={<AppLayout key={layoutKey} initialView="main" />} />
      <Route path="/help" element={<AppLayout key={layoutKey} initialView="help" />} />
      <Route path="/profiles" element={<AppLayout key={layoutKey} initialView="profiles" />} />
      <Route path="/deck-prompts" element={<AppLayout key={layoutKey} initialView="deck_prompts" />} />
      <Route path="/slide-styles" element={<AppLayout key={layoutKey} initialView="slide_styles" />} />
      <Route path="/design-systems" element={<AppLayout key={layoutKey} initialView="design_systems" />} />
      <Route path="/images" element={<AppLayout key={layoutKey} initialView="images" />} />
      <Route path="/history" element={<AppLayout key={layoutKey} initialView="history" />} />
      {/* /feedback redirects here, so it inherits this gate for free. */}
      <Route path="/admin" element={<RequireAdmin><AdminPage /></RequireAdmin>} />
      <Route path="/feedback" element={<Navigate to="/admin" replace />} />
      <Route path="/sessions/:sessionId/edit" element={<AppLayout key={layoutKey} initialView="main" />} />
      <Route path="/sessions/:sessionId/view" element={<AppLayout key={layoutKey} initialView="main" viewOnly={true} />} />
      <Route path="*" element={<Navigate to="/" replace />} />
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
    <SessionProvider>
      <GenerationProvider>
        <SelectionProvider>
          <ToastProvider>
            <AgentConfigProvider>
              <TourProvider>
                <AppRoutes />
                <AppTour />
                <WelcomeModal />
              </TourProvider>
            </AgentConfigProvider>
          </ToastProvider>
        </SelectionProvider>
      </GenerationProvider>
    </SessionProvider>
  );
}

export default App;

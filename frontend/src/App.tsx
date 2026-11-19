import { useState, useEffect } from 'react';
import { Routes, Route, Navigate, matchPath, useLocation } from 'react-router-dom';
import { AppLayout } from './components/Layout/AppLayout';
import { AdminPage } from './components/Admin/AdminPage';
import { ReviewAndPublishPage } from './components/Admin/GraphRelease';
import { PresenterPage } from './components/Presenter';
import { useCurrentUser } from './hooks/useCurrentUser';
import { WelcomeSetup } from './components/Setup';
import './index.css';
import { AgentConfigProvider } from './contexts/AgentConfigContext';
import { SessionProvider } from './contexts/SessionContext';
import { GenerationProvider } from './contexts/GenerationContext';
import { ToastProvider } from './contexts/ToastContext';
import { TourProvider } from './contexts/TourContext';
import { AppTour } from './components/Tour/AppTour';
import { WelcomeModal } from './components/Tour/WelcomeModal';
import { WhatsNewModal } from './components/WhatsNew/WhatsNewModal';
import { WhatsNewProvider } from './contexts/WhatsNewContext';

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

/** The presenter window's route. It is a private second window, not the editor. */
const PRESENTER_ROUTE = '/sessions/:sessionId/present';

/** True on the presenter window, where the editor's onboarding overlays must not appear. */
function isPresenterPath(pathname: string): boolean {
  return matchPath(PRESENTER_ROUTE, pathname) !== null;
}

/**
 * The tour, welcome and "What's new" overlays belong to the editor. The
 * presenter window is a small pop-up the presenter reads from mid-talk, so
 * none of them may mount over it.
 */
function EditorOverlays() {
  const { pathname } = useLocation();
  if (isPresenterPath(pathname)) return null;
  return (
    <>
      <AppTour />
      <WelcomeModal />
      <WhatsNewModal />
    </>
  );
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
      <Route path="/settings" element={<AppLayout key={layoutKey} initialView="settings" />} />
      <Route path="/history" element={<AppLayout key={layoutKey} initialView="history" />} />
      {/* /feedback redirects here, so it inherits this gate for free. */}
      <Route path="/admin" element={<RequireAdmin><AdminPage /></RequireAdmin>} />
      <Route path="/admin/agent-definitions/review" element={<RequireAdmin><ReviewAndPublishPage /></RequireAdmin>} />
      <Route path="/feedback" element={<Navigate to="/admin" replace />} />
      <Route path="/sessions/:sessionId/edit" element={<AppLayout key={layoutKey} initialView="main" />} />
      <Route path="/sessions/:sessionId/view" element={<AppLayout key={layoutKey} initialView="main" viewOnly={true} />} />
      {/* The presenter window: its own page, outside the editor chrome. */}
      <Route path={PRESENTER_ROUTE} element={<PresenterPage />} />
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
          <ToastProvider>
            <AgentConfigProvider>
              <TourProvider>
                <WhatsNewProvider>
                  <AppRoutes />
                  <EditorOverlays />
                </WhatsNewProvider>
              </TourProvider>
            </AgentConfigProvider>
          </ToastProvider>
      </GenerationProvider>
    </SessionProvider>
  );
}

export default App;

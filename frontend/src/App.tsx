import { useState, useEffect } from 'react';
import { AppLayout } from './components/Layout/AppLayout';
import { WelcomeSetup } from './components/Setup';
import './index.css';
import { SelectionProvider } from './contexts/SelectionContext';
import { ProfileProvider } from './contexts/ProfileContext';
import { SessionProvider } from './contexts/SessionContext';
import { GenerationProvider } from './contexts/GenerationContext';

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
            <AppLayout />
          </SelectionProvider>
        </GenerationProvider>
      </SessionProvider>
    </ProfileProvider>
  );
}

export default App;

import { useState } from 'react';
import './WelcomeSetup.css';

interface WelcomeSetupProps {
  onSetupComplete: () => void;
}

export function WelcomeSetup({ onSetupComplete }: WelcomeSetupProps) {
  const [workspaceUrl, setWorkspaceUrl] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [step, setStep] = useState<'input' | 'authenticate' | 'verifying'>('input');
  const [savedUrl, setSavedUrl] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setIsLoading(true);

    try {
      // Normalize the URL
      let url = workspaceUrl.trim();
      if (!url.startsWith('http://') && !url.startsWith('https://')) {
        url = `https://${url}`;
      }
      url = url.replace(/\/$/, ''); // Remove trailing slash

      // Save the configuration
      const response = await fetch('/api/setup/configure', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ host: url }),
      });

      if (!response.ok) {
        const data = await response.json();
        let errorMsg = 'Failed to save configuration';
        if (data.detail) {
          if (Array.isArray(data.detail)) {
            errorMsg = data.detail.map((e: { msg?: string }) => e.msg || String(e)).join(', ');
          } else if (typeof data.detail === 'string') {
            errorMsg = data.detail;
          }
        }
        throw new Error(errorMsg);
      }

      setSavedUrl(url);
      setStep('authenticate');
      
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred');
    } finally {
      setIsLoading(false);
    }
  };

  const handleOpenAuth = () => {
    // Trigger the OAuth flow - this opens Databricks auth in browser
    fetch('/api/setup/test-connection', { method: 'POST' })
      .then(response => {
        if (response.ok) {
          // Auth succeeded, move to main app
          onSetupComplete();
        }
      })
      .catch(() => {
        // Will handle in verify step
      });

    // Show verifying state after a short delay
    setTimeout(() => {
      setStep('verifying');
    }, 1000);
  };

  const handleVerifyConnection = async () => {
    setIsLoading(true);
    setError(null);

    try {
      const response = await fetch('/api/setup/test-connection', {
        method: 'POST',
      });

      if (!response.ok) {
        const data = await response.json();
        let errorMsg = 'Connection failed. Please try signing in again.';
        if (data.detail) {
          if (Array.isArray(data.detail)) {
            errorMsg = data.detail.map((e: { msg?: string }) => e.msg || String(e)).join(', ');
          } else if (typeof data.detail === 'string') {
            errorMsg = data.detail;
          }
        }
        throw new Error(errorMsg);
      }

      // Success!
      onSetupComplete();
      
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="welcome-setup">
      <div className="welcome-card">
        <div className="welcome-header">
          <h1>Welcome to tellr</h1>
          <p className="subtitle">AI-powered slide generator for Databricks</p>
        </div>

        {step === 'input' && (
          <form onSubmit={handleSubmit} className="setup-form">
            <div className="form-group">
              <label htmlFor="workspace-url">
                Enter your Databricks workspace URL
              </label>
              <input
                id="workspace-url"
                type="text"
                value={workspaceUrl}
                onChange={(e) => setWorkspaceUrl(e.target.value)}
                placeholder="https://your-workspace.cloud.databricks.com"
                disabled={isLoading}
                autoFocus
              />
              <p className="help-text">
                This is the URL you use to access your Databricks workspace.
              </p>
            </div>

            {error && (
              <div className="error-message">
                {error}
              </div>
            )}

            <button
              type="submit"
              className="connect-button"
              disabled={!workspaceUrl.trim() || isLoading}
            >
              {isLoading ? 'Saving...' : 'Continue'}
            </button>
          </form>
        )}

        {step === 'authenticate' && (
          <div className="authenticate-state">
            <div className="workspace-badge">
              <span className="badge-icon">✓</span>
              <span className="badge-text">{savedUrl}</span>
            </div>

            <p className="auth-instruction">
              Click below to sign in with your Databricks account.
              <br />
              A new window will open for authentication.
            </p>

            {error && (
              <div className="error-message">
                {error}
              </div>
            )}

            <button
              type="button"
              className="connect-button"
              onClick={handleOpenAuth}
            >
              Sign in with Databricks
            </button>

            <button
              type="button"
              className="back-button"
              onClick={() => setStep('input')}
            >
              ← Change workspace URL
            </button>
          </div>
        )}

        {step === 'verifying' && (
          <div className="verifying-state">
            <div className="workspace-badge">
              <span className="badge-icon">✓</span>
              <span className="badge-text">{savedUrl}</span>
            </div>

            <div className="auth-steps">
              <p><strong>Complete these steps:</strong></p>
              <ol>
                <li>Sign in to Databricks in the popup window</li>
                <li>When you see "You can close this tab", close the popup</li>
                <li>Click the button below to continue</li>
              </ol>
            </div>

            {error && (
              <div className="error-message">
                {error}
              </div>
            )}

            <button
              type="button"
              className="connect-button"
              onClick={handleVerifyConnection}
              disabled={isLoading}
            >
              {isLoading ? 'Verifying...' : "I've signed in - Continue →"}
            </button>

            <button
              type="button"
              className="secondary-button"
              onClick={handleOpenAuth}
            >
              Open sign-in window again
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

import React, { createContext, useContext, useState, useCallback } from 'react';
import { api } from '../services/api';
import type { SlideDeck } from '../types/slide';

/**
 * Generate a local UUID for ephemeral sessions.
 * Sessions are only persisted to the database on first message.
 */
function generateLocalSessionId(): string {
  return crypto.randomUUID();
}

interface SessionRestoreResult {
  slideDeck: SlideDeck | null;
  rawHtml: string | null;
}

interface SessionContextType {
  sessionId: string | null;
  sessionTitle: string | null;
  experimentUrl: string | null;
  isInitializing: boolean;
  error: string | null;
  lastWorkingSessionId: string | null;
  setLastWorkingSessionId: (id: string) => void;
  createNewSession: () => string;
  switchSession: (sessionId: string) => Promise<SessionRestoreResult>;
  renameSession: (title: string) => Promise<void>;
  setExperimentUrl: (url: string | null) => void;
}

const SessionContext = createContext<SessionContextType | undefined>(undefined);

export const SessionProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  // Generate local session ID immediately - no API call needed
  const [sessionId, setSessionId] = useState<string | null>(() => generateLocalSessionId());
  const [sessionTitle, setSessionTitle] = useState<string | null>(null);
  const [experimentUrl, setExperimentUrl] = useState<string | null>(null);
  const [isInitializing, setIsInitializing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastWorkingSessionId, setLastWorkingSessionIdState] = useState<string | null>(
    () => localStorage.getItem('lastWorkingSessionId')
  );

  const setLastWorkingSessionId = useCallback((id: string) => {
    setLastWorkingSessionIdState(id);
    localStorage.setItem('lastWorkingSessionId', id);
  }, []);

  // Set the session ID in the API service on initial render
  React.useEffect(() => {
    if (sessionId) {
      api.setCurrentSessionId(sessionId);
    }
  }, []);

  /**
   * Create a new ephemeral session (local UUID only, no API call).
   * The session will be persisted to DB on first message.
   * Returns the new session ID.
   */
  const createNewSession = useCallback((): string => {
    const newSessionId = generateLocalSessionId();
    setSessionId(newSessionId);
    setSessionTitle(null);
    setExperimentUrl(null);
    setError(null);
    api.setCurrentSessionId(newSessionId);
    return newSessionId;
  }, []);

  /**
   * Switch to an existing (persisted) session from history.
   * Returns both the slide deck and raw HTML for debug view.
   */
  const switchSession = useCallback(async (newSessionId: string): Promise<SessionRestoreResult> => {
    setIsInitializing(true);
    setError(null);
    try {
      // Validate session exists and get its info
      const sessionInfo = await api.getSession(newSessionId);

      // Get slide deck if it has one
      let slideDeck: SlideDeck | null = null;
      let rawHtml: string | null = null;
      if (sessionInfo.has_slide_deck) {
        const result = await api.getSlides(newSessionId);
        slideDeck = result.slide_deck;
        // Extract raw HTML from the slide deck (stored as html_content in DB)
        rawHtml = slideDeck?.html_content || null;
      }

      // Update state
      setSessionId(newSessionId);
      setSessionTitle(sessionInfo.title);
      api.setCurrentSessionId(newSessionId);

      return { slideDeck, rawHtml };
    } catch (err) {
      console.error('Failed to switch session:', err);
      setError('Failed to restore session. Starting new session.');
      // Fall back to creating new local session
      createNewSession();
      return { slideDeck: null, rawHtml: null };
    } finally {
      setIsInitializing(false);
    }
  }, [createNewSession]);

  /**
   * Rename the current session.
   * Note: This only works for sessions that have been persisted (have sent at least one message).
   */
  const renameSession = useCallback(async (title: string) => {
    if (!sessionId) return;

    try {
      await api.renameSession(sessionId, title);
      setSessionTitle(title);
    } catch (err) {
      console.error('Failed to rename session:', err);
      throw err;
    }
  }, [sessionId]);

  return (
    <SessionContext.Provider
      value={{
        sessionId,
        sessionTitle,
        experimentUrl,
        isInitializing,
        error,
        lastWorkingSessionId,
        setLastWorkingSessionId,
        createNewSession,
        switchSession,
        renameSession,
        setExperimentUrl,
      }}
    >
      {children}
    </SessionContext.Provider>
  );
};

export const useSession = (): SessionContextType => {
  const context = useContext(SessionContext);
  if (context === undefined) {
    throw new Error('useSession must be used within a SessionProvider');
  }
  return context;
};

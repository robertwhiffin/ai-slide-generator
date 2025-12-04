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

interface SessionContextType {
  sessionId: string | null;
  sessionTitle: string | null;
  isInitializing: boolean;
  error: string | null;
  createNewSession: () => void;
  switchSession: (sessionId: string) => Promise<SlideDeck | null>;
  renameSession: (title: string) => Promise<void>;
}

const SessionContext = createContext<SessionContextType | undefined>(undefined);

export const SessionProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  // Generate local session ID immediately - no API call needed
  const [sessionId, setSessionId] = useState<string | null>(() => generateLocalSessionId());
  const [sessionTitle, setSessionTitle] = useState<string | null>(null);
  const [isInitializing, setIsInitializing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Set the session ID in the API service on initial render
  React.useEffect(() => {
    if (sessionId) {
      api.setCurrentSessionId(sessionId);
    }
  }, []);

  /**
   * Create a new ephemeral session (local UUID only, no API call).
   * The session will be persisted to DB on first message.
   */
  const createNewSession = useCallback(() => {
    const newSessionId = generateLocalSessionId();
    setSessionId(newSessionId);
    setSessionTitle(null);
    setError(null);
    api.setCurrentSessionId(newSessionId);
  }, []);

  /**
   * Switch to an existing (persisted) session from history.
   */
  const switchSession = useCallback(async (newSessionId: string): Promise<SlideDeck | null> => {
    setIsInitializing(true);
    setError(null);
    try {
      // Validate session exists and get its info
      const sessionInfo = await api.getSession(newSessionId);
      
      // Get slide deck if it has one
      let slideDeck: SlideDeck | null = null;
      if (sessionInfo.has_slide_deck) {
        const result = await api.getSlides(newSessionId);
        slideDeck = result.slide_deck;
      }

      // Update state
      setSessionId(newSessionId);
      setSessionTitle(sessionInfo.title);
      api.setCurrentSessionId(newSessionId);

      return slideDeck;
    } catch (err) {
      console.error('Failed to switch session:', err);
      setError('Failed to restore session. Starting new session.');
      // Fall back to creating new local session
      createNewSession();
      return null;
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
        isInitializing,
        error,
        createNewSession,
        switchSession,
        renameSession,
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

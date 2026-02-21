import React, { createContext, useContext, useState, useCallback } from 'react';
import { api, ApiError } from '../services/api';
import type { SlideDeck } from '../types/slide';

function generateLocalSessionId(): string {
  return crypto.randomUUID();
}

interface SessionRestoreResult {
  slideDeck: SlideDeck | null;
  rawHtml: string | null;
}

/** Optional session info to avoid duplicate getSession when caller already has it */
export interface OptionalSessionInfo {
  title: string | null;
  has_slide_deck?: boolean;
}

interface SessionContextType {
  sessionId: string | null;
  sessionTitle: string | null;
  experimentUrl: string | null;
  isInitializing: boolean;
  error: string | null;
  createNewSession: () => string;
  switchSession: (sessionId: string, existingSessionInfo?: OptionalSessionInfo) => Promise<SessionRestoreResult>;
  renameSession: (title: string, slideCount?: number) => Promise<void>;
  setSessionTitle: (title: string | null) => void;
  setExperimentUrl: (url: string | null) => void;
}

const SessionContext = createContext<SessionContextType | undefined>(undefined);

export const SessionProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [sessionId, setSessionId] = useState<string | null>(() => generateLocalSessionId());
  const [sessionTitle, setSessionTitle] = useState<string | null>(null);
  const [experimentUrl, setExperimentUrl] = useState<string | null>(null);
  const [isInitializing, setIsInitializing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Set the session ID in the API service on initial render
  React.useEffect(() => {
    if (sessionId) {
      api.setCurrentSessionId(sessionId);
    }
  }, []);

  /**
   * Create a new local session (UUID + context state only).
   * Callers are responsible for DB persistence via api.createSession().
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
   * When existingSessionInfo is provided (e.g. from a prior getSession), skips the getSession call.
   */
  const switchSession = useCallback(
    async (newSessionId: string, existingSessionInfo?: OptionalSessionInfo): Promise<SessionRestoreResult> => {
      setIsInitializing(true);
      setError(null);
      try {
        let sessionInfo: { title: string | null; has_slide_deck?: boolean };
        if (existingSessionInfo != null) {
          sessionInfo = {
            title: existingSessionInfo.title ?? null,
            has_slide_deck: existingSessionInfo.has_slide_deck,
          };
        } else {
          const full = await api.getSession(newSessionId);
          sessionInfo = { title: full.title, has_slide_deck: full.has_slide_deck };
        }

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
        // Let 404 (session not found) propagate so caller can redirect to /help
        if (err instanceof ApiError && err.status === 404) {
          throw err;
        }
        console.error('Failed to switch session:', err);
        setError('Failed to restore session. Starting new session.');
        createNewSession();
        return { slideDeck: null, rawHtml: null };
      } finally {
        setIsInitializing(false);
      }
    },
    [createNewSession],
  );

  /**
   * Rename the current session (optionally update slide count for sidebar/list).
   * Note: This only works for sessions that have been persisted (have sent at least one message).
   */
  const renameSession = useCallback(async (title: string, slideCount?: number) => {
    if (!sessionId) return;

    try {
      await api.renameSession(sessionId, title, slideCount);
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
        createNewSession,
        switchSession,
        renameSession,
        setSessionTitle,
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

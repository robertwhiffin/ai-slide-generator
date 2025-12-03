import React, { createContext, useContext, useEffect, useState, useCallback } from 'react';
import { api } from '../services/api';
import type { SlideDeck } from '../types/slide';

const STORAGE_KEY = 'ai-slide-generator-session-id';

interface SessionContextType {
  sessionId: string | null;
  sessionTitle: string | null;
  isInitializing: boolean;
  error: string | null;
  createNewSession: () => Promise<void>;
  switchSession: (sessionId: string) => Promise<SlideDeck | null>;
  renameSession: (title: string) => Promise<void>;
}

const SessionContext = createContext<SessionContextType | undefined>(undefined);

export const SessionProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessionTitle, setSessionTitle] = useState<string | null>(null);
  const [isInitializing, setIsInitializing] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const saveToStorage = (id: string) => {
    try {
      localStorage.setItem(STORAGE_KEY, id);
    } catch (err) {
      console.warn('Failed to save session to localStorage:', err);
    }
  };

  const loadFromStorage = (): string | null => {
    try {
      return localStorage.getItem(STORAGE_KEY);
    } catch (err) {
      console.warn('Failed to load session from localStorage:', err);
      return null;
    }
  };

  const clearStorage = () => {
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch (err) {
      console.warn('Failed to clear session from localStorage:', err);
    }
  };

  const createNewSession = useCallback(async () => {
    setIsInitializing(true);
    setError(null);
    try {
      const session = await api.createSession();
      setSessionId(session.session_id);
      setSessionTitle(session.title);
      api.setCurrentSessionId(session.session_id);
      saveToStorage(session.session_id);
    } catch (err) {
      console.error('Failed to create session:', err);
      setError('Failed to initialize session. Please refresh the page.');
    } finally {
      setIsInitializing(false);
    }
  }, []);

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
      saveToStorage(newSessionId);

      return slideDeck;
    } catch (err) {
      console.error('Failed to switch session:', err);
      setError('Failed to restore session. Starting new session.');
      // Fall back to creating new session
      await createNewSession();
      return null;
    } finally {
      setIsInitializing(false);
    }
  }, [createNewSession]);

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

  // Initialize session on mount - try to restore from localStorage first
  useEffect(() => {
    const initSession = async () => {
      const storedSessionId = loadFromStorage();

      if (storedSessionId) {
        try {
          // Try to restore existing session
          const sessionInfo = await api.getSession(storedSessionId);
          setSessionId(storedSessionId);
          setSessionTitle(sessionInfo.title);
          api.setCurrentSessionId(storedSessionId);
          setIsInitializing(false);
          return;
        } catch (err) {
          // Session no longer exists, clear storage and create new
          console.log('Stored session no longer valid, creating new session');
          clearStorage();
        }
      }

      // Create new session
      await createNewSession();
    };

    initSession();
  }, [createNewSession]);

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

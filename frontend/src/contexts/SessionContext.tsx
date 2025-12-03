import React, { createContext, useContext, useEffect, useState, useCallback } from 'react';
import { api } from '../services/api';

interface SessionContextType {
  sessionId: string | null;
  isInitializing: boolean;
  error: string | null;
  createNewSession: () => Promise<void>;
}

const SessionContext = createContext<SessionContextType | undefined>(undefined);

export const SessionProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [isInitializing, setIsInitializing] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const createNewSession = useCallback(async () => {
    setIsInitializing(true);
    setError(null);
    try {
      const session = await api.createSession();
      setSessionId(session.session_id);
      api.setCurrentSessionId(session.session_id);
    } catch (err) {
      console.error('Failed to create session:', err);
      setError('Failed to initialize session. Please refresh the page.');
    } finally {
      setIsInitializing(false);
    }
  }, []);

  // Initialize session on mount
  useEffect(() => {
    createNewSession();
  }, [createNewSession]);

  return (
    <SessionContext.Provider value={{ sessionId, isInitializing, error, createNewSession }}>
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


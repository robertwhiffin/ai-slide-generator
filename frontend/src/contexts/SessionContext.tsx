import React, { createContext, useContext, useState, useCallback } from 'react';
import { api, ApiError, type CollaborationHistory } from '../services/api';
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
  experiment_url?: string | null;
  graph_version?: number | null;
  active_graph_version?: number | null;
  is_older_than_active?: boolean;
}

interface SessionContextType {
  sessionId: string | null;
  sessionTitle: string | null;
  experimentUrl: string | null;
  graphVersion: number | null;
  activeGraphVersion: number | null;
  isGraphVersionOlder: boolean;
  /**
   * Privacy-safe collaboration evidence for the CURRENT session's shared deck,
   * or null when none has been loaded for it. Loaded only by a successful
   * switchSession, cleared by createNewSession — never inferred from the root
   * session's own pinned version, and never carried across a session change.
   */
  collaborationHistory: CollaborationHistory | null;
  /**
   * True when the collaboration-history load for the current session failed.
   * Deliberately a single boolean with no status or detail: the endpoint's 404
   * is byte-identical for an unauthorized real id and a fabricated one, so the
   * client keeps exactly one generic failure state and cannot become an
   * existence oracle.
   */
  collaborationHistoryFailed: boolean;
  isSessionPersisted: boolean;
  isInitializing: boolean;
  error: string | null;
  createNewSession: () => string;
  markSessionPersisted: () => void;
  switchSession: (sessionId: string, existingSessionInfo?: OptionalSessionInfo, isCancelled?: () => boolean) => Promise<SessionRestoreResult>;
  renameSession: (title: string, slideCount?: number) => Promise<void>;
  setSessionTitle: (title: string | null) => void;
  setExperimentUrl: (url: string | null) => void;
  setConversationGraphVersion: (info: Pick<OptionalSessionInfo, 'graph_version' | 'active_graph_version' | 'is_older_than_active'>) => void;
}

const SessionContext = createContext<SessionContextType | undefined>(undefined);

export const SessionProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [sessionId, setSessionId] = useState<string | null>(() => generateLocalSessionId());
  const [sessionTitle, setSessionTitle] = useState<string | null>(null);
  const [experimentUrl, setExperimentUrl] = useState<string | null>(null);
  const [graphVersion, setGraphVersion] = useState<number | null>(null);
  const [activeGraphVersion, setActiveGraphVersion] = useState<number | null>(null);
  const [isGraphVersionOlder, setIsGraphVersionOlder] = useState(false);
  const [collaborationHistory, setCollaborationHistory] = useState<CollaborationHistory | null>(null);
  const [collaborationHistoryFailed, setCollaborationHistoryFailed] = useState(false);
  const [isSessionPersisted, setIsSessionPersisted] = useState(false);
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
    setGraphVersion(null);
    setActiveGraphVersion(null);
    setIsGraphVersionOlder(false);
    setCollaborationHistory(null);
    setCollaborationHistoryFailed(false);
    setIsSessionPersisted(false);
    setError(null);
    api.setCurrentSessionId(newSessionId);
    return newSessionId;
  }, []);

  const markSessionPersisted = useCallback(() => {
    setIsSessionPersisted(true);
  }, []);

  const setConversationGraphVersion = useCallback((info: Pick<OptionalSessionInfo, 'graph_version' | 'active_graph_version' | 'is_older_than_active'>) => {
    setGraphVersion(info.graph_version ?? null);
    setActiveGraphVersion(info.active_graph_version ?? null);
    setIsGraphVersionOlder(info.is_older_than_active ?? false);
  }, []);

  /**
   * Switch to an existing (persisted) session from history.
   * Returns both the slide deck and raw HTML for debug view.
   * When existingSessionInfo is provided (e.g. from a prior getSession), skips the getSession call.
   *
   * isCancelled: optional predicate called before each side-effectful state update. If it returns
   * true (e.g. a newer restore has started), setSessionTitle and setSessionId are skipped so that
   * a superseded concurrent load doesn't bounce sessionId through a stale intermediate value —
   * which would cause ChatPanel to clear+reload messages and SlidePanel effects to fire spuriously.
   */
  const switchSession = useCallback(
    async (newSessionId: string, existingSessionInfo?: OptionalSessionInfo, isCancelled?: () => boolean): Promise<SessionRestoreResult> => {
      setIsInitializing(true);
      setError(null);
      try {
        let sessionInfo: OptionalSessionInfo;
        if (existingSessionInfo != null) {
          sessionInfo = {
            title: existingSessionInfo.title ?? null,
            has_slide_deck: existingSessionInfo.has_slide_deck,
            experiment_url: existingSessionInfo.experiment_url,
            graph_version: existingSessionInfo.graph_version,
            active_graph_version: existingSessionInfo.active_graph_version,
            is_older_than_active: existingSessionInfo.is_older_than_active,
          };
        } else {
          const full = await api.getSession(newSessionId);
          sessionInfo = {
            title: full.title,
            has_slide_deck: full.has_slide_deck,
            experiment_url: full.experiment_url,
            graph_version: full.graph_version,
            active_graph_version: full.active_graph_version,
            is_older_than_active: full.is_older_than_active,
          };
        }

        // Collaboration evidence for this session's shared deck. Started HERE,
        // before the slides fetch, so it runs in PARALLEL with it and adds no
        // serial round-trip to a restore.
        //
        // It deliberately does NOT block the commit below. Awaiting it there
        // would delay the title, sessionId and pinned Graph Version behind a
        // provenance query — a restore that renders later than it does today,
        // for a badge that is not part of the deck. The commit handler is
        // attached AFTER a successful commit instead (see below).
        //
        // The `.catch` is attached at creation, not at the consumer, so a
        // rejected history load can never surface as an unhandled rejection —
        // including on the path where the slides fetch throws first and no
        // consumer is ever attached.
        const collaborationLoad = api
          .getCollaborationHistory(newSessionId)
          .then((history) => ({ history, failed: false }))
          .catch(() => ({ history: null as CollaborationHistory | null, failed: true }));

        // Get slide deck if it has one
        let slideDeck: SlideDeck | null = null;
        let rawHtml: string | null = null;
        if (sessionInfo.has_slide_deck) {
          const result = await api.getSlides(newSessionId);
          slideDeck = result.slide_deck;
          // Extract raw HTML from the slide deck (stored as html_content in DB)
          rawHtml = slideDeck?.html_content || null;
        }

        // Commit all session state atomically — title, sessionId, and the caller's setSlideDeck
        // all happen in the same microtask continuation, so React 18 batches them into ONE render.
        // Previously setSessionTitle was called before api.getSlides (an "early update"), which
        // created an intermediate render showing the new title with the old slides. Moving it here
        // means isCancelled() is also evaluated AFTER the async gap where racing can occur —
        // if the user clicked a different session during api.getSlides, isCancelled() returns true
        // and none of the stale state is committed.
        if (!isCancelled?.()) {
          setSessionTitle(sessionInfo.title);
          setSessionId(newSessionId);
          api.setCurrentSessionId(newSessionId);
          setExperimentUrl(sessionInfo.experiment_url ?? null);
          setConversationGraphVersion(sessionInfo);
          // Clear the OUTGOING session's evidence in the same batch. Without
          // this, the previous deck's contributor rows would stay on screen
          // against the new conversation until the new load lands.
          setCollaborationHistory(null);
          setCollaborationHistoryFailed(false);
          setIsSessionPersisted(true);

          // Attached only on the committed path, so an abandoned restore (the
          // catch below calls createNewSession) can never have its in-flight
          // history land on the session that replaced it.
          void collaborationLoad.then((collaboration) => {
            // Two guards, both EXISTING mechanisms rather than a new generation
            // counter: the caller's cancellation predicate (a superseded
            // concurrent restore) and the api module's current-session id (any
            // session change while this load was in flight — createNewSession,
            // Start latest, another restore).
            if (isCancelled?.()) return;
            if (api.getCurrentSessionId() !== newSessionId) return;
            setCollaborationHistory(collaboration.history);
            setCollaborationHistoryFailed(collaboration.failed);
          });
        }

        return { slideDeck, rawHtml };
      } catch (err) {
        // Let 404 (session not found) and 403 (access revoked) propagate to caller
        if (err instanceof ApiError && (err.status === 404 || err.status === 403)) {
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
    [createNewSession, setConversationGraphVersion],
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
        graphVersion,
        activeGraphVersion,
        isGraphVersionOlder,
        collaborationHistory,
        collaborationHistoryFailed,
        isSessionPersisted,
        isInitializing,
        error,
        createNewSession,
        markSessionPersisted,
        switchSession,
        renameSession,
        setSessionTitle,
        setExperimentUrl,
        setConversationGraphVersion,
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

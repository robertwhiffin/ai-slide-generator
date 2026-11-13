import { useEffect, useRef, useState, forwardRef, useImperativeHandle } from 'react';
import { useNavigate } from 'react-router-dom';
import { Bot, Eraser } from 'lucide-react';
import type { Message } from '../../types/message';
import type { ReplacementInfo, SlideDeck, StageSlideContext } from '../../types/slide';
import { MessageList } from './MessageList';
import { ChatInput } from './ChatInput';
import { DeckModeSelect } from './DeckModeSelect';
import {
  api,
  CHAT_TURN_FALLBACK_ERROR,
  ChatTurnError,
  isPollingMode,
  type SessionMessage,
  type StreamEvent,
} from '../../services/api';
import { conversationApi } from '../../api/conversation';
import { canEditConversation } from '../../utils/conversationPermissions';
import { Button } from '@/ui/button';
import { ConfirmDialog } from '../ConfirmDialog';
import { useEscapeToStop } from './useEscapeToStop';
import {
  CANCELLED_NOTICE,
  FAILED_KEPT_NOTICE,
  FAILED_NOTICE,
  REFUSED_STOP_NOTICE,
  RESTORE_PENDING_NOTICE,
  STOP_CONFIRM_LABEL,
  STOP_DIALOG_TITLE,
  STOP_FAILED_ERROR,
  STOP_KEEP_LABEL,
  stopDialogMessage,
  stopNeedsConfirmation,
} from './stopGenerationCopy';
import {
  CLEAR_CHAT_LABEL,
  CLEAR_CHAT_DIALOG_TITLE,
  CLEAR_CHAT_DIALOG_MESSAGE,
  CLEAR_CHAT_DIALOG_MESSAGE_NO_SPEC,
  CLEAR_CHAT_TOOLTIP,
  CLEAR_CHAT_TOOLTIP_NO_SPEC,
  clearChatErrorMessage,
} from './clearChatCopy';
import {
  DELETE_MESSAGE_CONFIRM_LABEL,
  DELETE_MESSAGE_DIALOG_MESSAGE,
  DELETE_MESSAGE_DIALOG_TITLE,
  deleteMessageErrorMessage,
} from './deleteMessageCopy';
import { withoutTurn, withPersistedUserIds } from '../../utils/conversationTurns';
import { getRotatingLoadingMessage } from '../../utils/loadingMessages';
import { readMessageDetails } from '../../utils/messageDetails';
import { readGeneratedImages } from '../../utils/generatedImages';
import { pickImageMessage, regenerateMessage } from '../../utils/imageChatMessages';
import { useImageGenerationOptions } from '../../hooks/useImageGenerationOptions';
import type { GeneratedImageRef } from '../../types/message';
import {
  QUEUED_TURN_LABEL,
  describeTurnProgress,
  newerTurnProgress,
  parseTurnProgress,
} from '../../utils/turnProgress';
import type { TurnProgress } from '../../types/turnProgress';
import { ReplacementFeedback } from './ReplacementFeedback';
import { ErrorDisplay } from './ErrorDisplay';
import { LoadingIndicator } from './LoadingIndicator';
import { useSession } from '../../contexts/SessionContext';
import { useAgentConfig } from '../../contexts/AgentConfigContext';
import { useGeneration } from '../../contexts/GenerationContext';

interface SlideContext {
  indices: number[];
  slide_htmls: string[];
}

export interface ChatPanelHandle {
  sendMessage: (content: string, slideContext?: SlideContext) => void;
}

interface ChatPanelProps {
  rawHtml: string | null;
  onSlidesGenerated: (slideDeck: SlideDeck, rawHtml: string | null) => void;
  onGenerationStart?: () => void;
  /** E0: called for each slide_ready event; position + content arrive one slide at a
   *  time as the graph's reorder buffer releases them.  Called before `complete`. */
  onSlideReady?: (position: number, html: string, scripts: string) => void;
  /** #314: the deck the server holds, refetched after an ERRORED turn so the viewer does not keep a
   *  stale mid-turn view (synthetic `build-N` slides). Deliberately not `onSlidesGenerated`: that is
   *  the success path (survey trigger, "saved just now", versions reload). */
  onDeckRefetched?: (slideDeck: SlideDeck) => void;
  /** Interrupt generation: the deck the server holds after a rollback (a stop, or a failed turn that
   *  was rolled back); null when it rolled back to no deck. Replaces the viewer's mid-turn view. */
  onDeckRestored?: (slideDeck: SlideDeck | null) => void;
  ensureGraphCapableRoot: () => Promise<boolean>;
  /** Synchronous read of the slide on stage; sent with Agent turns only. */
  getStageSlide?: () => StageSlideContext | undefined;
  disabled?: boolean;
  previewMessages?: Message[] | null;  // When provided, show these instead of live messages
  viewOnlyReason?: string;  // When provided, show why the user cannot edit
  /** Whether the live deck has a Spec. Chooses Clear chat's wording: with a Spec the assistant carries on from it; without one the wording promises nothing about a Spec (#317 lifted #323's Spec gate). */
  hasDeckSpec?: boolean;
  /** Slides in the live deck: the choices of the Generate image dialog's For-slide select. */
  slideCount?: number;
}

// #317: the turn-end id read asks for the newest rows only (GET …/messages keeps messages[-limit:]).
const MESSAGE_ID_READ_LIMIT = 200;

/** A Gateway sign-in notice's link (metadata.sign_in_url), as a string or nothing; Message
 *  decides whether it is a link it will render (https only). */
const readSignInUrl = (value: unknown): string | undefined =>
  typeof value === 'string' && value ? value : undefined;

/** A stored row as the chat shows it. */
const toUiMessage = (msg: SessionMessage): Message => ({
  id: msg.id,
  role: msg.role,
  content: msg.content,
  timestamp: msg.created_at,
  tool_call: msg.metadata?.tool_name ? {
    name: msg.metadata.tool_name,
    arguments: msg.metadata.tool_input || {},
  } : undefined,
  details: readMessageDetails(msg.metadata?.details),
  agent: typeof msg.metadata?.agent === 'string' ? msg.metadata.agent : undefined,
  sign_in_url: readSignInUrl(msg.metadata?.sign_in_url),
  generated_images: toGeneratedImages(msg.metadata?.generated_images),
});

/** The send a stop belongs to: where it went, which send it was, and whether it was typed in the chat
 *  box (only then is there a draft to put back). */
interface TurnRef {
  sentTo: string | null;
  seq: number;
  fromInput: boolean;
}

/** How a send reached the panel. Only the chat box's own sends (`fromInput`) have a draft to restore. */
interface SendOptions {
  slideContext?: SlideContext;
  imageIds?: string[];
  fromInput: boolean;
}

/** A neutral note under the chat; `detail` is a muted second line (a rolled-back failure's cause). */
interface Notice {
  text: string;
  detail?: string;
}

/** The server's reason for a rolled-back failure, when it says more than the notice does. */
const failureDetail = (message: string | undefined): string | undefined => {
  const text = message?.trim();
  return text && text !== CHAT_TURN_FALLBACK_ERROR && text !== FAILED_NOTICE ? text : undefined;
};

/** The images a reply generated, or undefined (no card) when there are none. */
const toGeneratedImages = (value: unknown): GeneratedImageRef[] | undefined => {
  const images = readGeneratedImages(value);
  return images.length > 0 ? images : undefined;
};

/** The live label for a tool call. A Gateway MCP call names its connection and tool, as its
 *  progress row does ("{connection} · {tool}"); every other tool reads "Querying <tool>...". */
const toolCallLabel = (name: string, input: Record<string, unknown> | undefined): string => {
  const connection = input?.connection;
  const tool = input?.tool;
  if (name === 'gateway_mcp' && typeof connection === 'string' && connection && typeof tool === 'string' && tool) {
    return `${connection} · ${tool}`;
  }
  return `Querying ${name}...`;
};

/** The live label for the architect's image tool: "Generating 3 images…". */
const imageGenerationLabel = (input: Record<string, unknown> | undefined): string => {
  const count = input?.count;
  return typeof count === 'number' && Number.isInteger(count) && count >= 1
    ? `Generating ${count} ${count === 1 ? 'image' : 'images'}…`
    : 'Generating images…';
};

export const ChatPanel = forwardRef<ChatPanelHandle, ChatPanelProps>(({
  rawHtml,
  onSlidesGenerated,
  onGenerationStart,
  onSlideReady,
  onDeckRefetched,
  onDeckRestored,
  ensureGraphCapableRoot,
  getStageSlide,
  disabled = false,
  previewMessages = null,
  viewOnlyReason,
  hasDeckSpec = false,
  slideCount = 0,
}, ref) => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [loadingMessage, setLoadingMessage] = useState<string>('');
  const [turnProgress, setTurnProgress] = useState<TurnProgress | null>(null);
  // The turn is waiting for a free job runner (a 'queued' event from polling).
  const [isQueued, setIsQueued] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastReplacement, setLastReplacement] = useState<ReplacementInfo | null>(
    null,
  );
  // Clear chat (#323). Declared above the render-phase reset block below, which calls these setters.
  const [myPermission, setMyPermission] = useState<string | null>(null);
  const [isClearChatDialogOpen, setIsClearChatDialogOpen] = useState(false);
  const [isClearing, setIsClearing] = useState(false);
  // Delete a message (#317). Declared above the render-phase reset block for the same reason.
  const [pendingDeleteId, setPendingDeleteId] = useState<number | null>(null);
  const [isDeletingMessage, setIsDeletingMessage] = useState(false);
  // Interrupt generation. `requestIdRef` is the running turn's chat request id (from `request_accepted`);
  // `pendingStopRef` is the seq of a send whose stop was pressed before that id existed.
  const [stopDialogOpen, setStopDialogOpen] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [restoreDraftKey, setRestoreDraftKey] = useState(0);
  const requestIdRef = useRef<string | null>(null);
  const pendingStopRef = useRef<number | null>(null);
  // The seq of the send whose cancel request is in flight: until it is answered, a stop press or Esc
  // does nothing (no second cancel, no dialog reopened over a stop already confirmed).
  const stopInFlightRef = useRef<number | null>(null);
  // Mirrors isLoading, but is set the moment a send starts (and while a new deck is persisted for it),
  // so a second send in the same tick is refused too: one turn at a time.
  const loadingRef = useRef(false);
  const startingRef = useRef(false);
  const turnRef = useRef<TurnRef | null>(null);
  const finishedSeqRef = useRef(0);  // the send whose rollback outcome was already applied
  const messageIndexRef = useRef(0);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const cancelStreamRef = useRef<(() => void) | null>(null);
  const sendSeqRef = useRef(0);  // #317: the send a turn-end id read belongs to
  const navigate = useNavigate();
  const { sessionId, isSessionPersisted, isInitializing, error: sessionError, setExperimentUrl, setSessionTitle, storedDeckMode, selectedDeckMode, setStoredDeckMode, setSelectedDeckMode } = useSession();
  const { agentConfig, refreshConfig, configOwnerSessionId, isPreSession } = useAgentConfig();
  const { setIsGenerating } = useGeneration();
  const imageOptions = useImageGenerationOptions();
  // Synchronously clear messages when sessionId changes (avoids old-message flash on session switch).
  // React discards the intermediate render and immediately re-renders with empty messages,
  // so the user never sees old messages from the previous session.
  const [clearedForSessionId, setClearedForSessionId] = useState<string | null>(sessionId);
  if (clearedForSessionId !== sessionId) {
    setClearedForSessionId(sessionId);
    setMessages([]);
    setMyPermission(null);
    setIsClearChatDialogOpen(false);
    setIsClearing(false);
    setPendingDeleteId(null);
    setIsDeletingMessage(false);
    // A stop's or failure's notice belongs to the deck it happened on.
    setNotice(null);
    setStopDialogOpen(false);
  }

  // Show session error
  useEffect(() => {
    if (sessionError) {
      setError(sessionError);
    }
  }, [sessionError]);

  // Cancel in-flight polling/stream when session changes so parent doesn't need to remount us
  useEffect(() => {
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
      if (cancelStreamRef.current) {
        cancelStreamRef.current();
        cancelStreamRef.current = null;
      }
      setIsGenerating(false);
      loadingRef.current = false;
      setIsLoading(false);
      setLoadingMessage('');
    };
  }, [sessionId, setIsGenerating]);

  // Fetch the persisted message history for the current session into the chat.
  const loadSessionMessages = async (id: string, isStale: () => boolean = () => false) => {
    try {
      const session = await api.getSession(id);
      if (isStale()) return;
      setMyPermission(session.my_permission ?? null);
      if (session.messages && session.messages.length > 0) {
        // Convert database messages to UI Message format
        setMessages(session.messages.map(toUiMessage));
      } else {
        setMessages([]);
      }
    } catch (err: any) {
      // Session might not exist yet (new session with local UUID), which is fine
      // 404 is expected for new sessions that haven't sent their first message
      if (err?.status !== 404) {
        console.warn('Could not load session messages:', err);
      }
      if (isStale()) return;
      setMyPermission(null);
      setMessages([]);
    }
  };
  const currentSessionIdRef = useRef(sessionId);
  currentSessionIdRef.current = sessionId;

  // Load messages when session changes (for restored sessions)
  // Messages are already cleared synchronously in the render body above.
  useEffect(() => {
    if (!sessionId) return;
    loadSessionMessages(sessionId, () => currentSessionIdRef.current !== sessionId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  // A deck built in this panel starts on a browser-local id: its first load 404s and leaves the
  // permission null. ensureGraphCapableRoot then persists the SAME id, so sessionId never changes and
  // nothing reloads the permission. Re-read just the permission when the session becomes persisted
  // (not the transcript: the panel already shows the live turn). Only for the SAME id: a switch to a
  // saved deck (a page load, opening one from history) flips the flag too, but with a new id, and the
  // session-change load above already reads that session's permission.
  const persistedRef = useRef({ sessionId, isSessionPersisted });
  useEffect(() => {
    const prev = persistedRef.current;
    persistedRef.current = { sessionId, isSessionPersisted };
    const becamePersisted = prev.sessionId === sessionId && !prev.isSessionPersisted && isSessionPersisted;
    if (!becamePersisted || !sessionId) return;
    const target = sessionId;
    api.getSession(target)
      .then(s => { if (currentSessionIdRef.current === target) setMyPermission(s.my_permission ?? null); })
      .catch(() => { /* keep null: the button stays hidden, and the backend still gates */ });
  }, [isSessionPersisted, sessionId]);

  // Tour: a demo stage wrote new messages server-side for this same session, so sessionId does not
  // change and the effect above does not re-run. Reload explicitly when the event targets us.
  useEffect(() => {
    const handler = (e: Event) => {
      const sid = (e as CustomEvent<{ sessionId?: string }>).detail?.sessionId;
      if (sid && sid === sessionId) loadSessionMessages(sid, () => currentSessionIdRef.current !== sid);
    };
    window.addEventListener('tour:refresh-session', handler);
    return () => window.removeEventListener('tour:refresh-session', handler);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  const setLoading = (value: boolean) => {
    loadingRef.current = value;
    setIsLoading(value);
  };

  const stopLoadingMessages = () => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
    setLoadingMessage('');
  };

  // #317: a message sent here has no id until the panel matches it to its stored row, and only a
  // message with an id offers delete. Read the stored conversation and add ids; never replace.
  const refreshMessageIds = (target: string | null, seq: number) => {
    if (!target) return;
    Promise.resolve()
      .then(() => conversationApi.listMessages(target, MESSAGE_ID_READ_LIMIT))
      .then(result => {
        // Dropped after a session switch, and after a newer send: that send's message (often the
        // same text) would otherwise take this turn's row, and a delete would remove the wrong
        // turn. The next turn's read pairs whatever is not ambiguous.
        if (sendSeqRef.current !== seq || currentSessionIdRef.current !== target) return;
        if (!Array.isArray(result?.messages)) return;
        setMessages(prev => withPersistedUserIds(prev, result.messages));
      })
      .catch(() => { /* the ids arrive with the next load; the delete action waits for them */ });
  };

  // #314: after an errored turn, refetch the deck and hand it to `onDeckRefetched`. Called from BOTH
  // failure paths: an SSE `error` event, and the transport's onError callback (polling, the production
  // transport, never emits an `error` event: a failed job calls onError). The target is computed inside
  // the promise chain, so a throw there is swallowed by the catch like a failed request. Dropped after a
  // newer send and after a session switch, as refreshMessageIds does (the guard compares the session the
  // turn was sent to). A failed or empty refetch changes nothing.
  const refetchDeckAfterError = (sentTo: string | null, seq: number) => {
    if (!onDeckRefetched) return;
    Promise.resolve()
      .then(() => {
        const target = api.getCurrentSessionId() ?? sentTo;
        return target ? api.getSlides(target) : null;
      })
      .then(result => {
        if (!result?.slide_deck) return;
        if (sendSeqRef.current !== seq || currentSessionIdRef.current !== sentTo) return;
        onDeckRefetched(result.slide_deck);
      })
      .catch(() => { /* the viewer keeps what it has; the next turn's refetch corrects it */ });
  };

  // After a failed send the optimistic mode lock may be wrong (the server may have rejected the
  // mode with a 409, or never locked). Re-read the session and take its mode as the truth. Guarded
  // like refetchDeckAfterError, but with no onDeckRefetched early return. If the re-read fails,
  // nothing changes: the optimistic lock stays and the turn's error is already showing.
  const reconcileDeckModeAfterError = (sentTo: string | null, seq: number) => {
    Promise.resolve()
      .then(() => (sentTo ? api.getSession(sentTo) : null))
      .then(session => {
        if (!session) return;
        if (sendSeqRef.current !== seq || currentSessionIdRef.current !== sentTo) return;
        setStoredDeckMode(session.deck_mode ?? null);
      })
      .catch(() => { /* keep the optimistic lock */ });
  };

  // The turn is over without a result (a stop, or a failure): end polling and clear every running state.
  const endTurnLocally = () => {
    if (cancelStreamRef.current) {
      cancelStreamRef.current();
      cancelStreamRef.current = null;
    }
    stopLoadingMessages();
    setLoading(false);
    setIsGenerating(false);
    setIsQueued(false);
    setTurnProgress(null);
    setStopDialogOpen(false);
    requestIdRef.current = null;
    pendingStopRef.current = null;
  };

  // After a rollback the server's conversation and deck are the truth. Both refreshes are dropped after a
  // newer send and after a session switch, as refreshMessageIds is.
  const refreshAfterRollback = (sentTo: string | null, seq: number) => {
    if (sentTo) {
      Promise.resolve()
        .then(() => conversationApi.listMessages(sentTo))
        .then(result => {
          if (sendSeqRef.current !== seq || currentSessionIdRef.current !== sentTo) return;
          if (!Array.isArray(result?.messages)) return;
          setMessages(result.messages.map(toUiMessage));
        })
        .catch(() => { /* the chat keeps what it shows; the next load corrects it */ });
    }
    reconcileDeckModeAfterError(sentTo, seq);
    Promise.resolve()
      .then(() => (sentTo ? api.getSlides(sentTo) : null))
      .then(result => {
        if (!result) return;
        if (sendSeqRef.current !== seq || currentSessionIdRef.current !== sentTo) return;
        onDeckRestored?.(result.slide_deck ?? null);
      })
      .catch(() => { /* the viewer keeps what it has */ });
  };

  // The server rolled the turn back (a stop, or a failed turn): "Nothing was changed." The message is
  // gone from the server, so a message typed in the box comes back there. A send from elsewhere (a
  // finding's Apply, Optimize layout, an image card) has no draft: the box is left as it is.
  const finishAfterRollback = (kind: 'cancelled' | 'failed', turn: TurnRef, reason?: string) => {
    if (finishedSeqRef.current === turn.seq) return;
    finishedSeqRef.current = turn.seq;
    endTurnLocally();
    setError(null);
    if (turn.fromInput) setRestoreDraftKey(key => key + 1);
    refreshAfterRollback(turn.sentTo, turn.seq);
    setNotice(
      kind === 'cancelled'
        ? { text: CANCELLED_NOTICE }
        : { text: FAILED_NOTICE, detail: failureDetail(reason) },
    );
  };

  // The restore after a failed generation did not finish: the server says to try again shortly. Same
  // refresh as a rollback, with the message as an error and no notice.
  const finishRestorePending = (message: string | null | undefined, turn: TurnRef) => {
    if (finishedSeqRef.current === turn.seq) return;
    finishedSeqRef.current = turn.seq;
    endTurnLocally();
    if (turn.fromInput) setRestoreDraftKey(key => key + 1);
    refreshAfterRollback(turn.sentTo, turn.seq);
    setError(message || RESTORE_PENDING_NOTICE);
  };

  // Send the stop for a running turn and apply whatever the server answers. Only one at a time per send.
  const sendStop = async (requestId: string, turn: TurnRef) => {
    stopInFlightRef.current = turn.seq;
    try {
      await sendStopOnce(requestId, turn);
    } finally {
      if (stopInFlightRef.current === turn.seq) stopInFlightRef.current = null;
    }
  };

  const sendStopOnce = async (requestId: string, turn: TurnRef) => {
    const current = () => sendSeqRef.current === turn.seq && currentSessionIdRef.current === turn.sentTo;
    let outcome;
    try {
      outcome = await api.cancelChat(requestId);
    } catch {
      // Unknown whether the stop landed: ask the request once.
      let polled;
      try {
        polled = await api.pollChat(requestId);
      } catch {
        if (current()) setError(STOP_FAILED_ERROR);
        return;
      }
      if (!current()) return;
      if (polled.status === 'running' || polled.status === 'pending') {
        setError(STOP_FAILED_ERROR);
      } else if (polled.rollback === 'restore_failed') {
        finishRestorePending(polled.error, turn);
      } else if (polled.rollback === 'rolled_back' && polled.status === 'cancelled') {
        finishAfterRollback('cancelled', turn);
      }
      // Any other end (completed, failed with no rollback): the turn's own polling delivers it.
      return;
    }
    if (!current()) return;
    switch (outcome.outcome) {
      case 'cancelled':
        finishAfterRollback('cancelled', turn);
        break;
      case 'already_finished':
        // Whatever `status` says (it can still read "running"), polling delivers the result.
        setStopDialogOpen(false);
        break;
      case 'refused_foreign_change':
        setStopDialogOpen(false);
        setNotice({ text: REFUSED_STOP_NOTICE });
        break;
      default:
        setStopDialogOpen(false);
        setError(STOP_FAILED_ERROR);
    }
  };

  // The stop itself (after any confirmation). Before `request_accepted` there is no request id: queue
  // the stop for this send. Never a local cancel here: it would suppress `request_accepted`.
  const performStop = () => {
    const turn = turnRef.current;
    setStopDialogOpen(false);
    if (!turn) return;
    const requestId = requestIdRef.current;
    if (!requestId) {
      pendingStopRef.current = turn.seq;
      return;
    }
    void sendStop(requestId, turn);
  };

  const handleStopRequest = () => {
    // A stop already sent (or queued for the request id) for this send: nothing more to do.
    const seq = turnRef.current?.seq;
    if (seq != null && (stopInFlightRef.current === seq || pendingStopRef.current === seq)) return;
    if (stopNeedsConfirmation(turnProgress)) {
      setStopDialogOpen(true);
    } else {
      performStop();
    }
  };

  // Every send: the chat box (ChatInput), the imperative handle (a finding's Apply/Discuss, Optimize
  // layout, the slide image dialog) and an image card's Use / Regenerate.
  const handleSendMessage = async (
    content: string,
    { slideContext: explicitSlideContext, imageIds, fromInput }: SendOptions,
  ) => {
    const trimmedContent = content.trim();
    if (!trimmedContent) {
      return;
    }
    // A clear is running: the conversation is about to be emptied, so a send now would be lost.
    if (isClearing) {
      return;
    }
    if (isDeletingMessage) {
      return;
    }
    // One turn at a time: a second send would take over the running turn's stop state and leave that
    // turn unstoppable (its controls are disabled meanwhile; this is the backstop).
    if (loadingRef.current || startingRef.current) {
      return;
    }

    // Agent turns carry the slide on stage. Snapshot (copy) it now, before the first await, so paging
    // or mutation while the root is persisted cannot retarget the send. Legacy turns send none.
    const staged = (storedDeckMode ?? selectedDeckMode) === 'agent' ? getStageSlide?.() : undefined;
    const stageSlide: StageSlideContext | undefined = staged ? { ...staged } : undefined;

    // A browser-local root must be made graph-capable before a graph turn.
    // Failed persistence deliberately sends no chat request.
    if (!isSessionPersisted) {
      startingRef.current = true;
      let persisted = false;
      try {
        persisted = await ensureGraphCapableRoot();
      } finally {
        startingRef.current = false;
      }
      if (!persisted) return;
    }
    const sentTo = sessionId;

    // The stored mode wins on a locked deck; otherwise lock optimistically with the selection.
    // Set only now: a send that never goes out must not lock the deck.
    const deckMode = storedDeckMode ?? selectedDeckMode;
    if (storedDeckMode === null) {
      setStoredDeckMode(deckMode);
    }

    setLoading(true);
    setTurnProgress(null);
    setIsQueued(false);
    setNotice(null);
    setStopDialogOpen(false);
    requestIdRef.current = null;
    pendingStopRef.current = null;
    setIsGenerating(true);
    onGenerationStart?.();
    setError(null);
    setLastReplacement(null);

    // Add user message immediately
    setMessages(prev => [
      ...prev,
      {
        role: 'user',
        content: trimmedContent,
        timestamp: new Date().toISOString(),
      },
    ]);
    const seq = ++sendSeqRef.current;
    const turn: TurnRef = { sentTo, seq, fromInput };
    turnRef.current = turn;

    messageIndexRef.current = 0;
    setLoadingMessage(getRotatingLoadingMessage(0));
    intervalRef.current = setInterval(() => {
      messageIndexRef.current += 1;
      setLoadingMessage(getRotatingLoadingMessage(messageIndexRef.current));
    }, 3000);

    // Use explicit slide context if provided, otherwise none.
    // Selection context was retired when checkbox selection was removed (workstream 4).
    const slideContext = explicitSlideContext;

    // Handle streaming events
    const handleStreamEvent = (event: StreamEvent) => {
      switch (event.type) {
        case 'assistant':
          if (event.content) {
            setMessages(prev => [
              ...prev,
              {
                role: 'assistant',
                content: event.content!,
                timestamp: new Date().toISOString(),
                details: readMessageDetails(event.metadata?.details),
                agent: event.agent,
                sign_in_url: readSignInUrl(event.metadata?.sign_in_url),
                generated_images: toGeneratedImages(event.metadata?.generated_images),
              },
            ]);
          }
          break;

        case 'tool_call':
          if (event.tool_name) {
            setMessages(prev => [
              ...prev,
              {
                role: 'assistant',
                content: `Using tool: ${event.tool_name}`,
                timestamp: new Date().toISOString(),
                tool_call: {
                  name: event.tool_name!,
                  arguments: event.tool_input || {},
                },
              },
            ]);
            // Update loading message to show tool being used
            setLoadingMessage(
              event.tool_name === 'image_generation'
                ? imageGenerationLabel(event.tool_input)
                : toolCallLabel(event.tool_name, event.tool_input),
            );
          }
          break;

        case 'tool_result':
          if (event.tool_output) {
            setMessages(prev => [
              ...prev,
              {
                role: 'tool',
                content: event.tool_output!,
                timestamp: new Date().toISOString(),
                tool_call_id: event.tool_name,
              },
            ]);
          }
          break;

        case 'request_accepted':
          if (sendSeqRef.current === seq && event.request_id) {
            requestIdRef.current = event.request_id;
            if (pendingStopRef.current === seq) {
              pendingStopRef.current = null;
              void sendStop(event.request_id, turn);
            }
          }
          break;

        case 'cancelled':
          // Stopped from another tab (or by the server): same ending as a stop sent from here.
          if (event.rollback === 'restore_failed') {
            finishRestorePending(RESTORE_PENDING_NOTICE, turn);
          } else {
            finishAfterRollback('cancelled', turn);
          }
          break;

        case 'session_title':
          if (event.session_title) {
            setSessionTitle(event.session_title);
          }
          break;

        case 'session_created':
          // Backend created a session for us — navigate to the new session URL
          if (event.session_id) {
            api.setCurrentSessionId(event.session_id);
            navigate(`/sessions/${event.session_id}/edit`, { replace: true });
          }
          break;

        case 'error':
          setError(event.error || 'An error occurred');
          stopLoadingMessages();
          setLoading(false);
          setIsGenerating(false);
          refreshMessageIds(sentTo, seq);
          // A per-slide notice (metadata.position: one slide became a placeholder) is
          // emitted MID-turn and the turn carries on to `complete`, whose own refetch is
          // the right one. Refetching here could race it with a pre-completion deck.
          if (event.metadata?.position == null) {
            refetchDeckAfterError(sentTo, seq);
            reconcileDeckModeAfterError(sentTo, seq);
          }
          break;

        case 'complete':
          stopLoadingMessages();
          setLoading(false);
          setIsGenerating(false);
          // A stop that failed said the generation is still running; now it has finished.
          setError(prev => (prev === STOP_FAILED_ERROR ? null : prev));

          const nextRawHtml = event.raw_html ?? rawHtml ?? null;

          // Capture experiment URL for Run Details link
          if (event.experiment_url) {
            setExperimentUrl(event.experiment_url);
          }

          if (event.slides && !event.metadata?.clarification_needed) {
            // Fetch slides from API to get content_hash for auto-verification
            // The API returns slides with content_hash computed and verification merged
            // Save point is now created by the backend during chat processing
            // Use getCurrentSessionId() to pick up session_created updates during streaming
            const activeSessionId = api.getCurrentSessionId() ?? sessionId ?? '';
            api.getSlides(activeSessionId).then(result => {
              if (result.slide_deck) {
                onSlidesGenerated(result.slide_deck, nextRawHtml);
              } else {
                onSlidesGenerated(event.slides!, nextRawHtml);
              }
            }).catch(() => {
              onSlidesGenerated(event.slides!, nextRawHtml);
            });
          }

          if (event.replacement_info && slideContext) {
            // Include conflict_note from metadata if present (RC11)
            const replacementWithConflict = {
              ...event.replacement_info,
              conflict_note: event.metadata?.conflict_note,
            };
            setLastReplacement(replacementWithConflict);
          } else if (event.metadata?.sync_error) {
            // RC14: Deck sync error (no replacement_info, but show error feedback)
            setLastReplacement({ sync_error: event.metadata.sync_error });
          }

          // Refresh agent config to pick up updated conversation_ids from
          // Genie tools. DS + template selections are SESSION-SCOPED STICKY:
          // they persist across every prompt/generation in this session until
          // the user changes them (no after-generation reset).
          refreshConfig();
          refreshMessageIds(sentTo, seq);
          break;

        // #319 — the graph's stage summary.  Never a chat message: it only feeds
        // the placeholder.  Older, repeated and malformed snapshots are ignored,
        // so the label never steps backwards.
        case 'turn_progress': {
          const incoming = parseTurnProgress(event.turn_progress);
          if (incoming) setTurnProgress(prev => newerTurnProgress(prev, incoming));
          break;
        }

        // The turn is waiting for a free job runner, or no longer is.  Like
        // turn_progress, it only feeds the placeholder.
        case 'queued':
          setIsQueued(event.queued === true);
          break;

        // E0: ws4d D3 — one committed slide released by the graph's reorder buffer,
        // delivered before `complete`.  Forwards position + content to AppLayout so
        // the viewer can render slides as they land in ascending order.
        case 'slide_ready':
          if (event.position != null && event.html != null) {
            onSlideReady?.(event.position, event.html, event.scripts ?? '');
          }
          break;
      }
    };

    // A chat request may only carry config that was LOADED-FOR or
    // EXPLICITLY-SET-IN the session it targets (ownership) — otherwise the
    // backend sync would overwrite this session's persisted config with
    // another surface's leftovers (the switch-race data loss). While a
    // session's config load is still pending, the request omits agent_config
    // entirely and the backend keeps the session's own persisted config.
    // Pre-session sends always carry it: that config seeds the new session.
    const configIsForThisSession =
      isPreSession || (configOwnerSessionId != null && configOwnerSessionId === sessionId);

    // Start streaming (automatically uses SSE or polling based on environment)
    cancelStreamRef.current = api.sendChatMessage(
      sessionId ?? '',
      trimmedContent,
      slideContext,
      handleStreamEvent,
      (err) => {
        console.error('Chat error:', err);
        requestIdRef.current = null;
        pendingStopRef.current = null;
        setStopDialogOpen(false);
        const rollback = err instanceof ChatTurnError ? err.rollback : null;
        if (rollback === 'rolled_back') {
          finishAfterRollback('failed', turn, err.message);
          return;
        }
        if (rollback === 'restore_failed') {
          finishRestorePending(err.message, turn);
          return;
        }
        setError(rollback === 'kept_foreign_change' ? FAILED_KEPT_NOTICE : err.message || 'Failed to send message');
        stopLoadingMessages();
        setLoading(false);
        setIsGenerating(false);
        refreshMessageIds(sentTo, seq);
        refetchDeckAfterError(sentTo, seq);
        reconcileDeckModeAfterError(sentTo, seq);
      },
      imageIds,
      configIsForThisSession ? agentConfig : undefined,
      deckMode,
      deckMode === 'agent' ? stageSlide : undefined,
    );
  };

  // Clear chat: for editors, on a persisted session, with or without a Spec.
  const showClearChat = isSessionPersisted && canEditConversation(myPermission);
  const clearChatDisabled =
    isLoading || isClearing || isDeletingMessage || disabled || !!previewMessages || messages.length === 0;

  // Delete a message (#317): shown to editors on a persisted session, never in a save-point preview.
  const canDeleteMessages = isSessionPersisted && canEditConversation(myPermission) && !previewMessages;
  const deleteMessageDisabled = isLoading || isClearing || isDeletingMessage || disabled;

  const handleConfirmDeleteMessage = async () => {
    const messageId = pendingDeleteId;
    if (!sessionId || messageId == null || isDeletingMessage) return;
    const target = sessionId;
    setPendingDeleteId(null);
    setIsDeletingMessage(true);
    setError(null);
    try {
      await conversationApi.deleteMessage(target, messageId);
      if (currentSessionIdRef.current !== target) return;  // the user moved on; leave the new session alone
      setMessages(prev => withoutTurn(prev, messageId));
      setLastReplacement(null);
    } catch (err) {
      if (currentSessionIdRef.current !== target) return;
      setError(deleteMessageErrorMessage(err));
    } finally {
      if (currentSessionIdRef.current === target) setIsDeletingMessage(false);
    }
  };

  const handleConfirmClearChat = async () => {
    if (!sessionId || isClearing) return;
    const target = sessionId;
    setIsClearChatDialogOpen(false);
    setIsClearing(true);
    setError(null);
    try {
      await conversationApi.clearChat(target);
      if (currentSessionIdRef.current !== target) return;  // the user moved on; leave the new session alone
      setMessages([]);
      setLastReplacement(null);
    } catch (err) {
      if (currentSessionIdRef.current !== target) return;
      setError(clearChatErrorMessage(err));
    } finally {
      // Only for the session this clear was for: after a switch the render-phase reset has already
      // cleared the flag, and the new session may be running its own clear.
      if (currentSessionIdRef.current === target) setIsClearing(false);
    }
  };

  const chatInputDisabled =
    isLoading || isInitializing || !sessionId || disabled || isClearing || isDeletingMessage;
  const effectiveDeckMode = storedDeckMode ?? selectedDeckMode;
  // A stop needs the request id the polling transport reports, and an Agent deck's server-side rollback.
  const stoppable = effectiveDeckMode !== 'legacy' && isPollingMode();
  const canStop = stoppable && isLoading && !previewMessages;
  useEscapeToStop(canStop, handleStopRequest);

  // The dialog follows the turn: it closes itself when the turn completes, errors or is cancelled.
  useEffect(() => {
    if (!isLoading) setStopDialogOpen(false);
  }, [isLoading]);

  const imageRequestAvailable = imageOptions?.available === true && effectiveDeckMode !== 'legacy';

  // Expose sendMessage method to parent components via ref
  useImperativeHandle(ref, () => ({
    sendMessage: (content: string, slideContext?: SlideContext) => {
      void handleSendMessage(content, { slideContext, fromInput: false });
    },
  }), [handleSendMessage]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
      // Cancel any in-flight stream
      if (cancelStreamRef.current) {
        cancelStreamRef.current();
      }
      // Reset generation state on unmount
      setIsGenerating(false);
    };
  }, [setIsGenerating]);

  return (
    <div className="flex flex-col flex-1 min-h-0 bg-background" data-testid="chat-panel">
      <div className="flex items-center gap-3 border-b border-border bg-card px-4 py-3">
        <div className="flex size-8 items-center justify-center rounded-lg bg-primary/10">
          <Bot className="size-4 text-primary" />
        </div>
        <div className="flex-1">
          <h2 className="text-sm font-medium text-foreground">AI Assistant</h2>
          <p className="text-xs text-muted-foreground">Ask me to create or edit slides</p>
        </div>
        {showClearChat && (
          <Button
            data-testid="clear-chat-button"
            size="sm"
            variant="ghost"
            disabled={clearChatDisabled}
            title={hasDeckSpec ? CLEAR_CHAT_TOOLTIP : CLEAR_CHAT_TOOLTIP_NO_SPEC}
            onClick={() => setIsClearChatDialogOpen(true)}
          >
            <Eraser />
            {CLEAR_CHAT_LABEL}
          </Button>
        )}
      </div>
      <ConfirmDialog
        open={isClearChatDialogOpen}
        title={CLEAR_CHAT_DIALOG_TITLE}
        message={hasDeckSpec ? CLEAR_CHAT_DIALOG_MESSAGE : CLEAR_CHAT_DIALOG_MESSAGE_NO_SPEC}
        confirmLabel={CLEAR_CHAT_LABEL}
        cancelLabel="Cancel"
        variant="danger"
        onConfirm={handleConfirmClearChat}
        onCancel={() => setIsClearChatDialogOpen(false)}
      />
      <ConfirmDialog
        open={pendingDeleteId !== null}
        title={DELETE_MESSAGE_DIALOG_TITLE}
        message={DELETE_MESSAGE_DIALOG_MESSAGE}
        confirmLabel={DELETE_MESSAGE_CONFIRM_LABEL}
        cancelLabel="Cancel"
        variant="danger"
        onConfirm={handleConfirmDeleteMessage}
        onCancel={() => setPendingDeleteId(null)}
      />

      <ConfirmDialog
        open={stopDialogOpen && canStop}
        title={STOP_DIALOG_TITLE}
        message={stopDialogMessage(turnProgress?.slides.done.length ?? 0, turnProgress?.slides.total ?? 0)}
        confirmLabel={STOP_CONFIRM_LABEL}
        cancelLabel={STOP_KEEP_LABEL}
        variant="danger"
        initialFocus="cancel"
        onConfirm={performStop}
        onCancel={() => setStopDialogOpen(false)}
      />

      <div className="flex-1 overflow-y-auto">
        <MessageList
          messages={previewMessages ?? messages}
          isLoading={isLoading && !previewMessages}
          progressLabel={isQueued && !turnProgress ? QUEUED_TURN_LABEL : describeTurnProgress(turnProgress)}
          deleteAction={canDeleteMessages ? { disabled: deleteMessageDisabled, onDelete: setPendingDeleteId } : undefined}
          imageActions={{
            onUse: (img) => {
              void handleSendMessage(pickImageMessage(img), { imageIds: [img.token], fromInput: false });
            },
            onRegenerate: (images) => { void handleSendMessage(regenerateMessage(images), { fromInput: false }); },
            disabled: chatInputDisabled,
            hidden: previewMessages != null,
          }}
        />
      </div>

      {error && (
        <ErrorDisplay error={error} onDismiss={() => setError(null)} />
      )}

      {notice && (
        <div
          role="status"
          className="px-4 py-3 bg-muted border-t border-border flex items-center justify-between gap-3 text-sm text-muted-foreground"
        >
          <div className="min-w-0">
            <span>{notice.text}</span>
            {notice.detail && (
              <p className="mt-0.5 break-words text-xs text-muted-foreground/80">{notice.detail}</p>
            )}
          </div>
          <button
            type="button"
            onClick={() => setNotice(null)}
            className="font-semibold hover:underline"
            aria-label="Dismiss notice"
          >
            Dismiss
          </button>
        </div>
      )}

      {loadingMessage && <LoadingIndicator message={loadingMessage} />}

      <ChatInput
        onSend={(message, imageIds) => { void handleSendMessage(message, { imageIds, fromInput: true }); }}
        disabled={chatInputDisabled}
        generating={isLoading}
        onStop={canStop ? handleStopRequest : undefined}
        restoreDraftKey={restoreDraftKey}
        imageRequest={imageRequestAvailable ? { slideCount } : undefined}
        placeholder={
          viewOnlyReason
            ? viewOnlyReason
            : disabled
            ? 'Exit preview mode to send messages...'
            : isInitializing
            ? 'Initializing session...'
            : 'Ask to generate or modify slides...'
        }
        modeControl={
          <DeckModeSelect
            value={storedDeckMode ?? selectedDeckMode}
            locked={storedDeckMode !== null || disabled || !!viewOnlyReason || previewMessages != null}
            onChange={setSelectedDeckMode}
          />
        }
      />

      {lastReplacement && (
        <div className="px-4 pb-4">
          <ReplacementFeedback replacementInfo={lastReplacement} />
        </div>
      )}
    </div>
  );
});

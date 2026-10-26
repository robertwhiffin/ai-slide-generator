import { useEffect, useRef, useState, forwardRef, useImperativeHandle } from 'react';
import { useNavigate } from 'react-router-dom';
import { Bot, Eraser } from 'lucide-react';
import type { Message } from '../../types/message';
import type { ReplacementInfo, SlideDeck } from '../../types/slide';
import { MessageList } from './MessageList';
import { ChatInput } from './ChatInput';
import { DeckModeSelect } from './DeckModeSelect';
import { api, type StreamEvent } from '../../services/api';
import { conversationApi } from '../../api/conversation';
import { canEditConversation } from '../../utils/conversationPermissions';
import { Button } from '@/ui/button';
import { ConfirmDialog } from '../ConfirmDialog';
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
import { describeTurnProgress, newerTurnProgress, parseTurnProgress } from '../../utils/turnProgress';
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
  ensureGraphCapableRoot: () => Promise<boolean>;
  disabled?: boolean;
  previewMessages?: Message[] | null;  // When provided, show these instead of live messages
  viewOnlyReason?: string;  // When provided, show why the user cannot edit
  /** Whether the live deck has a Spec. Chooses Clear chat's wording: with a Spec the assistant carries on from it; without one the wording promises nothing about a Spec (#317 lifted #323's Spec gate). */
  hasDeckSpec?: boolean;
}

// #317: the turn-end id read asks for the newest rows only (GET …/messages keeps messages[-limit:]).
const MESSAGE_ID_READ_LIMIT = 200;

export const ChatPanel = forwardRef<ChatPanelHandle, ChatPanelProps>(({
  rawHtml,
  onSlidesGenerated,
  onGenerationStart,
  onSlideReady,
  onDeckRefetched,
  ensureGraphCapableRoot,
  disabled = false,
  previewMessages = null,
  viewOnlyReason,
  hasDeckSpec = false,
}, ref) => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [loadingMessage, setLoadingMessage] = useState<string>('');
  const [turnProgress, setTurnProgress] = useState<TurnProgress | null>(null);
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
  const messageIndexRef = useRef(0);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const cancelStreamRef = useRef<(() => void) | null>(null);
  const sendSeqRef = useRef(0);  // #317: the send a turn-end id read belongs to
  const navigate = useNavigate();
  const { sessionId, isSessionPersisted, isInitializing, error: sessionError, setExperimentUrl, setSessionTitle, storedDeckMode, selectedDeckMode, setStoredDeckMode, setSelectedDeckMode } = useSession();
  const { agentConfig, refreshConfig, configOwnerSessionId, isPreSession } = useAgentConfig();
  const { setIsGenerating } = useGeneration();
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
        const uiMessages: Message[] = session.messages.map(msg => ({
          id: msg.id,
          role: msg.role as 'user' | 'assistant' | 'tool',
          content: msg.content,
          timestamp: msg.created_at,
          tool_call: msg.metadata?.tool_name ? {
            name: msg.metadata.tool_name,
            arguments: msg.metadata.tool_input || {},
          } : undefined,
          details: readMessageDetails(msg.metadata?.details),
        }));
        setMessages(uiMessages);
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

  const handleSendMessage = async (content: string, explicitSlideContextOrImageIds?: SlideContext | string[], maybeImageIds?: string[]) => {
    // Support two calling conventions:
    // 1. From ChatInput: (content, imageIds)
    // 2. From imperative ref: (content, slideContext)
    let explicitSlideContext: SlideContext | undefined;
    let imageIds: string[] | undefined;

    if (Array.isArray(explicitSlideContextOrImageIds)) {
      imageIds = explicitSlideContextOrImageIds;
    } else {
      explicitSlideContext = explicitSlideContextOrImageIds;
      imageIds = maybeImageIds;
    }
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

    // A browser-local root must be made graph-capable before a graph turn.
    // Failed persistence deliberately sends no chat request.
    if (!isSessionPersisted && !await ensureGraphCapableRoot()) {
      return;
    }
    const sentTo = sessionId;

    // The stored mode wins on a locked deck; otherwise lock optimistically with the selection.
    // Set only now: a send that never goes out must not lock the deck.
    const deckMode = storedDeckMode ?? selectedDeckMode;
    if (storedDeckMode === null) {
      setStoredDeckMode(deckMode);
    }

    setIsLoading(true);
    setTurnProgress(null);
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
            setLoadingMessage(`Querying ${event.tool_name}...`);
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
          setIsLoading(false);
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
          setIsLoading(false);
          setIsGenerating(false);

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
        setError(err.message || 'Failed to send message');
        stopLoadingMessages();
        setIsLoading(false);
        setIsGenerating(false);
        refreshMessageIds(sentTo, seq);
        refetchDeckAfterError(sentTo, seq);
        reconcileDeckModeAfterError(sentTo, seq);
      },
      imageIds,
      configIsForThisSession ? agentConfig : undefined,
      deckMode,
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

  // Expose sendMessage method to parent components via ref
  useImperativeHandle(ref, () => ({
    sendMessage: (content: string, slideContext?: SlideContext) => {
      handleSendMessage(content, slideContext);
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

      <div className="flex-1 overflow-y-auto">
        <MessageList
          messages={previewMessages ?? messages}
          isLoading={isLoading && !previewMessages}
          progressLabel={describeTurnProgress(turnProgress)}
          deleteAction={canDeleteMessages ? { disabled: deleteMessageDisabled, onDelete: setPendingDeleteId } : undefined}
        />
      </div>

      {error && (
        <ErrorDisplay error={error} onDismiss={() => setError(null)} />
      )}

      {loadingMessage && <LoadingIndicator message={loadingMessage} />}

      <ChatInput
        onSend={handleSendMessage}
        disabled={
          isLoading || isInitializing || !sessionId || disabled
          || isClearing
          || isDeletingMessage
        }
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

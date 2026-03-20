import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  FiSend,
  FiEdit2,
  FiTrash2,
  FiCheck,
  FiRotateCcw,
  FiCornerDownRight,
  FiX,
  FiEye,
  FiEyeOff,
  FiAtSign,
} from 'react-icons/fi';
import type { SlideComment } from '../../types/comment';
import { api } from '../../services/api';

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

export interface MentionableUser {
  username: string;
  display_name: string;
}

function renderContentWithMentions(content: string, users: MentionableUser[] = []): React.ReactNode {
  const emailToName = new Map(users.map(u => [u.username.toLowerCase(), u.display_name]));
  const parts = content.split(/(@[\w.+\-]+@[\w.\-]+)/g);
  return parts.map((part, i) => {
    if (part.startsWith('@')) {
      const email = part.slice(1).toLowerCase();
      const display = emailToName.get(email);
      return <span key={i} className="text-blue-600 font-medium">@{display || part.slice(1)}</span>;
    }
    return <span key={i}>{part}</span>;
  });
}


// ---------------------------------------------------------------------------
// Mention-aware text input
// ---------------------------------------------------------------------------

interface MentionInputProps {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  placeholder?: string;
  users: MentionableUser[];
  onSearch?: (query: string) => void;
  searching?: boolean;
  autoFocus?: boolean;
  className?: string;
}

const MentionInput: React.FC<MentionInputProps> = ({
  value, onChange, onSubmit, placeholder, users, onSearch, searching = false, autoFocus, className,
}) => {
  const inputRef = useRef<HTMLInputElement>(null);
  const [showDropdown, setShowDropdown] = useState(false);
  const [mentionQuery, setMentionQuery] = useState('');
  const [mentionStart, setMentionStart] = useState(-1);
  const [selectedIdx, setSelectedIdx] = useState(0);
  const searchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const filtered = mentionQuery
    ? users.filter(u =>
        u.display_name.toLowerCase().includes(mentionQuery.toLowerCase()) ||
        u.username.toLowerCase().includes(mentionQuery.toLowerCase())
      ).slice(0, 8)
    : users.slice(0, 8);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const v = e.target.value;
    onChange(v);
    const pos = e.target.selectionStart ?? v.length;
    const before = v.slice(0, pos);
    const atMatch = before.match(/@([\w.+\-]*(?:@[\w.\-]*)?)$/);
    if (atMatch) {
      setShowDropdown(true);
      setMentionQuery(atMatch[1]);
      setMentionStart(atMatch.index!);
      setSelectedIdx(0);
      if (onSearch && atMatch[1].length >= 2) {
        if (searchTimerRef.current) clearTimeout(searchTimerRef.current);
        searchTimerRef.current = setTimeout(() => onSearch(atMatch[1]), 150);
      }
    } else {
      setShowDropdown(false);
    }
  };

  const insertMention = (user: MentionableUser) => {
    const before = value.slice(0, mentionStart);
    const afterCursor = value.slice(mentionStart + 1 + mentionQuery.length);
    onChange(`${before}@${user.username} ${afterCursor}`);
    setShowDropdown(false);
    inputRef.current?.focus();
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (showDropdown && filtered.length > 0) {
      if (e.key === 'ArrowDown') { e.preventDefault(); setSelectedIdx(i => Math.min(i + 1, filtered.length - 1)); return; }
      if (e.key === 'ArrowUp') { e.preventDefault(); setSelectedIdx(i => Math.max(i - 1, 0)); return; }
      if (e.key === 'Tab' || e.key === 'Enter') { e.preventDefault(); insertMention(filtered[selectedIdx]); return; }
      if (e.key === 'Escape') { setShowDropdown(false); return; }
    }
    if (e.key === 'Enter' && !showDropdown) onSubmit();
  };

  const showPanel = showDropdown && (filtered.length > 0 || (searching && mentionQuery.length >= 2));

  return (
    <div className="relative flex-1">
      <input
        ref={inputRef}
        className={className}
        placeholder={placeholder}
        value={value}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        autoFocus={autoFocus}
      />
      {showPanel && (
        <div className="absolute bottom-full left-0 mb-1 w-full bg-white border border-gray-200 rounded-lg shadow-lg z-50 max-h-40 overflow-y-auto">
          {filtered.map((user, idx) => (
            <button
              key={user.username}
              onMouseDown={(e) => { e.preventDefault(); insertMention(user); }}
              className={`w-full text-left px-3 py-1.5 text-sm flex items-center gap-2 ${
                idx === selectedIdx ? 'bg-blue-50 text-blue-700' : 'text-gray-700 hover:bg-gray-50'
              }`}
            >
              <FiAtSign size={12} className="text-gray-400" />
              <span>{user.display_name}</span>
              {user.display_name !== user.username && (
                <span className="text-gray-400 text-xs ml-auto truncate">{user.username}</span>
              )}
            </button>
          ))}
          {searching && (
            <div className="px-3 py-1.5 text-xs text-gray-400 flex items-center gap-2">
              <svg className="animate-spin h-3 w-3" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              Searching workspace users…
            </div>
          )}
        </div>
      )}
    </div>
  );
};

// ---------------------------------------------------------------------------
// Single comment bubble
// ---------------------------------------------------------------------------

interface CommentBubbleProps {
  comment: SlideComment;
  sessionId: string;
  slideId: string;
  onRefresh: () => void;
  mentionableUsers: MentionableUser[];
  onMentionSearch?: (query: string) => void;
  mentionSearching?: boolean;
  depth?: number;
  currentUser?: string;
  canManage?: boolean;
}

const CommentBubble: React.FC<CommentBubbleProps> = ({
  comment,
  sessionId,
  slideId,
  onRefresh,
  mentionableUsers,
  onMentionSearch,
  mentionSearching = false,
  depth = 0,
  currentUser = '',
  canManage = false,
}) => {
  const [isEditing, setIsEditing] = useState(false);
  const [editContent, setEditContent] = useState(comment.content);
  const [isReplying, setIsReplying] = useState(false);
  const [replyContent, setReplyContent] = useState('');
  const [busy, setBusy] = useState(false);
  const isAuthor = currentUser !== '' && comment.user_email?.toLowerCase() === currentUser.toLowerCase();

  const handleEdit = async () => {
    if (!editContent.trim() || busy) return;
    setBusy(true);
    try {
      await api.updateComment(comment.id, editContent.trim());
      setIsEditing(false);
      onRefresh();
    } catch (err) {
      console.error('Failed to edit comment:', err);
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = async () => {
    if (!confirm('Delete this comment?') || busy) return;
    setBusy(true);
    try {
      await api.deleteComment(comment.id);
      onRefresh();
    } catch (err) {
      console.error('Failed to delete comment:', err);
    } finally {
      setBusy(false);
    }
  };

  const handleReply = async () => {
    if (!replyContent.trim() || busy) return;
    setBusy(true);
    try {
      await api.addComment(sessionId, slideId, replyContent.trim(), comment.id);
      setReplyContent('');
      setIsReplying(false);
      onRefresh();
    } catch (err) {
      console.error('Failed to reply:', err);
    } finally {
      setBusy(false);
    }
  };

  const handleResolve = async () => {
    setBusy(true);
    try {
      if (comment.resolved) {
        await api.unresolveComment(comment.id);
      } else {
        await api.resolveComment(comment.id);
      }
      onRefresh();
    } catch (err) {
      console.error('Failed to toggle resolve:', err);
    } finally {
      setBusy(false);
    }
  };

  const isTopLevel = depth === 0;
  const maxDepth = 2;

  return (
    <div id={`comment-${comment.id}`} className={`${depth > 0 ? 'ml-5 border-l-2 border-gray-200 pl-3' : ''} transition-all duration-300`}>
      <div
        className={`rounded-lg p-2.5 text-sm ${
          comment.resolved ? 'bg-green-50 opacity-70' : 'bg-white border border-gray-200'
        }`}
      >
        {/* Header */}
        <div className="flex items-center justify-between mb-1">
          <div className="flex items-center gap-1.5 text-xs text-gray-500">
            <span className="font-semibold text-gray-700">{comment.user_name}</span>
            <span>&middot;</span>
            <span title={new Date(comment.created_at).toLocaleString()}>
              {timeAgo(comment.created_at)}
            </span>
            {comment.updated_at !== comment.created_at && (
              <span className="italic">(edited)</span>
            )}
            {comment.resolved && (
              <span className="text-green-600 font-medium flex items-center gap-0.5">
                <FiCheck size={12} /> Resolved
              </span>
            )}
          </div>

          {/* Actions */}
          <div className="flex items-center gap-0.5">
            {isTopLevel && (
              <button
                onClick={handleResolve}
                disabled={busy}
                className="p-1 rounded hover:bg-gray-100 text-gray-400 hover:text-gray-600"
                title={comment.resolved ? 'Re-open' : 'Resolve'}
              >
                {comment.resolved ? <FiRotateCcw size={13} /> : <FiCheck size={13} />}
              </button>
            )}
            {isAuthor && (
              <button
                onClick={() => { setIsEditing(true); setEditContent(comment.content); }}
                className="p-1 rounded hover:bg-gray-100 text-gray-400 hover:text-blue-600"
                title="Edit"
              >
                <FiEdit2 size={13} />
              </button>
            )}
            {(isAuthor || canManage) && (
              <button
                onClick={handleDelete}
                disabled={busy}
                className="p-1 rounded hover:bg-gray-100 text-gray-400 hover:text-red-600"
                title="Delete"
              >
                <FiTrash2 size={13} />
              </button>
            )}
          </div>
        </div>

        {/* Body */}
        {isEditing ? (
          <div className="flex gap-1 mt-1">
            <input
              className="flex-1 text-sm border rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-blue-400"
              value={editContent}
              onChange={(e) => setEditContent(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleEdit()}
              autoFocus
            />
            <button
              onClick={handleEdit}
              disabled={busy || !editContent.trim()}
              className="px-2 py-1 text-xs bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
            >
              Save
            </button>
            <button
              onClick={() => setIsEditing(false)}
              className="px-2 py-1 text-xs bg-gray-200 text-gray-700 rounded hover:bg-gray-300"
            >
              <FiX size={14} />
            </button>
          </div>
        ) : (
          <p className="text-gray-800 whitespace-pre-wrap break-words">{renderContentWithMentions(comment.content, mentionableUsers)}</p>
        )}

        {/* Reply trigger */}
        {!isReplying && depth < maxDepth && !comment.resolved && (
          <button
            onClick={() => setIsReplying(true)}
            className="mt-1 text-xs text-blue-600 hover:text-blue-800 flex items-center gap-0.5"
          >
            <FiCornerDownRight size={12} /> Reply
          </button>
        )}

        {/* Reply input */}
        {isReplying && (
          <div className="mt-2 flex gap-1">
            <MentionInput
              className="flex-1 text-sm border rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-blue-400"
              placeholder="Write a reply... (type @ to mention)"
              value={replyContent}
              onChange={setReplyContent}
              onSubmit={handleReply}
              users={mentionableUsers}
              onSearch={onMentionSearch}
              searching={mentionSearching}
              autoFocus
            />
            <button
              onClick={handleReply}
              disabled={busy || !replyContent.trim()}
              className="p-1.5 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
            >
              <FiSend size={14} />
            </button>
            <button
              onClick={() => { setIsReplying(false); setReplyContent(''); }}
              className="p-1.5 bg-gray-200 text-gray-700 rounded hover:bg-gray-300"
            >
              <FiX size={14} />
            </button>
          </div>
        )}
      </div>

      {/* Nested replies */}
      {comment.replies.length > 0 && (
        <div className="mt-1.5 space-y-1.5">
          {comment.replies.map((reply) => (
            <CommentBubble
              key={reply.id}
              comment={reply}
              sessionId={sessionId}
              slideId={slideId}
              onRefresh={onRefresh}
              mentionableUsers={mentionableUsers}
              onMentionSearch={onMentionSearch}
              mentionSearching={mentionSearching}
              depth={depth + 1}
              currentUser={currentUser}
              canManage={canManage}
            />
          ))}
        </div>
      )}
    </div>
  );
};

// ---------------------------------------------------------------------------
// Main thread panel rendered below a slide
// ---------------------------------------------------------------------------

interface CommentThreadProps {
  sessionId: string;
  slideId: string;
  onCommentChange?: (commentCount: number, hasMentions: boolean) => void;
  highlightCommentId?: number | null;
  canManage?: boolean;
}

export const CommentThread: React.FC<CommentThreadProps> = ({ sessionId, slideId, onCommentChange, highlightCommentId, canManage = false }) => {
  const [comments, setComments] = useState<SlideComment[]>([]);
  const [loading, setLoading] = useState(true);
  const [newContent, setNewContent] = useState('');
  const [posting, setPosting] = useState(false);
  const [showResolved, setShowResolved] = useState(false);
  const [mentionableUsers, setMentionableUsers] = useState<MentionableUser[]>([]);
  const [isGlobalProfile, setIsGlobalProfile] = useState(false);
  const [mentionSearching, setMentionSearching] = useState(false);
  const [currentUser, setCurrentUser] = useState<string>('');
  const listRef = useRef<HTMLDivElement>(null);

  const fetchComments = useCallback(async () => {
    try {
      const resp = await api.listComments(sessionId, slideId, showResolved);
      setComments(resp.comments);
      if (resp.current_user) setCurrentUser(resp.current_user);
    } catch (err) {
      console.error('Failed to load comments:', err);
    } finally {
      setLoading(false);
    }
  }, [sessionId, slideId, showResolved]);

  // Notify parent with current count
  const notifyParent = useCallback((count: number, hasMentions: boolean) => {
    onCommentChange?.(count, hasMentions);
  }, [onCommentChange]);

  const refreshAndNotify = useCallback(async () => {
    const resp = await api.listComments(sessionId, slideId, showResolved);
    setComments(resp.comments);
    if (resp.current_user) setCurrentUser(resp.current_user);
    const user = resp.current_user || currentUser;
    const hasMentions = resp.comments.some(
      (c: { mentions?: string[] }) => c.mentions?.some(m => m.toLowerCase() === user.toLowerCase())
    );
    notifyParent(resp.comments.length, hasMentions);
  }, [sessionId, slideId, showResolved, notifyParent, currentUser]);

  useEffect(() => {
    fetchComments();
  }, [fetchComments]);

  useEffect(() => {
    api.getMentionableUsers(sessionId).then(data => {
      setMentionableUsers(data.users);
      setIsGlobalProfile(data.is_global);
    }).catch(() => {});
  }, [sessionId]);

  const handleMentionSearch = useCallback((query: string) => {
    if (!isGlobalProfile) return;
    setMentionSearching(true);
    api.getMentionableUsers(sessionId, query).then(data => {
      setMentionableUsers(prev => {
        const seen = new Set(prev.map(u => u.username));
        const merged = [...prev];
        for (const u of data.users) {
          if (!seen.has(u.username)) {
            merged.push(u);
            seen.add(u.username);
          }
        }
        return merged;
      });
    }).catch(() => {}).finally(() => setMentionSearching(false));
  }, [sessionId, isGlobalProfile]);

  // Scroll to highlighted comment when thread opens or highlightCommentId changes
  useEffect(() => {
    if (!highlightCommentId || loading) return;
    const timer = setTimeout(() => {
      const el = document.getElementById(`comment-${highlightCommentId}`);
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'center' });
        el.classList.add('ring-2', 'ring-blue-400', 'ring-offset-1');
        setTimeout(() => el.classList.remove('ring-2', 'ring-blue-400', 'ring-offset-1'), 2500);
      }
    }, 100);
    return () => clearTimeout(timer);
  }, [highlightCommentId, loading]);

  const handleAdd = async () => {
    if (!newContent.trim() || posting) return;
    const content = newContent.trim();
    const mentionMatches = content.match(/@[\w.+\-]+@[\w.\-]+/g) || [];
    const hasMentions = mentionMatches.length > 0;

    // Optimistic: insert placeholder immediately
    const optimisticId = -(Date.now());
    const optimistic: SlideComment = {
      id: optimisticId,
      slide_id: slideId,
      user_name: 'You',
      user_email: currentUser || '',
      content,
      mentions: mentionMatches.map(m => m.slice(1)),
      resolved: false,
      resolved_by: null,
      resolved_at: null,
      parent_comment_id: null,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      replies: [],
    };
    setComments(prev => {
      const next = [...prev, optimistic];
      // Notify parent immediately with new count
      notifyParent(next.length, hasMentions);
      return next;
    });
    setNewContent('');

    setTimeout(() => listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: 'smooth' }), 50);

    setPosting(true);
    try {
      const real = await api.addComment(sessionId, slideId, content);
      setComments(prev => prev.map(c => c.id === optimisticId ? { ...real, replies: real.replies || [] } : c));
      // Re-notify after the comment is persisted so fetchMentions finds it
      if (hasMentions) notifyParent(comments.length + 1, true);
    } catch (err) {
      console.error('Failed to add comment:', err);
      setComments(prev => {
        const next = prev.filter(c => c.id !== optimisticId);
        notifyParent(next.length, false);
        return next;
      });
    } finally {
      setPosting(false);
    }
  };

  return (
    <div className="bg-gray-50 border-t px-4 py-3">
      {/* Header row */}
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-semibold text-gray-600 uppercase tracking-wide">
          Comments {!loading && `(${comments.length})`}
        </span>
        <button
          onClick={() => setShowResolved((v) => !v)}
          className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700"
        >
          {showResolved ? <FiEyeOff size={12} /> : <FiEye size={12} />}
          {showResolved ? 'Hide resolved' : 'Show resolved'}
        </button>
      </div>

      {/* Comment list */}
      {loading ? (
        <p className="text-xs text-gray-400 py-2">Loading comments...</p>
      ) : comments.length === 0 ? (
        <p className="text-xs text-gray-400 py-2">No comments yet. Start a discussion below.</p>
      ) : (
        <div ref={listRef} className="space-y-2 mb-3 max-h-64 overflow-y-auto">
          {comments.map((c) => (
            <CommentBubble
              key={c.id}
              comment={c}
              sessionId={sessionId}
              slideId={slideId}
              onRefresh={refreshAndNotify}
              mentionableUsers={mentionableUsers}
              onMentionSearch={handleMentionSearch}
              mentionSearching={mentionSearching}
              currentUser={currentUser}
              canManage={canManage}
            />
          ))}
        </div>
      )}

      {/* New comment input */}
      <div className="flex gap-1.5">
        <MentionInput
          className="w-full text-sm border border-gray-300 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-400"
          placeholder="Add a comment... (type @ to mention)"
          value={newContent}
          onChange={setNewContent}
          onSubmit={handleAdd}
          users={mentionableUsers}
          onSearch={handleMentionSearch}
          searching={mentionSearching}
        />
        <button
          onClick={handleAdd}
          disabled={posting || !newContent.trim()}
          className="px-3 py-1.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 flex items-center gap-1 text-sm"
        >
          <FiSend size={14} />
        </button>
      </div>
    </div>
  );
};

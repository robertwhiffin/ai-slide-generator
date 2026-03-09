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

// ---------------------------------------------------------------------------
// Single comment bubble
// ---------------------------------------------------------------------------

interface CommentBubbleProps {
  comment: SlideComment;
  sessionId: string;
  slideId: string;
  onRefresh: () => void;
  depth?: number;
}

const CommentBubble: React.FC<CommentBubbleProps> = ({
  comment,
  sessionId,
  slideId,
  onRefresh,
  depth = 0,
}) => {
  const [isEditing, setIsEditing] = useState(false);
  const [editContent, setEditContent] = useState(comment.content);
  const [isReplying, setIsReplying] = useState(false);
  const [replyContent, setReplyContent] = useState('');
  const [busy, setBusy] = useState(false);

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
    <div className={`${depth > 0 ? 'ml-5 border-l-2 border-gray-200 pl-3' : ''}`}>
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
            <button
              onClick={() => { setIsEditing(true); setEditContent(comment.content); }}
              className="p-1 rounded hover:bg-gray-100 text-gray-400 hover:text-blue-600"
              title="Edit"
            >
              <FiEdit2 size={13} />
            </button>
            <button
              onClick={handleDelete}
              disabled={busy}
              className="p-1 rounded hover:bg-gray-100 text-gray-400 hover:text-red-600"
              title="Delete"
            >
              <FiTrash2 size={13} />
            </button>
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
          <p className="text-gray-800 whitespace-pre-wrap break-words">{comment.content}</p>
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
            <input
              className="flex-1 text-sm border rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-blue-400"
              placeholder="Write a reply..."
              value={replyContent}
              onChange={(e) => setReplyContent(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleReply()}
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
              depth={depth + 1}
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
}

export const CommentThread: React.FC<CommentThreadProps> = ({ sessionId, slideId }) => {
  const [comments, setComments] = useState<SlideComment[]>([]);
  const [loading, setLoading] = useState(true);
  const [newContent, setNewContent] = useState('');
  const [posting, setPosting] = useState(false);
  const [showResolved, setShowResolved] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const fetchComments = useCallback(async () => {
    try {
      const { comments: data } = await api.listComments(sessionId, slideId, showResolved);
      setComments(data);
    } catch (err) {
      console.error('Failed to load comments:', err);
    } finally {
      setLoading(false);
    }
  }, [sessionId, slideId, showResolved]);

  useEffect(() => {
    fetchComments();
  }, [fetchComments]);

  const handleAdd = async () => {
    if (!newContent.trim() || posting) return;
    setPosting(true);
    try {
      await api.addComment(sessionId, slideId, newContent.trim());
      setNewContent('');
      await fetchComments();
      inputRef.current?.focus();
    } catch (err) {
      console.error('Failed to add comment:', err);
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
        <div className="space-y-2 mb-3 max-h-64 overflow-y-auto">
          {comments.map((c) => (
            <CommentBubble
              key={c.id}
              comment={c}
              sessionId={sessionId}
              slideId={slideId}
              onRefresh={fetchComments}
            />
          ))}
        </div>
      )}

      {/* New comment input */}
      <div className="flex gap-1.5">
        <input
          ref={inputRef}
          className="flex-1 text-sm border border-gray-300 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-400"
          placeholder="Add a comment..."
          value={newContent}
          onChange={(e) => setNewContent(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleAdd()}
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

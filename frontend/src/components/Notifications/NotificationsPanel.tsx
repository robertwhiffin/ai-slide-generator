import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { FiAtSign, FiMessageCircle, FiExternalLink } from 'react-icons/fi';
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

function renderContentWithMentions(content: string): React.ReactNode {
  const parts = content.split(/(@[\w.+-]+@[\w.-]+)/g);
  return parts.map((part, i) =>
    part.startsWith('@') ? (
      <span key={i} className="text-blue-600 font-medium">{part}</span>
    ) : (
      <span key={i}>{part}</span>
    )
  );
}

export const NotificationsPanel: React.FC = () => {
  const [mentions, setMentions] = useState<SlideComment[]>([]);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  const fetchMentions = useCallback(async () => {
    try {
      const data = await api.listMentions();
      setMentions(data.mentions);
    } catch (err) {
      console.error('Failed to load mentions:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchMentions();
  }, [fetchMentions]);

  const handleOpen = (mention: SlideComment) => {
    if (mention.session_id_str) {
      navigate(`/sessions/${mention.session_id_str}`);
    }
  };

  return (
    <div className="max-w-3xl mx-auto">
      <h2 className="text-xl font-semibold text-gray-800 mb-4 flex items-center gap-2">
        <FiAtSign size={20} />
        Mentions
      </h2>

      {loading ? (
        <div className="text-sm text-gray-400 py-8 text-center">Loading notifications...</div>
      ) : mentions.length === 0 ? (
        <div className="text-center py-12">
          <FiMessageCircle size={40} className="mx-auto text-gray-300 mb-3" />
          <p className="text-gray-500">No mentions yet</p>
          <p className="text-sm text-gray-400 mt-1">
            When someone @mentions you in a comment, it will appear here.
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {mentions.map((m) => (
            <div
              key={m.id}
              className="bg-white border border-gray-200 rounded-lg p-4 hover:border-blue-300 transition-colors cursor-pointer"
              onClick={() => handleOpen(m)}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="font-semibold text-sm text-gray-800">{m.user_name}</span>
                    <span className="text-xs text-gray-400">&middot;</span>
                    <span className="text-xs text-gray-400" title={new Date(m.created_at).toLocaleString()}>
                      {timeAgo(m.created_at)}
                    </span>
                    <span className="text-xs text-gray-400 bg-gray-100 px-1.5 py-0.5 rounded">
                      {m.slide_id.replace('slide_', 'Slide ')}
                    </span>
                  </div>
                  <p className="text-sm text-gray-700 whitespace-pre-wrap break-words">
                    {renderContentWithMentions(m.content)}
                  </p>
                </div>
                <button
                  className="flex-shrink-0 p-2 rounded-lg hover:bg-blue-50 text-gray-400 hover:text-blue-600 transition-colors"
                  title="Open presentation"
                >
                  <FiExternalLink size={16} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { FiBell, FiExternalLink } from 'react-icons/fi';
import type { SlideComment } from '../../types/comment';
import { api } from '../../services/api';

const POLL_INTERVAL = 3_000;

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
      <span key={i} className="text-blue-400 font-medium">{part}</span>
    ) : (
      <span key={i}>{part}</span>
    )
  );
}

export const NotificationBell: React.FC<{ disabled?: boolean }> = ({ disabled }) => {
  const [mentions, setMentions] = useState<SlideComment[]>([]);
  const [open, setOpen] = useState(false);
  const [lastSeenCount, setLastSeenCount] = useState(() => {
    const stored = localStorage.getItem('tellr_last_seen_mention_count');
    return stored ? parseInt(stored, 10) : 0;
  });
  const dropdownRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();

  const fetchMentions = useCallback(async () => {
    try {
      const data = await api.listMentions();
      setMentions(data.mentions);
    } catch {
      // silent — non-critical
    }
  }, []);

  useEffect(() => {
    fetchMentions();
    const interval = setInterval(fetchMentions, POLL_INTERVAL);
    return () => clearInterval(interval);
  }, [fetchMentions]);

  // Close dropdown on outside click
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    if (open) {
      document.addEventListener('mousedown', handleClickOutside);
      return () => document.removeEventListener('mousedown', handleClickOutside);
    }
  }, [open]);

  const unreadCount = Math.max(0, mentions.length - lastSeenCount);

  const handleToggle = () => {
    if (!open) {
      fetchMentions();
    } else {
      // Mark all as "seen" when closing
      setLastSeenCount(mentions.length);
      localStorage.setItem('tellr_last_seen_mention_count', String(mentions.length));
    }
    setOpen(!open);
  };

  const handleOpenMention = (mention: SlideComment) => {
    if (mention.session_id_str) {
      setOpen(false);
      setLastSeenCount(mentions.length);
      localStorage.setItem('tellr_last_seen_mention_count', String(mentions.length));
      navigate(`/sessions/${mention.session_id_str}`);
    }
  };

  const handleViewAll = () => {
    setOpen(false);
    setLastSeenCount(mentions.length);
    localStorage.setItem('tellr_last_seen_mention_count', String(mentions.length));
    navigate('/notifications');
  };

  return (
    <div className="relative" ref={dropdownRef}>
      {/* Bell Button */}
      <button
        onClick={handleToggle}
        disabled={disabled}
        className={`relative p-2 rounded-lg transition-colors ${
          open
            ? 'bg-muted text-foreground'
            : disabled
            ? 'text-muted-foreground cursor-not-allowed opacity-50'
            : 'text-muted-foreground hover:bg-muted hover:text-foreground'
        }`}
        title="Notifications"
      >
        <FiBell size={18} />
        {unreadCount > 0 && (
          <span className="absolute -top-1 -right-1 flex items-center justify-center rounded-full bg-red-500 text-[10px] font-bold text-white ring-2 ring-background min-w-[18px] h-[18px] px-1">
            {unreadCount > 99 ? '99+' : unreadCount}
          </span>
        )}
      </button>

      {/* Dropdown Panel */}
      {open && (
        <div className="absolute right-0 top-full mt-2 w-96 bg-white rounded-xl shadow-2xl border border-gray-200 z-50 overflow-hidden">
          {/* Header */}
          <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between">
            <h3 className="font-semibold text-gray-800 text-sm">Notifications</h3>
            {mentions.length > 0 && (
              <button
                onClick={handleViewAll}
                className="text-xs text-blue-600 hover:text-blue-800 font-medium"
              >
                View all
              </button>
            )}
          </div>

          {/* Mentions list */}
          <div className="max-h-96 overflow-y-auto">
            {mentions.length === 0 ? (
              <div className="py-10 text-center">
                <FiBell size={28} className="mx-auto text-gray-300 mb-2" />
                <p className="text-sm text-gray-500">No notifications yet</p>
                <p className="text-xs text-gray-400 mt-1">
                  You'll be notified when someone @mentions you
                </p>
              </div>
            ) : (
              mentions.slice(0, 20).map((m, idx) => {
                const isUnread = mentions.length - lastSeenCount > 0 && idx < mentions.length - lastSeenCount;
                return (
                  <div
                    key={m.id}
                    onClick={() => handleOpenMention(m)}
                    className={`px-4 py-3 cursor-pointer border-b border-gray-50 last:border-0 transition-colors hover:bg-gray-50 ${
                      isUnread ? 'bg-blue-50' : ''
                    }`}
                  >
                    <div className="flex items-start gap-3">
                      {/* Unread dot */}
                      <div className="pt-1.5 flex-shrink-0">
                        <div className={`w-2 h-2 rounded-full ${isUnread ? 'bg-blue-500' : 'bg-transparent'}`} />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-1.5 mb-0.5">
                          <span className="font-semibold text-xs text-gray-800 truncate">{m.user_name}</span>
                          <span className="text-xs text-gray-400 flex-shrink-0">{timeAgo(m.created_at)}</span>
                        </div>
                        <p className="text-xs text-gray-600 line-clamp-2">
                          {renderContentWithMentions(m.content)}
                        </p>
                        <span className="text-[10px] text-gray-400 mt-1 inline-block">
                          {m.slide_id.replace('slide_', 'Slide ')}
                        </span>
                      </div>
                      <FiExternalLink size={12} className="flex-shrink-0 text-gray-300 mt-1" />
                    </div>
                  </div>
                );
              })
            )}
          </div>

          {/* Footer */}
          {mentions.length > 20 && (
            <div className="px-4 py-2 border-t border-gray-100 bg-gray-50">
              <button
                onClick={handleViewAll}
                className="w-full text-center text-xs text-blue-600 hover:text-blue-800 font-medium"
              >
                View all {mentions.length} notifications
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

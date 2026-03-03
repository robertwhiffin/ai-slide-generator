import React, { useEffect, useState } from 'react';
import { api } from '../../services/api';
import type { Session } from '../../services/api';

interface SessionHistoryProps {
  onSessionSelect: (sessionId: string) => void;
}

type TabType = 'my' | 'shared';

export const SessionHistory: React.FC<SessionHistoryProps> = ({
  onSessionSelect,
}) => {
  const [mySessions, setMySessions] = useState<Session[]>([]);
  const [sharedSessions, setSharedSessions] = useState<Session[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState('');
  const [activeTab, setActiveTab] = useState<TabType>('my');

  const loadSessions = async () => {
    try {
      setLoading(true);
      const [myResult, sharedResult] = await Promise.all([
        api.listSessions(100),
        api.listSharedSessions(100),
      ]);
      setMySessions(myResult.sessions);
      setSharedSessions(sharedResult.sessions);
      setError(null);
    } catch (err) {
      setError('Failed to load sessions');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadSessions();
  }, []);

  // Get current sessions based on active tab
  const sessions = activeTab === 'my' ? mySessions : sharedSessions;

  const handleRename = async (sessionId: string) => {
    if (!editTitle.trim()) return;

    try {
      await api.renameSession(sessionId, editTitle.trim());
      setEditingId(null);
      setEditTitle('');
      loadSessions();
    } catch (err) {
      console.error('Failed to rename session:', err);
    }
  };

  const handleDelete = async (sessionId: string) => {
    if (!confirm('Delete this session? This cannot be undone.')) return;

    try {
      await api.deleteSession(sessionId);
      loadSessions();
    } catch (err) {
      console.error('Failed to delete session:', err);
    }
  };

  const handleRestore = (sessionId: string) => {
    onSessionSelect(sessionId);
  };

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    // Compact date format with year: "1/8/2026, 2:20 PM"
    return date.toLocaleDateString('en-US', { 
      month: 'numeric', 
      day: 'numeric',
      year: 'numeric'
    }) + ', ' + date.toLocaleTimeString('en-US', { 
      hour: 'numeric', 
      minute: '2-digit',
      hour12: true 
    });
  };

  // Permission helpers
  const canEdit = (session: Session) => 
    session.my_permission === 'CAN_EDIT' || session.my_permission === 'CAN_MANAGE';
  const canManage = (session: Session) => 
    session.my_permission === 'CAN_MANAGE';

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-gray-500">Loading sessions...</div>
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto">
      <div className="mb-6">
        <h2 className="text-2xl font-bold text-gray-900">Sessions</h2>
        
        {/* Tab Navigation */}
        <div className="mt-4 border-b border-gray-200">
          <nav className="-mb-px flex space-x-8">
            <button
              onClick={() => setActiveTab('my')}
              className={`py-2 px-1 border-b-2 font-medium text-sm ${
                activeTab === 'my'
                  ? 'border-blue-500 text-blue-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
              }`}
            >
              My Sessions
              <span className="ml-2 py-0.5 px-2 rounded-full text-xs bg-gray-100 text-gray-600">
                {mySessions.length}
              </span>
            </button>
            <button
              onClick={() => setActiveTab('shared')}
              className={`py-2 px-1 border-b-2 font-medium text-sm ${
                activeTab === 'shared'
                  ? 'border-blue-500 text-blue-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
              }`}
            >
              Shared with Me
              <span className="ml-2 py-0.5 px-2 rounded-full text-xs bg-gray-100 text-gray-600">
                {sharedSessions.length}
              </span>
            </button>
          </nav>
        </div>
      </div>

      {error && (
        <div className="mb-4 p-4 bg-red-50 border border-red-200 rounded-md text-red-700">
          {error}
        </div>
      )}

      {sessions.length === 0 ? (
        <div className="text-center py-12 bg-white rounded-lg border border-gray-200">
          <svg
            className="mx-auto h-12 w-12 text-gray-400"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"
            />
          </svg>
          <h3 className="mt-4 text-lg font-medium text-gray-900">
            {activeTab === 'my' ? 'No sessions yet' : 'No shared sessions'}
          </h3>
          <p className="mt-2 text-sm text-gray-500">
            {activeTab === 'my' 
              ? 'Start creating slides and save your sessions to see them here.'
              : 'When someone shares a profile with you, their sessions will appear here.'}
          </p>
        </div>
      ) : (
        <div className="bg-white rounded-lg border border-gray-200">
          <table className="w-full divide-y divide-gray-200 table-fixed">
            <thead className="bg-gray-50">
              <tr>
                <th className="w-[13%] px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Profile
                </th>
                {activeTab === 'shared' && (
                  <th className="w-[12%] px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Owner
                  </th>
                )}
                <th className={`${activeTab === 'shared' ? 'w-[20%]' : 'w-[28%]'} px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider`}>
                  Session Name
                </th>
                <th className="w-[12%] px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Created
                </th>
                <th className="w-[12%] px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Last Activity
                </th>
                <th className="w-[8%] px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Slides
                </th>
                {activeTab === 'shared' && (
                  <th className="w-[8%] px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Access
                  </th>
                )}
                <th className={`${activeTab === 'shared' ? 'w-[15%]' : 'w-[18%]'} px-3 py-3 text-center text-xs font-medium text-gray-500 uppercase tracking-wider`}>
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {sessions.map((session) => (
                <tr
                  key={session.session_id}
                  className="hover:bg-gray-50"
                >
                  <td className="px-3 py-3">
                    {session.profile_name ? (
                      <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-purple-100 text-purple-800 truncate max-w-full" title={session.profile_name}>
                        {session.profile_name}
                      </span>
                    ) : (
                      <span className="text-gray-400 text-xs">—</span>
                    )}
                  </td>
                  {activeTab === 'shared' && (
                    <td className="px-3 py-3 text-xs text-gray-600 truncate" title={session.created_by || ''}>
                      {session.created_by?.split('@')[0] || '—'}
                    </td>
                  )}
                  <td className="px-3 py-3">
                    {editingId === session.session_id ? (
                      <div className="flex items-center gap-1">
                        <input
                          type="text"
                          value={editTitle}
                          onChange={(e) => setEditTitle(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') handleRename(session.session_id);
                            if (e.key === 'Escape') setEditingId(null);
                          }}
                          className="w-full px-2 py-1 border border-gray-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                          autoFocus
                        />
                        <button
                          onClick={() => handleRename(session.session_id)}
                          className="text-green-600 hover:text-green-800 flex-shrink-0"
                        >
                          ✓
                        </button>
                        <button
                          onClick={() => setEditingId(null)}
                          className="text-gray-400 hover:text-gray-600 flex-shrink-0"
                        >
                          ✕
                        </button>
                      </div>
                    ) : (
                      <div className="flex items-center gap-1">
                        <span className="text-sm font-medium text-gray-900 truncate" title={session.title}>
                          {session.title}
                        </span>
                      </div>
                    )}
                  </td>
                  <td className="px-3 py-3 text-xs text-gray-500">
                    {formatDate(session.created_at)}
                  </td>
                  <td className="px-3 py-3 text-xs text-gray-500">
                    {session.last_activity ? formatDate(session.last_activity) : '-'}
                  </td>
                  <td className="px-3 py-3 text-xs text-gray-500">
                    {session.has_slide_deck ? (
                      <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800">
                        Yes
                      </span>
                    ) : (
                      <span className="text-gray-400">No</span>
                    )}
                  </td>
                  {activeTab === 'shared' && (
                    <td className="px-3 py-3">
                      <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
                        session.my_permission === 'CAN_MANAGE' 
                          ? 'bg-green-100 text-green-800'
                          : session.my_permission === 'CAN_EDIT'
                          ? 'bg-blue-100 text-blue-800'
                          : 'bg-gray-100 text-gray-800'
                      }`}>
                        {session.my_permission === 'CAN_MANAGE' ? 'Manage' : 
                         session.my_permission === 'CAN_EDIT' ? 'Edit' : 'View'}
                      </span>
                    </td>
                  )}
                  <td className="px-3 py-3 text-center text-sm font-medium">
                    <div className="flex items-center justify-center gap-2">
                      {session.has_slide_deck && (
                        <button
                          onClick={() => handleRestore(session.session_id)}
                          className="text-blue-600 hover:text-blue-900 text-xs"
                        >
                          {activeTab === 'shared' && !canEdit(session) ? 'View' : 'Open'}
                        </button>
                      )}
                      {canEdit(session) && (
                        <button
                          onClick={() => {
                            setEditingId(session.session_id);
                            setEditTitle(session.title);
                          }}
                          className="text-gray-600 hover:text-gray-900 text-xs"
                        >
                          Rename
                        </button>
                      )}
                      {canManage(session) && (
                        <button
                          onClick={() => handleDelete(session.session_id)}
                          className="text-red-600 hover:text-red-900 text-xs"
                        >
                          Delete
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};


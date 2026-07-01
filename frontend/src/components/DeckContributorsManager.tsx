/**
 * Deck contributors management component for sharing decks (sessions).
 *
 * Allows adding, updating, and removing contributors (users/groups)
 * with CAN_VIEW / CAN_EDIT / CAN_MANAGE permission levels, and sharing
 * with all workspace users (CAN_VIEW or CAN_EDIT only).
 */

import React, { useState, useEffect, useCallback } from 'react';
import { FiSearch, FiUser, FiUsers, FiTrash2, FiUserPlus, FiLock, FiGlobe } from 'react-icons/fi';
import {
  configApi,
  ConfigApiError,
  type Contributor,
  type ContributorCreate,
  type DeckWorkspacePermission,
  type Identity,
  type PermissionLevel,
} from '../api/config';
import { matchesWorkspaceShareSearch } from '../utils/workspaceShareSearch';

const DECK_PERMISSION_OPTIONS: { value: PermissionLevel; label: string; description: string }[] = [
  { value: 'CAN_VIEW', label: 'Can View', description: 'View the deck and its slides' },
  { value: 'CAN_EDIT', label: 'Can Edit', description: 'Edit slides and chat with the agent' },
  { value: 'CAN_MANAGE', label: 'Can Manage', description: 'Full control including sharing' },
];

const WORKSPACE_DECK_PERMISSION_OPTIONS: { value: DeckWorkspacePermission; label: string }[] = [
  { value: 'CAN_VIEW', label: 'Can View' },
  { value: 'CAN_EDIT', label: 'Can Edit' },
];

interface DeckContributorsManagerProps {
  sessionId: string;
  canManage?: boolean;
  onSharingChange?: () => void;
}

export const DeckContributorsManager: React.FC<DeckContributorsManagerProps> = ({
  sessionId,
  canManage: canManageProp,
  onSharingChange,
}) => {
  const [contributors, setContributors] = useState<Contributor[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [canManage, setCanManage] = useState(canManageProp ?? true);

  const [globalPermission, setGlobalPermission] = useState<DeckWorkspacePermission | null>(null);
  const [updatingGlobal, setUpdatingGlobal] = useState(false);

  // Search state
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<Identity[]>([]);
  const [searching, setSearching] = useState(false);
  const [selectedPermission, setSelectedPermission] = useState<PermissionLevel>('CAN_EDIT');

  // Operation states
  const [addingContributor, setAddingContributor] = useState(false);
  const [updatingId, setUpdatingId] = useState<number | null>(null);
  const [removingId, setRemovingId] = useState<number | null>(null);

  const workspacePermissionFromSelection = (): DeckWorkspacePermission =>
    selectedPermission === 'CAN_EDIT' ? 'CAN_EDIT' : 'CAN_VIEW';

  // Load contributors
  const loadContributors = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const response = await configApi.listDeckContributors(sessionId);
      setContributors(response.contributors);
      setGlobalPermission(response.global_permission ?? null);
    } catch (err) {
      if (err instanceof ConfigApiError && err.status === 403) {
        setCanManage(false);
      } else {
        setError(err instanceof Error ? err.message : 'Failed to load contributors');
      }
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    loadContributors();
  }, [loadContributors]);

  const handleSetGlobalPermission = async (permission: DeckWorkspacePermission | null) => {
    setUpdatingGlobal(true);
    try {
      const result = await configApi.setDeckGlobal(sessionId, permission);
      setGlobalPermission(result.global_permission);
      onSharingChange?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update workspace sharing');
    } finally {
      setUpdatingGlobal(false);
    }
  };

  // Search identities with debounce
  const searchIdentities = useCallback(async (query: string) => {
    if (!query.trim() || query.length < 2) {
      setSearchResults([]);
      return;
    }
    setSearching(true);
    try {
      const response = await configApi.searchIdentities(query.trim());
      const existingIds = new Set(contributors.map(c => c.identity_id));
      setSearchResults(response.identities.filter(i => !existingIds.has(i.id)));
    } catch (err) {
      console.error('Search failed:', err);
      setSearchResults([]);
    } finally {
      setSearching(false);
    }
  }, [contributors]);

  useEffect(() => {
    const timer = setTimeout(() => {
      if (searchQuery) {
        searchIdentities(searchQuery);
      } else {
        setSearchResults([]);
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [searchQuery, searchIdentities]);

  const handleAddContributor = async (identity: Identity) => {
    setAddingContributor(true);
    try {
      const newContributor: ContributorCreate = {
        identity_id: identity.id,
        identity_type: identity.type,
        identity_name: identity.user_name || identity.display_name || 'Unknown',
        user_name: identity.user_name,
        permission_level: selectedPermission,
      };
      await configApi.addDeckContributor(sessionId, newContributor);
      setSearchQuery('');
      setSearchResults([]);
      await loadContributors();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to add contributor');
    } finally {
      setAddingContributor(false);
    }
  };

  const handleUpdatePermission = async (contributorId: number, permission: PermissionLevel) => {
    setUpdatingId(contributorId);
    try {
      await configApi.updateDeckContributor(sessionId, contributorId, { permission_level: permission });
      await loadContributors();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update permission');
    } finally {
      setUpdatingId(null);
    }
  };

  const handleRemoveContributor = async (contributorId: number) => {
    setRemovingId(contributorId);
    try {
      await configApi.removeDeckContributor(sessionId, contributorId);
      await loadContributors();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to remove contributor');
    } finally {
      setRemovingId(null);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-48">
        <div className="flex items-center gap-2 text-gray-600">
          <div className="w-5 h-5 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
          Loading contributors...
        </div>
      </div>
    );
  }

  if (!canManage) {
    return (
      <div className="space-y-4">
        <div>
          <h3 className="text-lg font-medium text-gray-900">Share Deck</h3>
        </div>
        <div className="bg-amber-50 border border-amber-200 rounded-md p-4 flex items-start gap-3">
          <FiLock className="text-amber-600 mt-0.5 flex-shrink-0" size={18} />
          <div>
            <p className="text-sm font-medium text-amber-800">
              You need the "Can Manage" permission to share this deck
            </p>
            <p className="text-sm text-amber-700 mt-1">
              You currently have edit access. Ask the deck owner to grant you "Can Manage" permission to add or remove contributors.
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-medium text-gray-900">Share Deck</h3>
        <p className="text-sm text-gray-500 mt-1">
          Add users from your Databricks workspace who can access this deck.
        </p>
      </div>

      {error && (
        <div className="p-3 bg-red-50 border border-red-200 rounded-md text-red-700 text-sm flex items-center justify-between">
          <span>{error}</span>
          <button onClick={() => setError(null)} className="text-red-500 hover:text-red-700">
            ✕
          </button>
        </div>
      )}

      {canManage && (
        <div className="bg-gray-50 rounded-lg p-4 border border-gray-200">
          <div className="flex items-center gap-2 mb-3">
            <FiUserPlus className="text-blue-500" />
            <span className="font-medium text-gray-700">Add Contributor</span>
          </div>

          <div className="flex gap-3">
            <div className="flex-1 relative">
              <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                <FiSearch className="text-gray-400" />
              </div>
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search users..."
                className="w-full pl-10 pr-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                disabled={addingContributor}
              />
              {searching && (
                <div className="absolute inset-y-0 right-0 pr-3 flex items-center">
                  <div className="w-4 h-4 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
                </div>
              )}
            </div>

            <select
              value={selectedPermission}
              onChange={(e) => setSelectedPermission(e.target.value as PermissionLevel)}
              className="px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 bg-white"
              disabled={addingContributor}
            >
              {DECK_PERMISSION_OPTIONS.map(opt => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          </div>

          {(searchResults.length > 0 || (searchQuery.length >= 1 && !globalPermission && canManage)) && (
            <div className="mt-2 border border-gray-200 rounded-md shadow-sm max-h-48 overflow-y-auto bg-white">
              {!globalPermission && canManage && matchesWorkspaceShareSearch(searchQuery) && (
                <button
                  onClick={() => handleSetGlobalPermission(workspacePermissionFromSelection())}
                  disabled={updatingGlobal}
                  className="w-full px-4 py-3 flex items-center gap-3 hover:bg-blue-50 border-b last:border-b-0 text-left disabled:opacity-50"
                >
                  <FiGlobe className="text-green-600 flex-shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="font-medium text-gray-900">All workspace users</p>
                    <p className="text-xs text-gray-500">Share with everyone in the workspace</p>
                  </div>
                  <span className="text-xs text-blue-600 font-medium">+ Add</span>
                </button>
              )}
              {searchResults.map(identity => (
                <button
                  key={identity.id}
                  onClick={() => handleAddContributor(identity)}
                  disabled={addingContributor}
                  className="w-full px-4 py-3 flex items-center gap-3 hover:bg-blue-50 border-b last:border-b-0 text-left disabled:opacity-50"
                >
                  {identity.type === 'USER' ? (
                    <FiUser className="text-blue-500 flex-shrink-0" />
                  ) : (
                    <FiUsers className="text-purple-500 flex-shrink-0" />
                  )}
                  <div className="flex-1 min-w-0">
                    <p className="font-medium text-gray-900 truncate">{identity.display_name}</p>
                    {identity.user_name && identity.user_name !== identity.display_name && (
                      <p className="text-xs text-gray-500 truncate">{identity.user_name}</p>
                    )}
                  </div>
                  <span className="text-xs text-blue-600 font-medium">+ Add</span>
                </button>
              ))}
            </div>
          )}

          {searchQuery.length >= 2 && !searching && searchResults.length === 0 && !(matchesWorkspaceShareSearch(searchQuery) && !globalPermission) && (
            <p className="mt-2 text-sm text-gray-500 text-center py-2">
              No users found matching "{searchQuery}"
            </p>
          )}
        </div>
      )}

      <div>
        <h4 className="text-sm font-medium text-gray-700 mb-3">
          Current Access ({contributors.length + (globalPermission ? 1 : 0)})
        </h4>

        {contributors.length === 0 && !globalPermission ? (
          <div className="bg-blue-50 border border-blue-200 rounded-md p-4 text-center">
            <FiUsers className="mx-auto text-blue-400 mb-2" size={24} />
            <p className="text-sm text-blue-700">
              No contributors yet. This deck is private to you.
            </p>
            <p className="text-xs text-blue-600 mt-1">
              Search above to add users or "All workspace users".
            </p>
          </div>
        ) : (
          <div className="space-y-2">
            {globalPermission && (
              <div className="flex items-center gap-3 p-3 bg-green-50 rounded-md border border-green-200 hover:border-green-300 transition-colors">
                <div className="w-10 h-10 rounded-full bg-green-100 flex items-center justify-center">
                  <FiGlobe className="text-green-600" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="font-medium text-gray-900">All workspace users</p>
                  <p className="text-xs text-gray-500">Everyone in the workspace</p>
                </div>
                {canManage ? (
                  <>
                    <select
                      value={globalPermission}
                      onChange={(e) => handleSetGlobalPermission(e.target.value as DeckWorkspacePermission)}
                      disabled={updatingGlobal}
                      className="text-sm px-3 py-1.5 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 bg-white disabled:opacity-50"
                    >
                      {WORKSPACE_DECK_PERMISSION_OPTIONS.map(opt => (
                        <option key={opt.value} value={opt.value}>{opt.label}</option>
                      ))}
                    </select>
                    <button
                      onClick={() => handleSetGlobalPermission(null)}
                      disabled={updatingGlobal}
                      className="p-2 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded transition-colors disabled:opacity-50"
                      title="Remove workspace access"
                    >
                      <FiTrash2 />
                    </button>
                  </>
                ) : (
                  <span className="text-sm text-gray-600 px-3 py-1.5">
                    {WORKSPACE_DECK_PERMISSION_OPTIONS.find(o => o.value === globalPermission)?.label}
                  </span>
                )}
              </div>
            )}
            {contributors.map(contributor => (
              <div
                key={contributor.id}
                className="flex items-center gap-3 p-3 bg-white rounded-md border border-gray-200 hover:border-gray-300 transition-colors"
              >
                {contributor.identity_type === 'USER' ? (
                  <div className="w-10 h-10 rounded-full bg-blue-100 flex items-center justify-center">
                    <FiUser className="text-blue-600" />
                  </div>
                ) : (
                  <div className="w-10 h-10 rounded-full bg-purple-100 flex items-center justify-center">
                    <FiUsers className="text-purple-600" />
                  </div>
                )}

                <div className="flex-1 min-w-0">
                  <p className="font-medium text-gray-900 truncate">
                    {contributor.display_name || contributor.identity_name}
                  </p>
                  <p className="text-xs text-gray-500 truncate">
                    {contributor.user_name && contributor.user_name !== (contributor.display_name || contributor.identity_name)
                      ? `${contributor.user_name} · Added ${new Date(contributor.created_at).toLocaleDateString()}`
                      : `${contributor.identity_type} · Added ${new Date(contributor.created_at).toLocaleDateString()}`}
                  </p>
                </div>

                {canManage ? (
                  <>
                    <select
                      value={contributor.permission_level}
                      onChange={(e) => handleUpdatePermission(contributor.id, e.target.value as PermissionLevel)}
                      disabled={updatingId === contributor.id || removingId === contributor.id}
                      className="text-sm px-3 py-1.5 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 bg-white disabled:opacity-50"
                    >
                      {DECK_PERMISSION_OPTIONS.map(opt => (
                        <option key={opt.value} value={opt.value}>{opt.label}</option>
                      ))}
                    </select>

                    <button
                      onClick={() => handleRemoveContributor(contributor.id)}
                      disabled={removingId === contributor.id || updatingId === contributor.id}
                      className="p-2 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded transition-colors disabled:opacity-50"
                      title="Remove contributor"
                    >
                      {removingId === contributor.id ? (
                        <div className="w-4 h-4 border-2 border-red-500 border-t-transparent rounded-full animate-spin" />
                      ) : (
                        <FiTrash2 />
                      )}
                    </button>
                  </>
                ) : (
                  <span className="text-sm text-gray-600 px-3 py-1.5">
                    {DECK_PERMISSION_OPTIONS.find(o => o.value === contributor.permission_level)?.label}
                  </span>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="bg-gray-50 rounded-md p-4 border border-gray-200">
        <h4 className="text-sm font-medium text-gray-700 mb-2">Permission Levels</h4>
        <ul className="space-y-1">
          {DECK_PERMISSION_OPTIONS.map(opt => (
            <li key={opt.value} className="text-sm flex items-start gap-2">
              <span className="font-medium text-gray-600 w-24">{opt.label}:</span>
              <span className="text-gray-500">{opt.description}</span>
            </li>
          ))}
        </ul>
        <p className="text-xs text-gray-500 mt-3">
          Workspace sharing supports Can View or Can Edit only.
        </p>
      </div>
    </div>
  );
};

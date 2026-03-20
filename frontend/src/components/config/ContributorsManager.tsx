/**
 * Contributors management component for sharing profiles.
 * 
 * Allows adding, updating, and removing contributors (users/groups)
 * with different permission levels, and sharing with all workspace users.
 */

import React, { useState, useEffect, useCallback } from 'react';
import { FiSearch, FiUser, FiUsers, FiTrash2, FiUserPlus, FiGlobe } from 'react-icons/fi';
import {
  configApi,
  type Contributor,
  type ContributorCreate,
  type Identity,
  type PermissionLevel,
} from '../../api/config';

const PERMISSION_OPTIONS: { value: PermissionLevel; label: string; description: string }[] = [
  { value: 'CAN_VIEW', label: 'Can View', description: 'View profile and use for presentations' },
  { value: 'CAN_EDIT', label: 'Can Edit', description: 'Edit profile settings' },
  { value: 'CAN_MANAGE', label: 'Can Manage', description: 'Full control including sharing' },
];

interface ContributorsManagerProps {
  profileId: number;
  globalPermission?: PermissionLevel | null;
  canManage?: boolean;
  onGlobalPermissionChange?: (permission: PermissionLevel | null) => void;
}

export const ContributorsManager: React.FC<ContributorsManagerProps> = ({
  profileId,
  globalPermission: initialGlobalPermission,
  canManage = true,
  onGlobalPermissionChange,
}) => {
  const [contributors, setContributors] = useState<Contributor[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Global permission level (null = private)
  const [globalPermission, setGlobalPermission] = useState<PermissionLevel | null>(initialGlobalPermission ?? null);
  const [updatingGlobal, setUpdatingGlobal] = useState(false);

  useEffect(() => {
    if (initialGlobalPermission !== undefined) setGlobalPermission(initialGlobalPermission);
  }, [initialGlobalPermission]);

  const handleSetGlobalPermission = async (permission: PermissionLevel | null) => {
    setUpdatingGlobal(true);
    try {
      const result = await configApi.setProfileGlobal(profileId, permission);
      setGlobalPermission(result.global_permission);
      onGlobalPermissionChange?.(result.global_permission);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update global sharing');
    } finally {
      setUpdatingGlobal(false);
    }
  };

  // Search state
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<Identity[]>([]);
  const [searching, setSearching] = useState(false);
  const [selectedPermission, setSelectedPermission] = useState<PermissionLevel>('CAN_VIEW');

  // Operation states
  const [addingContributor, setAddingContributor] = useState(false);
  const [updatingId, setUpdatingId] = useState<number | null>(null);
  const [removingId, setRemovingId] = useState<number | null>(null);

  // Load contributors
  const loadContributors = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const response = await configApi.listContributors(profileId);
      setContributors(response.contributors);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load contributors');
    } finally {
      setLoading(false);
    }
  }, [profileId]);

  useEffect(() => {
    loadContributors();
  }, [loadContributors]);

  // Search identities with debounce
  const searchIdentities = useCallback(async (query: string) => {
    if (!query.trim() || query.length < 2) {
      setSearchResults([]);
      return;
    }
    setSearching(true);
    try {
      const response = await configApi.searchIdentities(query.trim());
      // Filter out already-added contributors
      const existingIds = new Set(contributors.map(c => c.identity_id));
      setSearchResults(response.identities.filter(i => !existingIds.has(i.id)));
    } catch (err) {
      console.error('Search failed:', err);
      setSearchResults([]);
    } finally {
      setSearching(false);
    }
  }, [contributors]);

  // Debounce search
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

  // Add contributor
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
      await configApi.addContributor(profileId, newContributor);
      setSearchQuery('');
      setSearchResults([]);
      await loadContributors();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to add contributor');
    } finally {
      setAddingContributor(false);
    }
  };

  // Update contributor permission
  const handleUpdatePermission = async (contributorId: number, permission: PermissionLevel) => {
    setUpdatingId(contributorId);
    try {
      await configApi.updateContributor(profileId, contributorId, { permission_level: permission });
      await loadContributors();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update permission');
    } finally {
      setUpdatingId(null);
    }
  };

  // Remove contributor
  const handleRemoveContributor = async (contributorId: number) => {
    setRemovingId(contributorId);
    try {
      await configApi.removeContributor(profileId, contributorId);
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

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h3 className="text-lg font-medium text-gray-900">Share Profile</h3>
        <p className="text-sm text-gray-500 mt-1">
          Add users or groups from your Databricks workspace who can access this profile.
        </p>
      </div>

      {/* Error display */}
      {error && (
        <div className="p-3 bg-red-50 border border-red-200 rounded-md text-red-700 text-sm flex items-center justify-between">
          <span>{error}</span>
          <button onClick={() => setError(null)} className="text-red-500 hover:text-red-700">
            ✕
          </button>
        </div>
      )}

      {/* Add contributor section */}
      <div className="bg-gray-50 rounded-lg p-4 border border-gray-200">
        <div className="flex items-center gap-2 mb-3">
          <FiUserPlus className="text-blue-500" />
          <span className="font-medium text-gray-700">Add Contributor</span>
        </div>

        <div className="flex gap-3">
          {/* Search input */}
          <div className="flex-1 relative">
            <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
              <FiSearch className="text-gray-400" />
            </div>
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search users or groups..."
              className="w-full pl-10 pr-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              disabled={addingContributor}
            />
            {searching && (
              <div className="absolute inset-y-0 right-0 pr-3 flex items-center">
                <div className="w-4 h-4 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
              </div>
            )}
          </div>

          {/* Permission selector */}
          <select
            value={selectedPermission}
            onChange={(e) => setSelectedPermission(e.target.value as PermissionLevel)}
            className="px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 bg-white"
            disabled={addingContributor}
          >
            {PERMISSION_OPTIONS.map(opt => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </div>

        {/* Search results dropdown */}
        {(searchResults.length > 0 || (searchQuery.length >= 1 && !globalPermission && canManage)) && (
          <div className="mt-2 border border-gray-200 rounded-md shadow-sm max-h-48 overflow-y-auto bg-white">
            {/* "All workspace users" suggestion when not already global */}
            {!globalPermission && canManage && 'all workspace'.includes(searchQuery.toLowerCase()) && (
              <button
                onClick={() => handleSetGlobalPermission(selectedPermission)}
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

        {/* No results */}
        {searchQuery.length >= 2 && !searching && searchResults.length === 0 && (
          <p className="mt-2 text-sm text-gray-500 text-center py-2">
            No users or groups found matching "{searchQuery}"
          </p>
        )}
      </div>

      {/* Contributors list */}
      <div>
        <h4 className="text-sm font-medium text-gray-700 mb-3">
          Current Access ({contributors.length + (globalPermission ? 1 : 0)})
        </h4>

        {contributors.length === 0 && !globalPermission ? (
          <div className="bg-blue-50 border border-blue-200 rounded-md p-4 text-center">
            <FiUsers className="mx-auto text-blue-400 mb-2" size={24} />
            <p className="text-sm text-blue-700">
              No contributors yet. This profile is private to you.
            </p>
            <p className="text-xs text-blue-600 mt-1">
              Search above to add users, groups, or "All workspace users".
            </p>
          </div>
        ) : (
          <div className="space-y-2">
            {/* All workspace users row */}
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
                      onChange={(e) => handleSetGlobalPermission(e.target.value as PermissionLevel)}
                      disabled={updatingGlobal}
                      className="text-sm px-3 py-1.5 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 bg-white disabled:opacity-50"
                    >
                      {PERMISSION_OPTIONS.map(opt => (
                        <option key={opt.value} value={opt.value}>{opt.label}</option>
                      ))}
                    </select>
                    <button
                      onClick={() => handleSetGlobalPermission(null)}
                      disabled={updatingGlobal}
                      className="p-2 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded transition-colors disabled:opacity-50"
                      title="Remove global access"
                    >
                      <FiTrash2 />
                    </button>
                  </>
                ) : (
                  <span className="text-sm text-gray-600 px-3 py-1.5">
                    {PERMISSION_OPTIONS.find(o => o.value === globalPermission)?.label}
                  </span>
                )}
              </div>
            )}
            {contributors.map(contributor => (
              <div
                key={contributor.id}
                className="flex items-center gap-3 p-3 bg-white rounded-md border border-gray-200 hover:border-gray-300 transition-colors"
              >
                {/* Identity icon */}
                {contributor.identity_type === 'USER' ? (
                  <div className="w-10 h-10 rounded-full bg-blue-100 flex items-center justify-center">
                    <FiUser className="text-blue-600" />
                  </div>
                ) : (
                  <div className="w-10 h-10 rounded-full bg-purple-100 flex items-center justify-center">
                    <FiUsers className="text-purple-600" />
                  </div>
                )}

                {/* Identity info */}
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

                {/* Permission selector */}
                <select
                  value={contributor.permission_level}
                  onChange={(e) => handleUpdatePermission(contributor.id, e.target.value as PermissionLevel)}
                  disabled={updatingId === contributor.id || removingId === contributor.id}
                  className="text-sm px-3 py-1.5 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 bg-white disabled:opacity-50"
                >
                  {PERMISSION_OPTIONS.map(opt => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>

                {/* Remove button */}
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
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Permission levels explanation */}
      <div className="bg-gray-50 rounded-md p-4 border border-gray-200">
        <h4 className="text-sm font-medium text-gray-700 mb-2">Permission Levels</h4>
        <ul className="space-y-1">
          {PERMISSION_OPTIONS.map(opt => (
            <li key={opt.value} className="text-sm flex items-start gap-2">
              <span className="font-medium text-gray-600 w-24">{opt.label}:</span>
              <span className="text-gray-500">{opt.description}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
};


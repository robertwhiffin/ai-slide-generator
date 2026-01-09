/**
 * Profile management component.
 * 
 * Displays all profiles in a list with actions:
 * - View and edit profile configuration
 * - Delete profile
 * - Duplicate profile
 * - Set as default
 * - Load profile (hot-reload)
 */

import React, { useState, useEffect } from 'react';
import type { Profile, ProfileCreate, ProfileUpdate } from '../../api/config';
import { useProfiles } from '../../hooks/useProfiles';
import { ProfileForm } from './ProfileForm';
import { ProfileCreationWizard } from './ProfileCreationWizard';
import { ConfirmDialog } from './ConfirmDialog';
import { ProfileDetailView } from './ProfileDetail';

interface ProfileListProps {
  onProfileChange?: () => void;
}

export const ProfileList: React.FC<ProfileListProps> = ({ onProfileChange }) => {
  const {
    profiles,
    currentProfile,
    loading,
    error,
    deleteProfile,
    duplicateProfile,
    setDefaultProfile,
    loadProfile,
  } = useProfiles();

  const [formMode, setFormMode] = useState<'create' | 'edit' | null>(null);
  const [editingProfile, setEditingProfile] = useState<Profile | null>(null);
  const [showCreationWizard, setShowCreationWizard] = useState(false);
  const [currentUsername, setCurrentUsername] = useState('user');
  const [confirmDialog, setConfirmDialog] = useState<{
    isOpen: boolean;
    title: string;
    message: string;
    error?: string | null;
    loading?: boolean;
    onConfirm: () => void;
  }>({
    isOpen: false,
    title: '',
    message: '',
    error: null,
    loading: false,
    onConfirm: () => {},
  });
  const [actionLoading, setActionLoading] = useState<number | null>(null);
  const [duplicateName, setDuplicateName] = useState('');
  const [showDuplicateInput, setShowDuplicateInput] = useState<number | null>(null);
  const [duplicateError, setDuplicateError] = useState<string | null>(null);
  const [viewingProfileId, setViewingProfileId] = useState<number | null>(null);
  const [viewingProfileMode, setViewingProfileMode] = useState<'view' | 'edit'>('view');

  // Fetch current username from Databricks on mount
  useEffect(() => {
    const fetchUsername = async () => {
      try {
        // Use environment-aware URL
        const apiBase = import.meta.env.VITE_API_URL || (
          import.meta.env.MODE === 'production' ? '' : 'http://localhost:8000'
        );
        const response = await fetch(`${apiBase}/api/user/current`);
        if (response.ok) {
          const data = await response.json();
          setCurrentUsername(data.username || 'user');
        }
      } catch {
        // Use default if fetch fails
        setCurrentUsername('user');
      }
    };
    fetchUsername();
  }, []);

  // Handle create profile - show wizard
  const handleCreate = () => {
    setShowCreationWizard(true);
  };

  // Handle wizard success
  const handleWizardSuccess = async (profileId: number) => {
    setShowCreationWizard(false);
    // Load the new profile (default is only set automatically for the first profile by the backend)
    try {
      await loadProfile(profileId);
      if (onProfileChange) {
        onProfileChange();
      }
    } catch (err) {
      console.error('Failed to load new profile:', err);
    }
  };

  // Handle form submit (edit mode only - create uses wizard)
  const handleFormSubmit = async (_data: ProfileCreate | ProfileUpdate) => {
    // This is only used for editing, which is now handled in ProfileDetailView
    setFormMode(null);
    setEditingProfile(null);
  };

  // Handle delete with confirmation
  const handleDelete = (profile: Profile) => {
    setConfirmDialog({
      isOpen: true,
      title: 'Delete Profile',
      message: `Are you sure you want to delete the profile "${profile.name}"?\n\nThis action cannot be undone and will delete all associated configurations.`,
      error: null,
      loading: false,
      onConfirm: async () => {
        setConfirmDialog(prev => ({ ...prev, loading: true, error: null }));
        setActionLoading(profile.id);
        try {
          await deleteProfile(profile.id);
          setConfirmDialog(prev => ({ ...prev, isOpen: false, loading: false }));
        } catch (err) {
          const message = err instanceof Error ? err.message : 'Failed to delete profile';
          setConfirmDialog(prev => ({ ...prev, error: message, loading: false }));
        } finally {
          setActionLoading(null);
        }
      },
    });
  };

  // Handle set default with confirmation
  const handleSetDefault = (profile: Profile) => {
    setConfirmDialog({
      isOpen: true,
      title: 'Set Default Profile',
      message: `Set "${profile.name}" as the default profile?\n\nThe default profile is loaded when the application starts.`,
      error: null,
      loading: false,
      onConfirm: async () => {
        setConfirmDialog(prev => ({ ...prev, loading: true, error: null }));
        setActionLoading(profile.id);
        try {
          await setDefaultProfile(profile.id);
          setConfirmDialog(prev => ({ ...prev, isOpen: false, loading: false }));
        } catch (err) {
          const message = err instanceof Error ? err.message : 'Failed to set default profile';
          setConfirmDialog(prev => ({ ...prev, error: message, loading: false }));
        } finally {
          setActionLoading(null);
        }
      },
    });
  };

  // Handle load profile with confirmation
  const handleLoadProfile = (profile: Profile) => {
    setConfirmDialog({
      isOpen: true,
      title: 'Load Profile',
      message: `Load "${profile.name}" and hot-reload the application configuration?\n\nCurrent sessions will be preserved.`,
      error: null,
      loading: false,
      onConfirm: async () => {
        setConfirmDialog(prev => ({ ...prev, loading: true, error: null }));
        setActionLoading(profile.id);
        try {
          await loadProfile(profile.id);
          // Notify parent to reset chat state
          if (onProfileChange) {
            onProfileChange();
          }
          setConfirmDialog(prev => ({ ...prev, isOpen: false, loading: false }));
        } catch (err) {
          const message = err instanceof Error ? err.message : 'Failed to load profile';
          setConfirmDialog(prev => ({ ...prev, error: message, loading: false }));
        } finally {
          setActionLoading(null);
        }
      },
    });
  };

  // Handle duplicate
  const handleDuplicateClick = (profile: Profile) => {
    setDuplicateName(`${profile.name} (Copy)`);
    setShowDuplicateInput(profile.id);
    setDuplicateError(null);
  };

  const handleDuplicateCancel = () => {
    setShowDuplicateInput(null);
    setDuplicateName('');
    setDuplicateError(null);
  };

  const handleDuplicateSubmit = async (profileId: number) => {
    const trimmedName = duplicateName.trim();
    if (!trimmedName) return;
    
    // Client-side check for duplicate name
    const nameExists = profiles.some(p => p.name.toLowerCase() === trimmedName.toLowerCase());
    if (nameExists) {
      setDuplicateError(`A profile named "${trimmedName}" already exists. Please choose a different name.`);
      return;
    }
    
    setDuplicateError(null);
    setActionLoading(profileId);
    try {
      await duplicateProfile(profileId, trimmedName);
      setShowDuplicateInput(null);
      setDuplicateName('');
    } catch (err) {
      // Show error inline instead of letting it propagate
      const message = err instanceof Error ? err.message : 'Failed to duplicate profile';
      setDuplicateError(message);
    } finally {
      setActionLoading(null);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-gray-600">Loading profiles...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4 bg-red-50 border border-red-200 rounded text-red-700">
        Error: {error}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex justify-between items-center">
        <div>
          <h2 className="text-2xl font-semibold text-gray-900">Configuration Profiles</h2>
          <p className="text-sm text-gray-600 mt-1">
            Manage your configuration profiles. Load different profiles to switch settings without restarting.
          </p>
        </div>
        <button
          onClick={handleCreate}
          className="px-4 py-2 bg-blue-500 hover:bg-blue-600 text-white rounded transition-colors"
        >
          + Create Profile
        </button>
      </div>

      {/* Current Profile Badge */}
      {currentProfile && (
        <div className="p-3 bg-blue-50 border border-blue-200 rounded">
          <span className="text-sm text-blue-700">
            <strong>Currently Loaded:</strong> {currentProfile.name}
            {currentProfile.is_default && ' (Default)'}
          </span>
        </div>
      )}

      {/* Profiles Table */}
      <div className="border rounded-lg overflow-hidden">
        <table className="w-full">
          <thead className="bg-gray-50 border-b">
            <tr>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Name
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Description
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Status
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Actions
              </th>
            </tr>
          </thead>
          <tbody className="bg-white divide-y divide-gray-200">
            {profiles.map((profile) => (
              <React.Fragment key={profile.id}>
                <tr className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-sm font-medium text-gray-900">
                    {profile.name}
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-600">
                    {profile.description || <span className="italic text-gray-400">No description</span>}
                  </td>
                  <td className="px-4 py-3 text-sm">
                    <div className="flex gap-2">
                      {profile.is_default && (
                        <span className="px-2 py-1 bg-blue-100 text-blue-700 text-xs rounded">
                          Default
                        </span>
                      )}
                      {currentProfile?.id === profile.id && (
                        <span className="px-2 py-1 bg-green-100 text-green-700 text-xs rounded">
                          Loaded
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-sm">
                    <div className="flex gap-2">
                      {/* View and Edit Button */}
                      <button
                        onClick={() => {
                          setViewingProfileId(profile.id);
                          setViewingProfileMode('view');
                        }}
                        disabled={actionLoading === profile.id}
                        className="px-3 py-1 bg-indigo-500 hover:bg-indigo-600 text-white text-xs rounded transition-colors disabled:bg-gray-300"
                        title="View and edit configuration"
                      >
                        View and Edit
                      </button>

                      {/* Load Button */}
                      {currentProfile?.id !== profile.id && (
                        <button
                          onClick={() => handleLoadProfile(profile)}
                          disabled={actionLoading === profile.id}
                          className="px-3 py-1 bg-green-500 hover:bg-green-600 text-white text-xs rounded transition-colors disabled:bg-gray-300"
                          title="Load this profile"
                        >
                          Load
                        </button>
                      )}

                      {/* Set Default Button */}
                      {!profile.is_default && (
                        <button
                          onClick={() => handleSetDefault(profile)}
                          disabled={actionLoading === profile.id}
                          className="px-3 py-1 bg-blue-500 hover:bg-blue-600 text-white text-xs rounded transition-colors disabled:bg-gray-300"
                          title="Set as default"
                        >
                          Set Default
                        </button>
                      )}

                      {/* Duplicate Button */}
                      <button
                        onClick={() => handleDuplicateClick(profile)}
                        disabled={actionLoading === profile.id}
                        className="px-3 py-1 bg-purple-500 hover:bg-purple-600 text-white text-xs rounded transition-colors disabled:bg-gray-300"
                        title="Duplicate profile"
                      >
                        Duplicate
                      </button>

                      {/* Delete Button */}
                      {profiles.length > 1 && (
                        <button
                          onClick={() => handleDelete(profile)}
                          disabled={actionLoading === profile.id}
                          className="px-3 py-1 bg-red-500 hover:bg-red-600 text-white text-xs rounded transition-colors disabled:bg-gray-300"
                          title="Delete profile"
                        >
                          Delete
                        </button>
                      )}
                    </div>
                  </td>
                </tr>

                {/* Duplicate Input Row */}
                {showDuplicateInput === profile.id && (
                  <tr>
                    <td colSpan={4} className="px-4 py-3 bg-gray-50">
                      <div className="space-y-2">
                        <div className="flex items-center gap-3">
                          <label className="text-sm text-gray-700 font-medium">
                            New name:
                          </label>
                          <input
                            type="text"
                            value={duplicateName}
                            onChange={(e) => {
                              setDuplicateName(e.target.value);
                              setDuplicateError(null); // Clear error when user types
                            }}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter' && duplicateName.trim()) {
                                handleDuplicateSubmit(profile.id);
                              } else if (e.key === 'Escape') {
                                handleDuplicateCancel();
                              }
                            }}
                            className={`flex-1 px-3 py-1 border rounded text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 ${
                              duplicateError ? 'border-red-400 bg-red-50' : 'border-gray-300'
                            }`}
                            placeholder="Enter new profile name"
                            maxLength={100}
                            autoFocus
                          />
                          <button
                            onClick={() => handleDuplicateSubmit(profile.id)}
                            disabled={!duplicateName.trim() || actionLoading === profile.id}
                            className="px-3 py-1 bg-green-500 hover:bg-green-600 text-white text-sm rounded transition-colors disabled:bg-gray-300"
                          >
                            {actionLoading === profile.id ? 'Creating...' : 'Create'}
                          </button>
                          <button
                            onClick={handleDuplicateCancel}
                            className="px-3 py-1 bg-gray-300 hover:bg-gray-400 text-gray-800 text-sm rounded transition-colors"
                          >
                            Cancel
                          </button>
                        </div>
                        {/* Error Message */}
                        {duplicateError && (
                          <div className="flex items-center gap-2 px-3 py-2 bg-red-50 border border-red-200 rounded text-sm text-red-700">
                            <svg className="w-4 h-4 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                              <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
                            </svg>
                            <span>{duplicateError}</span>
                          </div>
                        )}
                      </div>
                    </td>
                  </tr>
                )}
              </React.Fragment>
            ))}
          </tbody>
        </table>

        {profiles.length === 0 && (
          <div className="p-8 text-center text-gray-500">
            No profiles found. Create your first profile to get started.
          </div>
        )}
      </div>

      {/* Profile Creation Wizard */}
      <ProfileCreationWizard
        isOpen={showCreationWizard}
        onClose={() => setShowCreationWizard(false)}
        onSuccess={handleWizardSuccess}
        currentUsername={currentUsername}
      />

      {/* Profile Form Modal (for editing only) */}
      <ProfileForm
        isOpen={formMode === 'edit'}
        mode="edit"
        profile={editingProfile || undefined}
        onSubmit={handleFormSubmit}
        onCancel={() => {
          setFormMode(null);
          setEditingProfile(null);
        }}
      />

      {/* Confirmation Dialog */}
      <ConfirmDialog
        isOpen={confirmDialog.isOpen}
        title={confirmDialog.title}
        message={confirmDialog.message}
        error={confirmDialog.error}
        loading={confirmDialog.loading}
        onConfirm={confirmDialog.onConfirm}
        onCancel={() => setConfirmDialog({ ...confirmDialog, isOpen: false, error: null })}
      />

      {/* Profile Detail View */}
      {viewingProfileId !== null && (
        <ProfileDetailView
          profileId={viewingProfileId}
          onClose={() => {
            setViewingProfileId(null);
            setViewingProfileMode('view');
          }}
          initialMode={viewingProfileMode}
        />
      )}
    </div>
  );
};


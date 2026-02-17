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
import { User, ChevronDown, Trash2, Plus, Copy, Play, Star } from 'lucide-react';
import { Button } from '@/ui/button';
import { Badge } from '@/ui/badge';
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

  const [expandedId, setExpandedId] = useState<number | null>(null);

  const toggleExpand = (id: number) => {
    setExpandedId(expandedId === id ? null : id);
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-muted-foreground">Loading profiles...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4 bg-destructive/10 border border-destructive rounded-lg text-destructive">
        Error: {error}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-bold text-foreground">Agent Profiles</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Manage your configuration profiles. Load different profiles to switch settings without restarting.
          </p>
        </div>
        <Button size="sm" onClick={handleCreate} className="gap-1.5">
          <Plus className="size-3.5" />
          New Agent
        </Button>
      </div>

      {/* Current Profile Badge */}
      {currentProfile && (
        <div className="rounded-lg border border-primary/30 bg-primary/5 px-4 py-3">
          <span className="text-sm text-primary">
            <strong>Currently Loaded:</strong> {currentProfile.name}
            {currentProfile.is_default && ' (Default)'}
          </span>
        </div>
      )}

      {/* Profile Cards */}
      {profiles.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-border bg-muted/20 p-12 text-center">
          <User className="mb-3 size-12 text-muted-foreground/50" />
          <p className="text-sm text-muted-foreground">
            No profiles found. Create your first profile to get started.
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {profiles.map((profile) => (
            <div
              key={profile.id}
              className="rounded-lg border border-border bg-card transition-colors hover:bg-accent/5"
            >
              {/* Profile Header */}
              <div className="flex items-start gap-4 p-4">
                {/* Icon */}
                <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  <User className="size-5" />
                </div>

                {/* Content */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <h3 className="text-sm font-medium text-foreground">
                          {profile.name}
                        </h3>
                        {profile.is_default && (
                          <Badge variant="secondary" className="text-xs">
                            Default
                          </Badge>
                        )}
                        {currentProfile?.id === profile.id && (
                          <Badge className="text-xs bg-green-500/10 text-green-700 hover:bg-green-500/20">
                            Loaded
                          </Badge>
                        )}
                      </div>
                      <p className="mt-0.5 text-sm text-muted-foreground">
                        {profile.description || 'No description'}
                      </p>
                    </div>

                    {/* Actions */}
                    <div className="flex shrink-0 items-center gap-1">
                      <Button
                        variant="ghost"
                        size="sm"
                        className="size-8 p-0"
                        onClick={() => toggleExpand(profile.id)}
                      >
                        <ChevronDown
                          className={`size-4 text-muted-foreground transition-transform ${
                            expandedId === profile.id ? "rotate-180" : ""
                          }`}
                        />
                      </Button>
                      {profiles.length > 1 && (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="size-8 p-0 text-muted-foreground hover:text-destructive"
                          onClick={() => handleDelete(profile)}
                          disabled={actionLoading === profile.id}
                        >
                          <Trash2 className="size-4" />
                        </Button>
                      )}
                    </div>
                  </div>

                  {/* Expanded Details */}
                  {expandedId === profile.id && (
                    <div className="mt-3 space-y-3">
                      {/* Duplicate Input (when active) */}
                      {showDuplicateInput === profile.id && (
                        <div className="rounded-md border border-border bg-muted/30 p-3 space-y-2">
                          <div className="flex items-center gap-2">
                            <input
                              type="text"
                              value={duplicateName}
                              onChange={(e) => {
                                setDuplicateName(e.target.value);
                                setDuplicateError(null);
                              }}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter' && duplicateName.trim()) {
                                  handleDuplicateSubmit(profile.id);
                                } else if (e.key === 'Escape') {
                                  handleDuplicateCancel();
                                }
                              }}
                              className={`flex-1 rounded-md border px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary ${
                                duplicateError ? 'border-destructive bg-destructive/5' : 'border-input bg-background'
                              }`}
                              placeholder="Enter new profile name"
                              maxLength={100}
                              autoFocus
                            />
                            <Button
                              size="sm"
                              onClick={() => handleDuplicateSubmit(profile.id)}
                              disabled={!duplicateName.trim() || actionLoading === profile.id}
                            >
                              {actionLoading === profile.id ? 'Creating...' : 'Create'}
                            </Button>
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={handleDuplicateCancel}
                            >
                              Cancel
                            </Button>
                          </div>
                          {duplicateError && (
                            <div className="flex items-center gap-2 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
                              <span>{duplicateError}</span>
                            </div>
                          )}
                        </div>
                      )}

                      {/* Action Buttons */}
                      {showDuplicateInput !== profile.id && (
                        <div className="flex flex-wrap gap-2">
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => {
                              setViewingProfileId(profile.id);
                              setViewingProfileMode('view');
                            }}
                            disabled={actionLoading === profile.id}
                          >
                            View and Edit
                          </Button>

                          {currentProfile?.id !== profile.id && (
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => handleLoadProfile(profile)}
                              disabled={actionLoading === profile.id}
                              className="gap-1.5"
                            >
                              <Play className="size-3.5" />
                              Load
                            </Button>
                          )}

                          {!profile.is_default && (
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => handleSetDefault(profile)}
                              disabled={actionLoading === profile.id}
                              className="gap-1.5"
                            >
                              <Star className="size-3.5" />
                              Set as Default
                            </Button>
                          )}

                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => handleDuplicateClick(profile)}
                            disabled={actionLoading === profile.id}
                            className="gap-1.5"
                          >
                            <Copy className="size-3.5" />
                            Duplicate
                          </Button>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

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


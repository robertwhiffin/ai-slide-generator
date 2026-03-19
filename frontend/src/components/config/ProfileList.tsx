/**
 * Saved Configurations management component.
 *
 * Displays all profiles in a list with actions:
 * - Rename profile
 * - Delete profile
 * - Set as default
 * - Load profile (hot-reload)
 */

import React, { useState } from 'react';
import { User, ChevronDown, Trash2, Play, Star, Pencil } from 'lucide-react';
import { Button } from '@/ui/button';
import { Badge } from '@/ui/badge';
import type { Profile } from '../../api/config';
import { useProfiles } from '../../hooks/useProfiles';
import { ConfirmDialog } from './ConfirmDialog';

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
    setDefaultProfile,
    loadProfile,
    updateProfile,
  } = useProfiles();

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
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [renamingId, setRenamingId] = useState<number | null>(null);
  const [renameValue, setRenameValue] = useState('');
  const [renameError, setRenameError] = useState<string | null>(null);

  const toggleExpand = (id: number) => {
    setExpandedId(expandedId === id ? null : id);
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

  // Handle rename
  const handleRenameClick = (profile: Profile) => {
    setRenamingId(profile.id);
    setRenameValue(profile.name);
    setRenameError(null);
  };

  const handleRenameCancel = () => {
    setRenamingId(null);
    setRenameValue('');
    setRenameError(null);
  };

  const handleRenameSubmit = async (profileId: number) => {
    const trimmedName = renameValue.trim();
    if (!trimmedName) return;

    const nameExists = profiles.some(
      p => p.id !== profileId && p.name.toLowerCase() === trimmedName.toLowerCase()
    );
    if (nameExists) {
      setRenameError(`A profile named "${trimmedName}" already exists.`);
      return;
    }

    setRenameError(null);
    setActionLoading(profileId);
    try {
      await updateProfile(profileId, { name: trimmedName });
      setRenamingId(null);
      setRenameValue('');
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to rename profile';
      setRenameError(message);
    } finally {
      setActionLoading(null);
    }
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
            Manage your saved configuration profiles. Load different profiles to switch settings without restarting.
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            To create a new profile, use "Save as Profile" from the generator.
          </p>
        </div>
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
            No saved configurations found. Use "Save as Profile" from the generator to create one.
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {profiles.map((profile) => (
            <div
              key={profile.id}
              data-testid="profile-card"
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
                        aria-label="Expand"
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
                          aria-label="Delete"
                        >
                          <Trash2 className="size-4" />
                        </Button>
                      )}
                    </div>
                  </div>

                  {/* Expanded Details */}
                  {expandedId === profile.id && (
                    <div className="mt-3 space-y-3">
                      {/* Rename Input (when active) */}
                      {renamingId === profile.id && (
                        <div className="rounded-md border border-border bg-muted/30 p-3 space-y-2">
                          <div className="flex items-center gap-2">
                            <input
                              type="text"
                              value={renameValue}
                              onChange={(e) => {
                                setRenameValue(e.target.value);
                                setRenameError(null);
                              }}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter' && renameValue.trim()) {
                                  handleRenameSubmit(profile.id);
                                } else if (e.key === 'Escape') {
                                  handleRenameCancel();
                                }
                              }}
                              className={`flex-1 rounded-md border px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary ${
                                renameError ? 'border-destructive bg-destructive/5' : 'border-input bg-background'
                              }`}
                              placeholder="Enter new name"
                              maxLength={100}
                              autoFocus
                            />
                            <Button
                              size="sm"
                              onClick={() => handleRenameSubmit(profile.id)}
                              disabled={!renameValue.trim() || actionLoading === profile.id}
                            >
                              {actionLoading === profile.id ? 'Saving...' : 'Save'}
                            </Button>
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={handleRenameCancel}
                            >
                              Cancel
                            </Button>
                          </div>
                          {renameError && (
                            <div className="flex items-center gap-2 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
                              <span>{renameError}</span>
                            </div>
                          )}
                        </div>
                      )}

                      {/* Action Buttons */}
                      {renamingId !== profile.id && (
                        <div className="flex flex-wrap gap-2">
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => handleRenameClick(profile)}
                            disabled={actionLoading === profile.id}
                            className="gap-1.5"
                          >
                            <Pencil className="size-3.5" />
                            Rename
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
    </div>
  );
};

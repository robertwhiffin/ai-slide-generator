/**
 * Saved Configurations management component.
 *
 * Displays all profiles in a list with actions:
 * - Rename profile
 * - Delete profile
 */

import React, { useEffect, useState } from 'react';
import { User, ChevronDown, Trash2, Pencil, Share2, MessageSquare, Palette, FileText, Wrench } from 'lucide-react';
import { Button } from '@/ui/button';
import { Badge } from '@/ui/badge';
import type { Profile } from '../../api/config';
import { configApi } from '../../api/config';
import { useProfiles } from '../../hooks/useProfiles';
import { ConfirmDialog } from './ConfirmDialog';
import { ContributorsManager } from './ContributorsManager';

interface ToolEntry {
  type: 'genie' | 'mcp';
  space_id?: string;
  space_name?: string;
  description?: string;
  server_uri?: string;
  server_name?: string;
}

interface AgentConfigShape {
  tools?: ToolEntry[];
  slide_style_id?: number | null;
  deck_prompt_id?: number | null;
  system_prompt?: string | null;
  slide_editing_instructions?: string | null;
}

interface NameLookups {
  slideStyles: Map<number, string>;
  deckPrompts: Map<number, string>;
}

const ConfigSummary: React.FC<{ config: Record<string, unknown> | null; names: NameLookups }> = ({ config, names }) => {
  if (!config || Object.keys(config).length === 0) {
    return (
      <div className="rounded-md border border-border bg-muted/20 px-3 py-2 text-sm text-muted-foreground">
        No configuration saved
      </div>
    );
  }

  const cfg = config as unknown as AgentConfigShape;
  const tools = cfg.tools ?? [];
  const genieTools = tools.filter(t => t.type === 'genie');
  const mcpTools = tools.filter(t => t.type === 'mcp');
  const hasCustomSystemPrompt = !!cfg.system_prompt;
  const hasCustomSlideInstructions = !!cfg.slide_editing_instructions;

  const styleName = cfg.slide_style_id != null
    ? names.slideStyles.get(cfg.slide_style_id) ?? `Unknown (ID ${cfg.slide_style_id})`
    : null;
  const promptName = cfg.deck_prompt_id != null
    ? names.deckPrompts.get(cfg.deck_prompt_id) ?? `Unknown (ID ${cfg.deck_prompt_id})`
    : null;

  return (
    <div className="grid gap-2 rounded-md border border-border bg-muted/20 p-3 text-sm">
      {/* Tools */}
      <div className="flex items-start gap-2">
        <Wrench className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
        <div className="min-w-0">
          <span className="font-medium text-foreground">Tools</span>
          {tools.length === 0 ? (
            <span className="ml-2 text-muted-foreground">None configured</span>
          ) : (
            <div className="mt-1 flex flex-wrap gap-1.5">
              {genieTools.map(t => (
                <Badge key={t.space_id} variant="outline" className="text-xs font-normal gap-1">
                  <MessageSquare className="size-3" />
                  {t.space_name}
                </Badge>
              ))}
              {mcpTools.map(t => (
                <Badge key={t.server_uri} variant="outline" className="text-xs font-normal gap-1">
                  <Wrench className="size-3" />
                  {t.server_name}
                </Badge>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Style & Prompt selections */}
      <div className="flex items-start gap-2">
        <Palette className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
        <div>
          <span className="font-medium text-foreground">Slide Style</span>
          <span className="ml-2 text-muted-foreground">
            {styleName ?? 'Default'}
          </span>
        </div>
      </div>

      <div className="flex items-start gap-2">
        <FileText className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
        <div>
          <span className="font-medium text-foreground">Deck Prompt</span>
          <span className="ml-2 text-muted-foreground">
            {promptName ?? 'Default'}
          </span>
        </div>
      </div>

      {/* Custom prompts indicator */}
      {(hasCustomSystemPrompt || hasCustomSlideInstructions) && (
        <div className="flex items-start gap-2">
          <MessageSquare className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
          <div className="flex flex-wrap gap-1.5">
            {hasCustomSystemPrompt && (
              <Badge variant="secondary" className="text-xs font-normal">Custom system prompt</Badge>
            )}
            {hasCustomSlideInstructions && (
              <Badge variant="secondary" className="text-xs font-normal">Custom slide instructions</Badge>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export const ProfileList: React.FC = () => {
  const {
    profiles,
    loading,
    error,
    deleteProfile,
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
  const [sharingProfileId, setSharingProfileId] = useState<number | null>(null);
  const [userDefaultProfileId, setUserDefaultProfileId] = useState<number | null>(() => {
    const stored = localStorage.getItem('userDefaultProfileId');
    return stored ? Number(stored) : null;
  });
  const [nameLookups, setNameLookups] = useState<NameLookups>({
    slideStyles: new Map(),
    deckPrompts: new Map(),
  });

  useEffect(() => {
    let cancelled = false;
    async function fetchLookups() {
      try {
        const [stylesRes, promptsRes] = await Promise.all([
          configApi.listSlideStyles(),
          configApi.listDeckPrompts(),
        ]);
        if (cancelled) return;
        setNameLookups({
          slideStyles: new Map(stylesRes.styles.map(s => [s.id, s.name])),
          deckPrompts: new Map(promptsRes.prompts.map(p => [p.id, p.name])),
        });
      } catch {
        // Non-critical — falls back to "Unknown (ID X)"
      }
    }
    fetchLookups();
    return () => { cancelled = true; };
  }, []);
  // Stale default cleanup: if stored default profile no longer exists, clear it
  useEffect(() => {
    if (!loading && userDefaultProfileId != null) {
      const exists = profiles.some(p => p.id === userDefaultProfileId);
      if (!exists) {
        localStorage.removeItem('userDefaultProfileId');
        setUserDefaultProfileId(null);
      }
    }
  }, [profiles, loading, userDefaultProfileId]);

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
          // Clear localStorage default if the deleted profile was the default
          if (userDefaultProfileId === profile.id) {
            localStorage.removeItem('userDefaultProfileId');
            setUserDefaultProfileId(null);
          }
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
            Manage your saved configuration profiles. Use "Save as Profile" from the generator to create new ones.
          </p>
        </div>
      </div>

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
                        {(userDefaultProfileId != null ? profile.id === userDefaultProfileId : profile.is_my_default) && (
                          <Badge className="text-xs bg-amber-500/10 text-amber-700 hover:bg-amber-500/20">
                            Default
                          </Badge>
                        )}
                      </div>
                      <p className="mt-0.5 text-sm text-muted-foreground">
                        {profile.description || 'No description'}
                      </p>
                    </div>

                    {/* Actions */}
                    <div className="flex shrink-0 items-center gap-1">
                      {!(userDefaultProfileId != null ? profile.id === userDefaultProfileId : profile.is_my_default) && (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-8 px-2 text-xs text-muted-foreground"
                          onClick={() => {
                            localStorage.setItem('userDefaultProfileId', String(profile.id));
                            setUserDefaultProfileId(profile.id);
                          }}
                          aria-label="Set as default"
                        >
                          Set as default
                        </Button>
                      )}
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
                      {profiles.length > 1 && (!profile.my_permission || profile.my_permission === 'CAN_MANAGE') && (
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
                      {/* Config Summary */}
                      <ConfigSummary config={profile.agent_config} names={nameLookups} />

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
                          {(!profile.my_permission || profile.my_permission === 'CAN_EDIT' || profile.my_permission === 'CAN_MANAGE') && (
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
                          )}
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => setSharingProfileId(profile.id)}
                            className="gap-1.5"
                          >
                            <Share2 className="size-3.5" />
                            Share
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

      {/* Share Profile Dialog */}
      {sharingProfileId != null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="w-full max-w-lg mx-4 rounded-lg border border-border bg-card shadow-lg max-h-[80vh] flex flex-col">
            <div className="flex items-center justify-between border-b border-border px-6 py-4">
              <h2 className="text-lg font-semibold text-foreground">
                Share Profile
              </h2>
              <button
                onClick={() => setSharingProfileId(null)}
                className="text-muted-foreground hover:text-foreground transition-colors"
              >
                ✕
              </button>
            </div>
            <div className="flex-1 overflow-y-auto px-6 py-4">
              <ContributorsManager
                profileId={sharingProfileId}
                globalPermission={profiles.find(p => p.id === sharingProfileId)?.global_permission}
                canManage={
                  (() => {
                    const prof = profiles.find(p => p.id === sharingProfileId);
                    return !prof?.my_permission || prof.my_permission === 'CAN_MANAGE';
                  })()
                }
              />
            </div>
          </div>
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

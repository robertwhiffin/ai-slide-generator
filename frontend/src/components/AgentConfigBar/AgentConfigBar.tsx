/**
 * AgentConfigBar — inline agent configuration panel shown above the chat input.
 *
 * Renders:
 *  - Active tools as removable chips
 *  - "Add Tool" button that opens ToolPicker
 *  - Style selector dropdown
 *  - Deck prompt selector dropdown
 *  - "Save as Profile" / "Load Profile" actions
 */

import React, { useState, useEffect, useCallback } from 'react';
import { Plus, X, Save, FolderOpen, Loader2, ChevronDown, ChevronUp } from 'lucide-react';
import { useAgentConfig } from '../../contexts/AgentConfigContext';
import { useToast } from '../../contexts/ToastContext';
import { configApi } from '../../api/config';
import type { SlideStyle, DeckPrompt } from '../../api/config';
import type { ProfileSummary, ToolEntry } from '../../types/agentConfig';
import { api } from '../../services/api';
import { ToolPicker } from './ToolPicker';

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

/** Removable chip for an active tool. */
const ToolChip: React.FC<{ tool: ToolEntry; onRemove: () => void }> = ({ tool, onRemove }) => {
  const label = tool.type === 'genie'
    ? tool.space_name
    : tool.server_name;

  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-800">
      <span className="uppercase text-[10px] opacity-60 mr-0.5">{tool.type}</span>
      {label}
      <button
        onClick={onRemove}
        className="ml-0.5 p-0.5 rounded-full hover:bg-blue-200 transition-colors"
        aria-label={`Remove ${label}`}
      >
        <X size={12} />
      </button>
    </span>
  );
};

/** Simple dialog for entering a profile name when saving. */
const SaveProfileDialog: React.FC<{
  isOpen: boolean;
  onClose: () => void;
  onSave: (name: string, description?: string) => void;
  saving: boolean;
}> = ({ isOpen, onClose, onSave, saving }) => {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black bg-opacity-50" onClick={onClose} />
      <div className="relative bg-white rounded-lg shadow-xl w-full max-w-sm mx-4 p-5">
        <h3 className="text-sm font-semibold text-gray-900 mb-3">Save as Profile</h3>
        <input
          type="text"
          placeholder="Profile name"
          value={name}
          onChange={e => setName(e.target.value)}
          className="w-full px-3 py-2 border border-gray-300 rounded text-sm focus:outline-none focus:ring-1 focus:ring-blue-500 mb-2"
          autoFocus
        />
        <input
          type="text"
          placeholder="Description (optional)"
          value={description}
          onChange={e => setDescription(e.target.value)}
          className="w-full px-3 py-2 border border-gray-300 rounded text-sm focus:outline-none focus:ring-1 focus:ring-blue-500 mb-4"
        />
        <div className="flex justify-end gap-2">
          <button
            onClick={onClose}
            disabled={saving}
            className="px-3 py-1.5 text-sm text-gray-600 hover:text-gray-800 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={() => onSave(name.trim(), description.trim() || undefined)}
            disabled={saving || !name.trim()}
            className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {saving ? 'Saving...' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  );
};

/** Simple dialog for choosing a profile to load. */
const LoadProfileDialog: React.FC<{
  isOpen: boolean;
  onClose: () => void;
  onLoad: (profileId: number) => void;
}> = ({ isOpen, onClose, onLoad }) => {
  const [profiles, setProfiles] = useState<ProfileSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isOpen) return;
    setLoading(true);
    setError(null);
    api.listProfiles()
      .then(setProfiles)
      .catch(err => setError(err instanceof Error ? err.message : 'Failed to load profiles'))
      .finally(() => setLoading(false));
  }, [isOpen]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black bg-opacity-50" onClick={onClose} />
      <div className="relative bg-white rounded-lg shadow-xl w-full max-w-sm mx-4 p-5">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-gray-900">Load Profile</h3>
          <button onClick={onClose} className="p-0.5 text-gray-400 hover:text-gray-600">
            <X size={14} />
          </button>
        </div>

        {loading && (
          <div className="flex items-center justify-center py-6 text-gray-500 text-sm gap-2">
            <Loader2 size={16} className="animate-spin" />
            Loading profiles...
          </div>
        )}

        {error && (
          <p className="text-sm text-red-600 py-4 text-center">{error}</p>
        )}

        {!loading && !error && profiles.length === 0 && (
          <p className="text-sm text-gray-500 py-4 text-center">No profiles available.</p>
        )}

        {!loading && !error && (
          <div className="max-h-56 overflow-y-auto space-y-1">
            {profiles.map(p => (
              <button
                key={p.id}
                onClick={() => {
                  onLoad(p.id);
                  onClose();
                }}
                className="w-full text-left px-3 py-2 rounded text-sm hover:bg-gray-100 transition-colors"
              >
                <div className="flex items-center gap-2">
                  <span className="font-medium text-gray-800">{p.name}</span>
                  {p.is_default && (
                    <span className="text-[10px] uppercase text-gray-400 border border-gray-200 rounded px-1">default</span>
                  )}
                </div>
                {p.description && (
                  <p className="text-xs text-gray-500 mt-0.5 line-clamp-1">{p.description}</p>
                )}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export const AgentConfigBar: React.FC = () => {
  const {
    agentConfig,
    addTool,
    removeTool,
    setStyle,
    setDeckPrompt,
    saveAsProfile,
    loadProfile,
    isPreSession,
  } = useAgentConfig();

  const { showToast } = useToast();

  // Expanded / collapsed state
  const [expanded, setExpanded] = useState(false);

  // ToolPicker visibility
  const [toolPickerOpen, setToolPickerOpen] = useState(false);

  // Save / Load dialogs
  const [saveDialogOpen, setSaveDialogOpen] = useState(false);
  const [loadDialogOpen, setLoadDialogOpen] = useState(false);
  const [saving, setSaving] = useState(false);

  // Slide styles and deck prompts for selectors
  const [slideStyles, setSlideStyles] = useState<SlideStyle[]>([]);
  const [deckPrompts, setDeckPrompts] = useState<DeckPrompt[]>([]);
  const [stylesLoading, setStylesLoading] = useState(false);
  const [promptsLoading, setPromptsLoading] = useState(false);

  // Fetch options when expanded
  useEffect(() => {
    if (!expanded) return;

    let cancelled = false;

    setStylesLoading(true);
    configApi.listSlideStyles()
      .then(res => { if (!cancelled) setSlideStyles(res.styles); })
      .catch(err => console.error('Failed to load slide styles:', err))
      .finally(() => { if (!cancelled) setStylesLoading(false); });

    setPromptsLoading(true);
    configApi.listDeckPrompts()
      .then(res => { if (!cancelled) setDeckPrompts(res.prompts); })
      .catch(err => console.error('Failed to load deck prompts:', err))
      .finally(() => { if (!cancelled) setPromptsLoading(false); });

    return () => { cancelled = true; };
  }, [expanded]);

  // Handlers
  const handleSaveProfile = useCallback(async (name: string, description?: string) => {
    setSaving(true);
    try {
      await saveAsProfile(name, description);
      setSaveDialogOpen(false);
    } catch {
      // Toast is shown by the context
    } finally {
      setSaving(false);
    }
  }, [saveAsProfile]);

  const handleLoadProfile = useCallback(async (profileId: number) => {
    await loadProfile(profileId);
  }, [loadProfile]);

  const handleStyleChange = useCallback(async (e: React.ChangeEvent<HTMLSelectElement>) => {
    const value = e.target.value;
    await setStyle(value === '' ? null : Number(value));
  }, [setStyle]);

  const handleDeckPromptChange = useCallback(async (e: React.ChangeEvent<HTMLSelectElement>) => {
    const value = e.target.value;
    await setDeckPrompt(value === '' ? null : Number(value));
  }, [setDeckPrompt]);

  // Summary line for collapsed state
  const toolCount = agentConfig.tools.length;
  const selectedStyleName = slideStyles.find(s => s.id === agentConfig.slide_style_id)?.name;
  const selectedPromptName = deckPrompts.find(p => p.id === agentConfig.deck_prompt_id)?.name;

  return (
    <div
      className="border border-gray-200 rounded-lg bg-gray-50 text-sm"
      data-testid="agent-config-bar"
    >
      {/* Collapsed header / toggle */}
      <button
        onClick={() => setExpanded(prev => !prev)}
        className="w-full flex items-center justify-between px-3 py-2 text-gray-600 hover:text-gray-800 transition-colors"
        data-testid="agent-config-toggle"
      >
        <span className="font-medium text-xs text-gray-500 uppercase tracking-wide">
          Agent Config
          {!expanded && toolCount > 0 && (
            <span className="ml-2 normal-case tracking-normal text-gray-400">
              {toolCount} tool{toolCount !== 1 ? 's' : ''}
              {selectedStyleName && ` / ${selectedStyleName}`}
              {selectedPromptName && ` / ${selectedPromptName}`}
            </span>
          )}
        </span>
        {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
      </button>

      {/* Expanded content */}
      {expanded && (
        <div className="px-3 pb-3 space-y-3 border-t border-gray-200 pt-3">
          {/* Tools row */}
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Tools</label>
            <div className="flex flex-wrap items-center gap-1.5 relative">
              {agentConfig.tools.map((tool, idx) => (
                <ToolChip
                  key={`${tool.type}-${tool.type === 'genie' ? tool.space_id : tool.server_uri}-${idx}`}
                  tool={tool}
                  onRemove={() => removeTool(tool)}
                />
              ))}
              <button
                onClick={() => setToolPickerOpen(true)}
                className="inline-flex items-center gap-0.5 px-2 py-0.5 rounded-full text-xs text-gray-500 border border-dashed border-gray-300 hover:border-gray-400 hover:text-gray-700 transition-colors"
                data-testid="add-tool-button"
              >
                <Plus size={12} />
                Add Tool
              </button>
              <ToolPicker
                isOpen={toolPickerOpen}
                onClose={() => setToolPickerOpen(false)}
                onSelect={addTool}
                existingTools={agentConfig.tools}
              />
            </div>
          </div>

          {/* Selectors row */}
          <div className="flex flex-wrap gap-3">
            {/* Style selector */}
            <div className="flex-1 min-w-[140px]">
              <label className="block text-xs font-medium text-gray-500 mb-1">Slide Style</label>
              <select
                value={agentConfig.slide_style_id ?? ''}
                onChange={handleStyleChange}
                disabled={stylesLoading}
                className="w-full px-2 py-1.5 border border-gray-300 rounded text-sm bg-white focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50"
                data-testid="style-selector"
              >
                <option value="">None (default)</option>
                {slideStyles.map(s => (
                  <option key={s.id} value={s.id}>{s.name}</option>
                ))}
              </select>
            </div>

            {/* Deck prompt selector */}
            <div className="flex-1 min-w-[140px]">
              <label className="block text-xs font-medium text-gray-500 mb-1">Deck Prompt</label>
              <select
                value={agentConfig.deck_prompt_id ?? ''}
                onChange={handleDeckPromptChange}
                disabled={promptsLoading}
                className="w-full px-2 py-1.5 border border-gray-300 rounded text-sm bg-white focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50"
                data-testid="deck-prompt-selector"
              >
                <option value="">None (default)</option>
                {deckPrompts.map(p => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
            </div>
          </div>

          {/* Profile actions row */}
          <div className="flex items-center gap-2 pt-1">
            <button
              onClick={() => setSaveDialogOpen(true)}
              disabled={isPreSession}
              className="inline-flex items-center gap-1 px-2 py-1 text-xs text-gray-600 hover:text-gray-800 border border-gray-300 rounded hover:bg-gray-100 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              title={isPreSession ? 'Save requires an active session' : 'Save current config as a profile'}
              data-testid="save-profile-button"
            >
              <Save size={12} />
              Save as Profile
            </button>
            <button
              onClick={() => setLoadDialogOpen(true)}
              className="inline-flex items-center gap-1 px-2 py-1 text-xs text-gray-600 hover:text-gray-800 border border-gray-300 rounded hover:bg-gray-100 transition-colors"
              data-testid="load-profile-button"
            >
              <FolderOpen size={12} />
              Load Profile
            </button>
          </div>
        </div>
      )}

      {/* Dialogs */}
      <SaveProfileDialog
        isOpen={saveDialogOpen}
        onClose={() => setSaveDialogOpen(false)}
        onSave={handleSaveProfile}
        saving={saving}
      />
      <LoadProfileDialog
        isOpen={loadDialogOpen}
        onClose={() => setLoadDialogOpen(false)}
        onLoad={handleLoadProfile}
      />
    </div>
  );
};

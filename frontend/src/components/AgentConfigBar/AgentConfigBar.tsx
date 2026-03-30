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

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { X, Save, FolderOpen, Loader2, ChevronDown, ChevronUp, ExternalLink } from 'lucide-react';
import { useAgentConfig } from '../../contexts/AgentConfigContext';
import { useSession } from '../../contexts/SessionContext';
import { configApi } from '../../api/config';
import type { SlideStyle, DeckPrompt } from '../../api/config';
import type { AvailableTool, GenieTool, ProfileSummary, ToolEntry, MCPTool, VectorIndexTool, ModelEndpointTool, AgentBricksTool } from '../../types/agentConfig';
import { TOOL_TYPE_BADGE_LABELS, TOOL_TYPE_COLORS } from '../../types/agentConfig';
import { api } from '../../services/api';
import { ToolPicker } from './ToolPicker';
import GenieDetailPanel from './GenieDetailPanel';

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

/** Removable chip for an active tool, with type-specific color badge. */
const ToolChip: React.FC<{
  tool: ToolEntry;
  onRemove: () => void;
  onEdit?: () => void;
  sessionId?: string | null;
}> = ({ tool, onRemove, onEdit, sessionId }) => {
  const label = tool.type === 'genie'
    ? tool.space_name
    : tool.type === 'mcp'
    ? tool.server_name
    : tool.endpoint_name;

  const conversationId = tool.type === 'genie' ? tool.conversation_id : undefined;
  const spaceId = tool.type === 'genie' ? tool.space_id : undefined;

  const colorClasses = TOOL_TYPE_COLORS[tool.type];
  const badgeLabel = TOOL_TYPE_BADGE_LABELS[tool.type];

  // Derive a hover background class from the chip's color class
  const hoverBgClass = tool.type === 'genie' ? 'hover:bg-blue-200'
    : tool.type === 'mcp' ? 'hover:bg-green-200'
    : tool.type === 'vector_index' ? 'hover:bg-indigo-200'
    : tool.type === 'model_endpoint' ? 'hover:bg-amber-200'
    : 'hover:bg-teal-200';

  const handleOpenGenieLink = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!sessionId || !spaceId) return;
    try {
      const link = await api.getGenieLink(sessionId, spaceId);
      if (link.url) {
        window.open(link.url, '_blank');
      }
    } catch (error) {
      console.error('Failed to get Genie link:', error);
    }
  };

  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${colorClasses}`}>
      <span className="uppercase text-[10px] font-bold opacity-70 mr-0.5">{badgeLabel}</span>
      {onEdit ? (
        <button
          onClick={onEdit}
          className="hover:underline cursor-pointer"
          data-testid="tool-chip-label"
        >
          {label}
        </button>
      ) : (
        <span>{label}</span>
      )}
      {conversationId && (
        <button
          onClick={handleOpenGenieLink}
          className={`p-0.5 rounded-full ${hoverBgClass} transition-colors`}
          aria-label={`View source data for ${label}`}
          title="View source data in Genie"
        >
          <ExternalLink size={10} />
        </button>
      )}
      <button
        onClick={(e) => { e.stopPropagation(); onRemove(); }}
        className={`ml-0.5 p-0.5 rounded-full ${hoverBgClass} transition-colors`}
        aria-label={`Remove ${label}`}
      >
        <X size={12} />
      </button>
    </span>
  );
};

/**
 * Generic edit panel for non-Genie tool types.
 * Shows read-only tool identity fields and an editable description.
 */
const ToolEditPanel: React.FC<{
  tool: MCPTool | VectorIndexTool | ModelEndpointTool | AgentBricksTool;
  onSave: (tool: MCPTool | VectorIndexTool | ModelEndpointTool | AgentBricksTool) => void;
  onCancel: () => void;
}> = ({ tool, onSave, onCancel }) => {
  const [description, setDescription] = useState(tool.description ?? '');

  const colorClasses = TOOL_TYPE_COLORS[tool.type];
  const badgeLabel = TOOL_TYPE_BADGE_LABELS[tool.type];

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      e.stopPropagation();
      onCancel();
    }
  };

  const handleSave = () => {
    onSave({ ...tool, description });
  };

  // Build read-only info rows based on tool type
  const infoRows: { label: string; value: string }[] = [];
  if (tool.type === 'mcp') {
    infoRows.push({ label: 'Connection', value: tool.connection_name });
  } else if (tool.type === 'vector_index') {
    infoRows.push({ label: 'Endpoint', value: tool.endpoint_name });
    infoRows.push({ label: 'Index', value: tool.index_name });
  } else if (tool.type === 'model_endpoint') {
    infoRows.push({ label: 'Endpoint', value: tool.endpoint_name });
    if (tool.endpoint_type) infoRows.push({ label: 'Type', value: tool.endpoint_type });
  } else if (tool.type === 'agent_bricks') {
    infoRows.push({ label: 'Endpoint', value: tool.endpoint_name });
  }

  const toolName = tool.type === 'mcp' ? tool.server_name : tool.endpoint_name;

  return (
    <div
      data-testid="tool-edit-panel"
      className="border rounded bg-gray-50 p-4"
      onKeyDown={handleKeyDown}
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className={`uppercase text-[10px] font-bold px-1.5 py-0.5 rounded ${colorClasses}`}>
            {badgeLabel}
          </span>
          <span className="font-semibold text-sm">{toolName}</span>
        </div>
        <button
          onClick={onCancel}
          className="text-gray-400 hover:text-gray-600"
          aria-label="Close"
        >
          <X size={16} />
        </button>
      </div>

      {/* Read-only identity fields */}
      {infoRows.map(({ label, value }) => (
        <div key={label} className="mb-3">
          <label className="block text-sm text-gray-500 mb-1">{label}</label>
          <div className="font-mono text-sm text-gray-700">{value}</div>
        </div>
      ))}

      {/* Editable description */}
      <div className="mb-4">
        <div className="flex items-baseline justify-between mb-1">
          <label className="text-sm text-gray-500">Description</label>
          <span className="text-xs text-gray-400">
            Used by the agent to decide when to use this tool
          </span>
        </div>
        <textarea
          autoFocus
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Describe when the agent should use this tool..."
          className="w-full border rounded px-3 py-2 text-sm resize-y min-h-[80px] focus:outline-none focus:ring-2 focus:ring-blue-400"
        />
      </div>

      {/* Buttons */}
      <div className="flex items-center justify-end gap-2">
        <button
          onClick={onCancel}
          className="px-3 py-1.5 text-sm text-gray-600 hover:text-gray-800"
        >
          Cancel
        </button>
        <button
          onClick={handleSave}
          className="px-3 py-1.5 text-sm bg-blue-500 text-white rounded hover:bg-blue-600"
        >
          Save
        </button>
      </div>
    </div>
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
  const userDefaultProfileId = useMemo(() => {
    const stored = localStorage.getItem('userDefaultProfileId');
    return stored ? Number(stored) : null;
  }, [isOpen]);

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
                  {(userDefaultProfileId != null ? p.id === userDefaultProfileId : p.is_default) && (
                    <span className="text-[10px] uppercase text-amber-700 bg-amber-500/10 border border-amber-200 rounded px-1">default</span>
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
    updateTool,
    updateToolEntry,
    setStyle,
    setDeckPrompt,
    saveAsProfile,
    loadProfile,
  } = useAgentConfig();
  const { sessionId } = useSession();

  // Expanded / collapsed state
  const [expanded, setExpanded] = useState(false);

  // Detail panel state
  const [detailTool, setDetailTool] = useState<GenieTool | AvailableTool | null>(null);
  const [detailMode, setDetailMode] = useState<'add' | 'edit'>('add');
  // For non-Genie tool editing
  const [editingNonGenieTool, setEditingNonGenieTool] = useState<MCPTool | VectorIndexTool | ModelEndpointTool | AgentBricksTool | null>(null);

  // Save / Load dialogs
  const [saveDialogOpen, setSaveDialogOpen] = useState(false);
  const [loadDialogOpen, setLoadDialogOpen] = useState(false);
  const [saving, setSaving] = useState(false);

  // Slide styles and deck prompts for selectors
  const [slideStyles, setSlideStyles] = useState<SlideStyle[]>([]);
  const [deckPrompts, setDeckPrompts] = useState<DeckPrompt[]>([]);
  const [stylesLoading, setStylesLoading] = useState(false);
  const [promptsLoading, setPromptsLoading] = useState(false);

  // Fetch style/prompt options eagerly so the collapsed summary can show names
  useEffect(() => {
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
  }, []);

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

  // Detail panel handlers
  const handlePreview = useCallback((tool: AvailableTool) => {
    setDetailTool(tool);
    setDetailMode('add');
  }, []);

  const handleEditChip = useCallback((tool: ToolEntry) => {
    if (tool.type === 'genie') {
      setDetailTool(tool);
      setDetailMode('edit');
      setEditingNonGenieTool(null);
    } else {
      setEditingNonGenieTool(tool as MCPTool | VectorIndexTool | ModelEndpointTool | AgentBricksTool);
      setDetailTool(null);
    }
  }, []);

  const handleDetailSave = useCallback(async (tool: GenieTool) => {
    try {
      if (detailMode === 'add') {
        await addTool(tool);
      } else {
        await updateTool(tool.space_id, { description: tool.description });
      }
      setDetailTool(null);
    } catch {
      // Panel stays open on failure; toast shown by context
    }
  }, [detailMode, addTool, updateTool]);

  const handleDetailCancel = useCallback(() => {
    setDetailTool(null);
    setEditingNonGenieTool(null);
  }, []);

  const handleNonGenieToolSave = useCallback(async (tool: MCPTool | VectorIndexTool | ModelEndpointTool | AgentBricksTool) => {
    try {
      await updateToolEntry(tool);
      setEditingNonGenieTool(null);
    } catch {
      // Panel stays open on failure; toast shown by context
    }
  }, [updateToolEntry]);

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
          {/* Detail panel (shown above tools row when active) */}
          {detailTool && (
            <GenieDetailPanel
              tool={detailTool}
              mode={detailMode}
              onSave={handleDetailSave}
              onCancel={handleDetailCancel}
            />
          )}
          {editingNonGenieTool && (
            <ToolEditPanel
              tool={editingNonGenieTool}
              onSave={handleNonGenieToolSave}
              onCancel={handleDetailCancel}
            />
          )}

          {/* Tools row */}
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Tools</label>
            <div className="flex flex-wrap items-center gap-1.5 relative">
              {agentConfig.tools.map((tool, idx) => (
                <ToolChip
                  key={`${tool.type}-${'space_id' in tool ? tool.space_id : 'connection_name' in tool ? tool.connection_name : 'endpoint_name' in tool ? tool.endpoint_name : idx}-${idx}`}
                  tool={tool}
                  onRemove={() => removeTool(tool)}
                  onEdit={() => handleEditChip(tool)}
                  sessionId={sessionId}
                />
              ))}
              <ToolPicker
                onSelect={addTool}
                onPreview={handlePreview}
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
              className="inline-flex items-center gap-1 px-2 py-1 text-xs text-gray-600 hover:text-gray-800 border border-gray-300 rounded hover:bg-gray-100 transition-colors"
              title="Save current config as a profile"
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

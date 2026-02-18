/**
 * Deck Prompt management component.
 * 
 * Displays all deck prompts in a list with actions:
 * - View and edit prompt content
 * - Delete prompt
 * - Create new prompt
 */

import React, { useState, useEffect, useCallback } from 'react';
import { FiExternalLink } from 'react-icons/fi';
import { configApi } from '../../api/config';
import type { DeckPrompt, DeckPromptCreate, DeckPromptUpdate } from '../../api/config';
import { DeckPromptForm } from './DeckPromptForm';
import { ConfirmDialog } from './ConfirmDialog';
import { DOCS_URLS } from '../../constants/docs';

export const DeckPromptList: React.FC = () => {
  const [prompts, setPrompts] = useState<DeckPrompt[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  
  const [formMode, setFormMode] = useState<'create' | 'edit' | null>(null);
  const [editingPrompt, setEditingPrompt] = useState<DeckPrompt | null>(null);
  const [actionLoading, setActionLoading] = useState<number | null>(null);
  const [expandedPromptId, setExpandedPromptId] = useState<number | null>(null);
  
  const [confirmDialog, setConfirmDialog] = useState<{
    isOpen: boolean;
    title: string;
    message: string;
    onConfirm: () => void;
  }>({
    isOpen: false,
    title: '',
    message: '',
    onConfirm: () => {},
  });

  // Load prompts
  const loadPrompts = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const response = await configApi.listDeckPrompts();
      setPrompts(response.prompts);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load deck prompts');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadPrompts();
  }, [loadPrompts]);

  // Handle create
  const handleCreate = () => {
    setEditingPrompt(null);
    setFormMode('create');
  };

  // Handle edit
  const handleEdit = (prompt: DeckPrompt) => {
    setEditingPrompt(prompt);
    setFormMode('edit');
  };

  // Handle form submit
  const handleFormSubmit = async (data: DeckPromptCreate | DeckPromptUpdate) => {
    try {
      if (formMode === 'create') {
        await configApi.createDeckPrompt(data as DeckPromptCreate);
      } else if (formMode === 'edit' && editingPrompt) {
        await configApi.updateDeckPrompt(editingPrompt.id, data as DeckPromptUpdate);
      }
      await loadPrompts();
      setFormMode(null);
      setEditingPrompt(null);
    } catch (err) {
      throw err; // Let the form handle the error
    }
  };

  // Handle delete with confirmation
  const handleDelete = (prompt: DeckPrompt) => {
    setConfirmDialog({
      isOpen: true,
      title: 'Delete Deck Prompt',
      message: `Are you sure you want to delete "${prompt.name}"?\n\nThis action cannot be undone. Any profiles using this prompt will have their selection cleared.`,
      onConfirm: async () => {
        setActionLoading(prompt.id);
        try {
          await configApi.deleteDeckPrompt(prompt.id);
          await loadPrompts();
        } catch (err) {
          setError(err instanceof Error ? err.message : 'Failed to delete prompt');
        } finally {
          setActionLoading(null);
          setConfirmDialog({ ...confirmDialog, isOpen: false });
        }
      },
    });
  };

  // Toggle expanded view
  const toggleExpanded = (promptId: number) => {
    setExpandedPromptId(expandedPromptId === promptId ? null : promptId);
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-gray-600">Loading deck prompts...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4 bg-red-50 border border-red-200 rounded text-red-700">
        Error: {error}
        <button 
          onClick={loadPrompts}
          className="ml-4 px-3 py-1 bg-red-100 hover:bg-red-200 text-red-700 rounded text-sm"
        >
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex justify-between items-center">
        <div>
          <h2 className="text-2xl font-semibold text-gray-900">Deck Prompt Library</h2>
          <p className="text-sm text-gray-600 mt-1">
            Manage reusable presentation templates. These prompts guide the AI in creating specific types of presentations.
            {' '}
            <a
              href={DOCS_URLS.advancedConfig}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-blue-600 hover:text-blue-800"
            >
              View guide <FiExternalLink size={12} />
            </a>
          </p>
        </div>
        <button
          onClick={handleCreate}
          className="px-4 py-2 bg-blue-500 hover:bg-blue-600 text-white rounded transition-colors"
        >
          + Create Prompt
        </button>
      </div>

      {/* Prompts Grid */}
      <div className="grid gap-4">
        {prompts.map((prompt) => (
          <div 
            key={prompt.id} 
            className="border rounded-lg bg-white shadow-sm hover:shadow-md transition-shadow"
          >
            {/* Header Row */}
            <div className="p-4 flex items-start justify-between">
              <div className="flex-1">
                <div className="flex items-center gap-3">
                  <h3 className="text-lg font-medium text-gray-900">{prompt.name}</h3>
                  {prompt.category && (
                    <span className="px-2 py-0.5 bg-purple-100 text-purple-700 text-xs rounded-full">
                      {prompt.category}
                    </span>
                  )}
                  {!prompt.is_active && (
                    <span className="px-2 py-0.5 bg-gray-100 text-gray-500 text-xs rounded-full">
                      Inactive
                    </span>
                  )}
                </div>
                {prompt.description && (
                  <p className="text-sm text-gray-600 mt-1">{prompt.description}</p>
                )}
                <p className="text-xs text-gray-400 mt-2">
                  Created by {prompt.created_by || 'system'} • 
                  Updated {new Date(prompt.updated_at).toLocaleDateString()}
                </p>
              </div>
              
              <div className="flex gap-2 ml-4">
                <button
                  onClick={() => toggleExpanded(prompt.id)}
                  className="px-3 py-1 bg-gray-100 hover:bg-gray-200 text-gray-700 text-xs rounded transition-colors"
                >
                  {expandedPromptId === prompt.id ? 'Hide' : 'Preview'}
                </button>
                <button
                  onClick={() => handleEdit(prompt)}
                  disabled={actionLoading === prompt.id}
                  className="px-3 py-1 bg-indigo-500 hover:bg-indigo-600 text-white text-xs rounded transition-colors disabled:bg-gray-300"
                >
                  Edit
                </button>
                <button
                  onClick={() => handleDelete(prompt)}
                  disabled={actionLoading === prompt.id}
                  className="px-3 py-1 bg-red-500 hover:bg-red-600 text-white text-xs rounded transition-colors disabled:bg-gray-300"
                >
                  Delete
                </button>
              </div>
            </div>

            {/* Expanded Content */}
            {expandedPromptId === prompt.id && (
              <div className="px-4 pb-4 border-t bg-gray-50">
                <div className="mt-3">
                  <label className="text-xs font-medium text-gray-500 uppercase">Prompt Content</label>
                  <pre className="mt-1 p-3 bg-white border rounded text-xs text-gray-800 whitespace-pre-wrap font-mono max-h-64 overflow-y-auto">
                    {prompt.prompt_content}
                  </pre>
                </div>
              </div>
            )}
          </div>
        ))}

        {prompts.length === 0 && (
          <div className="p-8 text-center text-gray-500 border rounded-lg bg-gray-50">
            No deck prompts found. Create your first prompt to get started.
          </div>
        )}
      </div>

      {/* Form Modal */}
      <DeckPromptForm
        isOpen={formMode !== null}
        mode={formMode || 'create'}
        prompt={editingPrompt || undefined}
        onSubmit={handleFormSubmit}
        onCancel={() => {
          setFormMode(null);
          setEditingPrompt(null);
        }}
      />

      {/* Confirmation Dialog */}
      <ConfirmDialog
        isOpen={confirmDialog.isOpen}
        title={confirmDialog.title}
        message={confirmDialog.message}
        onConfirm={confirmDialog.onConfirm}
        onCancel={() => setConfirmDialog({ ...confirmDialog, isOpen: false })}
      />
    </div>
  );
};


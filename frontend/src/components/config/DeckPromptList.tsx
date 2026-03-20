/**
 * Deck Prompt management component.
 * 
 * Displays all deck prompts in a list with actions:
 * - View and edit prompt content
 * - Delete prompt
 * - Create new prompt
 */

import React, { useState, useEffect, useCallback } from 'react';
import { FileText, Plus, ChevronDown, Edit, Trash2 } from 'lucide-react';
import { Button } from '@/ui/button';
import { Badge } from '@/ui/badge';
import { configApi } from '../../api/config';
import type { DeckPrompt, DeckPromptCreate, DeckPromptUpdate } from '../../api/config';
import { DeckPromptForm } from './DeckPromptForm';
import { ConfirmDialog } from './ConfirmDialog';

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
        <div className="text-muted-foreground">Loading deck prompts...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-destructive">
        Error: {error}
        <Button
          variant="outline"
          size="sm"
          onClick={loadPrompts}
          className="ml-4"
        >
          Retry
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-bold text-foreground">Deck Prompt Library</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Manage reusable presentation templates. These prompts guide the AI in creating specific types of presentations.
          </p>
        </div>
        <Button size="sm" onClick={handleCreate} className="gap-1.5">
          <Plus className="size-3.5" />
          New Prompt
        </Button>
      </div>

      {/* Prompts Grid */}
      {prompts.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-border bg-muted/20 p-12 text-center">
          <FileText className="mb-3 size-12 text-muted-foreground/50" />
          <p className="text-sm text-muted-foreground">
            No deck prompts found. Create your first prompt to get started.
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {prompts.map((prompt) => (
            <div
              key={prompt.id}
              className="rounded-lg border border-border bg-card transition-colors hover:bg-accent/5"
            >
              {/* Header Row */}
              <div className="flex items-start gap-4 p-4">
                {/* Icon */}
                <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  <FileText className="size-5" />
                </div>

                {/* Content */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <h3 className="text-sm font-medium text-foreground">
                          {prompt.name}
                        </h3>
                        {prompt.category && (
                          <Badge variant="secondary" className="text-xs">
                            {prompt.category}
                          </Badge>
                        )}
                        {!prompt.is_active && (
                          <Badge variant="outline" className="text-xs">
                            Inactive
                          </Badge>
                        )}
                      </div>
                      {prompt.description && (
                        <p className="mt-0.5 text-sm text-muted-foreground">
                          {prompt.description}
                        </p>
                      )}
                      <p className="mt-1.5 text-xs text-muted-foreground">
                        Created by {prompt.created_by || 'system'} •{' '}
                        Updated {new Date(prompt.updated_at).toLocaleDateString()}
                      </p>
                    </div>

                    {/* Actions */}
                    <div className="flex shrink-0 items-center gap-1">
                      <Button
                        variant="ghost"
                        size="sm"
                        className="size-8 p-0"
                        onClick={() => toggleExpanded(prompt.id)}
                        aria-label={expandedPromptId === prompt.id ? 'Hide' : 'Preview'}
                      >
                        <ChevronDown
                          className={`size-4 text-muted-foreground transition-transform ${
                            expandedPromptId === prompt.id ? 'rotate-180' : ''
                          }`}
                        />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="size-8 p-0"
                        onClick={() => handleEdit(prompt)}
                        disabled={actionLoading === prompt.id}
                        aria-label="Edit"
                      >
                        <Edit className="size-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="size-8 p-0 text-muted-foreground hover:text-destructive"
                        onClick={() => handleDelete(prompt)}
                        disabled={actionLoading === prompt.id}
                        aria-label="Delete"
                      >
                        <Trash2 className="size-4" />
                      </Button>
                    </div>
                  </div>

                  {/* Expanded Content */}
                  {expandedPromptId === prompt.id && (
                    <div className="mt-3 rounded-md border border-border bg-muted/30 p-3">
                      <label className="text-xs font-medium uppercase text-muted-foreground">
                        Prompt Content
                      </label>
                      <pre className="mt-2 max-h-64 overflow-y-auto whitespace-pre-wrap rounded-md border border-border bg-background p-3 font-mono text-xs text-foreground">
                        {prompt.prompt_content}
                      </pre>
                    </div>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

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


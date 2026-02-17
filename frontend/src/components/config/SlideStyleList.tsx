/**
 * Slide Style management component.
 * 
 * Displays all slide styles in a list with actions:
 * - View and edit style content
 * - Delete style
 * - Create new style
 */

import React, { useState, useEffect, useCallback } from 'react';
import { Palette, Plus, ChevronDown, Edit, Trash2 } from 'lucide-react';
import { Button } from '@/ui/button';
import { Badge } from '@/ui/badge';
import { configApi } from '../../api/config';
import type { SlideStyle, SlideStyleCreate, SlideStyleUpdate } from '../../api/config';
import { SlideStyleForm } from './SlideStyleForm';
import { ConfirmDialog } from './ConfirmDialog';

export const SlideStyleList: React.FC = () => {
  const [styles, setStyles] = useState<SlideStyle[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  
  const [formMode, setFormMode] = useState<'create' | 'edit' | null>(null);
  const [editingStyle, setEditingStyle] = useState<SlideStyle | null>(null);
  const [actionLoading, setActionLoading] = useState<number | null>(null);
  const [expandedStyleId, setExpandedStyleId] = useState<number | null>(null);
  
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

  // Load styles
  const loadStyles = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const response = await configApi.listSlideStyles();
      setStyles(response.styles);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load slide styles');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadStyles();
  }, [loadStyles]);

  // Handle create
  const handleCreate = () => {
    setEditingStyle(null);
    setFormMode('create');
  };

  // Handle edit
  const handleEdit = (style: SlideStyle) => {
    setEditingStyle(style);
    setFormMode('edit');
  };

  // Handle form submit
  const handleFormSubmit = async (data: SlideStyleCreate | SlideStyleUpdate) => {
    try {
      if (formMode === 'create') {
        await configApi.createSlideStyle(data as SlideStyleCreate);
      } else if (formMode === 'edit' && editingStyle) {
        await configApi.updateSlideStyle(editingStyle.id, data as SlideStyleUpdate);
      }
      await loadStyles();
      setFormMode(null);
      setEditingStyle(null);
    } catch (err) {
      throw err; // Let the form handle the error
    }
  };

  // Handle delete with confirmation
  const handleDelete = (style: SlideStyle) => {
    setConfirmDialog({
      isOpen: true,
      title: 'Delete Slide Style',
      message: `Are you sure you want to delete "${style.name}"?\n\nThis action cannot be undone. Any profiles using this style will have their selection cleared.`,
      onConfirm: async () => {
        setActionLoading(style.id);
        try {
          await configApi.deleteSlideStyle(style.id);
          await loadStyles();
        } catch (err) {
          setError(err instanceof Error ? err.message : 'Failed to delete style');
        } finally {
          setActionLoading(null);
          setConfirmDialog({ ...confirmDialog, isOpen: false });
        }
      },
    });
  };

  // Toggle expanded view
  const toggleExpanded = (styleId: number) => {
    setExpandedStyleId(expandedStyleId === styleId ? null : styleId);
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-muted-foreground">Loading slide styles...</div>
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
          onClick={loadStyles}
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
          <h1 className="text-xl font-bold text-foreground">Slide Style Library</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Manage visual styles for slide generation. These styles control typography, colors, layout, and overall appearance.
          </p>
        </div>
        <Button size="sm" onClick={handleCreate} className="gap-1.5">
          <Plus className="size-3.5" />
          New Style
        </Button>
      </div>

      {/* Styles Grid */}
      {styles.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-border bg-muted/20 p-12 text-center">
          <Palette className="mb-3 size-12 text-muted-foreground/50" />
          <p className="text-sm text-muted-foreground">
            No slide styles found. Create your first style to get started.
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {styles.map((style) => (
            <div
              key={style.id}
              className="rounded-lg border border-border bg-card transition-colors hover:bg-accent/5"
            >
              {/* Header Row */}
              <div className="flex items-start gap-4 p-4">
                {/* Icon */}
                <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  <Palette className="size-5" />
                </div>

                {/* Content */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <h3 className="text-sm font-medium text-foreground">
                          {style.name}
                        </h3>
                        {style.category && (
                          <Badge variant="secondary" className="text-xs">
                            {style.category}
                          </Badge>
                        )}
                        {style.is_system && (
                          <Badge className="text-xs bg-blue-500/10 text-blue-700 hover:bg-blue-500/20">
                            System
                          </Badge>
                        )}
                        {!style.is_active && (
                          <Badge variant="outline" className="text-xs">
                            Inactive
                          </Badge>
                        )}
                      </div>
                      {style.description && (
                        <p className="mt-0.5 text-sm text-muted-foreground">
                          {style.description}
                        </p>
                      )}
                      <p className="mt-1.5 text-xs text-muted-foreground">
                        Created by {style.created_by || 'system'} •{' '}
                        Updated {new Date(style.updated_at).toLocaleDateString()}
                      </p>
                    </div>

                    {/* Actions */}
                    <div className="flex shrink-0 items-center gap-1">
                      <Button
                        variant="ghost"
                        size="sm"
                        className="size-8 p-0"
                        onClick={() => toggleExpanded(style.id)}
                      >
                        <ChevronDown
                          className={`size-4 text-muted-foreground transition-transform ${
                            expandedStyleId === style.id ? 'rotate-180' : ''
                          }`}
                        />
                      </Button>
                      {!style.is_system && (
                        <>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="size-8 p-0"
                            onClick={() => handleEdit(style)}
                            disabled={actionLoading === style.id}
                          >
                            <Edit className="size-4" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="size-8 p-0 text-muted-foreground hover:text-destructive"
                            onClick={() => handleDelete(style)}
                            disabled={actionLoading === style.id}
                          >
                            <Trash2 className="size-4" />
                          </Button>
                        </>
                      )}
                    </div>
                  </div>

                  {/* Expanded Content */}
                  {expandedStyleId === style.id && (
                    <div className="mt-3 rounded-md border border-border bg-muted/30 p-3">
                      <label className="text-xs font-medium uppercase text-muted-foreground">
                        Style Content
                      </label>
                      <pre className="mt-2 max-h-64 overflow-y-auto whitespace-pre-wrap rounded-md border border-border bg-background p-3 font-mono text-xs text-foreground">
                        {style.style_content}
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
      <SlideStyleForm
        isOpen={formMode !== null}
        mode={formMode || 'create'}
        style={editingStyle || undefined}
        onSubmit={handleFormSubmit}
        onCancel={() => {
          setFormMode(null);
          setEditingStyle(null);
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

/**
 * Slide Style management component.
 * 
 * Displays all slide styles in a list with actions:
 * - View and edit style content
 * - Delete style
 * - Create new style
 */

import React, { useState, useEffect, useCallback } from 'react';
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
        <div className="text-gray-600">Loading slide styles...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4 bg-red-50 border border-red-200 rounded text-red-700">
        Error: {error}
        <button 
          onClick={loadStyles}
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
          <h2 className="text-2xl font-semibold text-gray-900">Slide Style Library</h2>
          <p className="text-sm text-gray-600 mt-1">
            Manage visual styles for slide generation. These styles control typography, colors, layout, and overall appearance.
          </p>
        </div>
        <button
          onClick={handleCreate}
          className="px-4 py-2 bg-blue-500 hover:bg-blue-600 text-white rounded transition-colors"
        >
          + Create Style
        </button>
      </div>

      {/* Styles Grid */}
      <div className="grid gap-4">
        {styles.map((style) => (
          <div 
            key={style.id} 
            className="border rounded-lg bg-white shadow-sm hover:shadow-md transition-shadow"
          >
            {/* Header Row */}
            <div className="p-4 flex items-start justify-between">
              <div className="flex-1">
                <div className="flex items-center gap-3">
                  <h3 className="text-lg font-medium text-gray-900">{style.name}</h3>
                  {style.category && (
                    <span className="px-2 py-0.5 bg-emerald-100 text-emerald-700 text-xs rounded-full">
                      {style.category}
                    </span>
                  )}
                  {style.is_system && (
                    <span className="px-2 py-0.5 bg-blue-100 text-blue-700 text-xs rounded-full">
                      System
                    </span>
                  )}
                  {!style.is_active && (
                    <span className="px-2 py-0.5 bg-gray-100 text-gray-500 text-xs rounded-full">
                      Inactive
                    </span>
                  )}
                </div>
                {style.description && (
                  <p className="text-sm text-gray-600 mt-1">{style.description}</p>
                )}
                <p className="text-xs text-gray-400 mt-2">
                  Created by {style.created_by || 'system'} • 
                  Updated {new Date(style.updated_at).toLocaleDateString()}
                </p>
              </div>
              
              <div className="flex gap-2 ml-4">
                <button
                  onClick={() => toggleExpanded(style.id)}
                  className="px-3 py-1 bg-gray-100 hover:bg-gray-200 text-gray-700 text-xs rounded transition-colors"
                >
                  {expandedStyleId === style.id ? 'Hide' : 'Preview'}
                </button>
                {!style.is_system && (
                  <>
                    <button
                      onClick={() => handleEdit(style)}
                      disabled={actionLoading === style.id}
                      className="px-3 py-1 bg-indigo-500 hover:bg-indigo-600 text-white text-xs rounded transition-colors disabled:bg-gray-300"
                    >
                      Edit
                    </button>
                    <button
                      onClick={() => handleDelete(style)}
                      disabled={actionLoading === style.id}
                      className="px-3 py-1 bg-red-500 hover:bg-red-600 text-white text-xs rounded transition-colors disabled:bg-gray-300"
                    >
                      Delete
                    </button>
                  </>
                )}
              </div>
            </div>

            {/* Expanded Content */}
            {expandedStyleId === style.id && (
              <div className="px-4 pb-4 border-t bg-gray-50">
                <div className="mt-3">
                  <label className="text-xs font-medium text-gray-500 uppercase">Style Content</label>
                  <pre className="mt-1 p-3 bg-white border rounded text-xs text-gray-800 whitespace-pre-wrap font-mono max-h-64 overflow-y-auto">
                    {style.style_content}
                  </pre>
                </div>
              </div>
            )}
          </div>
        ))}

        {styles.length === 0 && (
          <div className="p-8 text-center text-gray-500 border rounded-lg bg-gray-50">
            No slide styles found. Create your first style to get started.
          </div>
        )}
      </div>

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

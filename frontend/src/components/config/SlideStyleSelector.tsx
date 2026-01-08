/**
 * Slide Style Selector component.
 * 
 * Displays the global slide style library and allows selecting
 * a style for the current profile.
 */

import React, { useState, useEffect } from 'react';
import { configApi } from '../../api/config';
import type { SlideStyle, PromptsConfig } from '../../api/config';

interface SlideStyleSelectorProps {
  profileId: number;
  currentPrompts: PromptsConfig;
  onSave: () => Promise<void>;
  saving?: boolean;
}

export const SlideStyleSelector: React.FC<SlideStyleSelectorProps> = ({
  profileId,
  currentPrompts,
  onSave,
  saving = false,
}) => {
  const [slideStyles, setSlideStyles] = useState<SlideStyle[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(currentPrompts.selected_slide_style_id);
  const [isSaving, setIsSaving] = useState(false);
  const [success, setSuccess] = useState(false);
  const [expandedPreview, setExpandedPreview] = useState(false);

  // Load slide styles on mount
  useEffect(() => {
    loadSlideStyles();
  }, []);

  // Update selected when current prompts change
  useEffect(() => {
    setSelectedId(currentPrompts.selected_slide_style_id);
  }, [currentPrompts.selected_slide_style_id]);

  const loadSlideStyles = async () => {
    try {
      setLoading(true);
      setError(null);
      const response = await configApi.listSlideStyles();
      setSlideStyles(response.styles);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load slide styles');
    } finally {
      setLoading(false);
    }
  };

  const isDirty = selectedId !== currentPrompts.selected_slide_style_id;

  const handleSave = async () => {
    try {
      setIsSaving(true);
      setError(null);
      
      await configApi.updatePromptsConfig(profileId, {
        selected_slide_style_id: selectedId,
      });
      
      await onSave();
      setSuccess(true);
      setTimeout(() => setSuccess(false), 3000);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save');
    } finally {
      setIsSaving(false);
    }
  };

  const handleClearSelection = () => {
    setSelectedId(null);
  };

  const handleReset = () => {
    setSelectedId(currentPrompts.selected_slide_style_id);
    setError(null);
    setSuccess(false);
  };

  const selectedStyle = slideStyles.find(s => s.id === selectedId);

  // Group styles by category
  const categories = Array.from(new Set(slideStyles.map(s => s.category || 'Uncategorized')));

  if (loading) {
    return (
      <div className="flex items-center justify-center h-48">
        <div className="text-gray-600">Loading slide styles...</div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Status Messages */}
      {error && (
        <div className="p-3 bg-red-50 border border-red-200 rounded text-red-700 text-sm">
          {error}
        </div>
      )}
      {success && (
        <div className="p-3 bg-green-50 border border-green-200 rounded text-green-700 text-sm">
          Slide style selection saved!
        </div>
      )}

      {/* Description */}
      <div className="bg-emerald-50 border border-emerald-200 rounded p-4">
        <h3 className="text-sm font-medium text-emerald-800 mb-1">What are Slide Styles?</h3>
        <p className="text-sm text-emerald-700">
          Slide styles control the visual appearance of your presentations - typography, colors, 
          layout rules, and overall aesthetic. Select a style that matches your brand or preferences.
        </p>
      </div>

      {/* Current Selection */}
      {selectedStyle && (
        <div className="bg-emerald-50 border border-emerald-200 rounded p-4">
          <div className="flex items-start justify-between">
            <div className="flex-1">
              <div className="flex items-center gap-2">
                <span className="text-emerald-600 text-lg">✓</span>
                <h4 className="font-medium text-emerald-900">{selectedStyle.name}</h4>
                {selectedStyle.category && (
                  <span className="px-2 py-0.5 bg-emerald-200 text-emerald-800 text-xs rounded">
                    {selectedStyle.category}
                  </span>
                )}
              </div>
              {selectedStyle.description && (
                <p className="text-sm text-emerald-700 mt-1">{selectedStyle.description}</p>
              )}
            </div>
            <button
              onClick={() => setExpandedPreview(!expandedPreview)}
              className="text-sm text-emerald-600 hover:text-emerald-800"
            >
              {expandedPreview ? 'Hide preview' : 'Show preview'}
            </button>
          </div>
          
          {expandedPreview && (
            <div className="mt-3 pt-3 border-t border-emerald-200">
              <pre className="text-xs text-emerald-800 whitespace-pre-wrap bg-white p-3 rounded border border-emerald-200 max-h-48 overflow-y-auto">
                {selectedStyle.style_content}
              </pre>
            </div>
          )}
        </div>
      )}

      {/* Empty state when no selection */}
      {!selectedStyle && (
        <div className="bg-gray-50 border border-gray-200 border-dashed rounded p-4 text-center">
          <p className="text-gray-500 text-sm">
            No slide style selected. The agent will use default styling.
          </p>
        </div>
      )}

      {/* Style Library */}
      <div>
        <h3 className="text-sm font-medium text-gray-700 mb-3">
          Available Slide Styles {slideStyles.length > 0 && `(${slideStyles.length})`}
        </h3>

        {slideStyles.length === 0 ? (
          <div className="text-center py-8 bg-gray-50 rounded border border-gray-200">
            <p className="text-gray-500 text-sm">No slide styles available yet.</p>
            <p className="text-gray-400 text-xs mt-1">
              Slide styles can be created through the Slide Styles page.
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            {categories.map(category => (
              <div key={category}>
                <h4 className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-2">
                  {category}
                </h4>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                  {slideStyles
                    .filter(s => (s.category || 'Uncategorized') === category)
                    .map(style => (
                      <button
                        key={style.id}
                        onClick={() => setSelectedId(style.id)}
                        disabled={saving || isSaving}
                        className={`text-left p-4 rounded border-2 transition-all ${
                          selectedId === style.id
                            ? 'border-emerald-500 bg-emerald-50'
                            : 'border-gray-200 hover:border-gray-300 bg-white'
                        } ${(saving || isSaving) ? 'opacity-50 cursor-not-allowed' : ''}`}
                      >
                        <div className="flex items-start justify-between">
                          <h5 className={`font-medium text-sm ${
                            selectedId === style.id ? 'text-emerald-900' : 'text-gray-900'
                          }`}>
                            {style.name}
                          </h5>
                          {selectedId === style.id && (
                            <span className="text-emerald-600">✓</span>
                          )}
                        </div>
                        {style.description && (
                          <p className={`text-xs mt-1 line-clamp-2 ${
                            selectedId === style.id ? 'text-emerald-700' : 'text-gray-500'
                          }`}>
                            {style.description}
                          </p>
                        )}
                      </button>
                    ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Action Buttons */}
      <div className="flex justify-between pt-4 border-t">
        <button
          onClick={handleClearSelection}
          disabled={selectedId === null || saving || isSaving}
          className="px-4 py-2 text-gray-600 hover:text-gray-800 disabled:text-gray-400 disabled:cursor-not-allowed"
        >
          Clear Selection
        </button>
        <div className="flex gap-3">
          <button
            onClick={handleReset}
            disabled={!isDirty || saving || isSaving}
            className="px-4 py-2 bg-gray-200 hover:bg-gray-300 text-gray-800 rounded transition-colors disabled:bg-gray-100 disabled:text-gray-400 disabled:cursor-not-allowed"
          >
            Reset
          </button>
          <button
            onClick={handleSave}
            disabled={!isDirty || saving || isSaving}
            className="px-4 py-2 bg-emerald-500 hover:bg-emerald-600 text-white rounded transition-colors disabled:bg-emerald-300 disabled:cursor-not-allowed"
          >
            {isSaving ? 'Saving...' : 'Save Selection'}
          </button>
        </div>
      </div>
    </div>
  );
};

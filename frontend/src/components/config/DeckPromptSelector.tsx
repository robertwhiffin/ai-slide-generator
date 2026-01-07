/**
 * Deck Prompt Selector component.
 * 
 * Displays the global deck prompt library and allows selecting
 * a prompt template for the current profile.
 */

import React, { useState, useEffect } from 'react';
import { configApi } from '../../api/config';
import type { DeckPrompt, PromptsConfig } from '../../api/config';

interface DeckPromptSelectorProps {
  profileId: number;
  currentPrompts: PromptsConfig;
  onSave: () => Promise<void>;
  saving?: boolean;
}

export const DeckPromptSelector: React.FC<DeckPromptSelectorProps> = ({
  profileId,
  currentPrompts,
  onSave,
  saving = false,
}) => {
  const [deckPrompts, setDeckPrompts] = useState<DeckPrompt[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(currentPrompts.selected_deck_prompt_id);
  const [isSaving, setIsSaving] = useState(false);
  const [success, setSuccess] = useState(false);
  const [expandedPreview, setExpandedPreview] = useState(false);

  // Load deck prompts on mount
  useEffect(() => {
    loadDeckPrompts();
  }, []);

  // Update selected when current prompts change
  useEffect(() => {
    setSelectedId(currentPrompts.selected_deck_prompt_id);
  }, [currentPrompts.selected_deck_prompt_id]);

  const loadDeckPrompts = async () => {
    try {
      setLoading(true);
      setError(null);
      const response = await configApi.listDeckPrompts();
      setDeckPrompts(response.prompts);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load deck prompts');
    } finally {
      setLoading(false);
    }
  };

  const isDirty = selectedId !== currentPrompts.selected_deck_prompt_id;

  const handleSave = async () => {
    try {
      setIsSaving(true);
      setError(null);
      
      await configApi.updatePromptsConfig(profileId, {
        selected_deck_prompt_id: selectedId,
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
    setSelectedId(currentPrompts.selected_deck_prompt_id);
    setError(null);
    setSuccess(false);
  };

  const selectedPrompt = deckPrompts.find(p => p.id === selectedId);

  // Group prompts by category
  const categories = Array.from(new Set(deckPrompts.map(p => p.category || 'Uncategorized')));

  if (loading) {
    return (
      <div className="flex items-center justify-center h-48">
        <div className="text-gray-600">Loading deck prompts...</div>
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
          Deck prompt selection saved!
        </div>
      )}

      {/* Description */}
      <div className="bg-blue-50 border border-blue-200 rounded p-4">
        <h3 className="text-sm font-medium text-blue-800 mb-1">What are Deck Prompts?</h3>
        <p className="text-sm text-blue-700">
          Deck prompts are reusable templates that guide how specific types of presentations are created.
          For example, a "Consumption Review" deck prompt would tell the agent what data to query and 
          how to structure the findings for a consumption review meeting.
        </p>
      </div>

      {/* Current Selection */}
      {selectedPrompt && (
        <div className="bg-purple-50 border border-purple-200 rounded p-4">
          <div className="flex items-start justify-between">
            <div className="flex-1">
              <div className="flex items-center gap-2">
                <span className="text-purple-600 text-lg">✓</span>
                <h4 className="font-medium text-purple-900">{selectedPrompt.name}</h4>
                {selectedPrompt.category && (
                  <span className="px-2 py-0.5 bg-purple-200 text-purple-800 text-xs rounded">
                    {selectedPrompt.category}
                  </span>
                )}
              </div>
              {selectedPrompt.description && (
                <p className="text-sm text-purple-700 mt-1">{selectedPrompt.description}</p>
              )}
            </div>
            <button
              onClick={() => setExpandedPreview(!expandedPreview)}
              className="text-sm text-purple-600 hover:text-purple-800"
            >
              {expandedPreview ? 'Hide preview' : 'Show preview'}
            </button>
          </div>
          
          {expandedPreview && (
            <div className="mt-3 pt-3 border-t border-purple-200">
              <pre className="text-xs text-purple-800 whitespace-pre-wrap bg-white p-3 rounded border border-purple-200 max-h-48 overflow-y-auto">
                {selectedPrompt.prompt_content}
              </pre>
            </div>
          )}
        </div>
      )}

      {/* Empty state when no selection */}
      {!selectedPrompt && (
        <div className="bg-gray-50 border border-gray-200 border-dashed rounded p-4 text-center">
          <p className="text-gray-500 text-sm">
            No deck prompt selected. The agent will use default presentation generation behavior.
          </p>
        </div>
      )}

      {/* Prompt Library */}
      <div>
        <h3 className="text-sm font-medium text-gray-700 mb-3">
          Available Deck Prompts {deckPrompts.length > 0 && `(${deckPrompts.length})`}
        </h3>

        {deckPrompts.length === 0 ? (
          <div className="text-center py-8 bg-gray-50 rounded border border-gray-200">
            <p className="text-gray-500 text-sm">No deck prompts available yet.</p>
            <p className="text-gray-400 text-xs mt-1">
              Deck prompts can be created through the API.
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
                  {deckPrompts
                    .filter(p => (p.category || 'Uncategorized') === category)
                    .map(prompt => (
                      <button
                        key={prompt.id}
                        onClick={() => setSelectedId(prompt.id)}
                        disabled={saving || isSaving}
                        className={`text-left p-4 rounded border-2 transition-all ${
                          selectedId === prompt.id
                            ? 'border-purple-500 bg-purple-50'
                            : 'border-gray-200 hover:border-gray-300 bg-white'
                        } ${(saving || isSaving) ? 'opacity-50 cursor-not-allowed' : ''}`}
                      >
                        <div className="flex items-start justify-between">
                          <h5 className={`font-medium text-sm ${
                            selectedId === prompt.id ? 'text-purple-900' : 'text-gray-900'
                          }`}>
                            {prompt.name}
                          </h5>
                          {selectedId === prompt.id && (
                            <span className="text-purple-600">✓</span>
                          )}
                        </div>
                        {prompt.description && (
                          <p className={`text-xs mt-1 line-clamp-2 ${
                            selectedId === prompt.id ? 'text-purple-700' : 'text-gray-500'
                          }`}>
                            {prompt.description}
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
            className="px-4 py-2 bg-purple-500 hover:bg-purple-600 text-white rounded transition-colors disabled:bg-purple-300 disabled:cursor-not-allowed"
          >
            {isSaving ? 'Saving...' : 'Save Selection'}
          </button>
        </div>
      </div>
    </div>
  );
};


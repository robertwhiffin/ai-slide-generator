/**
 * Deck Prompt form modal.
 * 
 * Used for creating and editing deck prompts.
 */

import React, { useState, useEffect } from 'react';
import type { DeckPrompt, DeckPromptCreate, DeckPromptUpdate } from '../../api/config';
import { ExpandableEditor } from './ExpandableEditor';

interface DeckPromptFormProps {
  isOpen: boolean;
  mode: 'create' | 'edit';
  prompt?: DeckPrompt;
  onSubmit: (data: DeckPromptCreate | DeckPromptUpdate) => Promise<void>;
  onCancel: () => void;
}

export const DeckPromptForm: React.FC<DeckPromptFormProps> = ({
  isOpen,
  mode,
  prompt,
  onSubmit,
  onCancel,
}) => {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [category, setCategory] = useState('');
  const [promptContent, setPromptContent] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !saving) onCancel();
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, saving, onCancel]);

  // Reset form when opening
  useEffect(() => {
    if (isOpen) {
      if (mode === 'edit' && prompt) {
        setName(prompt.name);
        setDescription(prompt.description || '');
        setCategory(prompt.category || '');
        setPromptContent(prompt.prompt_content);
      } else {
        setName('');
        setDescription('');
        setCategory('');
        setPromptContent('');
      }
      setError(null);
    }
  }, [isOpen, mode, prompt]);

  const validate = (): string | null => {
    if (!name.trim()) {
      return 'Name is required';
    }
    if (!promptContent.trim()) {
      return 'Prompt content is required';
    }
    return null;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    
    const validationError = validate();
    if (validationError) {
      setError(validationError);
      return;
    }

    setSaving(true);
    setError(null);

    try {
      const data: DeckPromptCreate | DeckPromptUpdate = {
        name: name.trim(),
        description: description.trim() || null,
        category: category.trim() || null,
        prompt_content: promptContent,
      };
      await onSubmit(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save');
    } finally {
      setSaving(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-50">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-4xl max-h-[90vh] overflow-hidden flex flex-col">
        {/* Header */}
        <div className="px-6 py-4 border-b bg-gray-50">
          <h2 className="text-xl font-semibold text-gray-900">
            {mode === 'create' ? 'Create Deck Prompt' : 'Edit Deck Prompt'}
          </h2>
          <p className="text-sm text-gray-600 mt-1">
            Define a reusable prompt template for generating specific types of presentations.
          </p>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto">
          <div className="p-6 space-y-4">
            {/* Error Message */}
            {error && (
              <div className="p-3 bg-red-50 border border-red-200 rounded text-red-700 text-sm">
                {error}
              </div>
            )}

            {/* Name */}
            <div>
              <label htmlFor="prompt-name" className="block text-sm font-medium text-gray-700 mb-1">
                Name <span className="text-red-500">*</span>
              </label>
              <input
                id="prompt-name"
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g., Quarterly Business Review"
                className="w-full px-3 py-2 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
                maxLength={100}
                disabled={saving}
              />
            </div>

            {/* Description */}
            <div>
              <label htmlFor="prompt-description" className="block text-sm font-medium text-gray-700 mb-1">
                Description
              </label>
              <textarea
                id="prompt-description"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Brief description of what this prompt is for..."
                className="w-full px-3 py-2 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
                rows={2}
                disabled={saving}
              />
            </div>

            {/* Category */}
            <div>
              <label htmlFor="prompt-category" className="block text-sm font-medium text-gray-700 mb-1">
                Category
              </label>
              <input
                id="prompt-category"
                type="text"
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                placeholder="e.g., Review, Report, Summary, Analysis"
                className="w-full px-3 py-2 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
                maxLength={50}
                disabled={saving}
              />
              <p className="text-xs text-gray-500 mt-1">
                Optional category for organizing prompts.
              </p>
            </div>

            {/* Prompt Content */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Prompt Content <span className="text-red-500">*</span>
              </label>
              <ExpandableEditor
                value={promptContent}
                onChange={setPromptContent}
                readOnly={saving}
                modalTitle="Prompt Content"
              />
              <p className="text-xs text-gray-500 mt-1">
                Instructions for the AI on how to create this type of presentation. 
                Include sections, data to query, and formatting guidelines.
              </p>
            </div>
          </div>

          {/* Footer */}
          <div className="px-6 py-4 border-t bg-gray-50 flex justify-end gap-3">
            <button
              type="button"
              onClick={onCancel}
              disabled={saving}
              className="px-4 py-2 bg-gray-200 hover:bg-gray-300 text-gray-800 rounded transition-colors disabled:bg-gray-100"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving}
              className="px-4 py-2 bg-blue-500 hover:bg-blue-600 text-white rounded transition-colors disabled:bg-blue-300"
            >
              {saving ? 'Saving...' : mode === 'create' ? 'Create Prompt' : 'Save Changes'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};


/**
 * Advanced Settings Editor component.
 * 
 * Power-user interface for editing:
 * - System prompt (slide generation instructions)
 * - Slide editing instructions
 * 
 * These are typically not modified by regular users.
 * User prompt template is hidden (uses default {question}).
 */

import React, { useState, useEffect } from 'react';
import Editor from '@monaco-editor/react';
import type { PromptsConfig, PromptsConfigUpdate } from '../../api/config';

interface AdvancedSettingsEditorProps {
  config: PromptsConfig;
  onSave: (data: PromptsConfigUpdate) => Promise<void>;
  saving?: boolean;
}

export const AdvancedSettingsEditor: React.FC<AdvancedSettingsEditorProps> = ({ 
  config, 
  onSave, 
  saving = false 
}) => {
  const [systemPrompt, setSystemPrompt] = useState(config.system_prompt);
  const [slideEditingInstructions, setSlideEditingInstructions] = useState(config.slide_editing_instructions);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  // Update form when config changes
  useEffect(() => {
    setSystemPrompt(config.system_prompt);
    setSlideEditingInstructions(config.slide_editing_instructions);
  }, [config]);

  const isDirty =
    systemPrompt !== config.system_prompt ||
    slideEditingInstructions !== config.slide_editing_instructions;

  const validate = (): string | null => {
    if (!systemPrompt.trim()) {
      return 'System prompt is required';
    }
    if (!slideEditingInstructions.trim()) {
      return 'Slide editing instructions are required';
    }
    return null;
  };

  const handleSave = async () => {
    setError(null);
    setSuccess(false);

    const validationError = validate();
    if (validationError) {
      setError(validationError);
      return;
    }

    try {
      await onSave({
        system_prompt: systemPrompt,
        slide_editing_instructions: slideEditingInstructions,
      });
      setSuccess(true);
      setTimeout(() => setSuccess(false), 3000);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save');
    }
  };

  const handleReset = () => {
    setSystemPrompt(config.system_prompt);
    setSlideEditingInstructions(config.slide_editing_instructions);
    setError(null);
    setSuccess(false);
  };

  return (
    <div className="space-y-6">
      {/* Warning Banner */}
      <div className="bg-amber-50 border border-amber-200 rounded p-4">
        <div className="flex items-start gap-3">
          <span className="text-amber-600 text-xl">⚠️</span>
          <div>
            <h3 className="text-sm font-medium text-amber-800">Advanced Settings</h3>
            <p className="text-sm text-amber-700 mt-1">
              These settings control how the AI generates and formats slides. 
              Only modify these if you understand the impact on slide generation behavior.
              Most users should use the Deck Prompt tab instead.
            </p>
          </div>
        </div>
      </div>

      {/* Status Messages */}
      {error && (
        <div className="p-3 bg-red-50 border border-red-200 rounded text-red-700 text-sm">
          {error}
        </div>
      )}
      {success && (
        <div className="p-3 bg-green-50 border border-green-200 rounded text-green-700 text-sm">
          Advanced settings saved successfully!
        </div>
      )}

      {/* System Prompt */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <label className="block text-sm font-medium text-gray-700">
            Slide Generation Instructions <span className="text-red-500">*</span>
          </label>
          <span className="text-xs text-gray-500">
            Controls HTML/CSS output, chart formatting, slide structure
          </span>
        </div>
        <div className="border border-gray-300 rounded overflow-hidden">
          <Editor
            height="350px"
            defaultLanguage="text"
            value={systemPrompt}
            onChange={(value) => setSystemPrompt(value || '')}
            options={{
              minimap: { enabled: false },
              wordWrap: 'on',
              lineNumbers: 'on',
              scrollBeyondLastLine: false,
              fontSize: 13,
              readOnly: saving,
            }}
          />
        </div>
        <p className="mt-1 text-xs text-gray-500">
          Core instructions for how the agent generates slides. Includes HTML structure, 
          styling rules, Chart.js configuration, and output format requirements.
        </p>
      </div>

      {/* Slide Editing Instructions */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <label className="block text-sm font-medium text-gray-700">
            Slide Editing Instructions <span className="text-red-500">*</span>
          </label>
          <span className="text-xs text-gray-500">
            How to handle edit requests on existing slides
          </span>
        </div>
        <div className="border border-gray-300 rounded overflow-hidden">
          <Editor
            height="250px"
            defaultLanguage="text"
            value={slideEditingInstructions}
            onChange={(value) => setSlideEditingInstructions(value || '')}
            options={{
              minimap: { enabled: false },
              wordWrap: 'on',
              lineNumbers: 'on',
              scrollBeyondLastLine: false,
              fontSize: 13,
              readOnly: saving,
            }}
          />
        </div>
        <p className="mt-1 text-xs text-gray-500">
          Instructions for modifying existing slides when users request edits.
          Defines the slide-context format and replacement behavior.
        </p>
      </div>

      {/* Action Buttons */}
      <div className="flex justify-end gap-3 pt-4 border-t">
        <button
          onClick={handleReset}
          disabled={!isDirty || saving}
          className="px-4 py-2 bg-gray-200 hover:bg-gray-300 text-gray-800 rounded transition-colors disabled:bg-gray-100 disabled:text-gray-400 disabled:cursor-not-allowed"
        >
          Reset
        </button>
        <button
          onClick={handleSave}
          disabled={!isDirty || saving}
          className="px-4 py-2 bg-amber-500 hover:bg-amber-600 text-white rounded transition-colors disabled:bg-amber-300 disabled:cursor-not-allowed"
        >
          {saving ? 'Saving...' : 'Save Advanced Settings'}
        </button>
      </div>
    </div>
  );
};


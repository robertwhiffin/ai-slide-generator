/**
 * Prompts configuration editor.
 * 
 * Uses Monaco Editor for rich editing of:
 * - System prompt
 * - Slide editing instructions
 * - User prompt template
 * 
 * Includes placeholder validation.
 */

import React, { useState, useEffect } from 'react';
import Editor from '@monaco-editor/react';
import type { PromptsConfig, PromptsConfigUpdate } from '../../api/config';

interface PromptsEditorProps {
  config: PromptsConfig;
  onSave: (data: PromptsConfigUpdate) => Promise<void>;
  saving?: boolean;
}

export const PromptsEditor: React.FC<PromptsEditorProps> = ({ config, onSave, saving = false }) => {
  const [systemPrompt, setSystemPrompt] = useState(config.system_prompt);
  const [slideEditingInstructions, setSlideEditingInstructions] = useState(config.slide_editing_instructions);
  const [userPromptTemplate, setUserPromptTemplate] = useState(config.user_prompt_template);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [warnings, setWarnings] = useState<string[]>([]);

  // Update form when config changes
  useEffect(() => {
    setSystemPrompt(config.system_prompt);
    setSlideEditingInstructions(config.slide_editing_instructions);
    setUserPromptTemplate(config.user_prompt_template);
  }, [config]);

  const isDirty =
    systemPrompt !== config.system_prompt ||
    slideEditingInstructions !== config.slide_editing_instructions ||
    userPromptTemplate !== config.user_prompt_template;

  // Validate placeholders
  useEffect(() => {
    const newWarnings: string[] = [];

    // Check for required placeholder in user prompt
    if (!userPromptTemplate.includes('{question}')) {
      newWarnings.push('User Prompt Template: Missing required placeholder {question}');
    }

    // Check for recommended placeholders in system prompt
    if (!systemPrompt.includes('{max_slides}')) {
      newWarnings.push('System Prompt: Missing recommended placeholder {max_slides}');
    }

    setWarnings(newWarnings);
  }, [systemPrompt, slideEditingInstructions, userPromptTemplate]);

  const validate = (): string | null => {
    if (!systemPrompt.trim()) {
      return 'System prompt is required';
    }
    if (!slideEditingInstructions.trim()) {
      return 'Slide editing instructions are required';
    }
    if (!userPromptTemplate.trim()) {
      return 'User prompt template is required';
    }
    if (!userPromptTemplate.includes('{question}')) {
      return 'User prompt template must include {question} placeholder';
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
        user_prompt_template: userPromptTemplate,
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
    setUserPromptTemplate(config.user_prompt_template);
    setError(null);
    setSuccess(false);
  };

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
          Configuration saved successfully!
        </div>
      )}
      {warnings.length > 0 && (
        <div className="p-3 bg-yellow-50 border border-yellow-200 rounded text-yellow-700 text-sm">
          <div className="font-medium mb-1">⚠️ Warnings:</div>
          <ul className="list-disc list-inside space-y-1">
            {warnings.map((warning, idx) => (
              <li key={idx}>{warning}</li>
            ))}
          </ul>
        </div>
      )}

      {/* System Prompt */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <label className="block text-sm font-medium text-gray-700">
            System Prompt <span className="text-red-500">*</span>
          </label>
          <span className="text-xs text-gray-500">
            Available: <code className="px-1 bg-gray-100 rounded">{'{max_slides}'}</code>
          </span>
        </div>
        <div className="border border-gray-300 rounded overflow-hidden">
          <Editor
            height="300px"
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
          Base instructions for the LLM. Sets the context and tone for slide generation.
        </p>
      </div>

      {/* Slide Editing Instructions */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">
          Slide Editing Instructions <span className="text-red-500">*</span>
        </label>
        <div className="border border-gray-300 rounded overflow-hidden">
          <Editor
            height="200px"
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
          Additional instructions for editing existing slides.
        </p>
      </div>

      {/* User Prompt Template */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <label className="block text-sm font-medium text-gray-700">
            User Prompt Template <span className="text-red-500">*</span>
          </label>
          <span className="text-xs text-gray-500">
            Required: <code className="px-1 bg-gray-100 rounded">{'{question}'}</code>
          </span>
        </div>
        <div className="border border-gray-300 rounded overflow-hidden">
          <Editor
            height="100px"
            defaultLanguage="text"
            value={userPromptTemplate}
            onChange={(value) => setUserPromptTemplate(value || '')}
            options={{
              minimap: { enabled: false },
              wordWrap: 'on',
              lineNumbers: 'off',
              scrollBeyondLastLine: false,
              fontSize: 13,
              readOnly: saving,
            }}
          />
        </div>
        <p className="mt-1 text-xs text-gray-500">
          Template for user messages. The <code className="px-1 bg-gray-100 rounded">{'{question}'}</code> placeholder is replaced with user input.
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
          className="px-4 py-2 bg-blue-500 hover:bg-blue-600 text-white rounded transition-colors disabled:bg-blue-300 disabled:cursor-not-allowed"
        >
          {saving ? 'Saving...' : 'Save Changes'}
        </button>
      </div>
    </div>
  );
};


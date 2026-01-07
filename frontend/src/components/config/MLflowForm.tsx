/**
 * MLflow configuration form.
 * 
 * Simple form for MLflow experiment name with validation.
 * The experiment name is auto-populated when a profile is created
 * based on the creator's username.
 */

import React, { useState, useEffect } from 'react';
import type { MLflowConfig, MLflowConfigUpdate } from '../../api/config';
import { configApi } from '../../api/config';

interface MLflowFormProps {
  config: MLflowConfig;
  onSave: (data: MLflowConfigUpdate) => Promise<void>;
  saving?: boolean;
}

export const MLflowForm: React.FC<MLflowFormProps> = ({ config, onSave, saving = false }) => {
  const [experimentName, setExperimentName] = useState(config.experiment_name);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [validating, setValidating] = useState(false);
  const [validationResult, setValidationResult] = useState<{ success: boolean; message: string } | null>(null);

  // Update form when config changes
  useEffect(() => {
    setExperimentName(config.experiment_name);
  }, [config]);

  const isDirty = experimentName !== config.experiment_name;

  const validate = (): string | null => {
    if (!experimentName.trim()) {
      return 'Experiment name is required';
    }
    if (!experimentName.startsWith('/')) {
      return 'Experiment name must start with / (e.g., /Workspace/Users/...)';
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
        experiment_name: experimentName.trim(),
      });
      setSuccess(true);
      setTimeout(() => setSuccess(false), 3000);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save');
    }
  };

  const handleReset = () => {
    setExperimentName(config.experiment_name);
    setError(null);
    setSuccess(false);
    setValidationResult(null);
  };

  const handleValidate = async () => {
    setValidating(true);
    setValidationResult(null);
    setError(null);

    try {
      const result = await configApi.validateMLflow(experimentName);
      setValidationResult(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Validation failed');
    } finally {
      setValidating(false);
    }
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
      {validationResult && (
        <div className={`p-3 border rounded text-sm ${
          validationResult.success 
            ? 'bg-green-50 border-green-200 text-green-700' 
            : 'bg-yellow-50 border-yellow-200 text-yellow-700'
        }`}>
          <strong>Validation:</strong> {validationResult.message}
        </div>
      )}

      {/* Experiment Name Input */}
      <div>
        <label htmlFor="experiment-name" className="block text-sm font-medium text-gray-700 mb-1">
          Experiment Name <span className="text-red-500">*</span>
        </label>
        <input
          id="experiment-name"
          type="text"
          value={experimentName}
          onChange={(e) => setExperimentName(e.target.value)}
          placeholder="/Workspace/Users/..."
          className="w-full px-3 py-2 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono text-sm"
          disabled={saving}
        />
        <div className="mt-2 text-xs text-gray-600 space-y-1">
          <p>
            <strong>Format:</strong> Must start with <code className="px-1 bg-gray-100 rounded">/</code>
          </p>
          <p>
            This value was automatically set based on the profile creator's username.
            You can customize it if needed.
          </p>
          <p>
            MLflow experiments are used to track model training and inference metrics.
          </p>
        </div>
      </div>

      {/* Action Buttons */}
      <div className="flex justify-between pt-4 border-t">
        <button
          onClick={handleValidate}
          disabled={validating || saving || !experimentName.trim()}
          className="px-4 py-2 bg-purple-500 hover:bg-purple-600 text-white rounded transition-colors disabled:bg-purple-300 disabled:cursor-not-allowed"
        >
          {validating ? 'Validating...' : 'Test Connection'}
        </button>
        <div className="flex gap-3">
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
    </div>
  );
};


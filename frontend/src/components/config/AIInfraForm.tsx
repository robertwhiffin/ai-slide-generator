/**
 * AI Infrastructure configuration form.
 *
 * Allows editing:
 * - LLM Endpoint selection (with searchable dropdown)
 * - Temperature slider (0.0 - 1.0)
 * - Max tokens input
 */

import React, { useState, useEffect } from 'react';
import { AlertCircle, CheckCircle } from 'lucide-react';
import { Button } from '@/ui/button';
import type { AIInfraConfig, AIInfraConfigUpdate } from '../../api/config';
import { configApi } from '../../api/config';
import { useEndpoints } from '../../hooks/useEndpoints';

interface AIInfraFormProps {
  config: AIInfraConfig;
  onSave: (data: AIInfraConfigUpdate) => Promise<void>;
  saving?: boolean;
}

export const AIInfraForm: React.FC<AIInfraFormProps> = ({ config, onSave, saving = false }) => {
  const { endpoints, loading: loadingEndpoints, error: endpointsError } = useEndpoints();
  
  const [llmEndpoint, setLlmEndpoint] = useState(config.llm_endpoint);
  const [llmTemperature, setLlmTemperature] = useState(config.llm_temperature);
  const [llmMaxTokens, setLlmMaxTokens] = useState(config.llm_max_tokens);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [validating, setValidating] = useState(false);
  const [validationResult, setValidationResult] = useState<{ success: boolean; message: string } | null>(null);

  // Update form when config changes
  useEffect(() => {
    setLlmEndpoint(config.llm_endpoint);
    setLlmTemperature(config.llm_temperature);
    setLlmMaxTokens(config.llm_max_tokens);
  }, [config]);

  const isDirty = 
    llmEndpoint !== config.llm_endpoint ||
    llmTemperature !== config.llm_temperature ||
    llmMaxTokens !== config.llm_max_tokens;

  const validate = (): string | null => {
    if (!llmEndpoint.trim()) {
      return 'LLM endpoint is required';
    }
    if (llmTemperature < 0 || llmTemperature > 1) {
      return 'Temperature must be between 0.0 and 1.0';
    }
    if (llmMaxTokens <= 0 || !Number.isInteger(llmMaxTokens)) {
      return 'Max tokens must be a positive integer';
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
        llm_endpoint: llmEndpoint,
        llm_temperature: llmTemperature,
        llm_max_tokens: llmMaxTokens,
      });
      setSuccess(true);
      setTimeout(() => setSuccess(false), 3000);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save');
    }
  };

  const handleReset = () => {
    setLlmEndpoint(config.llm_endpoint);
    setLlmTemperature(config.llm_temperature);
    setLlmMaxTokens(config.llm_max_tokens);
    setError(null);
    setSuccess(false);
    setValidationResult(null);
  };

  const handleValidate = async () => {
    setValidating(true);
    setValidationResult(null);
    setError(null);

    try {
      const result = await configApi.validateLLM(llmEndpoint);
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
        <div className="flex items-center gap-2 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
          <AlertCircle className="size-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}
      {success && (
        <div className="flex items-center gap-2 rounded-md border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-700">
          <CheckCircle className="size-4 shrink-0" />
          <span>Configuration saved successfully!</span>
        </div>
      )}
      {validationResult && (
        <div className={`flex items-center gap-2 rounded-md border px-3 py-2 text-sm ${
          validationResult.success
            ? 'border-green-200 bg-green-50 text-green-700'
            : 'border-yellow-200 bg-yellow-50 text-yellow-700'
        }`}>
          {validationResult.success ? (
            <CheckCircle className="size-4 shrink-0" />
          ) : (
            <AlertCircle className="size-4 shrink-0" />
          )}
          <span><strong>Validation:</strong> {validationResult.message}</span>
        </div>
      )}

      {/* LLM Endpoint Selection */}
      <div>
        <label htmlFor="llm-endpoint" className="block text-sm font-medium text-gray-700 mb-1">
          LLM Endpoint <span className="text-red-500">*</span>
        </label>
        
        {loadingEndpoints ? (
          <div className="text-sm text-gray-500">Loading endpoints...</div>
        ) : endpointsError ? (
          <div>
            <input
              id="llm-endpoint"
              type="text"
              value={llmEndpoint}
              onChange={(e) => setLlmEndpoint(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
              disabled={saving}
            />
            <p className="mt-1 text-xs text-yellow-600">
              Could not load endpoints. Enter manually.
            </p>
          </div>
        ) : (
          <select
            id="llm-endpoint"
            value={llmEndpoint}
            onChange={(e) => setLlmEndpoint(e.target.value)}
            className="w-full px-3 py-2 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
            disabled={saving}
          >
            <option value="">Select an endpoint...</option>
            
            {/* Databricks endpoints group */}
            {endpoints.filter(ep => ep.startsWith('databricks-')).length > 0 && (
              <optgroup label="Databricks Endpoints">
                {endpoints
                  .filter(ep => ep.startsWith('databricks-'))
                  .map(ep => (
                    <option key={ep} value={ep}>{ep}</option>
                  ))}
              </optgroup>
            )}
            
            {/* Other endpoints group */}
            {endpoints.filter(ep => !ep.startsWith('databricks-')).length > 0 && (
              <optgroup label="Other Endpoints">
                {endpoints
                  .filter(ep => !ep.startsWith('databricks-'))
                  .map(ep => (
                    <option key={ep} value={ep}>{ep}</option>
                  ))}
              </optgroup>
            )}
          </select>
        )}
        <p className="mt-1 text-xs text-gray-500">
          Databricks Model Serving endpoint name
        </p>
      </div>

      {/* Temperature Slider */}
      <div>
        <label htmlFor="temperature" className="block text-sm font-medium text-gray-700 mb-1">
          Temperature: <span className="font-mono text-blue-600">{llmTemperature.toFixed(1)}</span>
        </label>
        <div className="flex items-center gap-4">
          <input
            id="temperature"
            type="range"
            min="0"
            max="1"
            step="0.1"
            value={llmTemperature}
            onChange={(e) => setLlmTemperature(parseFloat(e.target.value))}
            className="flex-1"
            disabled={saving}
          />
          <input
            type="number"
            min="0"
            max="1"
            step="0.1"
            value={llmTemperature}
            onChange={(e) => setLlmTemperature(parseFloat(e.target.value) || 0)}
            className="w-20 px-2 py-1 border border-gray-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            disabled={saving}
          />
        </div>
        <p className="mt-1 text-xs text-gray-500">
          Controls randomness: 0.0 = deterministic, 1.0 = creative
        </p>
      </div>

      {/* Max Tokens Input */}
      <div>
        <label htmlFor="max-tokens" className="block text-sm font-medium text-gray-700 mb-1">
          Max Tokens <span className="text-red-500">*</span>
        </label>
        <input
          id="max-tokens"
          type="number"
          min="1"
          value={llmMaxTokens}
          onChange={(e) => setLlmMaxTokens(parseInt(e.target.value) || 0)}
          className="w-full px-3 py-2 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
          disabled={saving}
        />
        <p className="mt-1 text-xs text-gray-500">
          Maximum tokens in model response. Typical: 4000-8000
        </p>
      </div>

      {/* Action Buttons */}
      <div className="flex justify-between border-t border-border pt-4">
        <Button
          variant="secondary"
          onClick={handleValidate}
          disabled={validating || saving || !llmEndpoint.trim()}
        >
          {validating ? 'Validating...' : 'Test Connection'}
        </Button>
        <div className="flex gap-2">
          <Button
            variant="outline"
            onClick={handleReset}
            disabled={!isDirty || saving}
          >
            Reset
          </Button>
          <Button
            onClick={handleSave}
            disabled={!isDirty || saving}
          >
            {saving ? 'Saving...' : 'Save Changes'}
          </Button>
        </div>
      </div>
    </div>
  );
};


/**
 * Configuration validation button component.
 * 
 * Tests all components of a profile configuration:
 * - LLM endpoint connectivity
 * - Genie space access
 * - MLflow experiment permissions
 */

import React, { useState } from 'react';
import type { ValidationResponse, ValidationComponentResult } from '../../api/config';
import { configApi, ConfigApiError } from '../../api/config';

interface ValidationButtonProps {
  profileId: number;
  profileName: string;
}

export const ValidationButton: React.FC<ValidationButtonProps> = ({
  profileId,
  profileName,
}) => {
  const [isValidating, setIsValidating] = useState(false);
  const [showResults, setShowResults] = useState(false);
  const [results, setResults] = useState<ValidationResponse | null>(null);

  const handleValidate = async () => {
    try {
      setIsValidating(true);
      setShowResults(false);
      
      const response = await configApi.validateProfile(profileId);
      setResults(response);
      setShowResults(true);
    } catch (err) {
      const message = err instanceof ConfigApiError 
        ? err.message 
        : 'Failed to validate configuration';
      
      setResults({
        success: false,
        profile_id: profileId,
        profile_name: profileName,
        results: [],
        error: message,
      });
      setShowResults(true);
    } finally {
      setIsValidating(false);
    }
  };

  const getStatusIcon = (success: boolean) => {
    return success ? '✅' : '❌';
  };

  const getStatusColor = (success: boolean) => {
    return success ? 'text-green-700' : 'text-red-700';
  };

  const getStatusBg = (success: boolean) => {
    return success ? 'bg-green-50 border-green-200' : 'bg-red-50 border-red-200';
  };

  return (
    <div className="space-y-4">
      <button
        onClick={handleValidate}
        disabled={isValidating}
        className="px-4 py-2 bg-purple-600 hover:bg-purple-700 text-white rounded-md transition-colors disabled:bg-gray-400 disabled:cursor-not-allowed flex items-center gap-2"
      >
        {isValidating ? (
          <>
            <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
            <span>Testing Configuration...</span>
          </>
        ) : (
          <>
            <span>🧪</span>
            <span>Test Configuration</span>
          </>
        )}
      </button>

      {showResults && results && (
        <div className={`border rounded-lg p-4 ${getStatusBg(results.success)}`}>
          <div className="flex items-center gap-2 mb-3">
            <span className="text-2xl">{getStatusIcon(results.success)}</span>
            <h3 className={`font-semibold text-lg ${getStatusColor(results.success)}`}>
              {results.success ? 'All Tests Passed' : 'Configuration Issues Detected'}
            </h3>
          </div>

          {results.error && (
            <div className="text-red-700 mb-3">
              <p className="font-medium">Error:</p>
              <p className="text-sm">{results.error}</p>
            </div>
          )}

          {results.results && results.results.length > 0 && (
            <div className="space-y-3">
              {results.results.map((result: ValidationComponentResult, index: number) => (
                <div
                  key={index}
                  className={`border rounded-md p-3 ${getStatusBg(result.success)}`}
                >
                  <div className="flex items-start gap-2">
                    <span>{getStatusIcon(result.success)}</span>
                    <div className="flex-1">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="font-medium">{result.component}</span>
                        <span className={`text-xs px-2 py-0.5 rounded ${
                          result.success 
                            ? 'bg-green-100 text-green-800' 
                            : 'bg-red-100 text-red-800'
                        }`}>
                          {result.success ? 'PASS' : 'FAIL'}
                        </span>
                      </div>
                      <p className="text-sm mb-1">{result.message}</p>
                      {result.details && (
                        <p className="text-xs text-gray-600 italic">{result.details}</p>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}

          <div className="mt-4 text-xs text-gray-600 space-y-1">
            <p>• <strong>LLM Test:</strong> Sends "hello" message to verify endpoint connectivity</p>
            <p>• <strong>Genie Test:</strong> Queries "Return a table of how many rows you have per table"</p>
            <p>• <strong>MLflow Test:</strong> Verifies experiment creation/write permissions</p>
          </div>
        </div>
      )}
    </div>
  );
};


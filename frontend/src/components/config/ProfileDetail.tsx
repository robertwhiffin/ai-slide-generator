/**
 * Profile detail view component.
 * 
 * Displays all configuration settings for a profile:
 * - AI Infrastructure (endpoint, temperature, max tokens)
 * - Genie Spaces
 * - MLflow configuration
 * - Prompts
 */

import React, { useEffect, useState } from 'react';
import type { ProfileDetail } from '../../api/config';
import { configApi, ConfigApiError } from '../../api/config';

interface ProfileDetailProps {
  profileId: number;
  onClose: () => void;
}

export const ProfileDetailView: React.FC<ProfileDetailProps> = ({ profileId, onClose }) => {
  const [profile, setProfile] = useState<ProfileDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const loadProfile = async () => {
      try {
        setLoading(true);
        setError(null);
        const data = await configApi.getProfile(profileId);
        setProfile(data);
      } catch (err) {
        const message = err instanceof ConfigApiError 
          ? err.message 
          : 'Failed to load profile details';
        setError(message);
      } finally {
        setLoading(false);
      }
    };

    loadProfile();
  }, [profileId]);

  if (loading) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-50">
        <div className="bg-white rounded-lg shadow-xl p-8">
          <div className="text-center">Loading profile details...</div>
        </div>
      </div>
    );
  }

  if (error || !profile) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-50">
        <div className="bg-white rounded-lg shadow-xl p-8 max-w-md">
          <div className="text-red-600 mb-4">Error: {error || 'Profile not found'}</div>
          <button
            onClick={onClose}
            className="px-4 py-2 bg-gray-500 hover:bg-gray-600 text-white rounded transition-colors"
          >
            Close
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-50 overflow-y-auto">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-4xl mx-4 my-8">
        {/* Header */}
        <div className="px-6 py-4 border-b flex items-center justify-between bg-blue-50">
          <div>
            <h2 className="text-xl font-semibold text-gray-900">{profile.name}</h2>
            {profile.description && (
              <p className="text-sm text-gray-600 mt-1">{profile.description}</p>
            )}
            <div className="flex gap-2 mt-2">
              {profile.is_default && (
                <span className="px-2 py-1 bg-blue-100 text-blue-700 text-xs rounded">
                  Default
                </span>
              )}
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-gray-500 hover:text-gray-700 text-2xl"
          >
            ✕
          </button>
        </div>

        {/* Content */}
        <div className="px-6 py-4 max-h-[70vh] overflow-y-auto">
          {/* AI Infrastructure */}
          <div className="mb-6">
            <h3 className="text-lg font-semibold text-gray-900 mb-3 flex items-center gap-2">
              <span className="text-blue-600">🤖</span> AI Infrastructure
            </h3>
            <div className="bg-gray-50 rounded p-4 space-y-2">
              <div className="grid grid-cols-3 gap-4">
                <div>
                  <label className="text-xs font-medium text-gray-500 uppercase">LLM Endpoint</label>
                  <p className="text-sm text-gray-900 mt-1 font-mono">{profile.ai_infra.llm_endpoint}</p>
                </div>
                <div>
                  <label className="text-xs font-medium text-gray-500 uppercase">Temperature</label>
                  <p className="text-sm text-gray-900 mt-1">{profile.ai_infra.llm_temperature}</p>
                </div>
                <div>
                  <label className="text-xs font-medium text-gray-500 uppercase">Max Tokens</label>
                  <p className="text-sm text-gray-900 mt-1">{profile.ai_infra.llm_max_tokens}</p>
                </div>
              </div>
            </div>
          </div>

          {/* Genie Spaces */}
          <div className="mb-6">
            <h3 className="text-lg font-semibold text-gray-900 mb-3 flex items-center gap-2">
              <span className="text-purple-600">🧞</span> Genie Spaces
            </h3>
            <div className="space-y-2">
              {profile.genie_spaces.length > 0 ? (
                profile.genie_spaces.map((space) => (
                  <div key={space.id} className="bg-gray-50 rounded p-4">
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <span className="font-medium text-gray-900">{space.space_name}</span>
                        {space.is_default && (
                          <span className="px-2 py-0.5 bg-green-100 text-green-700 text-xs rounded">
                            Default
                          </span>
                        )}
                      </div>
                    </div>
                    <div className="text-sm text-gray-600">
                      <span className="font-mono">{space.space_id}</span>
                    </div>
                    {space.description && (
                      <p className="text-sm text-gray-600 mt-2">{space.description}</p>
                    )}
                  </div>
                ))
              ) : (
                <p className="text-sm text-gray-500 italic">No Genie spaces configured</p>
              )}
            </div>
          </div>

          {/* MLflow */}
          <div className="mb-6">
            <h3 className="text-lg font-semibold text-gray-900 mb-3 flex items-center gap-2">
              <span className="text-green-600">📊</span> MLflow
            </h3>
            <div className="bg-gray-50 rounded p-4">
              <label className="text-xs font-medium text-gray-500 uppercase">Experiment Name</label>
              <p className="text-sm text-gray-900 mt-1 font-mono">{profile.mlflow.experiment_name}</p>
            </div>
          </div>

          {/* Prompts */}
          <div className="mb-6">
            <h3 className="text-lg font-semibold text-gray-900 mb-3 flex items-center gap-2">
              <span className="text-orange-600">💬</span> Prompts
            </h3>
            <div className="space-y-4">
              <div className="bg-gray-50 rounded p-4">
                <label className="text-xs font-medium text-gray-500 uppercase">System Prompt</label>
                <pre className="text-xs text-gray-900 mt-2 whitespace-pre-wrap font-mono bg-white p-3 rounded border border-gray-200 max-h-40 overflow-y-auto">
                  {profile.prompts.system_prompt}
                </pre>
              </div>
              <div className="bg-gray-50 rounded p-4">
                <label className="text-xs font-medium text-gray-500 uppercase">Slide Editing Instructions</label>
                <pre className="text-xs text-gray-900 mt-2 whitespace-pre-wrap font-mono bg-white p-3 rounded border border-gray-200 max-h-40 overflow-y-auto">
                  {profile.prompts.slide_editing_instructions}
                </pre>
              </div>
              <div className="bg-gray-50 rounded p-4">
                <label className="text-xs font-medium text-gray-500 uppercase">User Prompt Template</label>
                <pre className="text-xs text-gray-900 mt-2 whitespace-pre-wrap font-mono bg-white p-3 rounded border border-gray-200 max-h-40 overflow-y-auto">
                  {profile.prompts.user_prompt_template}
                </pre>
              </div>
            </div>
          </div>

          {/* Metadata */}
          <div className="border-t pt-4">
            <h3 className="text-sm font-semibold text-gray-500 mb-2">Metadata</h3>
            <div className="grid grid-cols-2 gap-4 text-xs text-gray-600">
              <div>
                <span className="font-medium">Created:</span> {new Date(profile.created_at).toLocaleString()}
                {profile.created_by && <span className="ml-1">by {profile.created_by}</span>}
              </div>
              <div>
                <span className="font-medium">Updated:</span> {new Date(profile.updated_at).toLocaleString()}
                {profile.updated_by && <span className="ml-1">by {profile.updated_by}</span>}
              </div>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t flex justify-end">
          <button
            onClick={onClose}
            className="px-4 py-2 bg-blue-500 hover:bg-blue-600 text-white rounded transition-colors"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
};


/**
 * Profile detail view component.
 * 
 * Displays and allows editing of all configuration settings for a profile:
 * - Profile name and description
 * - AI Infrastructure (endpoint, temperature, max tokens)
 * - Genie Spaces
 * - MLflow configuration
 * - Prompts
 */

import React, { useEffect, useState } from 'react';
import type { ProfileDetail } from '../../api/config';
import { configApi, ConfigApiError } from '../../api/config';
import { ConfigTabs } from './ConfigTabs';

type ViewMode = 'view' | 'edit';

interface ProfileDetailProps {
  profileId: number;
  onClose: () => void;
}

export const ProfileDetailView: React.FC<ProfileDetailProps> = ({ profileId, onClose }) => {
  const [profile, setProfile] = useState<ProfileDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<ViewMode>('view');
  
  // Editable profile metadata
  const [editedName, setEditedName] = useState('');
  const [editedDescription, setEditedDescription] = useState('');
  const [isSavingMetadata, setIsSavingMetadata] = useState(false);
  const [metadataError, setMetadataError] = useState<string | null>(null);

  useEffect(() => {
    const loadProfile = async () => {
      try {
        setLoading(true);
        setError(null);
        const data = await configApi.getProfile(profileId);
        setProfile(data);
        setEditedName(data.name);
        setEditedDescription(data.description || '');
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

  const handleSaveMetadata = async () => {
    if (!profile) return;
    
    try {
      setIsSavingMetadata(true);
      setMetadataError(null);
      
      const updated = await configApi.updateProfile(profile.id, {
        name: editedName,
        description: editedDescription || null,
      });
      
      setProfile(updated);
    } catch (err) {
      const message = err instanceof ConfigApiError 
        ? err.message 
        : 'Failed to update profile';
      setMetadataError(message);
    } finally {
      setIsSavingMetadata(false);
    }
  };

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
    <div className="fixed inset-0 z-50 bg-black bg-opacity-50 overflow-y-auto">
      <div className="min-h-screen flex items-start justify-center p-4 sm:p-6">
        <div className="bg-white rounded-lg shadow-xl w-full max-w-4xl my-8">
        {/* Header */}
        <div className="px-6 py-4 border-b bg-blue-50">
          <div className="flex items-start justify-between">
            <div className="flex-1 mr-4">
              {mode === 'edit' ? (
                /* Edit Mode - Show Input Fields */
                <div className="space-y-3">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">
                      Profile Name
                    </label>
                    <input
                      type="text"
                      value={editedName}
                      onChange={(e) => setEditedName(e.target.value)}
                      className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500"
                      placeholder="Profile name"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">
                      Description (optional)
                    </label>
                    <textarea
                      value={editedDescription}
                      onChange={(e) => setEditedDescription(e.target.value)}
                      className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500"
                      placeholder="Profile description"
                      rows={2}
                    />
                  </div>
                  {metadataError && (
                    <div className="text-sm text-red-600">{metadataError}</div>
                  )}
                  <button
                    onClick={handleSaveMetadata}
                    disabled={isSavingMetadata || !editedName.trim()}
                    className="px-4 py-2 bg-green-600 hover:bg-green-700 text-white text-sm rounded transition-colors disabled:bg-gray-400"
                  >
                    {isSavingMetadata ? 'Saving...' : 'Save Profile Info'}
                  </button>
                </div>
              ) : (
                /* View Mode - Show Text */
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
              )}
            </div>
            
            <div className="flex items-center gap-3">
              {/* View/Edit Toggle */}
              <div className="flex gap-1 bg-white rounded border border-gray-300">
                <button
                  onClick={() => setMode('view')}
                  className={`px-3 py-1 text-sm rounded transition-colors ${
                    mode === 'view'
                      ? 'bg-blue-500 text-white'
                      : 'text-gray-600 hover:text-gray-900'
                  }`}
                >
                  View
                </button>
                <button
                  onClick={() => setMode('edit')}
                  className={`px-3 py-1 text-sm rounded transition-colors ${
                    mode === 'edit'
                      ? 'bg-blue-500 text-white'
                      : 'text-gray-600 hover:text-gray-900'
                  }`}
                >
                  Edit
                </button>
              </div>
              
              <button
                onClick={onClose}
                className="text-gray-500 hover:text-gray-700 text-2xl"
              >
                ✕
              </button>
            </div>
          </div>
        </div>

        {/* Content */}
        <div className="px-6 py-4 max-h-[70vh] overflow-y-auto">
          {mode === 'edit' ? (
            /* Edit Mode - Show ConfigTabs */
            <ConfigTabs profileId={profile.id} profileName={profile.name} />
          ) : (
            /* View Mode - Show Read-Only Details */
            <div>
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
          )}
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
    </div>
  );
};


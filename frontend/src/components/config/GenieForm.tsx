/**
 * Genie Space configuration form.
 * 
 * Allows selecting a single Genie space from available spaces in Databricks.
 * Replaces the multi-space manager with a simple dropdown selection.
 */

import React, { useState, useEffect } from 'react';
import type { GenieSpace } from '../../api/config';
import { configApi, ConfigApiError } from '../../api/config';

interface GenieFormProps {
  profileId: number;
  onSave: () => Promise<void>;
  saving?: boolean;
}

export const GenieForm: React.FC<GenieFormProps> = ({
  profileId,
  onSave,
  saving = false,
}) => {
  const [currentSpace, setCurrentSpace] = useState<GenieSpace | null>(null);
  const [availableSpaces, setAvailableSpaces] = useState<Record<string, string>>({});
  const [selectedSpaceId, setSelectedSpaceId] = useState('');
  const [searchTerm, setSearchTerm] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

  // Load current and available spaces
  useEffect(() => {
    const loadData = async () => {
      try {
        setLoading(true);
        setError(null);
        
        // Load current space and available spaces in parallel
        const [spaces, available] = await Promise.all([
          configApi.listGenieSpaces(profileId),
          configApi.getAvailableGenieSpaces(),
        ]);
        
        // Set current space (should only be one)
        if (spaces.length > 0) {
          setCurrentSpace(spaces[0]);
          setSelectedSpaceId(spaces[0].space_id);
        }
        
        setAvailableSpaces(available);
      } catch (err) {
        const message = err instanceof ConfigApiError 
          ? err.message 
          : 'Failed to load Genie spaces';
        setError(message);
        console.error('Error loading Genie spaces:', err);
      } finally {
        setLoading(false);
      }
    };

    loadData();
  }, [profileId]);

  const handleSave = async () => {
    if (!selectedSpaceId) {
      setSaveError('Please select a Genie space');
      return;
    }

    try {
      setSaveError(null);
      
      // Find the selected space name
      const spaceName = Object.keys(availableSpaces).find(
        name => availableSpaces[name] === selectedSpaceId
      ) || selectedSpaceId;

      if (currentSpace) {
        // Update existing space
        await configApi.updateGenieSpace(currentSpace.id, {
          space_name: spaceName,
          description: `Genie Space: ${spaceName}`,
        });
        
        // Also update the space_id if it changed
        // Note: This might require a different API endpoint
        // For now, we'll delete and re-create if the ID changed
        if (currentSpace.space_id !== selectedSpaceId) {
          await configApi.deleteGenieSpace(currentSpace.id);
          await configApi.addGenieSpace(profileId, {
            space_id: selectedSpaceId,
            space_name: spaceName,
            description: `Genie Space: ${spaceName}`,
            is_default: true,
          });
        }
      } else {
        // Create new space
        await configApi.addGenieSpace(profileId, {
          space_id: selectedSpaceId,
          space_name: spaceName,
          description: `Genie Space: ${spaceName}`,
          is_default: true,
        });
      }

      await onSave();
      
      // Reload data
      const spaces = await configApi.listGenieSpaces(profileId);
      if (spaces.length > 0) {
        setCurrentSpace(spaces[0]);
      }
    } catch (err) {
      const message = err instanceof ConfigApiError 
        ? err.message 
        : 'Failed to save Genie space';
      setSaveError(message);
      console.error('Error saving Genie space:', err);
    }
  };

  // Filter spaces by search term
  const filteredSpaces = Object.entries(availableSpaces).filter(([name]) =>
    name.toLowerCase().includes(searchTerm.toLowerCase())
  );

  if (loading) {
    return (
      <div className="p-4 text-center text-gray-600">
        Loading Genie spaces...
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4 bg-red-50 border border-red-200 rounded text-red-700">
        <p className="font-medium">Error loading Genie spaces</p>
        <p className="text-sm mt-1">{error}</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
          <span className="text-purple-600">🧞</span> Genie Space Configuration
        </h3>
        <p className="text-sm text-gray-600 mb-4">
          Select a Genie space to use for natural language data queries. Only one space can be configured per profile.
        </p>
      </div>

      {/* Current Space Display */}
      {currentSpace && (
        <div className="bg-gray-50 border border-gray-200 rounded-lg p-4">
          <div className="text-sm text-gray-600 mb-1">Current Genie Space</div>
          <div className="font-medium text-gray-900">{currentSpace.space_name}</div>
          <div className="text-sm text-gray-500 mt-1">ID: {currentSpace.space_id}</div>
        </div>
      )}

      {/* Space Selection */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">
          Select Genie Space
        </label>
        
        {/* Search Input */}
        <input
          type="text"
          placeholder="Search spaces..."
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500 mb-2"
        />

        {/* Dropdown */}
        <select
          value={selectedSpaceId}
          onChange={(e) => setSelectedSpaceId(e.target.value)}
          className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500"
          disabled={saving}
        >
          <option value="">-- Select a Genie Space --</option>
          {filteredSpaces.map(([name, id]) => (
            <option key={id} value={id}>
              {name}
            </option>
          ))}
        </select>

        {filteredSpaces.length === 0 && searchTerm && (
          <p className="mt-2 text-sm text-gray-500">
            No spaces found matching "{searchTerm}"
          </p>
        )}

        {Object.keys(availableSpaces).length === 0 && (
          <p className="mt-2 text-sm text-yellow-600">
            No Genie spaces available. Create a Genie space in Databricks first.
          </p>
        )}
      </div>

      {/* Error Message */}
      {saveError && (
        <div className="bg-red-50 border border-red-200 rounded-md p-3 text-sm text-red-700">
          {saveError}
        </div>
      )}

      {/* Save Button */}
      <div className="flex justify-end">
        <button
          onClick={handleSave}
          disabled={saving || !selectedSpaceId}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-md transition-colors disabled:bg-gray-400 disabled:cursor-not-allowed"
        >
          {saving ? 'Saving...' : 'Save Genie Configuration'}
        </button>
      </div>

      {/* Help Text */}
      <div className="text-xs text-gray-500 space-y-1">
        <p>• Genie spaces must be created in your Databricks workspace first</p>
        <p>• Only one space can be configured per profile</p>
        <p>• The space must have appropriate permissions and data access</p>
      </div>
    </div>
  );
};


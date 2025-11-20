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
  const [availableSpaces, setAvailableSpaces] = useState<{[spaceId: string]: {title: string; description: string}}>({});
  const [sortedTitles, setSortedTitles] = useState<string[]>([]);
  const [selectedSpaceId, setSelectedSpaceId] = useState('');
  const [description, setDescription] = useState('');
  const [searchTerm, setSearchTerm] = useState('');
  const [loading, setLoading] = useState(true);
  const [loadingSpaces, setLoadingSpaces] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [spacesLoaded, setSpacesLoaded] = useState(false);
  const [validating, setValidating] = useState(false);
  const [validationResult, setValidationResult] = useState<{ success: boolean; message: string } | null>(null);

  // Load current space on mount
  useEffect(() => {
    const loadCurrentSpace = async () => {
      try {
        setLoading(true);
        setError(null);
        
        const space = await configApi.getGenieSpace(profileId);
        
        // Set current space
        setCurrentSpace(space);
        setSelectedSpaceId(space.space_id);
        setDescription(space.description || '');
      } catch (err) {
        // 404 means no space configured yet - this is okay
        if (err instanceof ConfigApiError && err.message.includes('404')) {
          // No space configured, leave as null
          setCurrentSpace(null);
        } else {
          const message = err instanceof ConfigApiError 
            ? err.message 
            : 'Failed to load current Genie space';
          setError(message);
          console.error('Error loading current Genie space:', err);
        }
      } finally {
        setLoading(false);
      }
    };

    loadCurrentSpace();
  }, [profileId]);

  // Load available spaces only once (cached)
  const loadAvailableSpaces = async () => {
    if (spacesLoaded) return; // Already loaded
    
    try {
      setLoadingSpaces(true);
      const available = await configApi.getAvailableGenieSpaces();
      setAvailableSpaces(available.spaces);
      setSortedTitles(available.sorted_titles);
      setSpacesLoaded(true);
    } catch (err) {
      const message = err instanceof ConfigApiError 
        ? err.message 
        : 'Failed to load available Genie spaces';
      setError(message);
      console.error('Error loading available Genie spaces:', err);
    } finally {
      setLoadingSpaces(false);
    }
  };

  const handleValidate = async () => {
    setValidating(true);
    setValidationResult(null);
    setSaveError(null);

    try {
      const result = await configApi.validateGenie(selectedSpaceId);
      setValidationResult(result);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Validation failed');
    } finally {
      setValidating(false);
    }
  };

  const handleSave = async () => {
    if (!selectedSpaceId) {
      setSaveError('Please select a Genie space');
      return;
    }

    if (!description.trim()) {
      setSaveError('Please provide a description of the data available in this space');
      return;
    }

    try {
      setSaveError(null);
      setValidationResult(null);
      
      // Find the selected space name and auto-populate description if empty
      const spaceDetails = availableSpaces[selectedSpaceId];
      const spaceName = spaceDetails?.title || selectedSpaceId;
      
      // Use user's description if provided, otherwise use the space's default description
      const finalDescription = description.trim() || spaceDetails?.description || '';

      if (currentSpace && currentSpace.space_id === selectedSpaceId) {
        // Same space - just update the name and description
        await configApi.updateGenieSpace(currentSpace.id, {
          space_name: spaceName,
          description: finalDescription || null,
        });
      } else if (currentSpace && currentSpace.space_id !== selectedSpaceId) {
        // Different space - delete old one first, then create new one
        // (unique constraint enforces one space per profile)
        await configApi.deleteGenieSpace(currentSpace.id);
        await configApi.addGenieSpace(profileId, {
          space_id: selectedSpaceId,
          space_name: spaceName,
          description: finalDescription || null,
        });
      } else {
        // No current space - create new one
        await configApi.addGenieSpace(profileId, {
          space_id: selectedSpaceId,
          space_name: spaceName,
          description: finalDescription || null,
        });
      }

      await onSave();
      
      // Reload data
      const space = await configApi.getGenieSpace(profileId);
      setCurrentSpace(space);
    } catch (err) {
      const message = err instanceof ConfigApiError 
        ? err.message 
        : 'Failed to save Genie space';
      setSaveError(message);
      console.error('Error saving Genie space:', err);
    }
  };

  // Handle space selection change
  const handleSpaceChange = (spaceId: string) => {
    setSelectedSpaceId(spaceId);
    
    // Always update description from selected space (or clear if no description)
    if (spaceId && availableSpaces[spaceId]) {
      setDescription(availableSpaces[spaceId].description || '');
    }
  };

  // Filter spaces by search term (use sorted titles)
  const filteredTitles = sortedTitles.filter(title =>
    title.toLowerCase().includes(searchTerm.toLowerCase())
  );
  
  // Get space ID by title
  const getSpaceIdByTitle = (title: string): string | null => {
    for (const [id, details] of Object.entries(availableSpaces)) {
      if (details.title === title) return id;
    }
    return null;
  };

  if (loading) {
    return (
      <div className="p-8 flex flex-col items-center justify-center space-y-4">
        {/* Spinner */}
        <div className="relative w-16 h-16">
          <div className="absolute inset-0 border-4 border-purple-200 rounded-full"></div>
          <div className="absolute inset-0 border-4 border-purple-600 rounded-full border-t-transparent animate-spin"></div>
        </div>
        <div className="text-center">
          <p className="text-gray-700 font-medium">Loading Genie spaces...</p>
          <p className="text-sm text-gray-500 mt-1">This may take a moment</p>
        </div>
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
        <div className="bg-purple-50 border border-purple-200 rounded-lg p-4">
          <div className="text-sm text-purple-600 font-medium mb-1">Current Genie Space</div>
          <div className="font-medium text-gray-900">{currentSpace.space_name}</div>
          <div className="text-sm text-gray-500 mt-1">ID: {currentSpace.space_id}</div>
          {currentSpace.description && (
            <div className="text-sm text-gray-600 mt-2 italic">{currentSpace.description}</div>
          )}
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
          onFocus={loadAvailableSpaces}
          className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500 mb-2"
          disabled={loadingSpaces}
        />

        {/* Dropdown */}
        <select
          value={selectedSpaceId}
          onChange={(e) => handleSpaceChange(e.target.value)}
          onFocus={loadAvailableSpaces}
          className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500"
          disabled={saving || loadingSpaces}
        >
          <option value="">-- Select a Genie Space --</option>
          {filteredTitles.map((title) => {
            const spaceId = getSpaceIdByTitle(title);
            return spaceId ? (
              <option key={spaceId} value={spaceId}>
                {title}
              </option>
            ) : null;
          })}
        </select>

        {loadingSpaces && (
          <p className="mt-2 text-sm text-gray-500 flex items-center gap-2">
            <div className="w-4 h-4 border-2 border-purple-600 border-t-transparent rounded-full animate-spin"></div>
            Loading available spaces...
          </p>
        )}

        {filteredTitles.length === 0 && searchTerm && !loadingSpaces && (
          <p className="mt-2 text-sm text-gray-500">
            No spaces found matching "{searchTerm}"
          </p>
        )}

        {Object.keys(availableSpaces).length === 0 && !loadingSpaces && spacesLoaded && (
          <p className="mt-2 text-sm text-yellow-600">
            No Genie spaces available. Create a Genie space in Databricks first.
          </p>
        )}
      </div>

      {/* Description for AI Agent */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">
          Data Description (for AI Agent)
          <span className="text-red-500 ml-1">*</span>
        </label>
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Describe what data is available in this Genie space. The AI agent will use this to understand what queries it can make. E.g., 'Customer orders, product catalog, sales metrics by region and time period'"
          className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500 font-mono text-sm"
          rows={4}
          disabled={saving}
        />
        <p className="mt-2 text-xs text-gray-500">
          Provide a clear description of the data available in this Genie space. 
          The AI agent will use this to understand what information it can query.
          Be specific about tables, metrics, dimensions, and time ranges available.
        </p>
      </div>

      {/* Error Message */}
      {saveError && (
        <div className="bg-red-50 border border-red-200 rounded-md p-3 text-sm text-red-700">
          {saveError}
        </div>
      )}
      
      {/* Validation Result */}
      {validationResult && (
        <div className={`border rounded-md p-3 text-sm ${
          validationResult.success 
            ? 'bg-green-50 border-green-200 text-green-700' 
            : 'bg-yellow-50 border-yellow-200 text-yellow-700'
        }`}>
          <strong>Validation:</strong> {validationResult.message}
        </div>
      )}

      {/* Action Buttons */}
      <div className="flex justify-between">
        <button
          onClick={handleValidate}
          disabled={validating || saving || !selectedSpaceId}
          className="px-4 py-2 bg-purple-500 hover:bg-purple-600 text-white rounded-md transition-colors disabled:bg-purple-300 disabled:cursor-not-allowed"
        >
          {validating ? 'Validating...' : 'Test Connection'}
        </button>
        <button
          onClick={handleSave}
          disabled={saving || !selectedSpaceId || !description.trim()}
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


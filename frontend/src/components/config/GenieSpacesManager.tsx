/**
 * Genie Spaces management component.
 * 
 * CRUD operations for Genie spaces:
 * - List all spaces for profile
 * - Add new space
 * - Edit space (name, description)
 * - Delete space
 * - Set default space
 */

import React, { useState } from 'react';
import type { GenieSpace, GenieSpaceCreate, GenieSpaceUpdate } from '../../api/config';
import { ConfirmDialog } from './ConfirmDialog';

interface GenieSpacesManagerProps {
  spaces: GenieSpace[];
  onAdd: (data: GenieSpaceCreate) => Promise<void>;
  onUpdate: (spaceId: number, data: GenieSpaceUpdate) => Promise<void>;
  onDelete: (spaceId: number) => Promise<void>;
  onSetDefault: (spaceId: number) => Promise<void>;
  saving?: boolean;
}

export const GenieSpacesManager: React.FC<GenieSpacesManagerProps> = ({
  spaces,
  onAdd,
  onUpdate,
  onDelete,
  onSetDefault,
  saving = false,
}) => {
  const [showAddForm, setShowAddForm] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState<number | null>(null);
  
  // Form state
  const [spaceId, setSpaceId] = useState('');
  const [spaceName, setSpaceName] = useState('');
  const [description, setDescription] = useState('');
  const [isDefault, setIsDefault] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const resetForm = () => {
    setSpaceId('');
    setSpaceName('');
    setDescription('');
    setIsDefault(false);
    setError(null);
  };

  const handleAdd = async () => {
    setError(null);

    if (!spaceId.trim() || !spaceName.trim()) {
      setError('Space ID and Name are required');
      return;
    }

    try {
      await onAdd({
        space_id: spaceId.trim(),
        space_name: spaceName.trim(),
        description: description.trim() || null,
        is_default: isDefault,
      });
      setShowAddForm(false);
      resetForm();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to add space');
    }
  };

  const startEdit = (space: GenieSpace) => {
    setEditingId(space.id);
    setSpaceName(space.space_name);
    setDescription(space.description || '');
    setError(null);
  };

  const handleUpdate = async (spaceId: number) => {
    setError(null);

    if (!spaceName.trim()) {
      setError('Space name is required');
      return;
    }

    try {
      await onUpdate(spaceId, {
        space_name: spaceName.trim(),
        description: description.trim() || null,
      });
      setEditingId(null);
      resetForm();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update space');
    }
  };

  const handleDelete = async (spaceId: number) => {
    try {
      await onDelete(spaceId);
      setDeleteConfirm(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete space');
    }
  };

  const handleSetDefault = async (spaceId: number) => {
    try {
      await onSetDefault(spaceId);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to set default');
    }
  };

  return (
    <div className="space-y-4">
      {/* Error Display */}
      {error && (
        <div className="p-3 bg-red-50 border border-red-200 rounded text-red-700 text-sm">
          {error}
        </div>
      )}

      {/* Spaces List */}
      <div className="space-y-3">
        {spaces.length === 0 ? (
          <p className="text-sm text-gray-500 italic">No Genie spaces configured</p>
        ) : (
          spaces.map((space) => (
            <div key={space.id} className="border border-gray-200 rounded-lg p-4 bg-white">
              {editingId === space.id ? (
                /* Edit Mode */
                <div className="space-y-3">
                  <div>
                    <label className="block text-xs font-medium text-gray-700 mb-1">
                      Space Name <span className="text-red-500">*</span>
                    </label>
                    <input
                      type="text"
                      value={spaceName}
                      onChange={(e) => setSpaceName(e.target.value)}
                      className="w-full px-3 py-2 border border-gray-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                      disabled={saving}
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-700 mb-1">
                      Description
                    </label>
                    <textarea
                      value={description}
                      onChange={(e) => setDescription(e.target.value)}
                      rows={2}
                      className="w-full px-3 py-2 border border-gray-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
                      disabled={saving}
                    />
                  </div>
                  <div className="flex justify-end gap-2">
                    <button
                      onClick={() => {
                        setEditingId(null);
                        resetForm();
                      }}
                      disabled={saving}
                      className="px-3 py-1 bg-gray-200 hover:bg-gray-300 text-gray-800 text-sm rounded transition-colors disabled:bg-gray-100"
                    >
                      Cancel
                    </button>
                    <button
                      onClick={() => handleUpdate(space.id)}
                      disabled={saving}
                      className="px-3 py-1 bg-blue-500 hover:bg-blue-600 text-white text-sm rounded transition-colors disabled:bg-blue-300"
                    >
                      Save
                    </button>
                  </div>
                </div>
              ) : (
                /* View Mode */
                <div>
                  <div className="flex items-start justify-between mb-2">
                    <div className="flex items-center gap-2">
                      {/* Default Radio */}
                      <input
                        type="radio"
                        checked={space.is_default}
                        onChange={() => !space.is_default && handleSetDefault(space.id)}
                        disabled={saving || space.is_default}
                        className="mt-1"
                        title={space.is_default ? 'Default space' : 'Set as default'}
                      />
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="font-medium text-gray-900">{space.space_name}</span>
                          {space.is_default && (
                            <span className="px-2 py-0.5 bg-green-100 text-green-700 text-xs rounded">
                              Default
                            </span>
                          )}
                        </div>
                        <p className="text-xs text-gray-500 font-mono mt-1">{space.space_id}</p>
                        {space.description && (
                          <p className="text-sm text-gray-600 mt-1">{space.description}</p>
                        )}
                      </div>
                    </div>
                    
                    {/* Actions */}
                    <div className="flex gap-2">
                      <button
                        onClick={() => startEdit(space)}
                        disabled={saving}
                        className="px-3 py-1 bg-gray-500 hover:bg-gray-600 text-white text-xs rounded transition-colors disabled:bg-gray-300"
                        title="Edit space"
                      >
                        Edit
                      </button>
                      {spaces.length > 1 && (
                        <button
                          onClick={() => setDeleteConfirm(space.id)}
                          disabled={saving}
                          className="px-3 py-1 bg-red-500 hover:bg-red-600 text-white text-xs rounded transition-colors disabled:bg-red-300"
                          title="Delete space"
                        >
                          Delete
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              )}
            </div>
          ))
        )}
      </div>

      {/* Add Space Form */}
      {showAddForm ? (
        <div className="border border-blue-200 rounded-lg p-4 bg-blue-50">
          <h4 className="font-medium text-gray-900 mb-3">Add New Genie Space</h4>
          <div className="space-y-3">
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">
                Space ID <span className="text-red-500">*</span>
              </label>
              <input
                type="text"
                value={spaceId}
                onChange={(e) => setSpaceId(e.target.value)}
                placeholder="e.g., 01effebcc2781b6bbb749077a55d31e3"
                className="w-full px-3 py-2 border border-gray-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                disabled={saving}
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">
                Space Name <span className="text-red-500">*</span>
              </label>
              <input
                type="text"
                value={spaceName}
                onChange={(e) => setSpaceName(e.target.value)}
                placeholder="e.g., Databricks Usage Analytics"
                className="w-full px-3 py-2 border border-gray-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                disabled={saving}
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">
                Description
              </label>
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Optional description"
                rows={2}
                className="w-full px-3 py-2 border border-gray-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
                disabled={saving}
              />
            </div>
            <div className="flex items-center gap-2">
              <input
                type="checkbox"
                id="is-default"
                checked={isDefault}
                onChange={(e) => setIsDefault(e.target.checked)}
                disabled={saving}
              />
              <label htmlFor="is-default" className="text-sm text-gray-700">
                Set as default space
              </label>
            </div>
          </div>
          <div className="flex justify-end gap-2 mt-4">
            <button
              onClick={() => {
                setShowAddForm(false);
                resetForm();
              }}
              disabled={saving}
              className="px-3 py-2 bg-gray-200 hover:bg-gray-300 text-gray-800 text-sm rounded transition-colors disabled:bg-gray-100"
            >
              Cancel
            </button>
            <button
              onClick={handleAdd}
              disabled={saving}
              className="px-3 py-2 bg-blue-500 hover:bg-blue-600 text-white text-sm rounded transition-colors disabled:bg-blue-300"
            >
              Add Space
            </button>
          </div>
        </div>
      ) : (
        <button
          onClick={() => setShowAddForm(true)}
          disabled={saving}
          className="w-full px-4 py-3 border-2 border-dashed border-gray-300 rounded-lg text-gray-600 hover:border-blue-400 hover:text-blue-600 transition-colors disabled:opacity-50"
        >
          + Add Genie Space
        </button>
      )}

      {/* Delete Confirmation Dialog */}
      <ConfirmDialog
        isOpen={deleteConfirm !== null}
        title="Delete Genie Space"
        message="Are you sure you want to delete this Genie space? This action cannot be undone."
        confirmLabel="Delete"
        onConfirm={() => deleteConfirm && handleDelete(deleteConfirm)}
        onCancel={() => setDeleteConfirm(null)}
      />
    </div>
  );
};


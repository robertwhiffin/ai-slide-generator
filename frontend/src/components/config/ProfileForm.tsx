/**
 * Form component for creating and editing profiles.
 * 
 * Supports:
 * - Creating new profiles
 * - Editing profile name and description
 */

import React, { useState, useEffect } from 'react';
import type { ProfileCreate, ProfileUpdate } from '../../api/config';

interface ProfileFormProps {
  isOpen: boolean;
  mode: 'create' | 'edit';
  profile?: { name: string; description: string | null };
  onSubmit: (data: ProfileCreate | ProfileUpdate) => Promise<void>;
  onCancel: () => void;
}

export const ProfileForm: React.FC<ProfileFormProps> = ({
  isOpen,
  mode,
  profile,
  onSubmit,
  onCancel,
}) => {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Initialize form with profile data when editing
  useEffect(() => {
    if (mode === 'edit' && profile) {
      setName(profile.name);
      setDescription(profile.description || '');
    } else {
      setName('');
      setDescription('');
    }
    setError(null);
  }, [mode, profile, isOpen]);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    // Validation
    if (!name.trim()) {
      setError('Profile name is required');
      return;
    }

    if (name.trim().length > 100) {
      setError('Profile name must be 100 characters or less');
      return;
    }

    if (description.length > 500) {
      setError('Description must be 500 characters or less');
      return;
    }

    setIsSubmitting(true);
    try {
      if (mode === 'create') {
        const data: ProfileCreate = {
          name: name.trim(),
          description: description.trim() || null,
        };
        await onSubmit(data);
      } else {
        const data: ProfileUpdate = {
          name: name.trim(),
          description: description.trim() || null,
        };
        await onSubmit(data);
      }

      // Success - parent will close modal
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save profile');
    } finally {
      setIsSubmitting(false);
    }
  };

  const title = mode === 'create' ? 'Create New Profile' : 'Edit Profile';
  const submitLabel = mode === 'create' ? 'Create' : 'Save';

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-50">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-lg mx-4">
        {/* Header */}
        <div className="px-6 py-4 border-b flex items-center justify-between">
          <h2 className="text-xl font-semibold text-gray-900">{title}</h2>
          <button
            onClick={onCancel}
            className="text-gray-500 hover:text-gray-700"
            disabled={isSubmitting}
          >
            ✕
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="px-6 py-4 space-y-4">
          {/* Error Display */}
          {error && (
            <div className="p-3 bg-red-50 border border-red-200 rounded text-red-700 text-sm">
              {error}
            </div>
          )}

          {/* Name Field */}
          <div>
            <label htmlFor="name" className="block text-sm font-medium text-gray-700 mb-1">
              Name <span className="text-red-500">*</span>
            </label>
            <input
              id="name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g., Development, Production, Testing"
              className="w-full px-3 py-2 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
              disabled={isSubmitting}
              required
              maxLength={100}
            />
            <p className="mt-1 text-xs text-gray-500">
              {name.length}/100 characters
            </p>
          </div>

          {/* Description Field */}
          <div>
            <label htmlFor="description" className="block text-sm font-medium text-gray-700 mb-1">
              Description
            </label>
            <textarea
              id="description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Optional description"
              rows={3}
              className="w-full px-3 py-2 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
              disabled={isSubmitting}
              maxLength={500}
            />
            <p className="mt-1 text-xs text-gray-500">
              {description.length}/500 characters
            </p>
          </div>

          {/* Buttons */}
          <div className="flex justify-end gap-3 pt-4">
            <button
              type="button"
              onClick={onCancel}
              className="px-4 py-2 bg-gray-200 hover:bg-gray-300 text-gray-800 rounded transition-colors"
              disabled={isSubmitting}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="px-4 py-2 bg-blue-500 hover:bg-blue-600 text-white rounded transition-colors disabled:bg-blue-300"
              disabled={isSubmitting}
            >
              {isSubmitting ? 'Saving...' : submitLabel}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};


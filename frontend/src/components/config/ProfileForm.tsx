/**
 * Form component for creating and editing profiles.
 *
 * Supports:
 * - Creating new profiles
 * - Editing profile name and description
 */

import React, { useState, useEffect } from 'react';
import { X, AlertCircle } from 'lucide-react';
import { Button } from '@/ui/button';
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

  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !isSubmitting) onCancel();
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, isSubmitting, onCancel]);

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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div className="mx-4 w-full max-w-lg rounded-lg border border-border bg-card shadow-xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-6 py-4">
          <h2 className="text-lg font-semibold text-foreground">{title}</h2>
          <Button
            variant="ghost"
            size="icon"
            onClick={onCancel}
            disabled={isSubmitting}
            className="size-8 p-0"
          >
            <X className="size-4" />
          </Button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-4 px-6 py-4">
          {/* Error Display */}
          {error && (
            <div className="flex items-center gap-2 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
              <AlertCircle className="size-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {/* Name Field */}
          <div>
            <label htmlFor="name" className="mb-1 block text-sm font-medium text-foreground">
              Name <span className="text-destructive">*</span>
            </label>
            <input
              id="name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g., Development, Production, Testing"
              className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm transition-colors file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
              disabled={isSubmitting}
              required
              maxLength={100}
            />
            <p className="mt-1 text-xs text-muted-foreground">
              {name.length}/100 characters
            </p>
          </div>

          {/* Description Field */}
          <div>
            <label htmlFor="description" className="mb-1 block text-sm font-medium text-foreground">
              Description
            </label>
            <textarea
              id="description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Optional description"
              rows={3}
              className="flex min-h-[60px] w-full resize-none rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
              disabled={isSubmitting}
              maxLength={500}
            />
            <p className="mt-1 text-xs text-muted-foreground">
              {description.length}/500 characters
            </p>
          </div>

          {/* Buttons */}
          <div className="flex justify-end gap-2 pt-4">
            <Button
              type="button"
              variant="outline"
              onClick={onCancel}
              disabled={isSubmitting}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting ? 'Saving...' : submitLabel}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
};


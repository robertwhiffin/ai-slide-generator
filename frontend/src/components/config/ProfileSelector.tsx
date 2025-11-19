/**
 * Quick profile selector dropdown component.
 * 
 * Shows current profile and allows switching between profiles.
 * Designed to be embedded in the navbar/header.
 */

import React, { useState, useRef, useEffect } from 'react';
import { useProfiles } from '../../hooks/useProfiles';

interface ProfileSelectorProps {
  onManageClick?: () => void;
}

export const ProfileSelector: React.FC<ProfileSelectorProps> = ({ onManageClick }) => {
  const { profiles, currentProfile, loadProfile } = useProfiles();
  const [isOpen, setIsOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };

    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
      return () => document.removeEventListener('mousedown', handleClickOutside);
    }
  }, [isOpen]);

  const handleLoadProfile = async (profileId: number) => {
    setIsLoading(true);
    try {
      await loadProfile(profileId);
      setIsOpen(false);
    } catch (err) {
      console.error('Failed to load profile:', err);
      // Error is already handled by useProfiles hook
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="relative" ref={dropdownRef}>
      {/* Selector Button */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-2 px-3 py-2 bg-white border border-gray-300 rounded hover:bg-gray-50 transition-colors text-sm"
        disabled={isLoading}
      >
        <span className="text-gray-700">
          Profile: <strong>{currentProfile?.name || 'Loading...'}</strong>
        </span>
        {currentProfile?.is_default && (
          <span className="px-2 py-0.5 bg-blue-100 text-blue-700 text-xs rounded">
            Default
          </span>
        )}
        <svg
          className={`w-4 h-4 text-gray-500 transition-transform ${isOpen ? 'rotate-180' : ''}`}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {/* Dropdown Menu */}
      {isOpen && (
        <div className="absolute right-0 mt-2 w-64 bg-white border border-gray-200 rounded-lg shadow-lg z-50">
          <div className="py-1">
            {/* Header */}
            <div className="px-4 py-2 border-b">
              <p className="text-xs text-gray-500 uppercase font-medium">
                Switch Profile
              </p>
            </div>

            {/* Profile List */}
            <div className="max-h-64 overflow-y-auto">
              {profiles.map((profile) => (
                <button
                  key={profile.id}
                  onClick={() => handleLoadProfile(profile.id)}
                  disabled={isLoading || currentProfile?.id === profile.id}
                  className={`w-full text-left px-4 py-2 hover:bg-gray-50 transition-colors flex items-center justify-between ${
                    currentProfile?.id === profile.id ? 'bg-blue-50' : ''
                  }`}
                >
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-gray-900 truncate">
                        {profile.name}
                      </span>
                      {profile.is_default && (
                        <span className="px-1.5 py-0.5 bg-blue-100 text-blue-700 text-xs rounded">
                          Default
                        </span>
                      )}
                    </div>
                    {profile.description && (
                      <p className="text-xs text-gray-500 truncate mt-0.5">
                        {profile.description}
                      </p>
                    )}
                  </div>

                  {currentProfile?.id === profile.id && (
                    <svg
                      className="w-4 h-4 text-green-500 flex-shrink-0 ml-2"
                      fill="currentColor"
                      viewBox="0 0 20 20"
                    >
                      <path
                        fillRule="evenodd"
                        d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
                        clipRule="evenodd"
                      />
                    </svg>
                  )}
                </button>
              ))}
            </div>

            {/* Manage Profiles Button */}
            {onManageClick && (
              <>
                <div className="border-t" />
                <button
                  onClick={() => {
                    setIsOpen(false);
                    onManageClick();
                  }}
                  className="w-full text-left px-4 py-2 hover:bg-gray-50 transition-colors text-sm text-blue-600 font-medium"
                >
                  Manage Profiles →
                </button>
              </>
            )}
          </div>
        </div>
      )}

      {/* Loading Overlay */}
      {isLoading && (
        <div className="absolute inset-0 bg-white bg-opacity-75 flex items-center justify-center rounded">
          <div className="text-xs text-gray-600">Loading...</div>
        </div>
      )}
    </div>
  );
};


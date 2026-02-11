import React, { useState, useRef, useEffect } from 'react';

export interface SavePointVersion {
  version_number: number;
  description: string;
  created_at: string;
  slide_count: number;
}

interface SavePointDropdownProps {
  versions: SavePointVersion[];
  currentVersion: number | null;
  previewVersion: number | null;
  onPreview: (versionNumber: number) => void;
  onRevert: (versionNumber: number) => void;
  disabled?: boolean;
}

export const SavePointDropdown: React.FC<SavePointDropdownProps> = ({
  versions,
  currentVersion,
  previewVersion,
  onPreview,
  onRevert: _onRevert,
  disabled = false,
}) => {
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    return date.toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const displayVersion = previewVersion || currentVersion;

  if (versions.length === 0) {
    return null;
  }

  // Button styling based on state
  const getButtonClasses = () => {
    if (disabled) {
      return 'bg-blue-400 text-blue-200 cursor-not-allowed opacity-50';
    }
    if (previewVersion) {
      // Indigo theme for preview state - stands out but readable
      return 'bg-indigo-100 text-indigo-800 hover:bg-indigo-200 active:bg-indigo-300 border-indigo-300 ring-2 ring-indigo-400';
    }
    // Blue theme matching Save As/New buttons
    return 'bg-blue-500 hover:bg-blue-600 active:bg-blue-700 text-blue-100';
  };

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        disabled={disabled}
        className={`
          flex items-center gap-2 px-3 py-1.5 text-sm rounded transition-colors
          ${getButtonClasses()}
        `}
        title="Save Points"
      >
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        <span>
          {previewVersion 
            ? `Previewing v${previewVersion}` 
            : `Save Point ${displayVersion || '-'}`
          }
        </span>
        <svg className={`w-4 h-4 transition-transform ${isOpen ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {isOpen && (
        <div className="absolute right-0 mt-2 w-72 bg-white dark:bg-gray-800 rounded-lg shadow-lg border border-gray-200 dark:border-gray-700 z-50 max-h-80 overflow-y-auto">
          <div className="p-2 border-b border-gray-200 dark:border-gray-700">
            <span className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">
              Save Points ({versions.length})
            </span>
          </div>
          <div className="py-1">
            {versions.map((version) => {
              const isCurrent = version.version_number === currentVersion;
              const isPreviewing = version.version_number === previewVersion;
              
              return (
                <div
                  key={version.version_number}
                  className={`
                    px-3 py-2 cursor-pointer transition-colors
                    ${isPreviewing 
                      ? 'bg-indigo-50 hover:bg-indigo-100 dark:bg-indigo-900/30 dark:hover:bg-indigo-900/50' 
                      : isCurrent && !previewVersion 
                        ? 'bg-blue-50 hover:bg-blue-100 dark:bg-blue-900/20 dark:hover:bg-blue-900/40' 
                        : 'hover:bg-gray-100 dark:hover:bg-gray-700'
                    }
                  `}
                  onClick={() => {
                    if (!isCurrent || previewVersion) {
                      onPreview(version.version_number);
                    }
                    setIsOpen(false);
                  }}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-sm text-gray-800 dark:text-gray-100">
                        v{version.version_number}
                      </span>
                      {isCurrent && !previewVersion && (
                        <span className="text-xs px-1.5 py-0.5 bg-blue-100 dark:bg-blue-800 text-blue-700 dark:text-blue-200 rounded">
                          Current
                        </span>
                      )}
                      {isPreviewing && (
                        <span className="text-xs px-1.5 py-0.5 bg-indigo-100 dark:bg-indigo-800 text-indigo-700 dark:text-indigo-200 rounded">
                          Previewing
                        </span>
                      )}
                    </div>
                    <span className="text-xs text-gray-500 dark:text-gray-400">
                      {version.slide_count} slides
                    </span>
                  </div>
                  <div className="text-xs text-gray-600 dark:text-gray-300 mt-0.5 truncate">
                    {version.description}
                  </div>
                  <div className="text-xs text-gray-400 dark:text-gray-500 mt-0.5">
                    {formatDate(version.created_at)}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
};

export default SavePointDropdown;

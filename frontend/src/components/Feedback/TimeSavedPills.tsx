/**
 * Time saved pill button selector.
 * Single-select pills representing preset time values.
 */
import React from 'react';

const TIME_OPTIONS = [
  { label: '15 min', value: 15 },
  { label: '30 min', value: 30 },
  { label: '1 hr', value: 60 },
  { label: '2 hrs', value: 120 },
  { label: '4 hrs', value: 240 },
  { label: '8 hrs', value: 480 },
];

interface TimeSavedPillsProps {
  value: number | null;
  onChange: (minutes: number) => void;
}

export const TimeSavedPills: React.FC<TimeSavedPillsProps> = ({ value, onChange }) => {
  return (
    <div className="flex flex-wrap gap-2" data-testid="time-saved-pills">
      {TIME_OPTIONS.map((option) => (
        <button
          key={option.value}
          type="button"
          className={`px-4 py-2 rounded-full text-sm font-medium transition-colors focus:outline-none ${
            value === option.value
              ? 'bg-blue-600 text-white'
              : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
          }`}
          onClick={() => onChange(option.value)}
          data-testid={`time-${option.value}`}
          aria-label={`${option.label} saved`}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
};

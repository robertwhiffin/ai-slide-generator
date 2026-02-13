/**
 * NPS (Net Promoter Score) scale component (0-10).
 * Displays a row of numbered buttons with endpoint labels.
 */
import React from 'react';

interface NPSScaleProps {
  value: number | null;
  onChange: (score: number) => void;
}

export const NPSScale: React.FC<NPSScaleProps> = ({ value, onChange }) => {
  return (
    <div data-testid="nps-scale">
      <div className="flex gap-1">
        {Array.from({ length: 11 }, (_, i) => i).map((score) => (
          <button
            key={score}
            type="button"
            className={`w-9 h-9 rounded text-sm font-medium transition-colors focus:outline-none ${
              value === score
                ? 'bg-blue-600 text-white'
                : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
            }`}
            onClick={() => onChange(score)}
            data-testid={`nps-${score}`}
            aria-label={`Score ${score} out of 10`}
          >
            {score}
          </button>
        ))}
      </div>
      <div className="flex justify-between mt-1 text-xs text-gray-500">
        <span>Not likely</span>
        <span>Very likely</span>
      </div>
    </div>
  );
};

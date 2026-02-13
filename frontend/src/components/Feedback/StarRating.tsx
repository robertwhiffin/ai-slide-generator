/**
 * Star rating component (1-5 stars).
 * Stars fill on hover and click. Selected state is controlled by parent.
 */
import React, { useState } from 'react';

interface StarRatingProps {
  value: number | null;
  onChange: (rating: number) => void;
}

export const StarRating: React.FC<StarRatingProps> = ({ value, onChange }) => {
  const [hoverValue, setHoverValue] = useState<number | null>(null);
  const displayValue = hoverValue ?? value ?? 0;

  return (
    <div className="flex gap-1" data-testid="star-rating">
      {[1, 2, 3, 4, 5].map((star) => (
        <button
          key={star}
          type="button"
          className="text-3xl transition-colors focus:outline-none"
          onMouseEnter={() => setHoverValue(star)}
          onMouseLeave={() => setHoverValue(null)}
          onClick={() => onChange(star)}
          data-testid={`star-${star}`}
          aria-label={`Rate ${star} out of 5`}
        >
          <span className={displayValue >= star ? 'text-yellow-400' : 'text-gray-300'}>
            ★
          </span>
        </button>
      ))}
    </div>
  );
};

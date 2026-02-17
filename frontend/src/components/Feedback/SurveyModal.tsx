/**
 * Satisfaction survey modal.
 *
 * Collects: star rating (1-5), time saved (pill buttons), NPS (0-10).
 * Appears 60s after a generation, at most once per 7 days.
 */
import React, { useState } from 'react';
import { FiX } from 'react-icons/fi';
import { StarRating } from './StarRating';
import { TimeSavedPills } from './TimeSavedPills';
import { NPSScale } from './NPSScale';
import { api } from '../../services/api';

interface SurveyModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const SurveyModal: React.FC<SurveyModalProps> = ({ isOpen, onClose }) => {
  const [starRating, setStarRating] = useState<number | null>(null);
  const [timeSaved, setTimeSaved] = useState<number | null>(null);
  const [npsScore, setNpsScore] = useState<number | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  if (!isOpen) return null;

  const handleSubmit = async () => {
    if (!starRating) return;

    setSubmitting(true);
    try {
      await api.submitSurvey({
        star_rating: starRating,
        time_saved_minutes: timeSaved ?? undefined,
        nps_score: npsScore ?? undefined,
      });
      setSubmitted(true);
      setTimeout(onClose, 1500);
    } catch (err) {
      console.error('Failed to submit survey:', err);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-50"
      data-testid="survey-modal"
    >
      <div className="bg-white rounded-lg shadow-xl w-full max-w-lg mx-4 p-6 relative">
        {/* Close button */}
        <button
          onClick={onClose}
          className="absolute top-4 right-4 text-gray-400 hover:text-gray-600"
          data-testid="survey-close"
          aria-label="Close survey"
        >
          <FiX size={20} />
        </button>

        {submitted ? (
          <div className="text-center py-8">
            <p className="text-lg font-medium text-gray-900">Thank you for your feedback!</p>
          </div>
        ) : (
          <>
            <h2 className="text-xl font-semibold text-gray-900 mb-6">
              How's your experience with tellr?
            </h2>

            {/* Star Rating */}
            <div className="mb-6">
              <label className="block text-sm font-medium text-gray-700 mb-2">
                How would you rate tellr?
              </label>
              <StarRating value={starRating} onChange={setStarRating} />
            </div>

            {/* Time Saved */}
            <div className="mb-6">
              <label className="block text-sm font-medium text-gray-700 mb-2">
                How much time has tellr saved you?
              </label>
              <TimeSavedPills value={timeSaved} onChange={setTimeSaved} />
            </div>

            {/* NPS */}
            <div className="mb-6">
              <label className="block text-sm font-medium text-gray-700 mb-2">
                How likely are you to recommend tellr to a colleague?
              </label>
              <NPSScale value={npsScore} onChange={setNpsScore} />
            </div>

            {/* Submit */}
            <div className="flex justify-end">
              <button
                onClick={handleSubmit}
                disabled={!starRating || submitting}
                className="px-6 py-2 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                data-testid="survey-submit"
              >
                {submitting ? 'Submitting...' : 'Submit'}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
};

/**
 * Floating feedback button (bottom-right corner).
 * Toggles the FeedbackPopover open/closed.
 */
import React, { useState } from 'react';
import { FiMessageSquare } from 'react-icons/fi';
import { FeedbackPopover } from './FeedbackPopover';

export const FeedbackButton: React.FC = () => {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <>
      {isOpen && <FeedbackPopover onClose={() => setIsOpen(false)} />}

      <button
        onClick={() => setIsOpen((prev) => !prev)}
        className="fixed bottom-6 right-6 z-[60] w-12 h-12 rounded-full bg-blue-600 text-white shadow-lg hover:bg-blue-700 transition-colors flex items-center justify-center"
        data-testid="feedback-button"
        aria-label="Send feedback"
      >
        <FiMessageSquare size={20} />
      </button>
    </>
  );
};

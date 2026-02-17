import React, { useState } from 'react';
import { FeedbackDashboard } from '../Feedback/FeedbackDashboard';
import { GoogleSlidesAuthForm } from '../config/GoogleSlidesAuthForm';

type TabId = 'feedback' | 'google_slides';

export const AdminPage: React.FC = () => {
  const [activeTab, setActiveTab] = useState<TabId>('feedback');

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-6xl mx-auto p-6">
        <header className="mb-6">
          <h1 className="text-2xl font-bold text-gray-900">Admin</h1>
          <p className="text-sm text-gray-500 mt-1">
            Feedback reports and Google Slides configuration.
          </p>
        </header>

        <div
          role="tablist"
          className="flex gap-1 border-b border-gray-200 mb-6"
        >
          <button
            role="tab"
            aria-selected={activeTab === 'feedback'}
            aria-controls="feedback-panel"
            id="feedback-tab"
            onClick={() => setActiveTab('feedback')}
            className={`px-4 py-2 font-medium text-sm border-b-2 transition-colors -mb-px ${
              activeTab === 'feedback'
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-600 hover:text-gray-900 hover:border-gray-300'
            }`}
          >
            Feedback
          </button>
          <button
            role="tab"
            aria-selected={activeTab === 'google_slides'}
            aria-controls="google-slides-panel"
            id="google-slides-tab"
            onClick={() => setActiveTab('google_slides')}
            className={`px-4 py-2 font-medium text-sm border-b-2 transition-colors -mb-px ${
              activeTab === 'google_slides'
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-600 hover:text-gray-900 hover:border-gray-300'
            }`}
          >
            Google Slides
          </button>
        </div>

        <div
          role="tabpanel"
          id="feedback-panel"
          aria-labelledby="feedback-tab"
          hidden={activeTab !== 'feedback'}
          className={activeTab !== 'feedback' ? 'sr-only' : ''}
        >
          <FeedbackDashboard />
        </div>

        <div
          role="tabpanel"
          id="google-slides-panel"
          aria-labelledby="google-slides-tab"
          hidden={activeTab !== 'google_slides'}
          className={activeTab !== 'google_slides' ? 'sr-only' : ''}
        >
          <GoogleSlidesAuthForm />
        </div>
      </div>
    </div>
  );
};

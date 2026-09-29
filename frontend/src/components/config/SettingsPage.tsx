import React from 'react';
import { GoogleAccountConnection } from './GoogleAccountConnection';

export const SettingsPage: React.FC = () => {
  return (
    <div className="space-y-8">
      <section>
        <h3 className="text-lg font-semibold text-gray-900 mb-1">Google account</h3>
        <p className="text-sm text-gray-500 mb-4">
          Connect your Google account to export decks to Google Slides. Each user
          authorizes independently. App-wide OAuth client credentials are managed
          by admins.
        </p>
        <GoogleAccountConnection />
      </section>
    </div>
  );
};

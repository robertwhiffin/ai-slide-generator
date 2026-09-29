/**
 * Per-user Google account connection for Google Slides export.
 *
 * Does not call admin credential APIs. Uses GET/DELETE
 * /api/export/google-slides/auth only.
 */

import React, { useCallback, useEffect, useState } from 'react';
import { FiCheck, FiExternalLink, FiX } from 'react-icons/fi';
import { api, ApiError } from '../../services/api';
import { useGoogleOAuthPopup } from '../../hooks/useGoogleOAuthPopup';

export const GoogleAccountConnection: React.FC = () => {
  const [hasCredentials, setHasCredentials] = useState<boolean | null>(null);
  const [authorized, setAuthorized] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [authorizing, setAuthorizing] = useState(false);
  const [revoking, setRevoking] = useState(false);
  const { openOAuthPopup } = useGoogleOAuthPopup();

  const loadStatus = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { authorized: auth, has_credentials } = await api.checkGoogleSlidesAuth();
      setHasCredentials(has_credentials);
      setAuthorized(auth);
    } catch {
      setError('Failed to load Google account status');
      setHasCredentials(false);
      setAuthorized(false);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadStatus();
  }, [loadStatus]);

  const handleAuthorize = async () => {
    setAuthorizing(true);
    setError(null);
    try {
      const authResult = await openOAuthPopup();
      setAuthorized(authResult);
      if (!authResult) {
        setError('Authorization was not completed');
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Authorization failed';
      setError(msg);
    } finally {
      setAuthorizing(false);
    }
  };

  const handleDisconnect = async () => {
    if (!confirm('Disconnect your Google account? You will need to authorize again to export to Google Slides.')) {
      return;
    }
    setRevoking(true);
    setError(null);
    try {
      await api.revokeGoogleSlidesAuth();
      setAuthorized(false);
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : 'Disconnect failed';
      setError(msg);
    } finally {
      setRevoking(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-32">
        <div className="text-gray-500">Loading Google account status...</div>
      </div>
    );
  }

  if (hasCredentials === false) {
    return (
      <div className="bg-gray-50 border border-gray-200 rounded-lg p-4">
        <p className="font-medium text-gray-800">Google Slides export is not configured</p>
        <p className="text-sm text-gray-500 mt-1">
          Ask an admin to upload OAuth client credentials on the Admin page (Google Slides tab).
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {error && (
        <div className="p-3 bg-red-50 border border-red-200 rounded text-red-700 text-sm flex items-center gap-2">
          <FiX className="flex-shrink-0" /> {error}
        </div>
      )}

      <div className="flex items-center justify-between bg-gray-50 border border-gray-200 rounded-lg p-4">
        <div className="flex items-center gap-3">
          <div className={`w-10 h-10 rounded-full flex items-center justify-center ${
            authorized ? 'bg-green-100' : 'bg-gray-200'
          }`}>
            {authorized ? (
              <FiCheck className="text-green-600" size={20} />
            ) : (
              <FiExternalLink className="text-gray-500" size={20} />
            )}
          </div>
          <div>
            <p className={`font-medium ${authorized ? 'text-green-900' : 'text-gray-700'}`}>
              {authorized ? 'Authorized' : 'Not authorized'}
            </p>
            <p className="text-xs text-gray-500">
              {authorized
                ? 'Your Google account is connected for slide export'
                : 'Connect your Google account to export decks to Google Slides'}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {authorized && (
            <button
              type="button"
              onClick={handleDisconnect}
              disabled={revoking || authorizing}
              className="px-4 py-2 text-sm rounded border border-red-200 text-red-600 bg-white hover:bg-red-50 transition-colors disabled:opacity-50"
            >
              {revoking ? 'Disconnecting...' : 'Disconnect'}
            </button>
          )}
          <button
            type="button"
            onClick={handleAuthorize}
            disabled={authorizing || revoking}
            className={`px-4 py-2 text-sm rounded transition-colors flex items-center gap-2 ${
              authorized
                ? 'bg-white border border-gray-300 text-gray-700 hover:bg-gray-50'
                : 'bg-blue-600 text-white hover:bg-blue-700'
            } disabled:opacity-50`}
          >
            {authorizing ? (
              <>
                <span className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin" />
                Authorizing...
              </>
            ) : authorized ? (
              <>
                <FiExternalLink size={14} />
                Re-authorize
              </>
            ) : (
              <>
                <FiExternalLink size={14} />
                Authorize with Google
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
};

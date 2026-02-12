/**
 * Google Slides OAuth configuration form.
 *
 * Two sections:
 *   A) Credentials Upload — upload / view / delete the Google OAuth
 *      credentials.json stored (encrypted) on the profile.
 *   B) User Authorization — trigger the Google OAuth consent flow and
 *      display the current authorization status.
 */

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { FiUploadCloud, FiCheck, FiX, FiTrash2, FiExternalLink, FiShield } from 'react-icons/fi';
import { configApi, ConfigApiError } from '../../api/config';
import { api } from '../../services/api';

interface GoogleSlidesAuthFormProps {
  profileId: number;
}

export const GoogleSlidesAuthForm: React.FC<GoogleSlidesAuthFormProps> = ({ profileId }) => {
  // --- Credentials state ---
  const [hasCredentials, setHasCredentials] = useState<boolean | null>(null);
  const [loadingStatus, setLoadingStatus] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [credError, setCredError] = useState<string | null>(null);
  const [credSuccess, setCredSuccess] = useState<string | null>(null);

  // --- Auth state ---
  const [authorized, setAuthorized] = useState<boolean | null>(null);
  const [checkingAuth, setCheckingAuth] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);
  const [authorizing, setAuthorizing] = useState(false);

  // --- Drag & drop ---
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // ---------------------------------------------------------------
  // Load initial statuses
  // ---------------------------------------------------------------

  const loadStatuses = useCallback(async () => {
    setLoadingStatus(true);
    try {
      const { has_credentials } = await configApi.getGoogleCredentialsStatus(profileId);
      setHasCredentials(has_credentials);

      if (has_credentials) {
        setCheckingAuth(true);
        const { authorized: auth } = await api.checkGoogleSlidesAuth(profileId);
        setAuthorized(auth);
        setCheckingAuth(false);
      } else {
        setAuthorized(null);
      }
    } catch {
      setCredError('Failed to load status');
    } finally {
      setLoadingStatus(false);
    }
  }, [profileId]);

  useEffect(() => {
    loadStatuses();
  }, [loadStatuses]);

  // ---------------------------------------------------------------
  // Credentials upload
  // ---------------------------------------------------------------

  const handleFileUpload = async (file: File) => {
    if (!file.name.endsWith('.json')) {
      setCredError('Please upload a .json file');
      return;
    }

    setUploading(true);
    setCredError(null);
    setCredSuccess(null);

    try {
      await configApi.uploadGoogleCredentials(profileId, file);
      setHasCredentials(true);
      setCredSuccess('Credentials uploaded and encrypted successfully');
      // Re-check auth status (token may already exist from previous upload)
      setCheckingAuth(true);
      const { authorized: auth } = await api.checkGoogleSlidesAuth(profileId);
      setAuthorized(auth);
      setCheckingAuth(false);
    } catch (err) {
      const msg = err instanceof ConfigApiError ? err.message : 'Upload failed';
      setCredError(msg);
    } finally {
      setUploading(false);
    }
  };

  const handleFileInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) handleFileUpload(file);
    // Reset so re-selecting the same file triggers onChange
    e.target.value = '';
  };

  const handleDeleteCredentials = async () => {
    if (!confirm('Remove Google OAuth credentials from this profile? Existing user tokens will become unusable.')) return;

    setDeleting(true);
    setCredError(null);
    setCredSuccess(null);
    try {
      await configApi.deleteGoogleCredentials(profileId);
      setHasCredentials(false);
      setAuthorized(null);
      setCredSuccess('Credentials removed');
    } catch (err) {
      const msg = err instanceof ConfigApiError ? err.message : 'Delete failed';
      setCredError(msg);
    } finally {
      setDeleting(false);
    }
  };

  // ---------------------------------------------------------------
  // Drag & Drop handlers
  // ---------------------------------------------------------------

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = () => {
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) handleFileUpload(file);
  };

  // ---------------------------------------------------------------
  // OAuth authorization
  // ---------------------------------------------------------------

  const handleAuthorize = async () => {
    setAuthorizing(true);
    setAuthError(null);

    try {
      const { url } = await api.getGoogleSlidesAuthUrl(profileId);

      const authResult = await new Promise<boolean>((resolve) => {
        const popup = window.open(url, 'google-slides-auth', 'width=600,height=700,popup=yes');

        const handleMessage = (event: MessageEvent) => {
          if (event.data?.type === 'google-slides-auth') {
            window.removeEventListener('message', handleMessage);
            resolve(event.data.success === true);
          }
        };
        window.addEventListener('message', handleMessage);

        // Fallback: poll for popup closure
        const pollTimer = setInterval(() => {
          if (popup?.closed) {
            clearInterval(pollTimer);
            window.removeEventListener('message', handleMessage);
            api.checkGoogleSlidesAuth(profileId).then(({ authorized: ok }) => resolve(ok));
          }
        }, 1000);
      });

      setAuthorized(authResult);
      if (!authResult) {
        setAuthError('Authorization was not completed');
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Authorization failed';
      setAuthError(msg);
    } finally {
      setAuthorizing(false);
    }
  };

  // ---------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------

  if (loadingStatus) {
    return (
      <div className="flex items-center justify-center h-48">
        <div className="text-gray-500">Loading Google Slides configuration...</div>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {/* Section A: Credentials Upload */}
      <section>
        <h3 className="text-lg font-semibold text-gray-900 mb-1">OAuth Client Credentials</h3>
        <p className="text-sm text-gray-500 mb-4">
          Upload the <code className="px-1 py-0.5 bg-gray-100 rounded text-xs">credentials.json</code> file
          from your Google Cloud project. It will be stored encrypted.
        </p>

        {/* Status messages */}
        {credError && (
          <div className="mb-3 p-3 bg-red-50 border border-red-200 rounded text-red-700 text-sm flex items-center gap-2">
            <FiX className="flex-shrink-0" /> {credError}
          </div>
        )}
        {credSuccess && (
          <div className="mb-3 p-3 bg-green-50 border border-green-200 rounded text-green-700 text-sm flex items-center gap-2">
            <FiCheck className="flex-shrink-0" /> {credSuccess}
          </div>
        )}

        {hasCredentials ? (
          /* Credentials already uploaded */
          <div className="flex items-center justify-between bg-green-50 border border-green-200 rounded-lg p-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 bg-green-100 rounded-full flex items-center justify-center">
                <FiShield className="text-green-600" size={20} />
              </div>
              <div>
                <p className="font-medium text-green-900">Credentials uploaded</p>
                <p className="text-xs text-green-600">Stored encrypted on the server</p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => fileInputRef.current?.click()}
                disabled={uploading}
                className="px-3 py-1.5 text-sm bg-white border border-gray-300 rounded hover:bg-gray-50 transition-colors"
              >
                Replace
              </button>
              <button
                onClick={handleDeleteCredentials}
                disabled={deleting}
                className="px-3 py-1.5 text-sm text-red-600 bg-white border border-red-200 rounded hover:bg-red-50 transition-colors flex items-center gap-1"
              >
                <FiTrash2 size={14} />
                {deleting ? 'Removing...' : 'Remove'}
              </button>
            </div>
          </div>
        ) : (
          /* Upload zone */
          <div
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            className={`border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors ${
              isDragging
                ? 'border-blue-400 bg-blue-50'
                : 'border-gray-300 hover:border-gray-400 hover:bg-gray-50'
            }`}
          >
            <FiUploadCloud className="mx-auto text-gray-400 mb-3" size={36} />
            <p className="text-sm font-medium text-gray-700">
              {uploading ? 'Uploading...' : 'Drop credentials.json here or click to browse'}
            </p>
            <p className="text-xs text-gray-500 mt-1">
              Download from Google Cloud Console &rarr; APIs &amp; Services &rarr; Credentials
            </p>
          </div>
        )}

        <input
          ref={fileInputRef}
          type="file"
          accept=".json"
          onChange={handleFileInputChange}
          className="hidden"
        />
      </section>

      {/* Section B: User Authorization */}
      {hasCredentials && (
        <section>
          <h3 className="text-lg font-semibold text-gray-900 mb-1">Google Account Authorization</h3>
          <p className="text-sm text-gray-500 mb-4">
            Authorize your Google account to allow slide export. Each user authorizes independently.
          </p>

          {authError && (
            <div className="mb-3 p-3 bg-red-50 border border-red-200 rounded text-red-700 text-sm flex items-center gap-2">
              <FiX className="flex-shrink-0" /> {authError}
            </div>
          )}

          <div className="flex items-center justify-between bg-gray-50 border border-gray-200 rounded-lg p-4">
            <div className="flex items-center gap-3">
              <div className={`w-10 h-10 rounded-full flex items-center justify-center ${
                authorized ? 'bg-green-100' : 'bg-gray-200'
              }`}>
                {checkingAuth ? (
                  <span className="w-5 h-5 border-2 border-gray-400 border-t-transparent rounded-full animate-spin" />
                ) : authorized ? (
                  <FiCheck className="text-green-600" size={20} />
                ) : (
                  <FiExternalLink className="text-gray-500" size={20} />
                )}
              </div>
              <div>
                <p className={`font-medium ${authorized ? 'text-green-900' : 'text-gray-700'}`}>
                  {checkingAuth
                    ? 'Checking...'
                    : authorized
                      ? 'Authorized'
                      : 'Not authorized'}
                </p>
                <p className="text-xs text-gray-500">
                  {authorized
                    ? 'Your Google account is connected for slide export'
                    : 'Click to connect your Google account'}
                </p>
              </div>
            </div>

            <button
              onClick={handleAuthorize}
              disabled={authorizing || checkingAuth}
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
        </section>
      )}

      {/* Help text */}
      <section className="bg-blue-50 border border-blue-200 rounded-lg p-4">
        <h4 className="text-sm font-medium text-blue-900 mb-2">How to get credentials.json</h4>
        <ol className="text-sm text-blue-700 space-y-1 list-decimal list-inside">
          <li>Go to the <a href="https://console.cloud.google.com/apis/credentials" target="_blank" rel="noopener noreferrer" className="underline">Google Cloud Console &rarr; Credentials</a></li>
          <li>Create an OAuth 2.0 Client ID (type: Web application or Desktop)</li>
          <li>Add <code className="px-1 py-0.5 bg-blue-100 rounded text-xs">http://localhost:8000/api/export/google-slides/auth/callback</code> as an authorized redirect URI</li>
          <li>Download the JSON file and upload it here</li>
        </ol>
      </section>
    </div>
  );
};

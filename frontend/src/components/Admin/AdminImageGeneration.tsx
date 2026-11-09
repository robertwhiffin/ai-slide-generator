/**
 * Admin -> Connections: "Let users generate images with AI". Saves on click and shows the
 * value the server stored. Renders nothing when the deployment does not offer the capability.
 */

import React, { useEffect, useState } from 'react';
import { adminApi } from '../../api/admin';
import { useToast } from '../../contexts/ToastContext';

export const AdminImageGeneration: React.FC = () => {
  const [state, setState] = useState<{ available: boolean; enabled: boolean } | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { showToast } = useToast();

  useEffect(() => {
    let cancelled = false;
    adminApi
      .getImageGeneration()
      .then((res) => {
        if (!cancelled) setState({ available: res.available === true, enabled: res.enabled === true });
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleToggle = async () => {
    if (state === null) return;
    setSaving(true);
    try {
      const res = await adminApi.setImageGeneration(!state.enabled);
      setState({ available: res.available === true, enabled: res.enabled === true });
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      showToast(`Failed to save: ${message}`, 'error');
    } finally {
      setSaving(false);
    }
  };

  if (state !== null && !state.available) return null;

  return (
    <div className="mb-6 rounded border border-gray-200 bg-white p-4">
      <h2 className="text-lg font-semibold text-gray-900 mb-1">AI image generation</h2>
      {error ? (
        <div className="text-sm text-red-600">Failed to load: {error}</div>
      ) : state === null ? (
        <div className="text-sm text-gray-500">Loading…</div>
      ) : (
        <label className="flex items-start gap-3 cursor-pointer">
          <input
            type="checkbox"
            className="mt-1"
            checked={state.enabled}
            disabled={saving}
            onChange={() => void handleToggle()}
            aria-label="Let users generate images with AI"
            aria-describedby="image-generation-help"
            data-testid="image-generation-enabled"
          />
          <span>
            <span className="font-medium text-gray-900">Let users generate images with AI</span>
            <span id="image-generation-help" className="block text-xs text-gray-500 mt-0.5">
              Adds Generate and Edit with prompt to the Image Library. Each image is a paid model
              call made as the app&apos;s service principal. On by default.
            </span>
          </span>
        </label>
      )}
    </div>
  );
};

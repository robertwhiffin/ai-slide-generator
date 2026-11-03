/**
 * Admin -> Connections: "Add Genie One to new decks". Saves on click; existing decks are
 * not changed, and users can still remove the pill from a deck.
 */

import React, { useEffect, useState } from 'react';
import { adminApi } from '../../api/admin';
import { useToast } from '../../contexts/ToastContext';

export const AdminGenieOneDefault: React.FC = () => {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { showToast } = useToast();

  useEffect(() => {
    let cancelled = false;
    adminApi
      .getGenieOneDefault()
      .then((res) => {
        if (!cancelled) setEnabled(res.enabled === true);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleToggle = async () => {
    if (enabled === null) return;
    setSaving(true);
    try {
      const res = await adminApi.setGenieOneDefault(!enabled);
      setEnabled(res.enabled === true);
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      showToast(`Failed to save: ${message}`, 'error');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="mb-6 rounded border border-gray-200 bg-white p-4">
      <h2 className="text-lg font-semibold text-gray-900 mb-1">Genie One</h2>
      {error ? (
        <div className="text-sm text-red-600">Failed to load: {error}</div>
      ) : enabled === null ? (
        <div className="text-sm text-gray-500">Loading…</div>
      ) : (
        <label className="flex items-start gap-3 cursor-pointer">
          <input
            type="checkbox"
            className="mt-1"
            checked={enabled}
            disabled={saving}
            onChange={() => void handleToggle()}
            aria-label="Add Genie One to new decks"
            aria-describedby="genie-one-default-help"
            data-testid="genie-one-default"
          />
          <span>
            <span className="font-medium text-gray-900">Add Genie One to new decks</span>
            <span id="genie-one-default-help" className="block text-xs text-gray-500 mt-0.5">
              New decks start with the Genie One tool, and users can remove it. Existing decks
              are not changed. Genie One works in agent mode only.
            </span>
          </span>
        </label>
      )}
    </div>
  );
};

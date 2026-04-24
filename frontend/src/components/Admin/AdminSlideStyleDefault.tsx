import React, { useEffect, useState } from 'react';
import { configApi } from '../../api/config';
import type { SlideStyle } from '../../api/config';
import { useToast } from '../../contexts/ToastContext';

export const AdminSlideStyleDefault: React.FC = () => {
  const [styles, setStyles] = useState<SlideStyle[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<number | null>(null);
  const { showToast } = useToast();

  const load = async (): Promise<void> => {
    const resp = await configApi.listSlideStyles();
    setStyles(resp.styles);
  };

  useEffect(() => {
    let cancelled = false;
    load()
      .catch(err => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  const handleSet = async (id: number) => {
    setSaving(id);
    try {
      await configApi.setSlideStyleSystemDefault(id);
      await load();
      showToast('System default slide style updated', 'success');
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      showToast(`Failed to set system default: ${message}`, 'error');
    } finally {
      setSaving(null);
    }
  };

  if (loading) {
    return <div className="text-sm text-gray-500">Loading slide styles…</div>;
  }
  if (error) {
    return <div className="text-sm text-red-600">Failed to load slide styles: {error}</div>;
  }

  return (
    <div>
      <h2 className="text-lg font-semibold text-gray-900 mb-2">System Default Slide Style</h2>
      <p className="text-sm text-gray-500 mb-4">
        The style marked as the system default applies to every new deck — including
        those created via MCP — unless a user has chosen their own default from the
        Slide Styles settings page.
      </p>
      <ul className="divide-y divide-gray-200 rounded border border-gray-200 bg-white">
        {styles.map(style => (
          <li
            key={style.id}
            data-testid={`slide-style-row-${style.id}`}
            className="flex items-center justify-between px-4 py-3 gap-4"
          >
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="font-medium text-gray-900">{style.name}</span>
                {style.is_default && (
                  <span className="inline-flex items-center rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-700">
                    System default
                  </span>
                )}
              </div>
              {style.description && (
                <div className="text-xs text-gray-500 mt-0.5">{style.description}</div>
              )}
            </div>
            {style.is_active && !style.is_default && (
              <button
                type="button"
                disabled={saving === style.id}
                onClick={() => void handleSet(style.id)}
                className="shrink-0 text-xs font-medium text-blue-600 hover:text-blue-700 hover:underline disabled:cursor-not-allowed disabled:text-blue-300"
              >
                {saving === style.id ? 'Setting…' : 'Set as system default'}
              </button>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
};

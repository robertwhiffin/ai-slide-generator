import React, { useEffect, useState } from 'react';
import { configApi } from '../../api/config';
import type { SlideStyle } from '../../api/config';

export const AdminSlideStyleDefault: React.FC = () => {
  const [styles, setStyles] = useState<SlideStyle[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    configApi.listSlideStyles()
      .then(resp => {
        if (cancelled) return;
        setStyles(resp.styles);
      })
      .catch(err => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

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
          <li key={style.id} className="flex items-center justify-between px-4 py-3">
            <div>
              <div className="font-medium text-gray-900">{style.name}</div>
              {style.description && (
                <div className="text-xs text-gray-500 mt-0.5">{style.description}</div>
              )}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
};

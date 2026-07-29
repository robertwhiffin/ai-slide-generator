import React, { useEffect, useState } from 'react';
import { configApi } from '../../api/config';
import type { DesignSystemSummary } from '../../api/config';
import { useToast } from '../../contexts/ToastContext';

/**
 * Org-default DESIGN SYSTEM administration — the design-system counterpart of
 * {@link AdminSlideStyleDefault}, deliberately mirroring its shape.
 *
 * Setting the org default is what makes a design system apply to new decks (the
 * flag was previously settable but never consumed). Because a design system
 * outranks the legacy default slide style, the copy says so explicitly.
 */
export const AdminDesignSystemDefault: React.FC = () => {
  const [systems, setSystems] = useState<DesignSystemSummary[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<number | null>(null);
  const { showToast } = useToast();

  const load = async (): Promise<void> => {
    const resp = await configApi.listDesignSystems();
    setSystems(resp.design_systems);
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
      await configApi.setDesignSystemDefault(id);
      await load();
      showToast('Org default design system updated', 'success');
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      showToast(`Failed to set org default: ${message}`, 'error');
    } finally {
      setSaving(null);
    }
  };

  if (loading) {
    return <div className="text-sm text-gray-500">Loading design systems…</div>;
  }
  if (error) {
    return <div className="text-sm text-red-600">Failed to load design systems: {error}</div>;
  }

  return (
    <div>
      <h2 className="text-lg font-semibold text-gray-900 mb-2">Org Default Design System</h2>
      <p className="text-sm text-gray-500 mb-4">
        The design system marked as the org default is preselected for every new deck —
        including those created via MCP. A design system takes precedence over the
        default slide style, so new decks use the brand rather than the style.
      </p>
      {systems.length === 0 ? (
        <div className="text-sm text-gray-500">
          No design systems have been imported yet.
        </div>
      ) : (
        <ul className="divide-y divide-gray-200 rounded border border-gray-200 bg-white">
          {systems.map(ds => (
            <li
              key={ds.id}
              data-testid={`design-system-row-${ds.id}`}
              className="flex items-center justify-between px-4 py-3 gap-4"
            >
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-gray-900">{ds.name}</span>
                  {ds.is_default && (
                    <span
                      data-testid={`design-system-default-badge-${ds.id}`}
                      className="inline-flex items-center rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-700"
                    >
                      Org default
                    </span>
                  )}
                </div>
                {ds.description && (
                  <div className="text-xs text-gray-500 mt-0.5">{ds.description}</div>
                )}
              </div>
              {ds.is_active && !ds.is_default && (
                <button
                  type="button"
                  disabled={saving === ds.id}
                  onClick={() => void handleSet(ds.id)}
                  className="shrink-0 text-xs font-medium text-blue-600 hover:text-blue-700 hover:underline disabled:cursor-not-allowed disabled:text-blue-300"
                >
                  {saving === ds.id ? 'Setting…' : 'Set as org default'}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};

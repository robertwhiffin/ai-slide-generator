import React, { useEffect, useState } from 'react';
import { configApi } from '../../api/config';
import type { DesignSystemSummary, DesignSystemTemplate } from '../../api/config';
import { useToast } from '../../contexts/ToastContext';

/**
 * Org-default DESIGN SYSTEM administration — the design-system counterpart of
 * {@link AdminSlideStyleDefault}, deliberately mirroring its shape.
 *
 * Setting the org default is what makes a design system apply to new decks (the
 * flag was previously settable but never consumed) FOR USERS WHO HAVE NOT CHOSEN
 * A DEFAULT OF THEIR OWN — a personal default outranks this one. Because a
 * design system also outranks the legacy default slide style, the copy says both
 * things explicitly rather than promising every new deck.
 */
/**
 * One design system's DEFAULT TEMPLATE. New sessions on that design system are
 * pinned to it, and the architect falls back to it for an unpinned deck, so the
 * deck is built from that template's sections instead of improvised markup.
 * "No default" leaves new decks unpinned, as before.
 */
const DefaultTemplateSelect: React.FC<{ ds: DesignSystemSummary }> = ({ ds }) => {
  const [templates, setTemplates] = useState<DesignSystemTemplate[] | null>(null);
  const [saving, setSaving] = useState<boolean>(false);
  const { showToast } = useToast();

  useEffect(() => {
    let cancelled = false;
    configApi.listDesignSystemTemplates(ds.id)
      .then(res => { if (!cancelled) setTemplates(res.templates); })
      .catch(err => {
        console.error('Failed to load design system templates:', err);
        if (!cancelled) setTemplates([]);
      });
    return () => { cancelled = true; };
  }, [ds.id]);

  if (templates === null || templates.length === 0) return null;
  const current = templates.find(t => t.is_default) ?? null;

  const handleChange = async (value: string) => {
    setSaving(true);
    try {
      const res = value === ''
        ? current
          ? await configApi.clearDesignSystemTemplateDefault(ds.id, current.id)
          : null
        : await configApi.setDesignSystemTemplateDefault(ds.id, Number(value));
      if (res) setTemplates(res.templates);
      showToast(
        value === '' ? 'Default template cleared' : 'Default template updated',
        'success',
      );
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      showToast(`Failed to update default template: ${message}`, 'error');
    } finally {
      setSaving(false);
    }
  };

  return (
    <label className="mt-1 flex items-center gap-2 text-xs text-gray-500">
      Default template
      <select
        value={current ? String(current.id) : ''}
        disabled={saving}
        onChange={e => void handleChange(e.target.value)}
        data-testid={`design-system-default-template-${ds.id}`}
        className="rounded border border-gray-300 bg-white px-1.5 py-0.5 text-xs text-gray-900 disabled:cursor-not-allowed disabled:opacity-60"
      >
        <option value="">No default</option>
        {templates.map(t => (
          <option key={t.id} value={String(t.id)}>{t.name}</option>
        ))}
      </select>
    </label>
  );
};

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

  /**
   * TOGGLE the org default. Removing it had no control on any surface, so an admin
   * could promote a design system and switch between systems but never return the
   * org to "no default" — the legacy slide-style fallback was unreachable without
   * deleting the design system outright.
   */
  const handleToggle = async (ds: DesignSystemSummary) => {
    setSaving(ds.id);
    try {
      if (ds.is_default) {
        await configApi.clearDesignSystemDefault(ds.id);
        await load();
        showToast('Org default cleared — new decks use the default slide style', 'success');
      } else {
        await configApi.setDesignSystemDefault(ds.id);
        await load();
        showToast('Org default design system updated', 'success');
      }
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      const action = ds.is_default ? 'clear' : 'set';
      showToast(`Failed to ${action} org default: ${message}`, 'error');
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
        The design system marked as the org default is preselected for new decks.
        A deck created via MCP uses it whenever the caller supplies neither a design
        system nor a slide style of its own; a personal default never applies there,
        because it is stored in the user's browser and the server cannot see it. In
        the app, a user who has set their own default — in the Design System or Slide
        Style library — gets that instead. Where the org default does apply, it
        outranks the default slide style, so those decks use the brand.
      </p>
      <p className="text-sm text-gray-500 mb-4">
        A design system's default template is pinned on every new deck that uses that
        design system, so slides are built from the template's own sections. Users can
        still pick a different template for their deck.
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
                {ds.is_active && <DefaultTemplateSelect ds={ds} />}
              </div>
              {(ds.is_default || ds.is_active) && (
                <button
                  type="button"
                  disabled={saving === ds.id}
                  onClick={() => void handleToggle(ds)}
                  data-testid={`design-system-default-toggle-${ds.id}`}
                  className="shrink-0 text-xs font-medium text-blue-600 hover:text-blue-700 hover:underline disabled:cursor-not-allowed disabled:text-blue-300"
                >
                  {saving === ds.id
                    ? ds.is_default
                      ? 'Clearing…'
                      : 'Setting…'
                    : ds.is_default
                      ? 'Clear org default'
                      : 'Set as org default'}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};

/**
 * Design System Library — the Claude-Design-style front door under "slide style".
 *
 * MVP prioritizes UPLOAD + select. Provides:
 *  - a browse/pick list of org-shared design systems (name, description, counts,
 *    org-default badge), mirroring SlideStyleList
 *  - a detail panel (templates, color tokens, brand assets) via GET /{id}
 *  - the headline "Upload design system" control (POST .zip to /import)
 *  - a PERSONAL default (browser-local) and soft Delete, mirroring slide-style
 *    patterns. The ORG-WIDE default is an admin action and lives under /admin:
 *    this page is per-user, so every user can use all of it.
 *  - a minimal "New" placeholder (the full structured editor is a later phase)
 *
 * Everything rendered here is RUNTIME data from the API — no brand content is
 * hardcoded (public-repo hygiene).
 */

import React, { useState, useEffect, useCallback } from 'react';
import { Palette, Plus, Trash2, UploadCloud } from 'lucide-react';
import { Button } from '@/ui/button';
import { Badge } from '@/ui/badge';
import { configApi } from '../../api/config';
import type { DesignSystemSummary, DesignSystemDetail } from '../../api/config';
import {
  USER_DEFAULT_DESIGN_SYSTEM_KEY,
  useAgentConfig,
} from '../../contexts/AgentConfigContext';
import { ConfirmDialog } from './ConfirmDialog';
import { DesignSystemDetailPanel } from './DesignSystemDetailPanel';
import { DesignSystemUploadDialog } from './DesignSystemUploadDialog';

function pluralize(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? '' : 's'}`;
}

/** Ties the default controls to the one-line precedence note in the header. */
const PERSONAL_DEFAULT_HINT_ID = 'ds-personal-default-hint';

export const DesignSystemLibrary: React.FC = () => {
  const { setUserDefaultDesignSystem } = useAgentConfig();

  const [systems, setSystems] = useState<DesignSystemSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [userDefaultId, setUserDefaultId] = useState<number | null>(() => {
    const stored = localStorage.getItem(USER_DEFAULT_DESIGN_SYSTEM_KEY);
    return stored ? Number(stored) : null;
  });

  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<DesignSystemDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  const [uploadOpen, setUploadOpen] = useState(false);
  const [createPlaceholderOpen, setCreatePlaceholderOpen] = useState(false);
  const [actionId, setActionId] = useState<number | null>(null);

  const [confirmDialog, setConfirmDialog] = useState<{
    isOpen: boolean;
    title: string;
    message: string;
    onConfirm: () => void;
  }>({ isOpen: false, title: '', message: '', onConfirm: () => {} });

  const loadSystems = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const response = await configApi.listDesignSystems();
      setSystems(response.design_systems);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load design systems');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadSystems();
  }, [loadSystems]);

  const selectSystem = useCallback(async (id: number) => {
    setSelectedId(id);
    setDetailLoading(true);
    setDetailError(null);
    try {
      const d = await configApi.getDesignSystem(id);
      setDetail(d);
    } catch (err) {
      setDetail(null);
      setDetailError(err instanceof Error ? err.message : 'Failed to load design system');
    } finally {
      setDetailLoading(false);
    }
  }, []);

  const handleUploaded = useCallback(async (imported: DesignSystemDetail) => {
    setUploadOpen(false);
    await loadSystems();
    setSelectedId(imported.id);
    setDetail(imported);
  }, [loadSystems]);

  /**
   * PRUNE a stale preference: a stored id whose design system has since been
   * deleted or deactivated is not a default any more, and leaving it in place
   * lets it keep claiming the style slot for a design system that can no longer
   * be shown or selected.
   *
   * It RELEASES THE SLOT through the same mutator explicit Clear uses, and that
   * is the whole point. Removing the preference key alone left the dead id
   * sitting in the working config while deleting the only control that could
   * release it — the Clear button is rendered from this preference, so pruning
   * the key hid the escape hatch and wedged the user: a blank design-system
   * selection, no personal style default coming back, and a stale id free to
   * travel into the next deck. Both paths therefore go through
   * `setUserDefaultDesignSystem(null)`, so the key removal and the slot release
   * cannot drift apart.
   *
   * `releaseSlotOnlyIfHolding` is what separates this from explicit Clear. The
   * prune is automatic, so it may retire its own stale preference but must not
   * disturb a design system the user has since chosen in Agent Config: with a
   * different (or no) id in the slot, the key still goes and the slot is left
   * untouched. Explicit Clear passes no option and always releases — it is the
   * control the user asked for.
   *
   * IDEMPOTENT by the guard above: dropping `userDefaultId` first means the next
   * render returns early, so neither the release's config update nor the new
   * callback identity it produces can re-enter this effect — on either branch.
   *
   * Gated on a SUCCESSFUL load rather than on a non-empty list, so that deleting
   * your only design system prunes the preference too, while a failed list
   * request never discards it.
   */
  useEffect(() => {
    if (loading || error != null || userDefaultId == null) return;
    if (systems.some((system) => system.id === userDefaultId && system.is_active)) return;
    const staleId = userDefaultId;
    setUserDefaultId(null);
    setUserDefaultDesignSystem(null, { releaseSlotOnlyIfHolding: staleId }).catch((err) => {
      // Surfaced rather than discarded. The mutator drops the preference LAST, so
      // a failure here leaves it in place and the next visit retries this prune —
      // but a rejection nobody can see is how a silent wedge gets missed.
      console.error('Failed to prune the stale design-system default:', err);
    });
  }, [systems, loading, error, userDefaultId, setUserDefaultDesignSystem]);

  /**
   * The user's PERSONAL default — browser-local, no server call and no authz, so
   * it is available to every user. The ORG-WIDE default is a different thing
   * with a different audience and lives under /admin; this control used to call
   * that admin endpoint from a per-user page, which meant one user's click
   * silently re-branded every other user's new decks (and simply 403'd, tearing
   * the page down, for everyone who was not an admin).
   */
  const handleSetPersonalDefault = useCallback(async (system: DesignSystemSummary) => {
    setUserDefaultId(system.id);
    await setUserDefaultDesignSystem(system.id);
  }, [setUserDefaultDesignSystem]);

  const handleClearPersonalDefault = useCallback(async () => {
    setUserDefaultId(null);
    await setUserDefaultDesignSystem(null);
  }, [setUserDefaultDesignSystem]);

  const handleDelete = useCallback((system: DesignSystemSummary) => {
    setConfirmDialog({
      isOpen: true,
      title: 'Delete Design System',
      message: `Are you sure you want to delete "${system.name}"?\n\nThis soft-deletes the design system. Generation will fall back to the slide-style default.`,
      onConfirm: async () => {
        setActionId(system.id);
        try {
          await configApi.deleteDesignSystem(system.id);
          if (selectedId === system.id) {
            setSelectedId(null);
            setDetail(null);
          }
          await loadSystems();
        } catch (err) {
          setError(err instanceof Error ? err.message : 'Failed to delete design system');
        } finally {
          setActionId(null);
          setConfirmDialog((prev) => ({ ...prev, isOpen: false }));
        }
      },
    });
  }, [loadSystems, selectedId]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-muted-foreground">Loading design systems…</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-destructive">
        Error: {error}
        <Button variant="outline" size="sm" onClick={loadSystems} className="ml-4">
          Retry
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-foreground">Design System Library</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Org-shared, on-brand design systems — templates, color tokens, fonts, and brand assets.
            Upload a bundle, then select one in Agent Config to generate on-brand slides.
          </p>
          {/* Referenced by both default controls via aria-describedby, so the
              precedence is announced with the button rather than only read as
              page text. */}
          <p
            id={PERSONAL_DEFAULT_HINT_ID}
            data-testid="ds-personal-default-hint"
            className="mt-1 text-xs text-muted-foreground"
          >
            Your default applies to new decks in this browser and overrides your default slide
            style.
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setCreatePlaceholderOpen(true)}
            className="gap-1.5"
          >
            <Plus className="size-3.5" />
            New
          </Button>
          <Button size="sm" onClick={() => setUploadOpen(true)} className="gap-1.5">
            <UploadCloud className="size-3.5" />
            Upload design system
          </Button>
        </div>
      </div>

      {systems.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-border bg-muted/20 p-12 text-center">
          <Palette className="mb-3 size-12 text-muted-foreground/50" />
          <p className="text-sm text-muted-foreground">
            No design systems yet. Upload a bundle to get started.
          </p>
          <Button size="sm" onClick={() => setUploadOpen(true)} className="mt-4 gap-1.5">
            <UploadCloud className="size-3.5" />
            Upload design system
          </Button>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          {/* List */}
          <div className="flex flex-col gap-3">
            {systems.map((system) => {
              const isSelected = system.id === selectedId;
              return (
                /* Click-delegation wrapper (mouse convenience only): the card
                   title below is the real <button>, so keyboard/AT users get a
                   proper control and the action Buttons are never nested
                   inside an interactive element (a11y: nested-interactive). */
                <div
                  key={system.id}
                  data-testid="design-system-card"
                  onClick={() => selectSystem(system.id)}
                  className={`cursor-pointer rounded-lg border bg-card p-4 text-left transition-colors hover:bg-accent/5 focus-within:ring-1 focus-within:ring-ring ${
                    isSelected ? 'border-primary ring-1 ring-primary' : 'border-border'
                  }`}
                >
                  <div className="flex items-start gap-4">
                    <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                      <Palette className="size-5" />
                    </div>

                    <div className="min-w-0 flex-1">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <h3 className="text-sm font-medium text-foreground">
                              <button
                                type="button"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  selectSystem(system.id);
                                }}
                                className="text-left focus:outline-none focus-visible:underline"
                              >
                                {system.name}
                              </button>
                            </h3>
                            {system.is_default && (
                              <Badge className="text-xs bg-amber-500/10 text-amber-700 hover:bg-amber-500/20">
                                Default
                              </Badge>
                            )}
                            {system.published && (
                              <Badge variant="secondary" className="text-xs">Published</Badge>
                            )}
                            {!system.is_active && (
                              <Badge variant="outline" className="text-xs">Inactive</Badge>
                            )}
                          </div>
                          {system.description && (
                            <p className="mt-0.5 text-sm text-muted-foreground">{system.description}</p>
                          )}
                          <p className="mt-1.5 flex flex-wrap gap-x-1.5 text-xs text-muted-foreground">
                            <span>{pluralize(system.token_count, 'token')}</span>
                            <span aria-hidden="true">·</span>
                            <span>{pluralize(system.asset_count, 'asset')}</span>
                            <span aria-hidden="true">·</span>
                            <span>{pluralize(system.template_count, 'template')}</span>
                          </p>
                        </div>

                        {/* Actions */}
                        <div className="flex shrink-0 items-center gap-1">
                          {system.id === userDefaultId && (
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-8 px-2 text-xs text-muted-foreground"
                              aria-describedby={PERSONAL_DEFAULT_HINT_ID}
                              onClick={(e) => {
                                e.stopPropagation();
                                void handleClearPersonalDefault();
                              }}
                            >
                              Clear default
                            </Button>
                          )}
                          {system.id !== userDefaultId && system.is_active && (
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-8 px-2 text-xs text-muted-foreground"
                              aria-describedby={PERSONAL_DEFAULT_HINT_ID}
                              onClick={(e) => {
                                e.stopPropagation();
                                void handleSetPersonalDefault(system);
                              }}
                            >
                              Set as default
                            </Button>
                          )}
                          <Button
                            variant="ghost"
                            size="sm"
                            className="size-8 p-0 text-muted-foreground hover:text-destructive"
                            disabled={actionId === system.id}
                            onClick={(e) => {
                              e.stopPropagation();
                              handleDelete(system);
                            }}
                            aria-label="Delete"
                          >
                            <Trash2 className="size-4" />
                          </Button>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Detail */}
          <div>
            <DesignSystemDetailPanel
              detail={selectedId != null ? detail : null}
              loading={detailLoading}
              error={detailError}
              onRenamed={(updated) => {
                setDetail(updated);
                void loadSystems();
              }}
            />
          </div>
        </div>
      )}

      {/* Upload dialog */}
      <DesignSystemUploadDialog
        isOpen={uploadOpen}
        onUploaded={handleUploaded}
        onCancel={() => setUploadOpen(false)}
      />

      {/* Create placeholder (structured editor is a later phase) */}
      {createPlaceholderOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="w-full max-w-md mx-4 rounded-lg border border-border bg-card shadow-lg">
            <div className="border-b border-border px-6 py-4">
              <h2 className="text-lg font-semibold text-foreground">Create from scratch</h2>
            </div>
            <div className="px-6 py-4 text-sm text-muted-foreground">
              The in-app structured editor (token pickers, asset uploads, template refs) is coming
              soon. For now, assemble a bundle and use <strong>Upload design system</strong>.
            </div>
            <div className="flex justify-end gap-2 border-t border-border px-6 py-4">
              <Button variant="outline" onClick={() => setCreatePlaceholderOpen(false)}>
                Close
              </Button>
              <Button
                onClick={() => {
                  setCreatePlaceholderOpen(false);
                  setUploadOpen(true);
                }}
              >
                Upload instead
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Delete confirmation */}
      <ConfirmDialog
        isOpen={confirmDialog.isOpen}
        title={confirmDialog.title}
        message={confirmDialog.message}
        onConfirm={confirmDialog.onConfirm}
        onCancel={() => setConfirmDialog((prev) => ({ ...prev, isOpen: false }))}
      />
    </div>
  );
};

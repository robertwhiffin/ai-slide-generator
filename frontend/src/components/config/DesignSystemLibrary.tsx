/**
 * Design System Library — the Claude-Design-style front door under "slide style".
 *
 * MVP prioritizes UPLOAD + select. Provides:
 *  - a browse/pick list of org-shared design systems (name, description, counts,
 *    org-default badge), mirroring SlideStyleList
 *  - a detail panel (templates, color tokens, brand assets) via GET /{id}
 *  - the headline "Upload design system" control (POST .zip to /import)
 *  - Set-as-org-default and soft Delete, mirroring slide-style patterns
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
import { ConfirmDialog } from './ConfirmDialog';
import { DesignSystemDetailPanel } from './DesignSystemDetailPanel';
import { DesignSystemUploadDialog } from './DesignSystemUploadDialog';

function pluralize(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? '' : 's'}`;
}

export const DesignSystemLibrary: React.FC = () => {
  const [systems, setSystems] = useState<DesignSystemSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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

  const handleSetDefault = useCallback(async (system: DesignSystemSummary) => {
    setActionId(system.id);
    try {
      await configApi.setDesignSystemDefault(system.id);
      await loadSystems();
      if (selectedId === system.id) await selectSystem(system.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to set default');
    } finally {
      setActionId(null);
    }
  }, [loadSystems, selectSystem, selectedId]);

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
                <div
                  key={system.id}
                  data-testid="design-system-card"
                  role="button"
                  tabIndex={0}
                  onClick={() => selectSystem(system.id)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      selectSystem(system.id);
                    }
                  }}
                  className={`cursor-pointer rounded-lg border bg-card p-4 text-left transition-colors hover:bg-accent/5 focus:outline-none focus-visible:ring-1 focus-visible:ring-ring ${
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
                            <h3 className="text-sm font-medium text-foreground">{system.name}</h3>
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
                          {!system.is_default && system.is_active && (
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-8 px-2 text-xs text-muted-foreground"
                              disabled={actionId === system.id}
                              onClick={(e) => {
                                e.stopPropagation();
                                handleSetDefault(system);
                              }}
                            >
                              Set as org default
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

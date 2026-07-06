/**
 * Design System detail panel.
 *
 * Renders the runtime detail of a selected design system (Claude-Design-style):
 *  - Templates (from the manifest)
 *  - Color tokens (swatch + name + hex) and other tokens grouped
 *  - Brand-asset summary grouped by kind
 *
 * All content is RUNTIME data from the API — nothing brand-specific is hardcoded.
 */

import React, { useEffect, useState } from 'react';
import { Check, Layers, Palette, Image as ImageIcon, FileText } from 'lucide-react';
import { Badge } from '@/ui/badge';
import { configApi, resolveApiUrl } from '../../api/config';
import type {
  DesignSystemDetail,
  DesignSystemTemplate,
  DesignSystemToken,
} from '../../api/config';
import { useAgentConfig } from '../../contexts/AgentConfigContext';
import { useToast } from '../../contexts/ToastContext';

interface DesignSystemDetailPanelProps {
  detail: DesignSystemDetail | null;
  loading: boolean;
  error: string | null;
}

interface ManifestTemplate {
  name?: string;
  description?: string;
}

const HEX_COLOR = /^#([0-9a-f]{3}|[0-9a-f]{4}|[0-9a-f]{6}|[0-9a-f]{8})$/i;

function isColorToken(token: DesignSystemToken): boolean {
  return HEX_COLOR.test(token.value.trim());
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function readTemplates(manifest: Record<string, unknown> | null): ManifestTemplate[] {
  const templates = manifest?.templates;
  if (!Array.isArray(templates)) return [];
  return templates.filter((t): t is ManifestTemplate => typeof t === 'object' && t !== null);
}

export const DesignSystemDetailPanel: React.FC<DesignSystemDetailPanelProps> = ({
  detail,
  loading,
  error,
}) => {
  const { agentConfig, updateConfig } = useAgentConfig();
  const { showToast } = useToast();

  // Addressable template entities (thumbnail + "Use"). Systems imported before
  // source files were retained have none — the manifest listing is the fallback.
  const [entityTemplates, setEntityTemplates] = useState<DesignSystemTemplate[]>([]);
  const [templatesLoading, setTemplatesLoading] = useState(false);
  const detailId = detail?.id ?? null;

  useEffect(() => {
    if (detailId == null) {
      setEntityTemplates([]);
      return;
    }
    let cancelled = false;
    setTemplatesLoading(true);
    configApi.listDesignSystemTemplates(detailId)
      .then(res => { if (!cancelled) setEntityTemplates(res.templates); })
      .catch(err => {
        console.error('Failed to load design system templates:', err);
        if (!cancelled) setEntityTemplates([]);
      })
      .finally(() => { if (!cancelled) setTemplatesLoading(false); });

    return () => { cancelled = true; };
  }, [detailId]);

  const handleUseTemplate = async (template: DesignSystemTemplate) => {
    if (detailId == null) return;
    // One atomic config update: selecting a template also selects its design
    // system (the same selection the AgentConfigBar dropdowns drive).
    await updateConfig({
      ...agentConfig,
      design_system_id: detailId,
      template_id: template.id,
    });
    showToast(`Template "${template.name}" selected for generation`, 'success');
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center rounded-lg border border-border bg-card p-8 text-sm text-muted-foreground">
        Loading design system…
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
        {error}
      </div>
    );
  }

  if (!detail) {
    return (
      <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-border bg-muted/20 p-8 text-center">
        <Palette className="mb-3 size-10 text-muted-foreground/50" />
        <p className="text-sm text-muted-foreground">
          Select a design system to see its templates, colors, and brand assets.
        </p>
      </div>
    );
  }

  const templates = readTemplates(detail.manifest_json);
  const colorTokens = detail.tokens.filter(isColorToken);
  const otherTokens = detail.tokens.filter((t) => !isColorToken(t));

  return (
    <div
      data-testid="design-system-detail"
      className="flex flex-col gap-5 rounded-lg border border-border bg-card p-5"
    >
      {/* Header */}
      <div>
        <div className="flex items-center gap-2 flex-wrap">
          <h2 className="text-lg font-semibold text-foreground">{detail.name}</h2>
          {detail.is_default && (
            <Badge className="text-xs bg-amber-500/10 text-amber-700 hover:bg-amber-500/20">
              Org default
            </Badge>
          )}
          {detail.published && (
            <Badge variant="secondary" className="text-xs">Published</Badge>
          )}
          {!detail.is_active && (
            <Badge variant="outline" className="text-xs">Inactive</Badge>
          )}
        </div>
        {detail.description && (
          <p className="mt-1 text-sm text-muted-foreground">{detail.description}</p>
        )}
        <p className="mt-1.5 text-xs text-muted-foreground">
          Created by {detail.created_by || 'system'} • Version {detail.version}
        </p>
      </div>

      {/* Templates */}
      <section>
        <div className="mb-2 flex items-center gap-1.5">
          <Layers className="size-4 text-muted-foreground" />
          <h3 className="text-sm font-medium text-foreground">Templates</h3>
        </div>
        {templatesLoading ? (
          <p className="text-xs text-muted-foreground">Loading templates…</p>
        ) : entityTemplates.length > 0 ? (
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2" data-testid="template-cards">
            {entityTemplates.map((tmpl) => {
              const isSelected =
                agentConfig.design_system_id === detail.id &&
                agentConfig.template_id === tmpl.id;
              return (
                <div
                  key={tmpl.id}
                  className="flex flex-col overflow-hidden rounded-md border border-border bg-muted/20"
                  data-testid="template-card"
                >
                  {tmpl.thumbnail_url ? (
                    <img
                      src={resolveApiUrl(tmpl.thumbnail_url)}
                      alt={`${tmpl.name} preview`}
                      className="aspect-video w-full border-b border-border bg-background object-cover"
                      onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = 'none'; }}
                    />
                  ) : (
                    <div className="flex aspect-video w-full items-center justify-center border-b border-border bg-background text-muted-foreground/40">
                      <Layers className="size-6" />
                    </div>
                  )}
                  <div className="flex flex-1 flex-col gap-1 p-3">
                    <div className="text-sm font-medium text-foreground">{tmpl.name}</div>
                    {tmpl.description && (
                      <div className="text-xs text-muted-foreground">{tmpl.description}</div>
                    )}
                    <div className="mt-auto pt-2">
                      <button
                        onClick={() => handleUseTemplate(tmpl)}
                        disabled={isSelected}
                        className="inline-flex items-center gap-1 rounded border border-border bg-background px-2 py-1 text-xs font-medium text-foreground transition-colors hover:bg-muted disabled:cursor-default disabled:opacity-70"
                        data-testid="use-template-button"
                      >
                        {isSelected ? (
                          <>
                            <Check className="size-3" /> Selected
                          </>
                        ) : (
                          'Use'
                        )}
                      </button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        ) : templates.length === 0 ? (
          <p className="text-xs text-muted-foreground">No templates in this design system.</p>
        ) : (
          /* Manifest-only fallback: systems imported before template sources
             were retained list names/descriptions but are not selectable. */
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {templates.map((tmpl, idx) => (
              <div
                key={`${tmpl.name ?? 'template'}-${idx}`}
                className="rounded-md border border-border bg-muted/20 p-3"
              >
                <div className="text-sm font-medium text-foreground">
                  {tmpl.name || `Template ${idx + 1}`}
                </div>
                {tmpl.description && (
                  <div className="mt-0.5 text-xs text-muted-foreground">{tmpl.description}</div>
                )}
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Color tokens */}
      <section>
        <div className="mb-2 flex items-center gap-1.5">
          <Palette className="size-4 text-muted-foreground" />
          <h3 className="text-sm font-medium text-foreground">Color tokens</h3>
        </div>
        {colorTokens.length === 0 ? (
          <p className="text-xs text-muted-foreground">No color tokens.</p>
        ) : (
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {colorTokens.map((token) => (
              <div
                key={token.id}
                className="flex items-center gap-2 rounded-md border border-border bg-muted/20 p-2"
              >
                <span
                  data-testid="color-swatch"
                  className="size-8 shrink-0 rounded border border-border"
                  style={{ backgroundColor: token.value }}
                  aria-hidden="true"
                />
                <div className="min-w-0">
                  <div className="truncate text-xs font-medium text-foreground">{token.name}</div>
                  <div className="font-mono text-[11px] uppercase text-muted-foreground">
                    {token.value}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {otherTokens.length > 0 && (
          <div className="mt-3">
            <h4 className="mb-1.5 text-xs font-medium uppercase text-muted-foreground">
              Type &amp; spacing
            </h4>
            <div className="flex flex-wrap gap-1.5">
              {otherTokens.map((token) => (
                <span
                  key={token.id}
                  className="inline-flex items-center gap-1 rounded-full border border-border bg-muted/30 px-2 py-0.5 text-xs text-foreground"
                >
                  <span className="text-muted-foreground">{token.group}/{token.name}:</span>
                  <span className="font-mono">{token.value}</span>
                </span>
              ))}
            </div>
          </div>
        )}
      </section>

      {/* Brand assets */}
      <section>
        <div className="mb-2 flex items-center gap-1.5">
          <ImageIcon className="size-4 text-muted-foreground" />
          <h3 className="text-sm font-medium text-foreground">
            Brand assets ({detail.assets.length})
          </h3>
        </div>
        {detail.assets.length === 0 ? (
          <p className="text-xs text-muted-foreground">No brand assets.</p>
        ) : (
          <div className="flex flex-col gap-1.5">
            {detail.assets.map((asset) => (
              <div
                key={asset.id}
                className="flex items-center gap-3 rounded-md border border-border bg-muted/20 p-2"
              >
                {asset.mime.startsWith('image/') ? (
                  <img
                    src={resolveApiUrl(asset.url)}
                    alt={asset.filename}
                    className="size-9 shrink-0 rounded border border-border bg-background object-contain"
                    onError={(e) => { (e.currentTarget as HTMLImageElement).style.visibility = 'hidden'; }}
                  />
                ) : (
                  <span className="flex size-9 shrink-0 items-center justify-center rounded border border-border bg-background text-muted-foreground">
                    <FileText className="size-4" />
                  </span>
                )}
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm text-foreground">{asset.filename}</div>
                  <div className="text-xs text-muted-foreground">
                    {asset.kind} • {formatBytes(asset.size_bytes)}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
};

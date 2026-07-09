/**
 * Design System source-file browser (v1 Phase 6) — the "Open source file" view.
 *
 * Renders the selected design system's retained bundle file tree as collapsible
 * sections — Readme first, then Templates / Brand / Colors / Components / Fonts
 * (plus a trailing Other for anything unbucketed, e.g. SKILL.md). Sections are
 * derived generically from each entry's stored kind + top-level path segment, so
 * the browser works for ANY uploaded bundle — nothing brand-specific is
 * hardcoded.
 *
 * SECURITY: everything here is user-uploaded content. File contents come from
 * the /files/{path} endpoint (which serves text sources as text/plain) and are
 * rendered EXCLUSIVELY as text nodes inside a read-only <pre> — never via
 * dangerouslySetInnerHTML or any other raw-HTML injection. Template thumbnails
 * reuse the existing hardened thumbnail endpoint; binary files are listed as
 * metadata only.
 */

import React, { useCallback, useEffect, useState } from 'react';
import { ChevronDown, ChevronRight, FileText, FolderOpen, X } from 'lucide-react';
import { configApi } from '../../api/config';
import type { DesignSystemFileEntry, DesignSystemTemplate } from '../../api/config';
import { TemplateThumbnail } from './TemplateThumbnail';

interface DesignSystemFileBrowserProps {
  dsId: number;
  /** Addressable template entities (Phase 4) — thumbnail/name/description. */
  templates: DesignSystemTemplate[];
}

type SectionId = 'readme' | 'templates' | 'brand' | 'colors' | 'components' | 'fonts' | 'other';

const SECTION_ORDER: Array<{ id: SectionId; label: string }> = [
  { id: 'readme', label: 'Readme' },
  { id: 'templates', label: 'Templates' },
  { id: 'brand', label: 'Brand' },
  { id: 'colors', label: 'Colors' },
  { id: 'components', label: 'Components' },
  { id: 'fonts', label: 'Fonts' },
  { id: 'other', label: 'Other' },
];

function topSegment(path: string): string {
  const idx = path.indexOf('/');
  return idx === -1 ? '' : path.slice(0, idx).toLowerCase();
}

/** Bucket a file into a browser section from its stored kind + top-level path. */
function sectionFor(file: DesignSystemFileEntry): SectionId {
  const kind = file.kind.toLowerCase();
  const top = topSegment(file.path);
  if (kind === 'readme') return 'readme';
  if (kind === 'template' || top === 'templates') return 'templates';
  if (kind === 'css') return 'colors';
  if (kind === 'font' || top === 'fonts') return 'fonts';
  if (top === 'components' || top === 'ui_kits' || top === 'cards') return 'components';
  if (kind === 'asset' || top === 'assets') return 'brand';
  return 'other';
}

// Mirrors the backend's text-source classification: these open in the source
// viewer; anything else is listed as metadata only (binary payloads are not
// meaningfully viewable as text).
const TEXT_SOURCE_EXTENSIONS = new Set([
  'md', 'markdown', 'css', 'json', 'html', 'htm', 'js', 'mjs', 'svg', 'txt', 'xml',
]);
const TEXT_SOURCE_MIMES = new Set([
  'application/json', 'application/javascript', 'application/ecmascript', 'application/xml',
]);

function isTextSource(file: DesignSystemFileEntry): boolean {
  const mime = file.mime.toLowerCase();
  if (mime.startsWith('text/')) return true;
  if (TEXT_SOURCE_MIMES.has(mime) || mime.endsWith('+json') || mime.endsWith('+xml')) return true;
  const base = file.path.split('/').pop() ?? '';
  const dot = base.lastIndexOf('.');
  const ext = dot === -1 ? '' : base.slice(dot + 1).toLowerCase();
  return TEXT_SOURCE_EXTENSIONS.has(ext);
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

interface OpenFileState {
  path: string;
  content: string | null;
  loading: boolean;
  error: string | null;
}

export const DesignSystemFileBrowser: React.FC<DesignSystemFileBrowserProps> = ({
  dsId,
  templates,
}) => {
  const [files, setFiles] = useState<DesignSystemFileEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [openSections, setOpenSections] = useState<Partial<Record<SectionId, boolean>>>({
    readme: true,
  });
  const [openFile, setOpenFile] = useState<OpenFileState | null>(null);
  const [readme, setReadme] = useState<{ path: string; content: string } | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setFiles([]);
    setOpenFile(null);
    setReadme(null);
    setOpenSections({ readme: true });
    configApi.listDesignSystemFiles(dsId)
      .then((res) => { if (!cancelled) setFiles(res.files); })
      .catch((err) => {
        console.error('Failed to load design system files:', err);
        if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load source files');
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [dsId]);

  // Auto-load the first readme's content — it fronts the browser as safe text.
  const readmePath = files.find((f) => sectionFor(f) === 'readme')?.path ?? null;
  useEffect(() => {
    if (readmePath == null) return;
    let cancelled = false;
    configApi.getDesignSystemFileText(dsId, readmePath)
      .then((text) => { if (!cancelled) setReadme({ path: readmePath, content: text }); })
      .catch((err) => { console.error('Failed to load readme:', err); });
    return () => { cancelled = true; };
  }, [dsId, readmePath]);

  const toggleSection = useCallback((id: SectionId) => {
    setOpenSections((prev) => ({ ...prev, [id]: !prev[id] }));
  }, []);

  const openSourceFile = useCallback((path: string) => {
    setOpenFile({ path, content: null, loading: true, error: null });
    configApi.getDesignSystemFileText(dsId, path)
      .then((text) => {
        setOpenFile((prev) =>
          prev?.path === path ? { path, content: text, loading: false, error: null } : prev
        );
      })
      .catch((err) => {
        console.error('Failed to load file:', err);
        setOpenFile((prev) =>
          prev?.path === path
            ? {
                path,
                content: null,
                loading: false,
                error: err instanceof Error ? err.message : 'Failed to load file',
              }
            : prev
        );
      });
  }, [dsId]);

  const sections = SECTION_ORDER.map(({ id, label }) => ({
    id,
    label,
    files: files.filter((f) => sectionFor(f) === id),
  }));
  const templateEntryPaths = new Set(templates.map((t) => t.entry_path));

  const renderFileRow = (file: DesignSystemFileEntry) => {
    const viewable = isTextSource(file);
    const meta = (
      <>
        <FileText className="size-3.5 shrink-0 text-muted-foreground" />
        <span className="min-w-0 flex-1 truncate text-left font-mono text-xs text-foreground">
          {file.path}
        </span>
        <span className="shrink-0 text-[11px] text-muted-foreground">
          {formatBytes(file.size_bytes)}
        </span>
      </>
    );
    if (!viewable) {
      return (
        <div
          key={file.path}
          title={`${file.mime} — binary file`}
          className="flex items-center gap-2 rounded px-2 py-1 opacity-70"
          data-testid="ds-file-row"
        >
          {meta}
        </div>
      );
    }
    return (
      <button
        key={file.path}
        type="button"
        onClick={() => openSourceFile(file.path)}
        className="flex w-full items-center gap-2 rounded px-2 py-1 transition-colors hover:bg-muted focus:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        data-testid="ds-file-row"
      >
        {meta}
      </button>
    );
  };

  return (
    <section data-testid="ds-file-browser">
      <div className="mb-2 flex items-center gap-1.5">
        <FolderOpen className="size-4 text-muted-foreground" />
        <h3 className="text-sm font-medium text-foreground">Source files</h3>
      </div>

      {loading ? (
        <p className="text-xs text-muted-foreground">Loading source files…</p>
      ) : error ? (
        <p className="text-xs text-destructive">{error}</p>
      ) : files.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          No source files retained for this design system. Re-upload the bundle to browse
          its files.
        </p>
      ) : (
        <div className="flex flex-col gap-1.5">
          {sections.map(({ id, label, files: sectionFiles }) => {
            if (sectionFiles.length === 0) return null;
            const open = Boolean(openSections[id]);
            return (
              <div key={id} className="rounded-md border border-border bg-muted/20">
                <button
                  type="button"
                  onClick={() => toggleSection(id)}
                  aria-expanded={open}
                  className="flex w-full items-center justify-between px-3 py-2 text-left focus:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                  data-testid={`ds-file-section-${id}`}
                >
                  <span className="text-xs font-medium text-foreground">
                    {label}{' '}
                    <span className="font-normal text-muted-foreground">
                      ({sectionFiles.length})
                    </span>
                  </span>
                  {open ? (
                    <ChevronDown className="size-3.5 text-muted-foreground" />
                  ) : (
                    <ChevronRight className="size-3.5 text-muted-foreground" />
                  )}
                </button>

                {open && (
                  <div className="flex flex-col gap-1 border-t border-border p-2">
                    {id === 'readme' && readme != null && (
                      <pre
                        data-testid="ds-readme-content"
                        className="max-h-64 overflow-auto whitespace-pre-wrap break-words rounded border border-border bg-background p-3 font-mono text-xs text-foreground"
                      >
                        {readme.content}
                      </pre>
                    )}

                    {id === 'templates' &&
                      templates.map((tmpl) => (
                        <button
                          key={tmpl.id}
                          type="button"
                          onClick={() => openSourceFile(tmpl.entry_path)}
                          className="flex w-full items-center gap-2 rounded border border-border bg-background px-2 py-1.5 text-left transition-colors hover:bg-muted focus:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                          data-testid="ds-file-template-card"
                        >
                          <TemplateThumbnail
                            dsId={dsId}
                            template={tmpl}
                            className="h-10 w-16 shrink-0 rounded border border-border bg-background"
                          />
                          <span className="min-w-0 flex-1">
                            <span className="block truncate text-xs font-medium text-foreground">
                              {tmpl.name}
                            </span>
                            {tmpl.description && (
                              <span className="block truncate text-[11px] text-muted-foreground">
                                {tmpl.description}
                              </span>
                            )}
                            <span className="block truncate font-mono text-[11px] text-muted-foreground">
                              {tmpl.entry_path}
                            </span>
                          </span>
                        </button>
                      ))}

                    {sectionFiles
                      .filter(
                        (f) => !(id === 'templates' && templateEntryPaths.has(f.path))
                      )
                      .map(renderFileRow)}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {openFile != null && (
        <div
          className="mt-2 rounded-md border border-border bg-muted/20"
          data-testid="ds-file-viewer"
        >
          <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-1.5">
            <span className="min-w-0 truncate font-mono text-xs text-foreground">
              {openFile.path}
            </span>
            <button
              type="button"
              onClick={() => setOpenFile(null)}
              aria-label="Close file"
              className="shrink-0 rounded p-0.5 text-muted-foreground transition-colors hover:text-foreground focus:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            >
              <X className="size-3.5" />
            </button>
          </div>
          {openFile.error ? (
            <p className="p-3 text-xs text-destructive">{openFile.error}</p>
          ) : openFile.loading ? (
            <p className="p-3 text-xs text-muted-foreground">Loading file…</p>
          ) : (
            <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words p-3 font-mono text-xs text-foreground">
              {openFile.content}
            </pre>
          )}
        </div>
      )}
    </section>
  );
};

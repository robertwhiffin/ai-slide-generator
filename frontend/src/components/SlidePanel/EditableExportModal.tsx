// @ts-nocheck
/**
 * Editable-PPTX export picker — 4 modes matching Claude Design's
 * "Export as PPTX" dialog. Presented when the user clicks the
 * "Export as PPTX (editable)" menu item.
 */

import React, { useState } from 'react';

export type EditableExportMode = 'custom' | 'universal' | 'google_slides' | 'screenshot';

interface Props {
  open: boolean;
  onClose: () => void;
  onGenerate: (mode: EditableExportMode) => void;
}

interface Option {
  value: EditableExportMode;
  title: string;
  description: string;
  tag?: string;
}

const OPTIONS: Option[] = [
  {
    value: 'custom',
    title: 'Editable · custom fonts',
    description: 'For computers with brand fonts installed. Best fidelity with full editability.',
  },
  {
    value: 'universal',
    title: 'Editable · universal fonts',
    description: "Substitutes web-safe fonts everyone has. Best for sharing broadly.",
    tag: 'Recommended',
  },
  {
    value: 'google_slides',
    title: 'Editable · Google Slides fonts',
    description: 'Uses Google Fonts for full compatibility when uploading to Google Slides.',
  },
  {
    value: 'screenshot',
    title: 'Screenshot-based PPTX',
    description: 'Pixel-perfect slides as images. Not editable, but exactly what you see.',
  },
];

export function EditableExportModal({ open, onClose, onGenerate }: Props) {
  const [mode, setMode] = useState<EditableExportMode>('universal');

  if (!open) return null;

  return (
    <div
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.4)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        zIndex: 9999,
      }}
      onClick={onClose}
    >
      <div
        style={{
          width: 560, maxWidth: '90vw', background: '#fff', borderRadius: 12,
          boxShadow: '0 12px 40px rgba(0,0,0,0.2)', padding: 0, overflow: 'hidden',
        }}
        onClick={e => e.stopPropagation()}
      >
        <div style={{ display: 'flex', alignItems: 'center', padding: '20px 24px', borderBottom: '1px solid #eee' }}>
          <div style={{ fontSize: 18, fontWeight: 600, flex: 1 }}>Export as PPTX</div>
          <button
            onClick={onClose}
            style={{ border: 0, background: 'transparent', fontSize: 20, cursor: 'pointer', color: '#888' }}
            aria-label="Close"
          >×</button>
        </div>

        <div style={{ padding: '18px 24px' }}>
          <div style={{ fontSize: 14, color: '#888', marginBottom: 12 }}>
            Where is this deck headed?
          </div>
          {OPTIONS.map((opt, i) => (
            <label
              key={opt.value}
              htmlFor={`exp-mode-${opt.value}`}
              style={{
                display: 'flex', alignItems: 'flex-start', gap: 12,
                padding: '14px 0',
                borderTop: i === 0 ? 'none' : '1px solid #eee',
                cursor: 'pointer',
              }}
            >
              <input
                id={`exp-mode-${opt.value}`}
                type="radio"
                name="editable-export-mode"
                value={opt.value}
                checked={mode === opt.value}
                onChange={() => setMode(opt.value)}
                style={{ marginTop: 4 }}
              />
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 15, fontWeight: 600, display: 'flex', alignItems: 'center', gap: 8 }}>
                  {opt.title}
                  {opt.tag && (
                    <span style={{
                      fontSize: 11, fontWeight: 500, padding: '2px 8px', borderRadius: 10,
                      background: '#FFE4DE', color: '#C73E28',
                    }}>{opt.tag}</span>
                  )}
                </div>
                <div style={{ fontSize: 13, color: '#666', marginTop: 3 }}>{opt.description}</div>
              </div>
            </label>
          ))}
        </div>

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 12, padding: '16px 24px', borderTop: '1px solid #eee' }}>
          <button
            onClick={onClose}
            style={{ border: 0, background: 'transparent', color: '#555', fontSize: 14, fontWeight: 500, cursor: 'pointer' }}
          >Cancel</button>
          <button
            onClick={() => { onGenerate(mode); onClose(); }}
            style={{
              background: '#111', color: '#fff', border: 0, borderRadius: 8,
              padding: '10px 18px', fontSize: 14, fontWeight: 500, cursor: 'pointer',
            }}
          >Generate PPTX…</button>
        </div>
      </div>
    </div>
  );
}

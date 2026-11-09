import React, { useEffect, useId, useState } from 'react';
import { Button } from '@/ui/button';
import { generateImageMessage } from '../../utils/imageChatMessages';
import type { GeneratedImageKind } from '../../types/message';

interface GenerateImageRequestDialogProps {
  slideCount: number;
  /** Pre-selects a slide (1-based). */
  forSlide?: number | null;
  onSubmit: (message: string) => void;
  onClose: () => void;
}

const KIND_CHIPS: Array<{ kind: GeneratedImageKind; label: string }> = [
  { kind: 'illustration', label: 'Illustration' },
  { kind: 'icon', label: 'Icon' },
  { kind: 'background', label: 'Background' },
  { kind: 'vector_icon', label: 'Vector icon' },
];

/** Composes a chat message asking the assistant for images; it generates nothing itself. */
export const GenerateImageRequestDialog: React.FC<GenerateImageRequestDialogProps> = ({
  slideCount,
  forSlide = null,
  onSubmit,
  onClose,
}) => {
  const [prompt, setPrompt] = useState('');
  const [kind, setKind] = useState<GeneratedImageKind>('illustration');
  const [options, setOptions] = useState(true);
  const [slide, setSlide] = useState<number | null>(forSlide);
  const titleId = useId();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  const canSend = prompt.trim().length > 0 || slide !== null;

  const submit = () => {
    if (!canSend) return;
    onSubmit(generateImageMessage({ prompt, kind, options, forSlide: slide }));
  };

  const slideNumbers = Array.from({ length: Math.max(0, slideCount) }, (_, i) => i + 1);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="flex w-full max-w-md flex-col gap-4 rounded-lg bg-white p-5 shadow-xl"
      >
        <h2 id={titleId} className="text-lg font-semibold text-gray-800">
          Generate image
        </h2>

        <textarea
          aria-label="Describe the image"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          rows={3}
          autoFocus
          placeholder="Describe the image you want"
          className="w-full resize-none rounded-lg border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
        />

        <div className="flex flex-wrap gap-2">
          {KIND_CHIPS.map((chip) => (
            <button
              key={chip.kind}
              type="button"
              aria-pressed={kind === chip.kind}
              onClick={() => setKind(chip.kind)}
              className={`rounded-full border px-3 py-1 text-xs transition-colors ${
                kind === chip.kind
                  ? 'border-primary bg-primary text-primary-foreground'
                  : 'border-border bg-background text-foreground hover:bg-muted'
              }`}
            >
              {chip.label}
            </button>
          ))}
        </div>

        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={options} onChange={(e) => setOptions(e.target.checked)} />
          Show me 3 options
        </label>

        <label className="flex items-center gap-2 text-sm">
          For slide
          <select
            value={slide === null ? '' : String(slide)}
            onChange={(e) => setSlide(e.target.value === '' ? null : Number(e.target.value))}
            className="rounded border border-input bg-background px-2 py-1 text-sm"
          >
            <option value="">None</option>
            {slideNumbers.map((n) => (
              <option key={n} value={String(n)}>
                {n}
              </option>
            ))}
          </select>
        </label>

        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="button" disabled={!canSend} onClick={submit}>
            Send to chat
          </Button>
        </div>
      </div>
    </div>
  );
};

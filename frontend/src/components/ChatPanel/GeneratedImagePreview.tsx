import React, { useEffect, useId, useState } from 'react';
import { createPortal } from 'react-dom';
import { ChevronLeft, ChevronRight, X } from 'lucide-react';
import { Button } from '@/ui/button';
import { api } from '../../services/api';
import type { GeneratedImageRef } from '../../types/message';
import { cachedFullImage, rememberFullImage } from '../../utils/fullImageCache';

interface GeneratedImagePreviewProps {
  images: GeneratedImageRef[];
  index: number;
  onIndexChange: (index: number) => void;
  onClose: () => void;
  onUse: (img: GeneratedImageRef) => void;
  actionsDisabled: boolean;
  hideActions: boolean;
}

type FullImage = { token: string; src: string | null; failed: boolean };

/** The full-size data URI of a library image (the card's thumbnails are 150 px). */
function useFullImage(token: string): FullImage {
  const [state, setState] = useState<FullImage>({ token, src: null, failed: false });
  useEffect(() => {
    let cancelled = false;
    const cached = cachedFullImage(token);
    if (cached) {
      setState({ token, src: cached, failed: false });
      return;
    }
    Promise.resolve()
      .then(() => api.getImageData(token))
      .then((data) => {
        if (cancelled) return;
        const src = data?.data_uri || null;
        if (src) rememberFullImage(token, src);
        setState({ token, src, failed: !src });
      })
      .catch(() => {
        if (!cancelled) setState({ token, src: null, failed: true });
      });
    return () => {
      cancelled = true;
    };
  }, [token]);
  // A step to another option shows "Loading" until its own image arrives.
  if (state.token === token) return state;
  const cached = cachedFullImage(token);
  return { token, src: cached ?? null, failed: false };
}

/** One option of the options card at full size, to judge detail the chat panel cannot show. */
export const GeneratedImagePreview: React.FC<GeneratedImagePreviewProps> = ({
  images,
  index,
  onIndexChange,
  onClose,
  onUse,
  actionsDisabled,
  hideActions,
}) => {
  const image = images[index];
  const titleId = useId();
  const { src, failed } = useFullImage(image.token);
  const hasPrevious = index > 0;
  const hasNext = index < images.length - 1;
  const label = `Option ${image.option}`;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
      else if (e.key === 'ArrowLeft' && hasPrevious) onIndexChange(index - 1);
      else if (e.key === 'ArrowRight' && hasNext) onIndexChange(index + 1);
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose, onIndexChange, index, hasPrevious, hasNext]);

  return createPortal(
    <div
      className="fixed inset-0 z-[70] flex items-center justify-center bg-black/70 p-4"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="flex max-h-full w-full max-w-5xl flex-col gap-3 rounded-lg bg-white p-4 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between gap-3">
          <h2 id={titleId} className="text-base font-semibold text-gray-800">
            {label}
          </h2>
          <Button type="button" variant="ghost" size="icon" aria-label="Close" onClick={onClose}>
            <X className="size-4" aria-hidden="true" />
          </Button>
        </div>

        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="icon"
            aria-label="Previous option"
            disabled={!hasPrevious}
            onClick={() => onIndexChange(index - 1)}
          >
            <ChevronLeft className="size-4" aria-hidden="true" />
          </Button>
          <div className="flex min-h-[40vh] flex-1 items-center justify-center rounded bg-gray-50">
            {src ? (
              <img
                src={src}
                alt={`${label}, full size`}
                className="max-h-[70vh] max-w-full object-contain"
              />
            ) : (
              <p className="text-sm text-muted-foreground">
                {failed ? "Couldn't load the full-size image." : 'Loading…'}
              </p>
            )}
          </div>
          <Button
            type="button"
            variant="outline"
            size="icon"
            aria-label="Next option"
            disabled={!hasNext}
            onClick={() => onIndexChange(index + 1)}
          >
            <ChevronRight className="size-4" aria-hidden="true" />
          </Button>
        </div>

        <div className="flex items-center justify-between gap-3">
          <div className="flex flex-wrap gap-1.5">
            {image.slides.map((n) => (
              <span key={n} className="rounded bg-primary/10 px-1.5 py-0.5 text-xs text-primary">
                {`On slide ${n}`}
              </span>
            ))}
          </div>
          {!hideActions && image.slides.length === 0 && (
            <Button
              type="button"
              disabled={actionsDisabled}
              onClick={() => {
                onUse(image);
                onClose();
              }}
            >
              Use this
            </Button>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
};

import React, { useEffect, useState } from 'react';
import { ImageOff } from 'lucide-react';
import { Button } from '@/ui/button';
import { api } from '../../services/api';
import type { GeneratedImageRef } from '../../types/message';

interface GeneratedImagesCardProps {
  images: GeneratedImageRef[];
  onUse: (img: GeneratedImageRef) => void;
  onRegenerate: (images: GeneratedImageRef[]) => void;
  actionsDisabled?: boolean;
  hideActions?: boolean;
}

/** The thumbnail data URI for a token, or null when it could not be loaded. */
function useThumbnail(token: string): string | null {
  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    Promise.resolve()
      .then(() => api.getImage(token))
      .then((asset) => {
        if (!cancelled) setSrc(asset?.thumbnail_base64 || null);
      })
      .catch(() => {
        if (!cancelled) setSrc(null);
      });
    return () => {
      cancelled = true;
    };
  }, [token]);
  return src;
}

const Option: React.FC<{
  image: GeneratedImageRef;
  onUse: (img: GeneratedImageRef) => void;
  actionsDisabled: boolean;
  hideActions: boolean;
}> = ({ image, onUse, actionsDisabled, hideActions }) => {
  const src = useThumbnail(image.token);
  const label = `Option ${image.option}`;
  return (
    <li className="flex w-28 flex-col gap-1.5 rounded-lg border border-border bg-background p-1.5">
      <div className="flex h-20 w-full items-center justify-center overflow-hidden rounded bg-white">
        {src ? (
          <img src={src} alt={label} className="h-full w-full object-contain" />
        ) : (
          <div
            data-testid="generated-image-placeholder"
            className="flex h-full w-full items-center justify-center bg-muted text-muted-foreground"
          >
            <ImageOff className="size-5" aria-hidden="true" />
          </div>
        )}
      </div>
      <span className="text-xs font-medium text-foreground">{label}</span>
      {image.slides.map((n) => (
        <span key={n} className="rounded bg-primary/10 px-1.5 py-0.5 text-[11px] text-primary">
          {`On slide ${n}`}
        </span>
      ))}
      {!hideActions && image.slides.length === 0 && (
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="h-7 px-2 text-xs"
          disabled={actionsDisabled}
          onClick={() => onUse(image)}
        >
          Use this
        </Button>
      )}
    </li>
  );
};

/** The options under a reply that generated images: thumbnails, where each is placed, Use / Regenerate. */
export const GeneratedImagesCard: React.FC<GeneratedImagesCardProps> = ({
  images,
  onUse,
  onRegenerate,
  actionsDisabled = false,
  hideActions = false,
}) => (
  <div
    className="max-w-[85%] rounded-xl border border-border bg-card px-3 py-2.5"
    data-testid="generated-images-card"
  >
    <ul className="flex flex-wrap gap-2">
      {images.map((image) => (
        <Option
          key={image.token}
          image={image}
          onUse={onUse}
          actionsDisabled={actionsDisabled}
          hideActions={hideActions}
        />
      ))}
    </ul>
    <div className="mt-2 flex items-center justify-between gap-3">
      <span className="text-xs text-muted-foreground">Saved to your Image Library</span>
      {!hideActions && (
        <Button
          type="button"
          size="sm"
          variant="ghost"
          className="h-7 px-2 text-xs"
          disabled={actionsDisabled}
          onClick={() => onRegenerate(images)}
        >
          Regenerate
        </Button>
      )}
    </div>
  </div>
);

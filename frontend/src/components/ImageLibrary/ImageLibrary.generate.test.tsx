/**
 * @vitest-environment jsdom
 *
 * ImageLibrary x image generation. The library asks the server once whether image
 * generation is available and, only when it is (and the library is editable):
 * - shows a header "Generate" button that opens GenerateImageDialog (no `source`);
 * - shows an "Edit with prompt" control on raster tiles (never SVG) outside picker mode, which opens
 *   the dialog with that tile's image as `source`;
 * - reloads the list when the dialog reports a created image.
 * Tiles tagged `ai_generated` carry a small "AI" badge whatever the availability.
 *
 * Contract: docs/superpowers/plans/2026-11-08-ai-image-generation-CORRECTIONS.md (Unit C).
 *
 * The API module is mocked, and GenerateImageDialog is replaced by a stub (it has its own test
 * file), so these tests see exactly which props the library hands the dialog. The stub requires
 * `GenerateImageDialog` to be a named export of `./GenerateImageDialog`.
 */
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ImageAsset, ImageGenerationOptions, ImageListResponse } from '../../types/image';
import { ImageLibrary } from './ImageLibrary';

interface DialogProps {
  isOpen: boolean;
  onClose: () => void;
  onCreated: (image: ImageAsset) => void;
  options: ImageGenerationOptions;
  source?: ImageAsset;
}

const h = vi.hoisted(() => ({
  listImages: vi.fn(),
  imageGenerationOptions: vi.fn(),
  uploadImage: vi.fn(),
  deleteImage: vi.fn(),
  dialogProps: [] as unknown[],
  createdImage: null as unknown,
}));

vi.mock('../../services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../services/api')>();
  return {
    ...actual,
    api: {
      listImages: (...args: unknown[]) => h.listImages(...args),
      imageGenerationOptions: (...args: unknown[]) => h.imageGenerationOptions(...args),
      uploadImage: (...args: unknown[]) => h.uploadImage(...args),
      deleteImage: (...args: unknown[]) => h.deleteImage(...args),
    },
  };
});

vi.mock('./GenerateImageDialog', () => {
  const GenerateImageDialog = (props: DialogProps) => {
    h.dialogProps.push(props);
    if (!props.isOpen) return null;
    return (
      <div role="dialog" aria-label="Generate image dialog stub">
        <p>source: {props.source ? props.source.id : 'none'}</p>
        <button onClick={() => props.onCreated(h.createdImage as ImageAsset)}>stub: created</button>
        <button onClick={props.onClose}>stub: close</button>
      </div>
    );
  };
  return { GenerateImageDialog, default: GenerateImageDialog };
});

// ---------------------------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------------------------

function asset(overrides: Partial<ImageAsset>): ImageAsset {
  return {
    id: 'tok',
    filename: 'file',
    original_filename: 'file',
    mime_type: 'image/png',
    size_bytes: 4096,
    thumbnail_base64: null,
    tags: [],
    description: null,
    category: 'content',
    uploaded_by: 'alice@example.com',
    is_active: true,
    created_at: '2026-11-08T10:00:00Z',
    updated_at: '2026-11-08T10:00:00Z',
    ...overrides,
  };
}

const JPEG = asset({
  id: 'tok_jpg',
  filename: 'team-photo.jpg',
  original_filename: 'team-photo.jpg',
  mime_type: 'image/jpeg',
  thumbnail_base64: 'data:image/jpeg;base64,/9j/4AAQSkZJRg==',
  tags: ['team'],
});
// The AI tile sits in the middle so a badge or control put on "the first tile" is caught.
const PNG_AI = asset({
  id: 'tok_png',
  filename: 'ai-rocket-icon.png',
  original_filename: 'ai-rocket-icon.png',
  mime_type: 'image/png',
  thumbnail_base64: 'data:image/png;base64,iVBORw0KGgo=',
  tags: ['ai_generated', 'gpt-image-2.6-flare', 'icon_png'],
  description: 'A rocket icon',
});
const SVG = asset({
  id: 'tok_svg',
  filename: 'brand-mark.svg',
  original_filename: 'brand-mark.svg',
  mime_type: 'image/svg+xml',
  thumbnail_base64: null,
  tags: ['brand'],
  category: 'branding',
});
const IMAGES = [JPEG, PNG_AI, SVG];
const NEW_IMAGE = asset({
  id: 'tok_new',
  filename: 'ai-a-lightbulb-20261108T101500Z-9f8e7d6c.png',
  original_filename: 'ai-a-lightbulb-20261108T101500Z-9f8e7d6c.png',
  mime_type: 'image/png',
  tags: ['ai_generated', 'gpt-image-2.6-flare', 'icon_png'],
});
const FILENAMES = [...IMAGES, NEW_IMAGE].map((i) => i.original_filename);

const MODEL = { id: 'gpt-image-2.6-flare', label: 'GPT Image 2.6 Flare', description: 'Newest' };
const AVAILABLE: ImageGenerationOptions = {
  available: true,
  max_prompt_chars: 2000,
  default_preset: 'icon_png',
  presets: [
    {
      id: 'icon_png',
      label: 'Transparent icon',
      description: 'Flat icon on a see-through PNG',
      output_format: 'png',
      category: 'content',
      transparent: true,
      models: [MODEL],
      default_model: MODEL.id,
      qualities: ['low', 'medium', 'high'],
      default_quality: 'low',
    },
  ],
  edit: { models: [MODEL], default_model: MODEL.id, qualities: ['low', 'medium', 'high'], default_quality: 'low' },
};
const UNAVAILABLE: ImageGenerationOptions = {
  available: false,
  max_prompt_chars: 0,
  default_preset: null,
  presets: [],
  edit: null,
};

const listResponse = (images: ImageAsset[]): ImageListResponse => ({ images, total: images.length });

/**
 * Chat image generation (2026-11-09 CORRECTIONS, Unit I): the library reads availability through the
 * module-cached probe in hooks/useImageGenerationOptions, so each test starts from an empty cache
 * (otherwise the first test's answer is served to the next and "asked once" counts leak across tests).
 * Loaded through a glob so this file keeps running before that module exists.
 */
const optionsCacheModules = import.meta.glob<{ __resetImageGenerationOptionsCacheForTests?: () => void }>(
  '../../hooks/useImageGenerationOptions.{ts,tsx}',
  { eager: true },
);
const resetOptionsCache = () => {
  for (const mod of Object.values(optionsCacheModules)) mod.__resetImageGenerationOptionsCacheForTests?.();
};

// ---------------------------------------------------------------------------------------------
// Helpers (roles, accessible names, visible text)
// ---------------------------------------------------------------------------------------------

const generateButton = () => screen.findByRole('button', { name: /^generate/i });
const queryGenerateButton = () => screen.queryByRole('button', { name: /^generate/i });
const queryEditButtons = () => screen.queryAllByRole('button', { name: /edit with prompt/i });

/**
 * The filenames of the tile an element belongs to: walk up to the nearest ancestor whose text
 * names any image. A control that belongs to one tile yields exactly that tile's filename.
 */
function tileOf(el: HTMLElement): string[] {
  let node: HTMLElement | null = el;
  while (node && node !== document.body) {
    const text = node.textContent ?? '';
    const found = FILENAMES.filter((n) => text.includes(n));
    if (found.length) return found;
    node = node.parentElement;
  }
  return [];
}

/** Wait for the grid and for the availability probe to have been asked and answered. */
async function settle({ probe = true }: { probe?: boolean } = {}) {
  await screen.findByText('team-photo.jpg');
  if (probe) await waitFor(() => expect(h.imageGenerationOptions).toHaveBeenCalled());
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

const lastDialogProps = () => h.dialogProps[h.dialogProps.length - 1] as DialogProps | undefined;

describe('ImageLibrary image generation', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    resetOptionsCache();
    h.dialogProps.length = 0;
    h.createdImage = NEW_IMAGE;
    h.listImages.mockResolvedValue(listResponse(IMAGES));
  });

  afterEach(() => {
    cleanup();
  });

  describe('when image generation is available', () => {
    beforeEach(() => {
      h.imageGenerationOptions.mockResolvedValue(AVAILABLE);
    });

    it('shows a Generate button that opens the dialog with the server options and no source', async () => {
      render(<ImageLibrary />);
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

      fireEvent.click(await generateButton());

      expect(await screen.findByRole('dialog')).toHaveTextContent('source: none');
      expect(lastDialogProps()?.isOpen).toBe(true);
      expect(lastDialogProps()?.options).toEqual(AVAILABLE);
      expect(lastDialogProps()?.source).toBeUndefined();

      fireEvent.click(screen.getByRole('button', { name: 'stub: close' }));
      await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    });

    it('puts "Edit with prompt" on the PNG and JPEG tiles and not on the SVG tile', async () => {
      render(<ImageLibrary />);
      await settle();

      const edits = await screen.findAllByRole('button', { name: /edit with prompt/i });
      expect(edits).toHaveLength(2);
      expect(edits.map((b) => tileOf(b)).sort()).toEqual([['ai-rocket-icon.png'], ['team-photo.jpg']]);
    });

    it('"Edit with prompt" opens the dialog with that tile’s image as the source', async () => {
      render(<ImageLibrary />);
      await settle();

      const edits = await screen.findAllByRole('button', { name: /edit with prompt/i });
      const jpegEdit = edits.find((b) => tileOf(b)[0] === 'team-photo.jpg');
      expect(jpegEdit).toBeDefined();
      fireEvent.click(jpegEdit!);

      expect(await screen.findByRole('dialog')).toHaveTextContent('source: tok_jpg');
      expect(lastDialogProps()?.source).toEqual(JPEG);
      expect(lastDialogProps()?.options).toEqual(AVAILABLE);
    });

    it('marks the ai_generated tile, and only it, with an "AI" badge', async () => {
      render(<ImageLibrary />);
      await settle();

      const badges = screen.getAllByText('AI');
      expect(badges).toHaveLength(1);
      expect(tileOf(badges[0])).toEqual(['ai-rocket-icon.png']);
    });

    it('reloads the list when the dialog reports a created image, without re-probing', async () => {
      render(<ImageLibrary />);
      await settle();
      expect(h.listImages).toHaveBeenCalledTimes(1);

      h.listImages.mockResolvedValue(listResponse([NEW_IMAGE, ...IMAGES]));
      fireEvent.click(await generateButton());
      fireEvent.click(await screen.findByRole('button', { name: 'stub: created' }));

      expect(await screen.findByText(NEW_IMAGE.original_filename)).toBeInTheDocument();
      expect(h.listImages).toHaveBeenCalledTimes(2);
      expect(h.imageGenerationOptions).toHaveBeenCalledTimes(1);
    });

    it('in picker mode (onSelect) still offers Generate but no tile edit control', async () => {
      const onSelect = vi.fn();
      render(<ImageLibrary onSelect={onSelect} readOnly={false} />);
      await settle();

      const generate = await generateButton();
      expect(queryEditButtons()).toHaveLength(0);

      fireEvent.click(generate);
      expect(await screen.findByRole('dialog')).toHaveTextContent('source: none');
      expect(onSelect).not.toHaveBeenCalled();
    });

    it('in picker mode a created image is reloaded into the grid', async () => {
      render(<ImageLibrary onSelect={vi.fn()} readOnly={false} />);
      await settle();

      h.listImages.mockResolvedValue(listResponse([NEW_IMAGE, ...IMAGES]));
      fireEvent.click(await generateButton());
      fireEvent.click(await screen.findByRole('button', { name: 'stub: created' }));

      expect(await screen.findByText(NEW_IMAGE.original_filename)).toBeInTheDocument();
      expect(h.listImages).toHaveBeenCalledTimes(2);
    });
  });

  describe('when image generation is not available', () => {
    it('available: false shows no Generate button and no edit control', async () => {
      h.imageGenerationOptions.mockResolvedValue(UNAVAILABLE);
      render(<ImageLibrary />);
      await settle();

      expect(queryGenerateButton()).not.toBeInTheDocument();
      expect(queryEditButtons()).toHaveLength(0);
      // The badge describes the stored image, not the feature flag.
      expect(screen.getAllByText('AI')).toHaveLength(1);
    });

    it('a rejected probe is treated as unavailable, without crashing or an unhandled rejection', async () => {
      const unhandled: unknown[] = [];
      const onUnhandled = (reason: unknown) => unhandled.push(reason);
      process.on('unhandledRejection', onUnhandled);
      try {
        h.imageGenerationOptions.mockRejectedValue(new TypeError('Failed to fetch'));
        render(<ImageLibrary />);
        await settle();
        // Give Node a macrotask turn to report any rejection nobody handled.
        await act(async () => {
          await new Promise((resolve) => setTimeout(resolve, 20));
        });

        expect(unhandled).toEqual([]);
        expect(screen.getByRole('heading', { name: 'Image Library' })).toBeInTheDocument();
        expect(screen.getByText('brand-mark.svg')).toBeInTheDocument();
        expect(queryGenerateButton()).not.toBeInTheDocument();
        expect(queryEditButtons()).toHaveLength(0);
      } finally {
        process.off('unhandledRejection', onUnhandled);
      }
    });

    it('readOnly never probes and shows no Generate button or edit control', async () => {
      h.imageGenerationOptions.mockResolvedValue(AVAILABLE);
      render(<ImageLibrary readOnly />);
      await settle({ probe: false });

      expect(h.imageGenerationOptions).not.toHaveBeenCalled();
      expect(queryGenerateButton()).not.toBeInTheDocument();
      expect(queryEditButtons()).toHaveLength(0);
      expect(screen.getAllByText('AI')).toHaveLength(1);
    });
  });
});

// Controller addition (chat image generation): the library reads availability through the one
// app-wide probe, so a probe the chat already answered is not asked again when the library mounts.
describe('ImageLibrary shares the app-wide availability probe', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    resetOptionsCache();
    h.dialogProps.length = 0;
    h.listImages.mockResolvedValue(listResponse(IMAGES));
    h.imageGenerationOptions.mockResolvedValue(AVAILABLE);
  });

  afterEach(() => {
    cleanup();
  });

  it('does not ask the server again when the probe was already answered', async () => {
    const [mod] = Object.values(
      import.meta.glob<{ getImageGenerationOptions: () => Promise<ImageGenerationOptions> }>(
        '../../hooks/useImageGenerationOptions.{ts,tsx}',
        { eager: true },
      ),
    );
    await expect(mod.getImageGenerationOptions()).resolves.toEqual(AVAILABLE);
    expect(h.imageGenerationOptions).toHaveBeenCalledTimes(1);

    render(<ImageLibrary />);

    expect(await generateButton()).toBeInTheDocument();
    expect(h.imageGenerationOptions).toHaveBeenCalledTimes(1);
  });
});

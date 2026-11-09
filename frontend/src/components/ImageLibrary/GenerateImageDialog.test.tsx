/**
 * @vitest-environment jsdom
 *
 * GenerateImageDialog : the modal that turns a prompt into a new
 * Image Library asset, either from scratch (one button per preset) or as an edited copy of an
 * existing raster image (`source` set).
 *
 * Contract (docs/superpowers/plans/2026-11-08-ai-image-generation-CORRECTIONS.md, Unit C):
 * - presets are `aria-pressed` buttons named by their label (+ description); the default is
 *   `options.default_preset`;
 * - `<select aria-label="Model">` / `<select aria-label="Quality">` hold the selected preset's models
 *   and qualities and reset to its defaults when the preset changes (edit mode: `options.edit`);
 * - the submit button ("Generate", edit mode "Create edited copy") is disabled for a blank prompt or
 *   one over `max_prompt_chars`, and sends EXACTLY `{prompt, preset, model, quality}` (edit:
 *   `{prompt, model, quality}`) with the prompt trimmed;
 * - while running, the inputs are disabled and the status text from `onProgress` plus elapsed
 *   seconds is shown; success calls `onCreated` and offers "Copy reference" (`{{image:<id>}}`) and
 *   "Generate another"; a failure shows `role="alert"` and keeps the prompt for a retry.
 *
 * The API module is mocked; only `ApiError` is kept real so an `instanceof` check still works.
 */
import type { ComponentProps } from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type {
  ImageAsset,
  ImageEditRequest,
  ImageGenerationOptions,
  ImageGenerationRequest,
} from '../../types/image';
import { GenerateImageDialog } from './GenerateImageDialog';

type OnProgress = (progress: number, total: number, status: string) => void;

const generateImage = vi.fn<(req: ImageGenerationRequest, onProgress?: OnProgress) => Promise<ImageAsset>>();
const editImageWithPrompt =
  vi.fn<(imageId: string, req: ImageEditRequest, onProgress?: OnProgress) => Promise<ImageAsset>>();

vi.mock('../../services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../services/api')>();
  return {
    ...actual,
    api: {
      generateImage: (...args: Parameters<typeof generateImage>) => generateImage(...args),
      editImageWithPrompt: (...args: Parameters<typeof editImageWithPrompt>) => editImageWithPrompt(...args),
    },
  };
});

// ---------------------------------------------------------------------------------------------
// Fixtures: shaped like GET /api/images/generate/available (Unit B ImageGenerationOptions).
// Defaults are deliberately NOT the first option of each list, so "pick the first" fails.
// ---------------------------------------------------------------------------------------------

const M25_FLARE = { id: 'gpt-image-2.5-flare', label: 'GPT Image 2.5 Flare', description: 'Fast, good all-rounder' };
const M25_SUNBURST = { id: 'gpt-image-2.5-sunburst', label: 'GPT Image 2.5 Sunburst', description: 'Richer detail' };
const M26_FLARE = { id: 'gpt-image-2.6-flare', label: 'GPT Image 2.6 Flare', description: 'Newest, vector capable' };
const M26_SUNBURST = { id: 'gpt-image-2.6-sunburst', label: 'GPT Image 2.6 Sunburst', description: 'Newest, highest detail' };
const ALL_MODELS = [M25_FLARE, M25_SUNBURST, M26_FLARE, M26_SUNBURST];
const SVG_MODELS = [M26_FLARE, M26_SUNBURST];
const QUALITIES = ['low', 'medium', 'high'];
const MAX_PROMPT_CHARS = 60;

const OPTIONS: ImageGenerationOptions = {
  available: true,
  max_prompt_chars: MAX_PROMPT_CHARS,
  default_preset: 'icon_png',
  presets: [
    {
      id: 'background',
      label: 'Slide background',
      description: 'Full-bleed backdrop with room for a title',
      output_format: 'jpeg',
      category: 'background',
      transparent: false,
      models: ALL_MODELS,
      default_model: M25_SUNBURST.id,
      qualities: QUALITIES,
      default_quality: 'medium',
    },
    {
      id: 'illustration',
      label: 'Illustration',
      description: 'Landscape artwork for a content slide',
      output_format: 'jpeg',
      category: 'content',
      transparent: false,
      models: ALL_MODELS,
      default_model: M25_FLARE.id,
      qualities: QUALITIES,
      default_quality: 'medium',
    },
    {
      id: 'icon_png',
      label: 'Transparent icon',
      description: 'Flat icon on a see-through PNG',
      output_format: 'png',
      category: 'content',
      transparent: true,
      models: ALL_MODELS,
      default_model: M26_FLARE.id,
      qualities: QUALITIES,
      default_quality: 'high',
    },
    {
      id: 'icon_svg',
      label: 'Vector icon',
      description: 'Scalable SVG icon for crisp slides',
      output_format: 'svg',
      category: 'content',
      transparent: false,
      models: SVG_MODELS,
      default_model: M26_SUNBURST.id,
      qualities: QUALITIES,
      default_quality: 'low',
    },
  ],
  // A distinct subset, so edit mode provably reads `options.edit` rather than a preset.
  edit: {
    models: [M25_FLARE, M26_FLARE],
    default_model: M26_FLARE.id,
    qualities: QUALITIES,
    default_quality: 'medium',
  },
  quality_descriptions: {
    low: 'Q-LOW: fastest drafts',
    medium: 'Q-MEDIUM: recommended balance',
    high: 'Q-HIGH: most detail',
  },
};

const PRESET_LABELS = OPTIONS.presets.map((p) => p.label);

function asset(overrides: Partial<ImageAsset>): ImageAsset {
  return {
    id: 'tok_default',
    filename: 'file.png',
    original_filename: 'file.png',
    mime_type: 'image/png',
    size_bytes: 2048,
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

const CREATED = asset({
  id: 'tok_new_rocket',
  filename: 'ai-a-rocket-icon-20261108T100000Z-1a2b3c4d.png',
  original_filename: 'ai-a-rocket-icon-20261108T100000Z-1a2b3c4d.png',
  thumbnail_base64: 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGD4DwABBAEAwS2OUAAAAABJRU5ErkJggg==',
  tags: ['ai_generated', M26_FLARE.id, 'icon_png'],
  description: 'A rocket icon',
});

const SOURCE = asset({
  id: 'tok_team_photo',
  filename: 'team-photo.jpg',
  original_filename: 'team-photo.jpg',
  mime_type: 'image/jpeg',
  thumbnail_base64: 'data:image/jpeg;base64,/9j/4AAQSkZJRg==',
});

// ---------------------------------------------------------------------------------------------
// Helpers (roles and accessible names only)
// ---------------------------------------------------------------------------------------------

const escapeRe = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const presetButton = (label: string) => screen.getByRole('button', { name: new RegExp(escapeRe(label)) });
const queryPresetButton = (label: string) => screen.queryByRole('button', { name: new RegExp(escapeRe(label)) });
const promptBox = () => screen.getByRole('textbox', { name: 'Prompt' }) as HTMLTextAreaElement;
const modelSelect = () => screen.getByRole('combobox', { name: 'Model' }) as HTMLSelectElement;
const qualitySelect = () => screen.getByRole('combobox', { name: 'Quality' }) as HTMLSelectElement;
const submitButton = () => screen.getByRole('button', { name: 'Generate' });
const editSubmitButton = () => screen.getByRole('button', { name: 'Create edited copy' });
const optionValues = (select: HTMLSelectElement) =>
  within(select).getAllByRole('option').map((o) => (o as HTMLOptionElement).value);

function typePrompt(value: string) {
  // fireEvent.change sets the value directly, so it also bypasses the textarea's maxLength.
  fireEvent.change(promptBox(), { target: { value } });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function renderDialog(props: Partial<ComponentProps<typeof GenerateImageDialog>> = {}) {
  const onClose = vi.fn();
  const onCreated = vi.fn();
  render(
    <GenerateImageDialog isOpen onClose={onClose} onCreated={onCreated} options={OPTIONS} {...props} />,
  );
  return { onClose, onCreated };
}

const writeText = vi.fn<(text: string) => Promise<void>>();

describe('GenerateImageDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    writeText.mockResolvedValue(undefined);
    Object.defineProperty(window.navigator, 'clipboard', {
      value: { writeText },
      configurable: true,
      writable: true,
    });
  });

  afterEach(() => {
    cleanup();
    // Remove the stub so jsdom's navigator is back to having no clipboard.
    delete (window.navigator as unknown as { clipboard?: unknown }).clipboard;
  });

  it('renders nothing when closed', () => {
    renderDialog({ isOpen: false });
    expect(screen.queryByRole('textbox', { name: 'Prompt' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Generate' })).not.toBeInTheDocument();
  });

  describe('generate mode', () => {
    it('opens on the default preset with that preset’s default model and quality', () => {
      renderDialog();

      expect(screen.getByRole('heading', { name: /Generate image/ })).toBeInTheDocument();

      // One pressed-state button per preset, labelled with its label and description.
      for (const preset of OPTIONS.presets) {
        const button = presetButton(preset.label);
        expect(button).toHaveTextContent(preset.label);
        expect(button).toHaveTextContent(preset.description);
        expect(button).toHaveAttribute('aria-pressed', preset.id === 'icon_png' ? 'true' : 'false');
      }
      expect(screen.getAllByRole('button', { pressed: true })).toHaveLength(1);

      expect(optionValues(modelSelect())).toEqual(ALL_MODELS.map((m) => m.id));
      expect(modelSelect()).toHaveValue(M26_FLARE.id);
      expect(optionValues(qualitySelect())).toEqual(QUALITIES);
      expect(qualitySelect()).toHaveValue('high');

      // Models are shown to the user by label.
      const labels = within(modelSelect()).getAllByRole('option').map((o) => o.textContent ?? '');
      ALL_MODELS.forEach((m, i) => expect(labels[i]).toContain(m.label));
    });

    it('switches the model list to the clicked preset’s models and resets to its defaults', () => {
      renderDialog();

      // Pick a non-default model/quality first, so a reset is observable.
      fireEvent.change(modelSelect(), { target: { value: M25_SUNBURST.id } });
      fireEvent.change(qualitySelect(), { target: { value: 'medium' } });
      expect(modelSelect()).toHaveValue(M25_SUNBURST.id);

      fireEvent.click(presetButton('Vector icon'));
      expect(presetButton('Vector icon')).toHaveAttribute('aria-pressed', 'true');
      expect(presetButton('Transparent icon')).toHaveAttribute('aria-pressed', 'false');
      expect(optionValues(modelSelect())).toEqual([M26_FLARE.id, M26_SUNBURST.id]);
      expect(modelSelect()).toHaveValue(M26_SUNBURST.id);
      expect(qualitySelect()).toHaveValue('low');

      fireEvent.click(presetButton('Slide background'));
      expect(presetButton('Slide background')).toHaveAttribute('aria-pressed', 'true');
      expect(optionValues(modelSelect())).toEqual(ALL_MODELS.map((m) => m.id));
      expect(modelSelect()).toHaveValue(M25_SUNBURST.id);
      expect(qualitySelect()).toHaveValue('medium');
    });

    it('limits the prompt to max_prompt_chars and shows a live counter', () => {
      renderDialog();
      expect(promptBox()).toHaveAttribute('maxLength', String(MAX_PROMPT_CHARS));
      typePrompt('A red fox');
      expect(screen.getByText(new RegExp(`\\b9\\s*/\\s*${MAX_PROMPT_CHARS}\\b`))).toBeInTheDocument();
    });

    it('enables Generate only for a non-blank prompt within the limit', () => {
      renderDialog();
      expect(submitButton()).toBeDisabled();

      typePrompt('   \n\t  ');
      expect(submitButton()).toBeDisabled();

      typePrompt('x'.repeat(MAX_PROMPT_CHARS + 1));
      expect(submitButton()).toBeDisabled();

      typePrompt('x'.repeat(MAX_PROMPT_CHARS));
      expect(submitButton()).toBeEnabled();

      typePrompt('A rocket icon');
      expect(submitButton()).toBeEnabled();
    });

    it('does not call the API for a blank prompt', () => {
      renderDialog();
      typePrompt('    ');
      fireEvent.click(submitButton());
      expect(generateImage).not.toHaveBeenCalled();
    });

    it('sends exactly {prompt, preset, model, quality} with the prompt trimmed', async () => {
      generateImage.mockReturnValue(new Promise(() => {}));
      renderDialog();

      typePrompt('  A rocket icon \n');
      fireEvent.click(submitButton());

      await waitFor(() => expect(generateImage).toHaveBeenCalledTimes(1));
      expect(generateImage.mock.calls[0][0]).toStrictEqual({
        prompt: 'A rocket icon',
        preset: 'icon_png',
        model: M26_FLARE.id,
        quality: 'high',
      });
      expect(generateImage.mock.calls[0][1]).toEqual(expect.any(Function));
      expect(editImageWithPrompt).not.toHaveBeenCalled();
    });

    it('sends the preset, model and quality the user picked', async () => {
      generateImage.mockReturnValue(new Promise(() => {}));
      renderDialog();

      fireEvent.click(presetButton('Vector icon'));
      fireEvent.change(modelSelect(), { target: { value: M26_FLARE.id } });
      fireEvent.change(qualitySelect(), { target: { value: 'medium' } });
      typePrompt('A lightbulb');
      fireEvent.click(submitButton());

      await waitFor(() => expect(generateImage).toHaveBeenCalledTimes(1));
      expect(generateImage.mock.calls[0][0]).toStrictEqual({
        prompt: 'A lightbulb',
        preset: 'icon_svg',
        model: M26_FLARE.id,
        quality: 'medium',
      });
    });

    it('disables the inputs and shows the progress status while running', async () => {
      const pending = deferred<ImageAsset>();
      generateImage.mockReturnValue(pending.promise);
      const { onCreated } = renderDialog();

      typePrompt('A rocket icon');
      fireEvent.click(submitButton());
      await waitFor(() => expect(generateImage).toHaveBeenCalledTimes(1));

      const onProgress = generateImage.mock.calls[0][1] as OnProgress;
      act(() => onProgress(0, 0, 'Generating image...'));
      expect(await screen.findByText(/Generating image\.\.\./)).toBeInTheDocument();

      expect(promptBox()).toBeDisabled();
      expect(modelSelect()).toBeDisabled();
      expect(qualitySelect()).toBeDisabled();
      for (const label of PRESET_LABELS) expect(presetButton(label)).toBeDisabled();
      expect(submitButton()).toBeDisabled();

      act(() => onProgress(0, 0, 'Saving...'));
      expect(await screen.findByText(/Saving\.\.\./)).toBeInTheDocument();

      // A second click while running must not start a second job.
      fireEvent.click(submitButton());
      expect(generateImage).toHaveBeenCalledTimes(1);
      expect(onCreated).not.toHaveBeenCalled();

      await act(async () => pending.resolve(CREATED));
    });

    it('shows elapsed seconds while running', async () => {
      generateImage.mockReturnValue(new Promise(() => {}));
      renderDialog();

      typePrompt('A rocket icon');
      fireEvent.click(submitButton());

      // Real clock: after ~1 s some element shows "1s" (also accepted: "1 s", "1 sec", "1 seconds").
      expect(
        await screen.findByText(/\b[1-9]\d*\s?s(ec(ond)?s?)?\b/, undefined, { timeout: 3000 }),
      ).toBeInTheDocument();
    });

    it('on success calls onCreated and offers "Copy reference" with the {{image:<id>}} token', async () => {
      generateImage.mockResolvedValue(CREATED);
      const { onCreated } = renderDialog();

      typePrompt('A rocket icon');
      fireEvent.click(submitButton());

      const copy = await screen.findByRole('button', { name: 'Copy reference' });
      expect(onCreated).toHaveBeenCalledTimes(1);
      expect(onCreated).toHaveBeenCalledWith(CREATED);

      // The result thumbnail is shown.
      expect(document.body.querySelector(`img[src="${CREATED.thumbnail_base64}"]`)).not.toBeNull();

      fireEvent.click(copy);
      await waitFor(() => expect(writeText).toHaveBeenCalledWith('{{image:tok_new_rocket}}'));
    });

    it('"Generate another" returns to an enabled form', async () => {
      generateImage.mockResolvedValue(CREATED);
      renderDialog();

      typePrompt('A rocket icon');
      fireEvent.click(submitButton());
      fireEvent.click(await screen.findByRole('button', { name: 'Generate another' }));

      expect(promptBox()).toBeEnabled();
      expect(screen.queryByRole('button', { name: 'Copy reference' })).not.toBeInTheDocument();
      typePrompt('A second icon');
      expect(submitButton()).toBeEnabled();
    });

    it('shows a failure in role="alert" and keeps the prompt for a retry', async () => {
      generateImage.mockRejectedValueOnce(new Error('The image model is rate limited (429). Try again shortly.'));
      const { onCreated } = renderDialog();

      typePrompt('A rocket icon');
      fireEvent.click(submitButton());

      expect(await screen.findByRole('alert')).toHaveTextContent(
        'The image model is rate limited (429). Try again shortly.',
      );
      expect(onCreated).not.toHaveBeenCalled();
      expect(promptBox()).toHaveValue('A rocket icon');
      expect(promptBox()).toBeEnabled();
      expect(submitButton()).toBeEnabled();

      // Retry with the same form.
      generateImage.mockResolvedValueOnce(CREATED);
      fireEvent.click(submitButton());
      await waitFor(() => expect(onCreated).toHaveBeenCalledWith(CREATED));
      expect(generateImage).toHaveBeenCalledTimes(2);
      expect(generateImage.mock.calls[1][0]).toStrictEqual(generateImage.mock.calls[0][0]);
    });

    it('the close button calls onClose', () => {
      const { onClose } = renderDialog();
      fireEvent.click(screen.getByRole('button', { name: /close/i }));
      expect(onClose).toHaveBeenCalledTimes(1);
    });
  });

  describe('edit mode (source set)', () => {
    it('titles the dialog with the source and shows no preset buttons', () => {
      renderDialog({ source: SOURCE });

      expect(screen.getByRole('heading', { name: /Edit with prompt/ })).toBeInTheDocument();
      expect(screen.getAllByText(/team-photo\.jpg/).length).toBeGreaterThan(0);
      for (const label of PRESET_LABELS) expect(queryPresetButton(label)).not.toBeInTheDocument();
      expect(screen.queryAllByRole('button', { pressed: true })).toHaveLength(0);
      expect(screen.queryAllByRole('button', { pressed: false })).toHaveLength(0);
      expect(screen.queryByRole('button', { name: 'Generate' })).not.toBeInTheDocument();
    });

    it('takes models and qualities from options.edit', () => {
      renderDialog({ source: SOURCE });
      expect(optionValues(modelSelect())).toEqual([M25_FLARE.id, M26_FLARE.id]);
      expect(modelSelect()).toHaveValue(M26_FLARE.id);
      expect(optionValues(qualitySelect())).toEqual(QUALITIES);
      expect(qualitySelect()).toHaveValue('medium');
    });

    it('gates "Create edited copy" on the prompt like Generate', () => {
      renderDialog({ source: SOURCE });
      expect(editSubmitButton()).toBeDisabled();
      typePrompt('   ');
      expect(editSubmitButton()).toBeDisabled();
      typePrompt('y'.repeat(MAX_PROMPT_CHARS + 1));
      expect(editSubmitButton()).toBeDisabled();
      typePrompt('Make the sky orange');
      expect(editSubmitButton()).toBeEnabled();
    });

    it('sends editImageWithPrompt(source.id, {prompt, model, quality}) and never generateImage', async () => {
      const edited = asset({ id: 'tok_edited', original_filename: 'ai-edit-team-photo.jpg', mime_type: 'image/jpeg' });
      editImageWithPrompt.mockResolvedValue(edited);
      const { onCreated } = renderDialog({ source: SOURCE });

      fireEvent.change(modelSelect(), { target: { value: M25_FLARE.id } });
      typePrompt(' Make the sky orange  ');
      fireEvent.click(editSubmitButton());

      await waitFor(() => expect(editImageWithPrompt).toHaveBeenCalledTimes(1));
      expect(editImageWithPrompt.mock.calls[0][0]).toBe('tok_team_photo');
      expect(editImageWithPrompt.mock.calls[0][1]).toStrictEqual({
        prompt: 'Make the sky orange',
        model: M25_FLARE.id,
        quality: 'medium',
      });
      expect(editImageWithPrompt.mock.calls[0][2]).toEqual(expect.any(Function));
      expect(generateImage).not.toHaveBeenCalled();

      await waitFor(() => expect(onCreated).toHaveBeenCalledWith(edited));
      fireEvent.click(await screen.findByRole('button', { name: 'Copy reference' }));
      await waitFor(() => expect(writeText).toHaveBeenCalledWith('{{image:tok_edited}}'));
    });

    it('shows an edit failure in role="alert" and keeps the prompt', async () => {
      editImageWithPrompt.mockRejectedValue(new Error('SVG images cannot be edited'));
      renderDialog({ source: SOURCE });

      typePrompt('Make the sky orange');
      fireEvent.click(editSubmitButton());

      expect(await screen.findByRole('alert')).toHaveTextContent('SVG images cannot be edited');
      expect(promptBox()).toHaveValue('Make the sky orange');
      expect(editSubmitButton()).toBeEnabled();
    });
  });
});

describe('GenerateImageDialog model and quality explainers', () => {
  afterEach(() => cleanup());

  it("shows the chosen model's and quality's explainers and follows the selection", () => {
    renderDialog();
    // icon_png defaults to 2.6 Flare at high in this fixture
    expect(screen.getByText(M26_FLARE.description)).toBeInTheDocument();
    expect(screen.getByText('Q-HIGH: most detail')).toBeInTheDocument();
    expect(screen.queryByText(M25_SUNBURST.description)).not.toBeInTheDocument();

    fireEvent.change(screen.getByRole('combobox', { name: 'Model' }), {
      target: { value: M25_SUNBURST.id },
    });
    expect(screen.getByText(M25_SUNBURST.description)).toBeInTheDocument();
    expect(screen.queryByText(M26_FLARE.description)).not.toBeInTheDocument();

    fireEvent.change(screen.getByRole('combobox', { name: 'Quality' }), {
      target: { value: 'low' },
    });
    expect(screen.getByText('Q-LOW: fastest drafts')).toBeInTheDocument();
    expect(screen.queryByText('Q-HIGH: most detail')).not.toBeInTheDocument();
  });

  it('renders without quality explainers when the server sends none', () => {
    const { quality_descriptions: _omit, ...withoutExplainers } = OPTIONS;
    renderDialog({ options: withoutExplainers as typeof OPTIONS });
    expect(screen.getByRole('combobox', { name: 'Quality' })).toBeInTheDocument();
    expect(screen.queryByText(/^Q-/)).not.toBeInTheDocument();
  });
});

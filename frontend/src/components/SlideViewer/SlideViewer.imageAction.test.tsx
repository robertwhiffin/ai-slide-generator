/**
 * Chat image generation, Unit I (Task 8): the slide stage's "Generate image for this slide" action.
 *
 * Contract: docs/superpowers/plans/2026-11-09-chat-image-generation-CORRECTIONS.md, "Unit I interface",
 * Entry points:
 *   SlideViewer gets a stage-toolbar button "Generate image for this slide", shown when the prop
 *   `imageGenerationAvailable` is set. It opens the same GenerateImageRequestDialog with
 *   `forSlide = currentIndex + 1` and sends through the existing `onSendMessage` path.
 * The graph engine ignores slide_context, so the message itself must name the slide.
 *
 * Choices pinned here where CORRECTIONS is silent (the button is a mutating control, like Optimize
 * layout beside it): no button when `readOnly`, or when there is no `onSendMessage` to send through.
 * AppLayout passes `imageGenerationAvailable` from useImageGenerationOptions() and a non-legacy deck
 * mode (exercised by tests/e2e/chat-image-generation.spec.ts).
 *
 * Harness as SlideInsert.test.tsx: the api module is mocked, `localStorage` is an in-memory stub
 * (local Node 25/26 exposes none to jsdom), the feedback drawer starts closed, decks carry no
 * content_hash so auto-verification stays out of the way.
 */
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SlideViewer } from './SlideViewer';
import { ToastProvider } from '../../contexts/ToastContext';
import type { SlideDeck } from '../../types/slide';
import type { DrawerCallbacks, SlideFinding } from '../../types/finding';

vi.mock('../../services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../services/api')>();
  return {
    ...actual,
    api: {
      getSlides: vi.fn().mockResolvedValue({ slide_deck: null }),
      verifySlide: vi.fn().mockResolvedValue({}),
    },
  };
});

class MemoryStorage implements Storage {
  private store = new Map<string, string>();
  get length() { return this.store.size; }
  clear() { this.store.clear(); }
  getItem(key: string) { return this.store.has(key) ? this.store.get(key)! : null; }
  key(i: number) { return Array.from(this.store.keys())[i] ?? null; }
  removeItem(key: string) { this.store.delete(key); }
  setItem(key: string, value: string) { this.store.set(key, String(value)); }
}

const noop = () => undefined;
const callbacks: DrawerCallbacks = { onApplyFinding: noop, onDismissFinding: noop, onDiscussFinding: noop };

function deckOf(n: number): SlideDeck {
  return {
    title: 'Deck',
    slide_count: n,
    css: '',
    external_scripts: [],
    scripts: '',
    slides: Array.from({ length: n }, (_, index) => ({
      index,
      slide_id: `s${index + 1}`,
      html: `<div class="slide"><h1>Slide ${index + 1}</h1></div>`,
      scripts: '',
    })),
  };
}

interface Props {
  imageGenerationAvailable?: boolean;
  readOnly?: boolean;
  withSend?: boolean;
  insertDisabled?: boolean;
  findings?: SlideFinding[];
  drawerCallbacks?: DrawerCallbacks;
}

function renderViewer({
  imageGenerationAvailable,
  readOnly = false,
  withSend = true,
  insertDisabled,
  findings = [],
  drawerCallbacks = callbacks,
}: Props = {}) {
  const onSendMessage = vi.fn();
  const extra = {
    ...(imageGenerationAvailable === undefined ? {} : { imageGenerationAvailable }),
    ...(insertDisabled === undefined ? {} : { insertDisabled }),
  };
  render(
    <ToastProvider>
      <SlideViewer
        slideDeck={deckOf(4)}
        deckKey="sess-img"
        findings={findings}
        callbacks={drawerCallbacks}
        onReorder={noop}
        onSlideChange={noop}
        onSendMessage={withSend ? onSendMessage : undefined}
        readOnly={readOnly}
        sessionId="sess-img"
        {...extra}
      />
    </ToastProvider>,
  );
  return { onSendMessage };
}

const ACTION = 'Generate image for this slide';
const action = () => screen.getByRole('button', { name: ACTION });
const queryAction = () => screen.queryByRole('button', { name: ACTION });
const dialog = () => screen.getByRole('dialog');
const slideSelect = () => within(dialog()).getByRole('combobox', { name: 'For slide' }) as HTMLSelectElement;

function goToSlide(n: number) {
  fireEvent.click(screen.getByTestId(`ribbon-thumb-${n - 1}`));
  expect(screen.getByTestId(`ribbon-thumb-${n - 1}`)).toHaveAttribute('data-current', 'true');
}

beforeEach(() => {
  vi.stubGlobal('localStorage', new MemoryStorage());
  localStorage.setItem(
    'tellr-viewer-view-state',
    JSON.stringify({ drawerOpen: false, drawerHeight: 180, activeTab: 'feedback' }),
  );
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('SlideViewer "Generate image for this slide"', () => {
  it('is on the stage toolbar when imageGenerationAvailable is set', () => {
    renderViewer({ imageGenerationAvailable: true });

    expect(within(screen.getByTestId('stage-toolbar')).getByRole('button', { name: ACTION })).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('opens the dialog for the current slide, and sends a message naming slide 3', () => {
    const { onSendMessage } = renderViewer({ imageGenerationAvailable: true });
    goToSlide(3);

    fireEvent.click(action());
    expect(slideSelect().selectedOptions[0]?.textContent).toBe('3');
    expect(within(slideSelect()).getAllByRole('option').map((o) => o.textContent)).toEqual(['None', '1', '2', '3', '4']);

    fireEvent.change(within(dialog()).getByRole('textbox', { name: 'Describe the image' }), {
      target: { value: 'A lighthouse at dusk' },
    });
    fireEvent.click(within(dialog()).getByRole('button', { name: 'Send to chat' }));

    expect(onSendMessage).toHaveBeenCalledTimes(1);
    const message = onSendMessage.mock.calls[0][0] as string;
    expect(message).toContain('slide 3');
    expect(message).toBe('Generate 3 illustration options for slide 3: A lighthouse at dusk');
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('on the first slide it names slide 1, and a single image is added to it', () => {
    const { onSendMessage } = renderViewer({ imageGenerationAvailable: true });

    fireEvent.click(action());
    fireEvent.click(within(dialog()).getByRole('button', { name: 'Icon' }));
    fireEvent.click(within(dialog()).getByRole('checkbox', { name: 'Show me 3 options' }));
    fireEvent.change(within(dialog()).getByRole('textbox', { name: 'Describe the image' }), {
      target: { value: 'A shield' },
    });
    fireEvent.click(within(dialog()).getByRole('button', { name: 'Send to chat' }));

    expect(onSendMessage.mock.calls[0][0]).toBe('Generate an icon and add it to slide 1: A shield');
  });

  it('Cancel sends nothing', () => {
    const { onSendMessage } = renderViewer({ imageGenerationAvailable: true });
    fireEvent.click(action());
    fireEvent.click(within(dialog()).getByRole('button', { name: 'Cancel' }));

    expect(screen.queryByRole('dialog')).toBeNull();
    expect(onSendMessage).not.toHaveBeenCalled();
  });

  it('is absent without imageGenerationAvailable (the other stage controls are there)', () => {
    renderViewer();

    expect(screen.getByTestId('stage-optimize-layout')).toBeInTheDocument();
    expect(queryAction()).toBeNull();
  });

  it('is absent when imageGenerationAvailable is false', () => {
    renderViewer({ imageGenerationAvailable: false });

    expect(screen.getByTestId('stage-optimize-layout')).toBeInTheDocument();
    expect(queryAction()).toBeNull();
  });

  it('is absent on a read-only viewer even when available', () => {
    renderViewer({ imageGenerationAvailable: true, readOnly: true });

    expect(screen.getByTestId('stage-toolbar')).toBeInTheDocument();
    expect(queryAction()).toBeNull();
  });

  it('is absent when there is no send path', () => {
    renderViewer({ imageGenerationAvailable: true, withSend: false });

    expect(screen.getByTestId('stage-insert-slide')).toBeInTheDocument();
    expect(queryAction()).toBeNull();
  });
});

// Controller addition (CORRECTIONS R13): the action sends a chat message, so while a turn is
// running (AppLayout passes `insertDisabled={isGenerating}`) it is disabled like the other stage actions.
describe('SlideViewer "Generate image for this slide" while a turn is running', () => {
  it('is disabled and opens nothing', () => {
    const { onSendMessage } = renderViewer({ imageGenerationAvailable: true, insertDisabled: true });

    expect(action()).toBeDisabled();
    fireEvent.click(action());
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(onSendMessage).not.toHaveBeenCalled();
  });

  it('is enabled when no turn is running', () => {
    renderViewer({ imageGenerationAvailable: true, insertDisabled: false });

    expect(action()).toBeEnabled();
  });
});

// Final review F2: a second send while a turn runs made the first one unstoppable. Every stage control
// that sends a chat message waits for the running turn: Optimize layout, and the feedback drawer's
// Apply and Discuss (Dismiss sends nothing, so it stays).
describe('SlideViewer chat-sending controls while a turn is running (final review F2)', () => {
  const finding: SlideFinding = {
    id: 'f-1',
    slideIndex: 0,
    category: 'content',
    criterion: 'test-criterion',
    message: 'An open finding',
    plainMessage: 'Something here may need a closer look. This was not fixed automatically.',
    plainIssue: 'Something here may need a closer look.',
    objective: true,
    status: 'open',
    seen: false,
  };
  const optimize = () => screen.getByTestId('stage-optimize-layout');

  function renderWithDrawer(insertDisabled: boolean) {
    localStorage.setItem(
      'tellr-viewer-view-state',
      JSON.stringify({ drawerOpen: true, drawerHeight: 180, activeTab: 'feedback' }),
    );
    const drawerCallbacks = { onApplyFinding: vi.fn(), onDismissFinding: vi.fn(), onDiscussFinding: vi.fn() };
    const { onSendMessage } = renderViewer({ insertDisabled, findings: [finding], drawerCallbacks });
    return { onSendMessage, drawerCallbacks };
  }

  it('Optimize layout, Apply and Discuss are disabled and send nothing', () => {
    const { onSendMessage, drawerCallbacks } = renderWithDrawer(true);

    expect(optimize()).toBeDisabled();
    fireEvent.click(optimize());
    expect(onSendMessage).not.toHaveBeenCalled();

    expect(screen.getByTestId('finding-apply-f-1')).toBeDisabled();
    expect(screen.getByTestId('finding-discuss-f-1')).toBeDisabled();
    fireEvent.click(screen.getByTestId('finding-apply-f-1'));
    fireEvent.click(screen.getByTestId('finding-discuss-f-1'));
    expect(drawerCallbacks.onApplyFinding).not.toHaveBeenCalled();
    expect(drawerCallbacks.onDiscussFinding).not.toHaveBeenCalled();
    expect(screen.getByTestId('finding-dismiss-f-1')).toBeEnabled();
  });

  it('they are enabled and send when no turn is running', () => {
    const { onSendMessage, drawerCallbacks } = renderWithDrawer(false);

    expect(screen.getByTestId('finding-apply-f-1')).toBeEnabled();
    fireEvent.click(screen.getByTestId('finding-apply-f-1'));
    expect(drawerCallbacks.onApplyFinding).toHaveBeenCalledWith('f-1');
    fireEvent.click(screen.getByTestId('finding-discuss-f-1'));
    expect(drawerCallbacks.onDiscussFinding).toHaveBeenCalledWith('f-1');

    expect(optimize()).toBeEnabled();
    fireEvent.click(optimize());
    expect(onSendMessage).toHaveBeenCalledTimes(1);
  });
});

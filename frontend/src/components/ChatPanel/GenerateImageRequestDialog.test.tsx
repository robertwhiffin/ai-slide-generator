/**
 * Chat image generation, Unit I (Task 8): the "Generate image" request dialog. It generates nothing
 * itself: it composes a chat message for the architect and hands it to its caller.
 *
 * Contract: docs/superpowers/plans/2026-11-09-chat-image-generation-CORRECTIONS.md, "Unit I interface",
 * `GenerateImageRequestDialog` (components/ChatPanel/GenerateImageRequestDialog.tsx, named export):
 *   - a prompt textarea, aria-label "Describe the image";
 *   - kind chips, buttons with `aria-pressed`: "Illustration", "Icon", "Background", "Vector icon";
 *   - a checkbox "Show me 3 options", checked by default;
 *   - an optional "For slide" select: None, 1..slideCount;
 *   - a submit button "Send to chat", disabled when the prompt is empty and no slide is chosen.
 *   The message is exactly `generateImageMessage({prompt, kind, options, forSlide})`.
 *
 * Props this test pins (the implementer must match them; the parent mounts the dialog to open it):
 *   slideCount: number            // the For-slide choices are 1..slideCount
 *   forSlide?: number | null      // pre-selects a slide (the slide stage passes currentIndex + 1)
 *   onSubmit: (message: string) => void
 *   onClose: () => void           // Cancel
 *
 * Choices this test pins where CORRECTIONS is silent:
 *   - the dialog is role="dialog";
 *   - the kind chips are single-select and "Illustration" is pressed when the dialog opens;
 *   - the For-slide control is a native <select> labelled "For slide", options read exactly
 *     "None", "1", "2", ...; None is selected unless `forSlide` says otherwise;
 *   - a whitespace-only prompt counts as empty;
 *   - a "Cancel" button calls onClose and sends nothing.
 */
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { GenerateImageRequestDialog } from './GenerateImageRequestDialog';

const KINDS = ['Illustration', 'Icon', 'Background', 'Vector icon'];

function renderDialog(props: { slideCount?: number; forSlide?: number | null } = {}) {
  const onSubmit = vi.fn();
  const onClose = vi.fn();
  render(
    <GenerateImageRequestDialog
      slideCount={props.slideCount ?? 4}
      forSlide={props.forSlide}
      onSubmit={onSubmit}
      onClose={onClose}
    />,
  );
  return { onSubmit, onClose };
}

// ── queries and actions ───────────────────────────────────────────────────────

const dialog = () => screen.getByRole('dialog');
const prompt = () => within(dialog()).getByRole('textbox', { name: 'Describe the image' });
const chip = (name: string) => within(dialog()).getByRole('button', { name });
const optionsBox = () => within(dialog()).getByRole('checkbox', { name: 'Show me 3 options' });
const slideSelect = () => within(dialog()).getByRole('combobox', { name: 'For slide' }) as HTMLSelectElement;
const submit = () => within(dialog()).getByRole('button', { name: 'Send to chat' });

const pressed = () => KINDS.filter((k) => chip(k).getAttribute('aria-pressed') === 'true');
const slideLabels = () => within(slideSelect()).getAllByRole('option').map((o) => o.textContent);
const selectedSlide = () => slideSelect().selectedOptions[0]?.textContent;

function type(text: string) {
  fireEvent.change(prompt(), { target: { value: text } });
}

/** Pick a For-slide choice by its visible label, whatever its value attribute is. */
function chooseSlide(label: string) {
  const option = within(slideSelect()).getByRole('option', { name: label }) as HTMLOptionElement;
  fireEvent.change(slideSelect(), { target: { value: option.value } });
}

afterEach(() => cleanup());

// ── tests ─────────────────────────────────────────────────────────────────────

describe('GenerateImageRequestDialog: controls', () => {
  it('is a dialog with the prompt, the kinds, the options toggle, the slide choice and Send to chat', () => {
    renderDialog();

    expect(dialog()).toBeInTheDocument();
    expect(prompt()).toHaveValue('');
    for (const k of KINDS) expect(chip(k)).toHaveAttribute('aria-pressed');
    expect(optionsBox()).toBeInTheDocument();
    expect(slideSelect()).toBeInTheDocument();
    expect(submit()).toBeInTheDocument();
  });

  it('opens with Illustration pressed, and the chips toggle as a single choice', () => {
    renderDialog();
    expect(pressed()).toEqual(['Illustration']);

    fireEvent.click(chip('Icon'));
    expect(pressed()).toEqual(['Icon']);
    expect(chip('Illustration')).toHaveAttribute('aria-pressed', 'false');

    fireEvent.click(chip('Vector icon'));
    expect(pressed()).toEqual(['Vector icon']);

    fireEvent.click(chip('Background'));
    expect(pressed()).toEqual(['Background']);
  });

  it('"Show me 3 options" is checked by default and can be turned off', () => {
    renderDialog();
    expect(optionsBox()).toBeChecked();
    fireEvent.click(optionsBox());
    expect(optionsBox()).not.toBeChecked();
  });

  it('the For-slide select lists None then 1..slideCount, None selected', () => {
    renderDialog({ slideCount: 4 });
    expect(slideLabels()).toEqual(['None', '1', '2', '3', '4']);
    expect(selectedSlide()).toBe('None');
  });

  it('follows slideCount', () => {
    renderDialog({ slideCount: 7 });
    expect(slideLabels()).toEqual(['None', '1', '2', '3', '4', '5', '6', '7']);
  });

  it('offers only None when the deck has no slides', () => {
    renderDialog({ slideCount: 0 });
    expect(slideLabels()).toEqual(['None']);
  });

  it('pre-selects the slide given as forSlide', () => {
    renderDialog({ slideCount: 4, forSlide: 3 });
    expect(selectedSlide()).toBe('3');
  });
});

describe('GenerateImageRequestDialog: Send to chat', () => {
  it('is disabled with an empty prompt and no slide', () => {
    renderDialog();
    expect(submit()).toBeDisabled();
  });

  it('is disabled with a whitespace-only prompt and no slide', () => {
    renderDialog();
    type('   ');
    expect(submit()).toBeDisabled();
  });

  it('is enabled once there is a prompt', () => {
    renderDialog();
    type('A shield');
    expect(submit()).toBeEnabled();
  });

  it('is enabled with an empty prompt when a slide is chosen', () => {
    renderDialog();
    chooseSlide('2');
    expect(submit()).toBeEnabled();
  });

  it('a disabled Send to chat sends nothing', () => {
    const { onSubmit } = renderDialog();
    fireEvent.click(submit());
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('sends the defaults: 3 illustration options, no slide', () => {
    const { onSubmit } = renderDialog();
    type('A calm lake at dawn');
    fireEvent.click(submit());
    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit).toHaveBeenCalledWith('Generate 3 illustration options: A calm lake at dawn');
  });

  it('sends 3 icon options for slide 2', () => {
    const { onSubmit } = renderDialog();
    type('A shield');
    fireEvent.click(chip('Icon'));
    chooseSlide('2');
    fireEvent.click(submit());
    expect(onSubmit).toHaveBeenCalledWith('Generate 3 icon options for slide 2: A shield');
  });

  it('with options off, sends one image to add to the chosen slide', () => {
    const { onSubmit } = renderDialog();
    type('A shield');
    fireEvent.click(chip('Icon'));
    fireEvent.click(optionsBox());
    chooseSlide('2');
    fireEvent.click(submit());
    expect(onSubmit).toHaveBeenCalledWith('Generate an icon and add it to slide 2: A shield');
  });

  it('with options off and no slide, sends one image', () => {
    const { onSubmit } = renderDialog();
    type('A soft blue gradient');
    fireEvent.click(chip('Background'));
    fireEvent.click(optionsBox());
    fireEvent.click(submit());
    expect(onSubmit).toHaveBeenCalledWith('Generate a background: A soft blue gradient');
  });

  it('an empty prompt with a slide ends the message with "."', () => {
    const { onSubmit } = renderDialog();
    fireEvent.click(chip('Vector icon'));
    chooseSlide('4');
    fireEvent.click(submit());
    expect(onSubmit).toHaveBeenCalledWith('Generate 3 vector icon options for slide 4.');
  });

  it('uses the pre-selected slide', () => {
    const { onSubmit } = renderDialog({ forSlide: 3 });
    type('A lighthouse');
    fireEvent.click(submit());
    expect(onSubmit).toHaveBeenCalledWith('Generate 3 illustration options for slide 3: A lighthouse');
  });

  it('choosing None again drops the slide', () => {
    const { onSubmit } = renderDialog({ forSlide: 3 });
    type('A lighthouse');
    chooseSlide('None');
    fireEvent.click(submit());
    expect(onSubmit).toHaveBeenCalledWith('Generate 3 illustration options: A lighthouse');
  });

  it('Cancel closes without sending', () => {
    const { onSubmit, onClose } = renderDialog();
    type('A shield');
    fireEvent.click(within(dialog()).getByRole('button', { name: 'Cancel' }));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onSubmit).not.toHaveBeenCalled();
  });
});

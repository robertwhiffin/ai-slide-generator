/**
 * @vitest-environment jsdom
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AdminDesignSystemDefault } from './AdminDesignSystemDefault';

const listDesignSystems = vi.fn();
const listDesignSystemTemplates = vi.fn();
const setDesignSystemTemplateDefault = vi.fn();
const clearDesignSystemTemplateDefault = vi.fn();
const showToast = vi.fn();

vi.mock('../../api/config', () => ({
  configApi: {
    listDesignSystems: (...args: unknown[]) => listDesignSystems(...args),
    listDesignSystemTemplates: (...args: unknown[]) => listDesignSystemTemplates(...args),
    setDesignSystemTemplateDefault: (...args: unknown[]) =>
      setDesignSystemTemplateDefault(...args),
    clearDesignSystemTemplateDefault: (...args: unknown[]) =>
      clearDesignSystemTemplateDefault(...args),
    setDesignSystemDefault: vi.fn(),
    clearDesignSystemDefault: vi.fn(),
  },
}));

vi.mock('../../contexts/ToastContext', () => ({
  useToast: () => ({ showToast }),
}));

const template = (id: number, name: string, isDefault: boolean) => ({
  id,
  name,
  description: null,
  entry_path: `templates/${name.toLowerCase()}/index.html`,
  thumbnail_url: null,
  is_default: isDefault,
});

describe('AdminDesignSystemDefault — default template', () => {
  afterEach(() => {
    cleanup();
  });

  beforeEach(() => {
    vi.clearAllMocks();
    listDesignSystems.mockResolvedValue({
      design_systems: [
        { id: 1, name: 'Acme', description: null, is_default: true, is_active: true },
      ],
    });
  });

  it('shows the current default template', async () => {
    listDesignSystemTemplates.mockResolvedValue({
      templates: [template(10, 'Corporate', true), template(11, 'Events', false)],
      total: 2,
    });
    render(<AdminDesignSystemDefault />);

    const select = (await screen.findByTestId(
      'design-system-default-template-1',
    )) as HTMLSelectElement;
    expect(select.value).toBe('10');
    expect(listDesignSystemTemplates).toHaveBeenCalledWith(1);
  });

  it('sets a new default template', async () => {
    listDesignSystemTemplates.mockResolvedValue({
      templates: [template(10, 'Corporate', false), template(11, 'Events', false)],
      total: 2,
    });
    setDesignSystemTemplateDefault.mockResolvedValue({
      templates: [template(10, 'Corporate', false), template(11, 'Events', true)],
      total: 2,
    });
    render(<AdminDesignSystemDefault />);

    const select = (await screen.findByTestId(
      'design-system-default-template-1',
    )) as HTMLSelectElement;
    expect(select.value).toBe('');
    fireEvent.change(select, { target: { value: '11' } });

    await waitFor(() => expect(setDesignSystemTemplateDefault).toHaveBeenCalledWith(1, 11));
    await waitFor(() => expect(select.value).toBe('11'));
    expect(clearDesignSystemTemplateDefault).not.toHaveBeenCalled();
  });

  it('clears the default with "No default"', async () => {
    listDesignSystemTemplates.mockResolvedValue({
      templates: [template(10, 'Corporate', true)],
      total: 1,
    });
    clearDesignSystemTemplateDefault.mockResolvedValue({
      templates: [template(10, 'Corporate', false)],
      total: 1,
    });
    render(<AdminDesignSystemDefault />);

    const select = (await screen.findByTestId(
      'design-system-default-template-1',
    )) as HTMLSelectElement;
    fireEvent.change(select, { target: { value: '' } });

    await waitFor(() => expect(clearDesignSystemTemplateDefault).toHaveBeenCalledWith(1, 10));
    await waitFor(() => expect(select.value).toBe(''));
  });

  it('renders no selector for a design system without templates', async () => {
    listDesignSystemTemplates.mockResolvedValue({ templates: [], total: 0 });
    render(<AdminDesignSystemDefault />);

    await screen.findByText('Acme');
    await waitFor(() => expect(listDesignSystemTemplates).toHaveBeenCalled());
    expect(screen.queryByTestId('design-system-default-template-1')).toBeNull();
  });
});

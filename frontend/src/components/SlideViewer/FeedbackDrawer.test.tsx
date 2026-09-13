/**
 * FeedbackDrawer — unit tests for B1.3's behaviour change:
 *   open findings → all three action buttons visible
 *   fixed findings → action buttons suppressed, "Fixed" marker rendered
 *
 * Sabotage target: the `f.status === 'fixed'` branch in FeedbackDrawer.tsx.
 * Replace with `true &&` to see these tests go red.
 */
import { render, screen } from '@testing-library/react';
import { FeedbackDrawer } from './FeedbackDrawer';
import { ViewerProvider } from '../../contexts/ViewerContext';
import type { DrawerCallbacks, SlideFinding } from '../../types/finding';

const noop = () => undefined;

const callbacks: DrawerCallbacks = {
  onApplyFinding: noop,
  onDismissFinding: noop,
  onDiscussFinding: noop,
};

const openFinding: SlideFinding = {
  id: 'f-open',
  slideIndex: 0,
  category: 'content',
  criterion: 'test-criterion',
  message: 'An open finding',
  objective: true,
  status: 'open',
  seen: false,
};

const fixedFinding: SlideFinding = {
  id: 'f-fixed',
  slideIndex: 0,
  category: 'design',
  criterion: 'test-criterion-2',
  message: 'A fixed finding',
  objective: true,
  status: 'fixed',
  seen: false,
};

function renderDrawer(findings: SlideFinding[], hasUnseen = false) {
  return render(
    <ViewerProvider slideCount={1}>
      <FeedbackDrawer findings={findings} callbacks={callbacks} hasUnseen={hasUnseen} />
    </ViewerProvider>,
  );
}

describe('FeedbackDrawer — status gate', () => {
  it('open finding renders all three action buttons', () => {
    renderDrawer([openFinding]);

    expect(screen.getByTestId('finding-apply-f-open')).toBeInTheDocument();
    expect(screen.getByTestId('finding-dismiss-f-open')).toBeInTheDocument();
    expect(screen.getByTestId('finding-discuss-f-open')).toBeInTheDocument();
    expect(screen.queryByTestId('finding-status-f-open')).not.toBeInTheDocument();
  });

  it('fixed finding renders Fixed marker and no action buttons', () => {
    renderDrawer([fixedFinding]);

    expect(screen.queryByTestId('finding-apply-f-fixed')).not.toBeInTheDocument();
    expect(screen.queryByTestId('finding-dismiss-f-fixed')).not.toBeInTheDocument();
    expect(screen.queryByTestId('finding-discuss-f-fixed')).not.toBeInTheDocument();

    const marker = screen.getByTestId('finding-status-f-fixed');
    expect(marker).toBeInTheDocument();
    expect(marker).toHaveTextContent('Fixed');
  });

  it('mixed findings: fixed hides actions, open shows all three', () => {
    renderDrawer([fixedFinding, openFinding]);

    // Fixed finding
    expect(screen.queryByTestId('finding-apply-f-fixed')).not.toBeInTheDocument();
    expect(screen.queryByTestId('finding-dismiss-f-fixed')).not.toBeInTheDocument();
    expect(screen.queryByTestId('finding-discuss-f-fixed')).not.toBeInTheDocument();
    expect(screen.getByTestId('finding-status-f-fixed')).toHaveTextContent('Fixed');

    // Open finding
    expect(screen.getByTestId('finding-apply-f-open')).toBeInTheDocument();
    expect(screen.getByTestId('finding-dismiss-f-open')).toBeInTheDocument();
    expect(screen.getByTestId('finding-discuss-f-open')).toBeInTheDocument();
    expect(screen.queryByTestId('finding-status-f-open')).not.toBeInTheDocument();
  });
});

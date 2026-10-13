import { Joyride, type EventData, STATUS, ACTIONS, EVENTS } from 'react-joyride';
import { useTour } from '../../contexts/TourContext';
import { TOUR_STEPS } from './tourSteps';
import { endDemo } from './tourDemo';

export function AppTour() {
  const { isTourActive, endTour } = useTour();

  const handleEvent = (data: EventData) => {
    const { status, action, type } = data;

    const tourStopped =
      type === EVENTS.TOUR_END ||
      status === STATUS.FINISHED ||
      status === STATUS.SKIPPED ||
      action === ACTIONS.SKIP;

    if (tourStopped) {
      endTour();
      endDemo();
    }
  };

  if (!isTourActive) return null;

  return (
    <Joyride
      steps={TOUR_STEPS}
      run={isTourActive}
      continuous
      scrollToFirstStep
      onEvent={handleEvent}
      options={{
        primaryColor: '#2563eb',
        zIndex: 10000,
        overlayColor: 'rgba(0, 0, 0, 0.5)',
        backgroundColor: '#ffffff',
        textColor: '#1f2937',
        arrowColor: '#ffffff',
        showProgress: true,
        spotlightRadius: 8,
        buttons: ['skip', 'back', 'close', 'primary'],
        // Default is 'close' (advance one step); X should end the tour like Skip Tour.
        closeButtonAction: 'skip',
      }}
      locale={{
        back: 'Back',
        close: 'Close',
        last: 'Get Started',
        next: 'Next',
        skip: 'Skip Tour',
      }}
      styles={{
        tooltip: {
          borderRadius: '12px',
          padding: '24px',
          maxWidth: '420px',
          boxShadow: '0 25px 60px rgba(0, 0, 0, 0.15)',
        },
        tooltipTitle: {
          fontSize: '17px',
          fontWeight: 600,
          marginBottom: '10px',
        },
        tooltipContent: {
          fontSize: '14px',
          lineHeight: '1.7',
          whiteSpace: 'pre-line',
        },
        buttonPrimary: {
          borderRadius: '8px',
          padding: '8px 20px',
          fontSize: '13px',
          fontWeight: 500,
        },
        buttonBack: {
          borderRadius: '8px',
          padding: '8px 20px',
          fontSize: '13px',
          fontWeight: 500,
        },
        buttonSkip: {
          fontSize: '13px',
        },
      }}
    />
  );
}

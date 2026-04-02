import { Joyride, type EventData, type Step, STATUS, ACTIONS } from 'react-joyride';
import { useTour } from '../../contexts/TourContext';

function clickNav(tourId: string): () => Promise<void> {
  return async () => {
    const item = document.querySelector(`[data-tour="${tourId}"]`);
    const btn = item?.querySelector('button') ?? (item as HTMLElement | null);
    if (btn) (btn as HTMLElement).click();
    await new Promise(r => setTimeout(r, 400));
  };
}

function navigateToMain(): Promise<void> {
  return new Promise(resolve => {
    window.dispatchEvent(new Event('tour:navigate-main'));
    setTimeout(resolve, 400);
  });
}

function expandAgentConfig(): Promise<void> {
  return new Promise(resolve => {
    const toggle = document.querySelector<HTMLElement>('[data-tour="agent-config-toggle"]');
    const expanded = toggle?.closest('[data-testid="agent-config-bar"]')
      ?.querySelector('.border-t.border-gray-200');
    if (toggle && !expanded) toggle.click();
    setTimeout(resolve, 300);
  });
}

const TOUR_STEPS: Step[] = [
  // ── Big picture: Layout ──────────────────────────────────────────
  {
    target: '[data-tour="sidebar"]',
    title: 'The App at a Glance',
    content:
      'The app is split into two areas. On the left is the sidebar for navigation — creating decks, accessing your history, and configuring the AI. ' +
      'On the right is the main workspace where you chat with the AI and view your slides. Let\'s explore each part.',
    placement: 'right',
    skipBeacon: true,
  },

  // ── Sidebar: Navigation ──────────────────────────────────────────
  {
    target: '[data-tour="new-deck"]',
    title: 'Navigation',
    content:
      'These are your primary actions. "New Deck" starts a fresh session with a blank canvas and a new conversation. ' +
      '"View All Decks" takes you to a full list of every deck you\'ve created or been shared.',
    placement: 'right',
    skipBeacon: true,
  },
  {
    target: '[data-tour="deck-history"]',
    title: 'Recent Decks',
    content:
      'Your most recent decks are listed right here for quick access. Click any deck to jump back into it — your conversation history and slides are preserved exactly where you left off.',
    placement: 'right',
    skipBeacon: true,
  },

  // ── Sidebar: Configure section (overview) ────────────────────────
  {
    target: '[data-tour="configure-section"]',
    title: 'Configuration',
    content:
      'This section lets you fine-tune how the AI generates slides. Let\'s visit each page to see what\'s there.',
    placement: 'right',
    skipBeacon: true,
  },

  // ── Config pages: navigate to each one ───────────────────────────
  {
    target: '[data-tour="page-profiles"]',
    title: 'Agent Profiles',
    content:
      'Profiles are saved AI configurations — a combination of tools, style, and prompt. Create profiles for different use cases (e.g. "Sales Deck", "Technical Review") and switch between them instantly.',
    placement: 'center',
    skipBeacon: true,
    before: clickNav('nav-profiles'),
  },
  {
    target: '[data-tour="page-deck-prompts"]',
    title: 'Deck Prompts',
    content:
      'Deck prompts are reusable system instructions that tell the AI how to structure your deck. For example, a prompt might enforce a specific narrative arc or slide ordering convention.',
    placement: 'center',
    skipBeacon: true,
    before: clickNav('nav-deck_prompts'),
  },
  {
    target: '[data-tour="page-slide-styles"]',
    title: 'Slide Styles',
    content:
      'Slide styles control the visual design — colors, fonts, layout templates. Pick from existing styles or create your own to match your brand.',
    placement: 'center',
    skipBeacon: true,
    before: clickNav('nav-slide_styles'),
  },
  {
    target: '[data-tour="page-images"]',
    title: 'Image Library',
    content:
      'Upload and manage images that the AI can reference when building slides. Logos, diagrams, photos — anything you want available during generation.',
    placement: 'center',
    skipBeacon: true,
    before: clickNav('nav-images'),
  },
  {
    target: '[data-tour="page-help"]',
    title: 'Help & Documentation',
    content:
      'Detailed guides and documentation live here. If you ever need a refresher on how a feature works, this is the place to look.',
    placement: 'center',
    skipBeacon: true,
    before: clickNav('nav-help'),
  },

  // ── Main workspace: Overview (navigate back) ─────────────────────
  {
    target: '[data-tour="chat-panel"]',
    title: 'The AI Workspace',
    content:
      'This is where you create slides. The workspace has three parts: the agent config bar at the top, the chat panel where you talk to the AI, and the slide panel on the right where results appear. Let\'s break each one down.',
    placement: 'right',
    skipBeacon: true,
    before: async () => { await navigateToMain(); },
  },

  // ── Agent Config: click to open, then walk through ───────────────
  {
    target: '[data-tour="agent-config"]',
    title: 'Agent Config Bar',
    content:
      'This bar controls what tools the agent can use, how slides look, and what instructions guide the generation. Let\'s open it and explore each section.',
    placement: 'bottom',
    skipBeacon: true,
    before: expandAgentConfig,
  },
  {
    target: '[data-tour="agent-tools"]',
    title: 'Tools',
    content:
      'Tools give the AI extra capabilities beyond text generation. Add Genie spaces to query your data, vector search indexes to reference documents, MCP connections, or model endpoints. Each tool appears as a chip — click it to edit, or click the X to remove.',
    placement: 'bottom',
    skipBeacon: true,
  },
  {
    target: '[data-tour="agent-style-selector"]',
    title: 'Slide Style',
    content:
      'Choose a visual style for your slides. Styles define colors, fonts, and layout templates. Select one from the dropdown, or leave it as "None" to use the default styling.',
    placement: 'bottom',
    skipBeacon: true,
  },
  {
    target: '[data-tour="agent-prompt-selector"]',
    title: 'Deck Prompt',
    content:
      'Deck prompts are system-level instructions that shape how the AI structures your deck — for example, enforcing a narrative arc, a specific number of slides, or a particular content format.',
    placement: 'bottom',
    skipBeacon: true,
  },
  {
    target: '[data-tour="agent-profile-actions"]',
    title: 'Save & Load Profiles',
    content:
      'Once you\'ve configured the perfect combination of tools, style, and prompt, save it as a profile. Next time, just load the profile to instantly restore your setup.',
    placement: 'bottom',
    skipBeacon: true,
  },

  // ── Chat, Ribbon, Slides ─────────────────────────────────────────
  {
    target: '[data-tour="chat-panel"]',
    title: 'Chat Panel',
    content:
      'Type your request here — for example, "Create a 5-slide deck about Q3 results with a revenue chart." ' +
      'The AI generates a full deck in response. Continue the conversation to refine individual slides, add new ones, or change the style.',
    placement: 'right',
    skipBeacon: true,
  },
  {
    target: '[data-tour="selection-ribbon"]',
    title: 'Slide Thumbnails',
    content:
      'This ribbon shows miniature thumbnails of every slide in your deck. Click a thumbnail to scroll to that slide. You can also select multiple slides here to give the AI context when asking for targeted edits.',
    placement: 'left',
    skipBeacon: true,
  },
  {
    target: '[data-tour="slide-panel"]',
    title: 'Slide Panel',
    content:
      'Your generated slides render here in full detail. Click any slide to edit its HTML directly. Drag slides to reorder them. Use the slide toolbar to duplicate, delete, or move individual slides.',
    placement: 'left',
    skipBeacon: true,
  },

  // ── Page header: title & actions ─────────────────────────────────
  {
    target: '[data-tour="header-title"]',
    title: 'Deck Title & Save Points',
    content:
      'Click the title to rename your deck. The save point dropdown (when available) lets you browse previous versions of your deck and revert to any point in your editing history.',
    placement: 'bottom',
    skipBeacon: true,
  },
  {
    target: '[data-tour="header-actions"]',
    title: 'Export, Share & Present',
    content:
      'When your deck is ready:\n' +
      '• Export — download as PPTX, PDF, HTML, or export to Google Slides\n' +
      '• Copy Link — share a read-only view link with anyone\n' +
      '• Share — add collaborators from your workspace with viewer or editor permissions\n' +
      '• Present — enter full-screen presentation mode right from the browser',
    placement: 'bottom',
    skipBeacon: true,
  },

  // ── Feedback ─────────────────────────────────────────────────────
  {
    target: '[data-tour="feedback-button"]',
    title: 'Feedback',
    content:
      'Spotted a bug or have a feature request? Click here anytime to send feedback directly to the team.',
    placement: 'top',
    skipBeacon: true,
  },

  // ── Closing ──────────────────────────────────────────────────────
  {
    target: 'body',
    title: 'You\'re All Set!',
    content:
      'That\'s the full tour. Start by typing a message in the chat panel to generate your first deck. ' +
      'You can replay this tour anytime from the "App Tour" button at the bottom of the sidebar.',
    placement: 'center',
    skipBeacon: true,
  },
];

export function AppTour() {
  const { isTourActive, endTour } = useTour();

  const handleEvent = (data: EventData) => {
    const { status, action } = data;

    if (
      status === STATUS.FINISHED ||
      status === STATUS.SKIPPED ||
      action === ACTIONS.SKIP
    ) {
      endTour();
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

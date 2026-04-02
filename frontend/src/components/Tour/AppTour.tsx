import { Joyride, type EventData, type Step, STATUS, ACTIONS } from 'react-joyride';
import { useTour } from '../../contexts/TourContext';

const TOUR_STEPS: Step[] = [
  // ── Welcome ──────────────────────────────────────────────────────
  {
    target: 'body',
    title: 'Welcome to Tellr!',
    content:
      'Tellr is an AI-powered slide generator that turns your ideas into polished presentations through a simple chat interface. ' +
      'Describe what you need, and the AI builds your deck — complete with layout, content, and styling.\n\n' +
      'This quick tour will walk you through the main areas: navigation, the AI workspace, and how to export and share your work.',
    placement: 'center',
    skipBeacon: true,
  },

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

  // ── Sidebar: Configure section (overview then individual items) ──
  {
    target: '[data-tour="configure-section"]',
    title: 'Configuration',
    content:
      'This section lets you fine-tune how the AI generates slides. It contains five areas — let\'s look at each one.',
    placement: 'right',
    skipBeacon: true,
  },
  {
    target: '[data-tour="nav-profiles"]',
    title: 'Agent Profiles',
    content:
      'Profiles are saved AI configurations — a combination of tools, style, and prompt. Create profiles for different use cases (e.g. "Sales Deck", "Technical Review") and switch between them instantly.',
    placement: 'right',
    skipBeacon: true,
  },
  {
    target: '[data-tour="nav-deck_prompts"]',
    title: 'Deck Prompts',
    content:
      'Deck prompts are reusable system instructions that tell the AI how to structure your deck. For example, a prompt might enforce a specific narrative arc or slide ordering convention.',
    placement: 'right',
    skipBeacon: true,
  },
  {
    target: '[data-tour="nav-slide_styles"]',
    title: 'Slide Styles',
    content:
      'Slide styles control the visual design — colors, fonts, layout templates. Pick from existing styles or create your own to match your brand.',
    placement: 'right',
    skipBeacon: true,
  },
  {
    target: '[data-tour="nav-images"]',
    title: 'Image Library',
    content:
      'Upload and manage images that the AI can reference when building slides. Logos, diagrams, photos — anything you want available during generation.',
    placement: 'right',
    skipBeacon: true,
  },
  {
    target: '[data-tour="nav-help"]',
    title: 'Help & Documentation',
    content:
      'Detailed guides and documentation live here. If you ever need a refresher on how a feature works, this is the place to look.',
    placement: 'right',
    skipBeacon: true,
  },

  // ── Main workspace: Overview ─────────────────────────────────────
  {
    target: '[data-tour="chat-panel"]',
    title: 'The AI Workspace',
    content:
      'This is where you create slides. The workspace has three parts: the agent config bar at the top, the chat panel where you talk to the AI, and the slide panel on the right where results appear. Let\'s break each one down.',
    placement: 'right',
    skipBeacon: true,
  },

  // ── Main workspace: Granular components ──────────────────────────
  {
    target: '[data-tour="agent-config"]',
    title: 'Agent Config Bar',
    content:
      'Before you start chatting, configure the AI here. Add tools (like Genie for data queries or vector search for documents), select a slide style, and choose a deck prompt. You can also save this setup as a profile for reuse.',
    placement: 'bottom',
    skipBeacon: true,
  },
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

import { Joyride, type EventData, type Step, STATUS, ACTIONS } from 'react-joyride';
import { useTour } from '../../contexts/TourContext';
import { api } from '../../services/api';

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

let _demoSessionId: string | null = null;

async function loadDemoPrompt(): Promise<void> {
  try {
    const result = await api.createTourDemoDeck();
    _demoSessionId = result.session_id;
    window.dispatchEvent(
      new CustomEvent('tour:load-demo-deck', { detail: { sessionId: result.session_id } })
    );
    await new Promise(r => setTimeout(r, 1500));
  } catch (err) {
    console.error('Failed to create tour demo deck:', err);
    await navigateToMain();
  }
}

async function loadDemoSlides(): Promise<void> {
  if (!_demoSessionId) return;
  try {
    await api.addTourDemoSlides(_demoSessionId);
    await new Promise(r => setTimeout(r, 2000));
    window.dispatchEvent(
      new CustomEvent('tour:refresh-session', { detail: { sessionId: _demoSessionId } })
    );
    await new Promise(r => setTimeout(r, 1200));
  } catch (err) {
    console.error('Failed to load tour demo slides:', err);
  }
}

/** Clears module state, tells the shell to leave the demo session if needed, then deletes server-side (errors ignored). Sidebar refresh runs only after DELETE succeeds so the list does not still show the demo. */
function scheduleDeleteTourDemoSession(): void {
  const sid = _demoSessionId;
  _demoSessionId = null;
  if (!sid) return;
  window.dispatchEvent(new CustomEvent('tour:demo-session-deleted', { detail: { sessionId: sid } }));
  void api
    .deleteSession(sid)
    .then(() => {
      window.dispatchEvent(new Event('tour:sessions-list-refresh'));
    })
    .catch(() => {});
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
  // ── Main workspace: Overview (navigate back) ─────────────────────
  {
    target: '[data-tour="chat-panel"]',
    title: 'The AI Workspace',
    content:
      'This is where you create slides. The workspace has three parts: the agent config bar at the top, the chat panel where you talk to the AI, and the slide panel on the right where results appear. Let\'s break each one down.',
    placement: 'right',
    skipBeacon: true,
    before: navigateToMain,
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
      'Type your request here and the AI generates a full deck in response. Continue the conversation to refine individual slides, add new ones, or change the style.',
    placement: 'right',
    skipBeacon: true,
  },
  {
    target: '[data-tour="selection-ribbon"]',
    title: 'Slide Thumbnails',
    content:
      'This ribbon shows miniature thumbnails of every slide in your deck. Click a thumbnail to scroll to that slide.',
    placement: 'left',
    skipBeacon: true,
  },
  {
    target: '[data-tour="slide-panel"]',
    title: 'Slide Panel',
    content:
      'Your generated slides render here in full detail. Click any slide to edit its HTML directly. Drag slides to reorder them.',
    placement: 'left',
    skipBeacon: true,
  },

  // ── Page header ──────────────────────────────────────────────────
  {
    target: '[data-tour="header-title"]',
    title: 'Deck Title & Save Points',
    content:
      'Click the title to rename your deck. The save point dropdown lets you browse previous versions and revert to any point in your editing history.',
    placement: 'bottom',
    skipBeacon: true,
  },

  // ── Demo: intro (appears instantly) ─────────────────────────────
  {
    target: '[data-tour="chat-panel"]',
    title: "Let's Try It!",
    content:
      "Let's see how easy it is to create slides. We'll send an example prompt and watch the AI build a deck for you.",
    placement: 'right',
    skipBeacon: true,
  },

  // ── Demo: Phase 1 — prompt appears in chat ─────────────────────
  {
    target: '[data-tour="chat-panel"]',
    title: 'Prompt Sent',
    content:
      'We sent: "Create 3 slides about the benefits of AI in modern healthcare, with a title slide, key advantages, and future outlook."\n\n' +
      "The AI is generating your slides...",
    placement: 'right',
    skipBeacon: true,
    before: loadDemoPrompt,
  },

  // ── Demo: Phase 2 — slides + response appear ──────────────────
  {
    target: '[data-tour="slide-panel"]',
    title: 'Slides Generated!',
    content:
      'The AI created 3 fully styled slides in seconds! A title slide, key advantages, and future outlook. ' +
      "This is exactly what happens every time you send a prompt.",
    placement: 'left',
    skipBeacon: true,
    before: loadDemoSlides,
  },
  // ── Post-demo: walkthrough of generated content ────────────────
  {
    target: '[data-tour="selection-ribbon"]',
    title: 'Browse Your Slides',
    content:
      'Each slide appears as a thumbnail here. Click any thumbnail to jump to that slide. ' +
      'Select multiple slides to give the AI context when asking for targeted edits.',
    placement: 'left',
    skipBeacon: true,
  },
  {
    target: '[data-tour="slide-panel"]',
    title: 'Edit Any Slide',
    content:
      'Click directly on any slide to edit its HTML. You can change text, restyle elements, or completely rewrite a slide. ' +
      'You can also ask the AI in the chat to refine specific slides.',
    placement: 'left',
    skipBeacon: true,
  },
  {
    target: '[data-tour="header-actions"]',
    title: 'Export & Share',
    content:
      'When your deck is ready:\n' +
      '• Export — download as PPTX, PDF, HTML, or Google Slides\n' +
      '• Copy Link — share a read-only view link\n' +
      '• Share — add collaborators with viewer or editor permissions\n' +
      '• Present — full-screen presentation mode right from the browser',
    placement: 'bottom',
    skipBeacon: true,
  },

  // ── Feedback then Help ────────────────────────────────────────
  {
    target: '[data-tour="feedback-button"]',
    title: 'Feedback',
    content:
      'Spotted a bug or have a feature request? Click here anytime to send feedback directly to the team.',
    placement: 'top',
    skipBeacon: true,
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

  // ── Closing (stays on Help page) ──────────────────────────────
  {
    target: '[data-tour="page-help"]',
    title: "You're All Set!",
    content:
      "That's the full tour! The example deck used for this walkthrough is removed automatically when you finish.\n\n" +
      'To create your own deck, click "+New Deck" and type a prompt in the chat.\n\n' +
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
      scheduleDeleteTourDemoSession();
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

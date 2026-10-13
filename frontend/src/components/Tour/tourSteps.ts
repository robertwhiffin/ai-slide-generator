import type { Step } from 'react-joyride';
import { startDemo, runStage, showView, focusViewer } from './tourDemo';

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

export const DEMO_DECK_SLIDE_COUNT = 3;

export const TOUR_STEPS: Step[] = [
  {
    target: '[data-tour="sidebar"]',
    title: 'The App at a Glance',
    placement: 'right',
    content: 'The sidebar on the left is for navigation: new decks, your deck history and configuration. The workspace on the right is where you chat with the AI and see your slides. Let\'s walk through both.',
    skipBeacon: true,
  },
  {
    target: '[data-tour="new-deck"]',
    title: 'Navigation',
    placement: 'right',
    content: '"New Deck" starts a fresh deck with a new conversation. "View All Decks" lists every deck you have created or that has been shared with you.',
    skipBeacon: true,
  },
  {
    target: '[data-tour="deck-history"]',
    title: 'Recent Decks',
    placement: 'right',
    content: 'Your recent decks are listed here. Click one to pick up where you left off, with its conversation and slides intact.',
    skipBeacon: true,
  },
  {
    target: '[data-tour="configure-section"]',
    title: 'Configuration',
    placement: 'right',
    content: 'These pages control what the AI works with and how your decks look. Let\'s visit each one.',
    skipBeacon: true,
  },
  {
    target: '[data-tour="page-profiles"]',
    title: 'Agent Profiles',
    placement: 'center',
    content: 'A profile saves a combination of tools, design system or slide style, and deck prompt, so you can switch set-ups in one click, for example "Sales Deck" or "Technical Review".',
    skipBeacon: true,
    before: clickNav('nav-profiles'),
  },
  {
    target: '[data-tour="page-deck-prompts"]',
    title: 'Deck Prompts',
    placement: 'center',
    content: 'Deck prompts are reusable instructions for how a deck should be structured, such as a required narrative or a standard section order.',
    skipBeacon: true,
    before: clickNav('nav-deck_prompts'),
  },
  {
    target: '[data-tour="page-design-systems"]',
    title: 'Design Systems',
    placement: 'center',
    content: 'A design system packages your brand: colours, fonts, logos and slide templates. Decks built with one come out on-brand. When a deck uses a design system, it takes the place of any slide style.',
    skipBeacon: true,
    before: clickNav('nav-design_systems'),
  },
  {
    target: '[data-tour="page-slide-styles"]',
    title: 'Slide Styles',
    placement: 'center',
    content: 'Slide styles are lighter-weight visual themes. A slide style is used only when no design system is selected.',
    skipBeacon: true,
    before: clickNav('nav-slide_styles'),
  },
  {
    target: '[data-tour="page-images"]',
    title: 'Image Library',
    placement: 'center',
    content: 'Upload logos, diagrams and photos here so the AI can place them on your slides.',
    skipBeacon: true,
    before: clickNav('nav-images'),
  },
  {
    target: '[data-tour="page-settings"]',
    title: 'Settings',
    placement: 'center',
    content: 'Connect or disconnect your Google account here for Google Slides export. Admins upload the app-wide OAuth client credentials on the Admin page.',
    skipBeacon: true,
    before: clickNav('nav-settings'),
  },
  {
    target: '[data-tour="chat-panel"]',
    title: 'The AI Workspace',
    placement: 'right',
    content: 'You chat here and your deck appears on the right. Behind the chat is a team of AI agents: one plans the deck, others build the slides in parallel, and reviewers check each slide and the deck as a whole.',
    skipBeacon: true,
    before: navigateToMain,
  },
  {
    target: '[data-tour="agent-config"]',
    title: 'Agent Config Bar',
    placement: 'bottom',
    content: 'This bar sets what the agents can use for this deck: tools, look and instructions. Your choices stay in place for every message in this deck until you change them.',
    skipBeacon: true,
    before: expandAgentConfig,
  },
  {
    target: '[data-tour="agent-tools"]',
    title: 'Tools',
    placement: 'bottom',
    content: 'Tools give the agents access to your data and documents: Genie agents, vector search indexes, MCP servers and model endpoints. Each tool appears as a chip. Click it to edit, or click the X to remove it.',
    skipBeacon: true,
  },
  {
    target: '[data-tour="agent-design-system-selector"]',
    title: 'Design System',
    placement: 'bottom',
    content: 'Pick a design system for this deck. If it has templates, a Template picker appears next to it.',
    skipBeacon: true,
  },
  {
    target: '[data-tour="agent-style-selector"]',
    title: 'Slide Style',
    placement: 'bottom',
    content: 'Pick a slide style if you are not using a design system. Leave it as "None" for the default look.',
    skipBeacon: true,
  },
  {
    target: '[data-tour="agent-prompt-selector"]',
    title: 'Deck Prompt',
    placement: 'bottom',
    content: 'Choose a deck prompt to shape the deck\'s structure, for example a fixed narrative or a set number of slides.',
    skipBeacon: true,
  },
  {
    target: '[data-tour="agent-profile-actions"]',
    title: 'Save & Load Profiles',
    placement: 'bottom',
    content: 'Save this combination as a profile, or load one to restore a set-up instantly.',
    skipBeacon: true,
  },
  {
    target: '[data-tour="chat-panel"]',
    title: 'Let\'s Try It',
    placement: 'right',
    content: 'Let\'s watch the agents build a deck. We\'ll send an example request for you.',
    skipBeacon: true,
  },
  {
    target: '[data-tour="chat-panel"]',
    title: 'Your Request',
    placement: 'right',
    content: 'We asked for "3 slides about the benefits of AI in modern healthcare, with a title slide, key advantages, and future outlook." Plain language is all you need.',
    skipBeacon: true,
    before: startDemo,
  },
  {
    target: '[data-tour="chat-panel"]',
    title: 'The Architect Plans',
    placement: 'right',
    content: 'The architect agent replies first with its plan: who the deck is for, the argument it will make, and what each slide must do. If your request is unclear, it asks you a question instead of guessing.',
    skipBeacon: true,
    before: () => runStage('plan'),
  },
  {
    target: '[data-tour="slide-viewer"]',
    title: 'Slides Arrive One by One',
    placement: 'left',
    content: 'Builder agents now write the slides in parallel, and each one appears here as soon as it is ready. The chat shows "Building 3 slide(s)." and then a review line for each slide.',
    skipBeacon: true,
    before: () => runStage('build'),
  },
  {
    target: '[data-tour="chat-panel"]',
    title: 'Every Slide Is Reviewed',
    placement: 'right',
    content: 'A reviewer checks every slide as it lands. "clean" means nothing to report. Mechanical problems such as overflowing text are fixed automatically. "surfaced" means the reviewer found something that needs your judgement.',
    skipBeacon: true,
  },
  {
    target: '[data-testid="thumbnail-ribbon"]',
    title: 'Browse Your Slides',
    placement: 'left',
    content: 'Click a thumbnail to jump to that slide, or drag it to reorder the deck. A dot on a thumbnail means that slide has review feedback you haven\'t read yet.',
    skipBeacon: true,
  },
  {
    target: '[data-testid="feedback-drawer"]',
    title: 'Review Feedback',
    placement: 'top',
    content: 'The feedback drawer lists the reviewer\'s findings for the current slide. Apply asks the agents to make the change, Dismiss hides the finding, and Discuss moves it into the chat so you can talk it through first.',
    skipBeacon: true,
    before: () => focusViewer({ index: 2, drawerOpen: true, tab: 'feedback' }),
  },
  {
    target: '[data-testid="stage-verification-badge"]',
    title: 'Data Check',
    placement: 'bottom',
    content: 'This badge checks the slide\'s facts against the data your tools returned, shown as green, amber or red. This demo deck uses no data tools, so there is nothing to check yet.',
    skipBeacon: true,
  },
  {
    target: '[data-tour="chat-panel"]',
    title: 'Whole-Deck Review',
    placement: 'right',
    content: 'When every slide is in, a deck reviewer reads the deck as a whole for gaps in the argument, repeated points and a missing conclusion. Its verdict appears in the chat.',
    skipBeacon: true,
    before: () => runStage('review'),
  },
  {
    target: '[data-testid="spec-view"]',
    title: 'The Deck Spec',
    placement: 'left',
    content: 'The Spec shows the plan the agents work from: audience, purpose, argument, narrative arc and a brief for every slide. To change it, ask in the chat, for example "make this for a board audience". The agents then update the spec and the slides it affects.',
    skipBeacon: true,
    before: () => showView('spec'),
  },
  {
    target: '[data-tour="slide-viewer"]',
    title: 'Edit by Asking',
    placement: 'left',
    content: 'To change a slide, just ask. We sent "Make slide 2 more concise". The architect works out which slide you mean, and only that slide is rebuilt and re-reviewed. The rest of the deck is untouched.',
    skipBeacon: true,
    before: async () => { await showView('slides'); await runStage('edit'); await focusViewer({ index: 1, drawerOpen: false }); },
  },
  {
    target: '[data-tour="slide-viewer"]',
    title: 'Hands-On Changes',
    placement: 'left',
    content: 'For direct changes, the toolbar above the slide lets you edit its HTML, delete it, or use Optimize layout to tidy spacing and text flow without changing the content.',
    skipBeacon: true,
  },
  {
    target: '[data-testid="graph-version-status"]',
    title: 'Pinned Agent Version',
    placement: 'bottom',
    content: 'Each deck stays on the version of the AI agents it started with, so updates an admin publishes never change a deck halfway through. This demo deck shows its version here. If a newer version exists, "Start latest" opens a new deck on it, and this deck is left as it is.',
    skipBeacon: true,
  },
  {
    target: '[data-tour="header-title"]',
    title: 'Deck Title & Save Points',
    placement: 'bottom',
    content: 'Click the title to rename your deck. The save point menu lets you browse earlier versions and revert to any of them.',
    skipBeacon: true,
  },
  {
    target: '[data-tour="header-actions"]',
    title: 'Export & Share',
    placement: 'bottom',
    content: 'When your deck is ready:\n• Export: PPTX, PDF, HTML or Google Slides\n• Copy Link: a read-only view link\n• Share: add viewers or editors\n• Present: full-screen in the browser',
    skipBeacon: true,
  },
  {
    target: '[data-tour="feedback-button"]',
    title: 'Feedback',
    placement: 'top',
    content: 'Spotted a bug or have an idea? Send it to the team from here at any time.',
    skipBeacon: true,
  },
  {
    target: '[data-tour="page-help"]',
    title: 'Help & Documentation',
    placement: 'center',
    content: 'Guides for every feature live here.',
    skipBeacon: true,
    before: clickNav('nav-help'),
  },
  {
    target: '[data-tour="page-help"]',
    title: 'You\'re All Set',
    placement: 'center',
    content: 'That\'s the tour. The example deck is removed when you finish.\n\nTo make your own, click "New Deck" and describe what you want in the chat.\n\nYou can replay this tour any time from "App Tour" at the bottom of the sidebar.',
    skipBeacon: true,
  },
];

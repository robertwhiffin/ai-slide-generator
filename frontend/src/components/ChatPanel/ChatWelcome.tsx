import React from 'react';

/**
 * Shown in an empty conversation, before the first message on a deck.
 *
 * Returning users skip the app tour, so this is where everyone learns how deck
 * generation works today. Describe current behaviour only, so the copy stays
 * true for new users too.
 */

const STEPS: { title: string; body: string }[] = [
  {
    title: 'Start with an idea, not a brief.',
    body:
      "You don't need a finished outline. Tell Tellr what you're thinking and it will interview you: " +
      'who it’s for, what you want them to take away, what evidence you have. It helps you sharpen ' +
      'the argument before a single slide is built. Already know what you want? Describe it and say “build it”.',
  },
  {
    title: 'An architect plans it.',
    body:
      "It replies with the deck's argument and a brief for every slide. If something's unclear, it asks you first.",
  },
  {
    title: 'Slides are built in parallel',
    body: 'and appear one by one as they finish.',
  },
  {
    title: 'Every slide is reviewed.',
    body:
      'Layout problems are fixed automatically. Anything that needs your judgement gets a dot on its ' +
      'thumbnail, with details in the feedback drawer.',
  },
  {
    title: 'The whole deck is reviewed',
    body: 'for gaps, repetition and a missing conclusion.',
  },
];

const TIPS: { lead: string; example?: string; rest?: string }[] = [
  {
    lead: 'Think it through first:',
    example:
      'I need to pitch our Q3 results to the board. Help me work out the story before you build anything.',
  },
  { lead: 'Change a slide by number:', example: 'Make slide 3 more concise.' },
  {
    lead: 'Change the whole deck:',
    example: 'Rewrite this for a board audience.',
    rest: 'The plan and the affected slides update together.',
  },
  {
    lead: 'Use your data:',
    rest: 'add a Genie space or other tool in the agent config bar above, then ask for the numbers.',
  },
  { lead: 'Open Spec', rest: 'at any time to see the plan the agents are working from.' },
];

export const ChatWelcome: React.FC = () => (
  <div data-testid="chat-welcome" className="text-[13px] leading-relaxed text-muted-foreground">
    <h3 className="mb-2 text-sm font-semibold text-foreground">How Tellr builds your deck</h3>
    <ol className="mb-5 list-decimal space-y-1.5 pl-5">
      {STEPS.map(step => (
        <li key={step.title}>
          <span className="font-medium text-foreground">{step.title}</span> {step.body}
        </li>
      ))}
    </ol>

    <h3 className="mb-2 text-sm font-semibold text-foreground">Using the chat</h3>
    <ul className="list-disc space-y-1.5 pl-5">
      {TIPS.map(tip => (
        <li key={tip.lead}>
          <span className="font-medium text-foreground">{tip.lead}</span>
          {tip.example && <> <em>&ldquo;{tip.example}&rdquo;</em></>}
          {tip.rest && <> {tip.rest}</>}
        </li>
      ))}
    </ul>
  </div>
);

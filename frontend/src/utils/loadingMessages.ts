/**
 * Amusing loading messages to entertain users while the agent works.
 * These messages rotate every few seconds to keep the wait engaging.
 */

export const LOADING_MESSAGES = [
  "🧠 Teaching the AI about comedy timing...",
  "📊 Convincing data to tell its story...",
  "🎨 Making slides less boring than usual...",
  "🔮 Consulting the data oracle...",
  "🎭 Rehearsing the presentation...",
  "📈 Turning numbers into narratives...",
  "☕ Waiting for the AI to finish its coffee...",
  "🎪 Juggling your data points...",
  "🎯 Aiming for chart perfection...",
  "🚀 Launching queries into the data stratosphere...",
  "🎼 Composing a data symphony...",
  "🔍 Finding insights hiding in plain sight...",
  "🧙 Casting data visualization spells...",
  "🎨 Choosing the perfect shade of corporate blue...",
  "📚 Reading 'Slide Design for Dummies'...",
  "🎲 Rolling for critical insights...",
  "🌟 Sprinkling some data magic...",
  "🎭 Method acting as a bar chart...",
  "🔬 Conducting very serious data science...",
  "🎨 Arguing with Comic Sans about life choices...",
];

/**
 * Get a random loading message
 */
export const getRandomLoadingMessage = (): string => {
  return LOADING_MESSAGES[Math.floor(Math.random() * LOADING_MESSAGES.length)];
};

/**
 * Get a loading message by rotating through the list
 */
export const getRotatingLoadingMessage = (index: number): string => {
  return LOADING_MESSAGES[index % LOADING_MESSAGES.length];
};


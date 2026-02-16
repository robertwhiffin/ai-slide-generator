import React, { useState } from 'react';
import { FiMessageSquare, FiClock, FiSettings, FiInfo, FiShield, FiFileText, FiLayout, FiExternalLink } from 'react-icons/fi';
import { FaGavel } from 'react-icons/fa';

type HelpTab = 'overview' | 'generator' | 'history' | 'profiles' | 'deck_prompts' | 'slide_styles' | 'verification';

export const HelpPage: React.FC = () => {
  const [activeTab, setActiveTab] = useState<HelpTab>('overview');

  const TabButton = ({ tab, label, icon: Icon }: { tab: HelpTab; label: string; icon: React.ElementType }) => (
    <button
      onClick={() => setActiveTab(tab)}
      className={`px-4 py-2 rounded-full text-sm font-medium transition-colors flex items-center gap-2 ${
        activeTab === tab
          ? 'bg-blue-600 text-white'
          : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
      }`}
    >
      <Icon size={16} />
      {label}
    </button>
  );

  const QuickLinkButton = ({ tab, label }: { tab: HelpTab; label: string }) => (
    <button
      onClick={() => setActiveTab(tab)}
      className="px-3 py-1.5 rounded-full text-xs font-medium bg-blue-100 text-blue-700 hover:bg-blue-200 transition-colors"
    >
      {label}
    </button>
  );

  return (
    <div className="max-w-4xl mx-auto">
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-800">How to Use databricks tellr</h1>
      </div>

      {/* Tab bar */}
      <div className="flex gap-2 mb-6 flex-wrap">
        <TabButton tab="overview" label="Overview" icon={FiInfo} />
        <TabButton tab="generator" label="Generator" icon={FiMessageSquare} />
        <TabButton tab="verification" label="Verification" icon={FiShield} />
        <TabButton tab="history" label="My Sessions" icon={FiClock} />
        <TabButton tab="profiles" label="Profiles" icon={FiSettings} />
        <TabButton tab="deck_prompts" label="Deck Prompts" icon={FiFileText} />
        <TabButton tab="slide_styles" label="Slide Styles" icon={FiLayout} />
      </div>

      {/* Content area */}
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 min-h-[400px]">
        {activeTab === 'overview' && <OverviewTab setActiveTab={setActiveTab} QuickLinkButton={QuickLinkButton} />}
        {activeTab === 'generator' && <GeneratorTab />}
        {activeTab === 'verification' && <VerificationTab />}
        {activeTab === 'history' && <HistoryTab />}
        {activeTab === 'profiles' && <ProfilesTab />}
        {activeTab === 'deck_prompts' && <DeckPromptsTab />}
        {activeTab === 'slide_styles' && <SlideStylesTab />}
      </div>
    </div>
  );
};

// Overview Tab Content
const OverviewTab: React.FC<{
  setActiveTab: (tab: HelpTab) => void;
  QuickLinkButton: React.FC<{ tab: HelpTab; label: string }>;
}> = ({ QuickLinkButton }) => (
  <div className="space-y-6">
    <section>
      <h2 className="text-lg font-semibold text-gray-800 mb-3">What is databricks tellr?</h2>
      <ul className="list-disc list-inside text-gray-600 space-y-2">
        <li>Creates presentation slides from natural language using AI</li>
        <li>Pulls data from Databricks Genie spaces for data-driven presentations</li>
        <li>Supports iterative editing through conversational interface</li>
      </ul>
    </section>

    <section>
      <h2 className="text-lg font-semibold text-gray-800 mb-3">Quick Start</h2>
      <div className="bg-blue-50 rounded-lg p-4">
        <ol className="list-decimal list-inside text-gray-700 space-y-3">
          <li>
            <span className="font-medium">Select a profile</span> (top-right) to configure your data source and AI settings
          </li>
          <li>
            <span className="font-medium">Type what slides you want</span> in the chat panel on the left
          </li>
          <li>
            <span className="font-medium">Review and refine</span> the generated slides using selection and editing
          </li>
        </ol>
      </div>
    </section>

    <section>
      <h2 className="text-lg font-semibold text-gray-800 mb-3">Navigation Quick Links</h2>
      <div className="flex gap-2 flex-wrap">
        <QuickLinkButton tab="generator" label="Learn about Generator →" />
        <QuickLinkButton tab="verification" label="Learn about Verification →" />
        <QuickLinkButton tab="history" label="Learn about History →" />
        <QuickLinkButton tab="profiles" label="Learn about Profiles →" />
        <QuickLinkButton tab="deck_prompts" label="Learn about Deck Prompts →" />
        <QuickLinkButton tab="slide_styles" label="Learn about Slide Styles →" />
      </div>
    </section>

    <section>
      <h2 className="text-lg font-semibold text-gray-800 mb-3">Full Documentation</h2>
      <p className="text-gray-600 mb-3">
        For detailed guides, API reference, and technical documentation:
      </p>
      <a
        href="https://robertwhiffin.github.io/ai-slide-generator/"
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
      >
        <FiExternalLink size={16} />
        View Full Documentation
      </a>
    </section>
  </div>
);

// Generator Tab Content
const GeneratorTab: React.FC = () => (
  <div className="space-y-6">
    <section>
      <h2 className="text-lg font-semibold text-gray-800 mb-3">Chat Panel (Left)</h2>
      <ul className="list-disc list-inside text-gray-600 space-y-2">
        <li>Type requests to generate or edit slides</li>
        <li>Shows AI responses and Genie data queries</li>
        <li>Selection badge appears when slides are selected for editing</li>
      </ul>
    </section>

    <section>
      <h2 className="text-lg font-semibold text-gray-800 mb-3">Selection Ribbon (Middle)</h2>
      <ul className="list-disc list-inside text-gray-600 space-y-2">
        <li>Click slides to select for editing</li>
        <li><kbd className="px-1.5 py-0.5 bg-gray-100 rounded text-xs font-mono">Shift</kbd> + click for range selection</li>
        <li><kbd className="px-1.5 py-0.5 bg-gray-100 rounded text-xs font-mono">Ctrl</kbd>/<kbd className="px-1.5 py-0.5 bg-gray-100 rounded text-xs font-mono">Cmd</kbd> + click for multi-select</li>
        <li>Clear selection with × button or <kbd className="px-1.5 py-0.5 bg-gray-100 rounded text-xs font-mono">Escape</kbd> key</li>
      </ul>
    </section>

    <section>
      <h2 className="text-lg font-semibold text-gray-800 mb-3">Slide Panel (Right)</h2>
      <ul className="list-disc list-inside text-gray-600 space-y-2">
        <li><span className="font-medium">Parsed Slides:</span> drag to reorder, edit/duplicate/delete actions</li>
        <li><span className="font-medium">Raw HTML tabs:</span> debug views for troubleshooting</li>
      </ul>
    </section>

    <section>
      <h2 className="text-lg font-semibold text-gray-800 mb-3">Editing Workflow</h2>
      <div className="bg-amber-50 rounded-lg p-4">
        <ol className="list-decimal list-inside text-gray-700 space-y-2">
          <li>Select slides in the ribbon that you want to modify</li>
          <li>Describe your changes in the chat panel</li>
          <li>AI updates only the selected slides, leaving others unchanged</li>
        </ol>
      </div>
    </section>
  </div>
);

// History Tab Content
const HistoryTab: React.FC = () => (
  <div className="space-y-6">
    <section>
      <h2 className="text-lg font-semibold text-gray-800 mb-3">Session List</h2>
      <p className="text-gray-600">
        View all saved sessions with their name, creation date, and slide count status.
      </p>
    </section>

    <section>
      <h2 className="text-lg font-semibold text-gray-800 mb-3">Actions</h2>
      <ul className="list-disc list-inside text-gray-600 space-y-2">
        <li><span className="font-medium">Restore:</span> Load a previous session and continue working</li>
        <li><span className="font-medium">Rename:</span> Change the session name for better organization</li>
        <li><span className="font-medium">Delete:</span> Permanently remove a session</li>
      </ul>
    </section>

    <section>
      <h2 className="text-lg font-semibold text-gray-800 mb-3">Tips</h2>
      <div className="bg-green-50 rounded-lg p-4">
        <ul className="list-disc list-inside text-gray-700 space-y-2">
          <li>Use "Save As" in the header to give sessions descriptive names</li>
          <li>Current session is highlighted with a badge in the list</li>
          <li>Sessions are automatically saved each time you send a message</li>
        </ul>
      </div>
    </section>
  </div>
);

// Verification Tab Content
const VerificationTab: React.FC = () => (
  <div className="space-y-6">
    <section>
      <h2 className="text-lg font-semibold text-gray-800 mb-3">What is Slide Verification?</h2>
      <p className="text-gray-600 mb-3">
        Verification uses an <strong>LLM as Judge</strong> to check that the numbers and data shown 
        on your slides accurately represent the source data from Genie. This helps ensure your 
        presentation doesn't contain AI hallucinations or calculation errors.
      </p>
      <div className="flex items-center gap-2 text-green-700 bg-green-50 rounded-lg p-3">
        <FaGavel size={20} />
        <span className="text-sm"><strong>Auto-verification:</strong> Slides are automatically verified when generated. You'll see the status appear on each slide.</span>
      </div>
    </section>

    <section>
      <h2 className="text-lg font-semibold text-gray-800 mb-3">How It Works</h2>
      <ol className="list-decimal list-inside text-gray-600 space-y-2">
        <li><strong>Auto-verification</strong> runs automatically when slides are generated or added</li>
        <li>The verifier compares <strong>Genie query results</strong> (source data) against <strong>slide content</strong></li>
        <li>It performs <strong>semantic comparison</strong> — "7M" and "7,000,000" are considered equivalent</li>
        <li>Derived calculations (like "50% growth") are validated against source numbers</li>
        <li>Chart data (Chart.js) is also verified against the source</li>
      </ol>
    </section>

    <section>
      <h2 className="text-lg font-semibold text-gray-800 mb-3">Verification Badge</h2>
      <div className="bg-amber-50 rounded-lg p-4 mb-3">
        <ul className="list-disc list-inside text-gray-700 space-y-2">
          <li>Each slide shows a <strong>verification badge</strong> with its score and rating</li>
          <li>Click the badge to see detailed explanation and any issues found</li>
          <li>If you <strong>edit a slide</strong>, verification automatically re-runs for that slide</li>
          <li>If you <strong>add a new slide</strong>, only the new slide is verified (existing slides keep their results)</li>
        </ul>
      </div>
    </section>

    <section>
      <h2 className="text-lg font-semibold text-gray-800 mb-3">Viewing Genie Source Data</h2>
      <div className="bg-purple-50 rounded-lg p-4">
        <p className="text-gray-700 mb-2">
          You can view the original Genie queries and data that were used to generate your slides:
        </p>
        <ul className="list-disc list-inside text-gray-700 space-y-2">
          <li><strong>Database icon</strong> on each slide tile — opens the Genie conversation in a new tab</li>
          <li><strong>"View Source Data in Genie" link</strong> — available in the verification details popup</li>
        </ul>
        <p className="text-sm text-gray-500 mt-2">
          This shows all queries made during your session, helping you understand where the data came from.
        </p>
      </div>
    </section>

    <section>
      <h2 className="text-lg font-semibold text-gray-800 mb-3">Verification Ratings</h2>
      <p className="text-sm text-gray-600 mb-3">
        Each slide is automatically verified against the source data. The verification uses a simple RAG (Red/Amber/Green) indicator:
      </p>
      <div className="space-y-2">
        <div className="flex items-center gap-3 p-2 bg-green-50 rounded-lg border border-green-200">
          <span className="px-2 py-1 text-xs font-medium rounded bg-green-100 text-green-800 border border-green-300 flex items-center gap-1">
            <span className="text-green-600">●</span> No issues
          </span>
          <span className="text-sm text-gray-700">All data correctly represents the source — no action needed</span>
        </div>
        <div className="flex items-center gap-3 p-2 bg-amber-50 rounded-lg border border-amber-200">
          <span className="px-2 py-1 text-xs font-medium rounded bg-amber-100 text-amber-800 border border-amber-300 flex items-center gap-1">
            <span className="text-amber-600">●</span> Review suggested
          </span>
          <span className="text-sm text-gray-700">Some concerns detected — a quick review is recommended</span>
        </div>
        <div className="flex items-center gap-3 p-2 bg-red-50 rounded-lg border border-red-200">
          <span className="px-2 py-1 text-xs font-medium rounded bg-red-100 text-red-800 border border-red-300 flex items-center gap-1">
            <span className="text-red-600">●</span> Review required
          </span>
          <span className="text-sm text-gray-700">Significant issues found — review before using this slide</span>
        </div>
        <div className="flex items-center gap-3 p-2 bg-gray-50 rounded-lg border border-gray-200">
          <span className="px-2 py-1 text-xs font-medium rounded bg-gray-100 text-gray-600 border border-gray-300 flex items-center gap-1">
            <span className="text-gray-500">○</span> Unable to verify
          </span>
          <span className="text-sm text-gray-700">No source data available (e.g., title slides with no numbers)</span>
        </div>
      </div>
    </section>

    <section>
      <h2 className="text-lg font-semibold text-gray-800 mb-3">What Passes / Fails</h2>
      <div className="grid md:grid-cols-2 gap-4">
        <div className="bg-green-50 rounded-lg p-3">
          <h4 className="font-medium text-green-800 mb-2">✓ These Pass</h4>
          <ul className="text-sm text-green-700 space-y-1">
            <li>• 7,234,567 shown as "7.2M" or "$7.2M"</li>
            <li>• 0.15 shown as "15%"</li>
            <li>• Reasonable rounding</li>
            <li>• "50% growth" if Q1=100, Q2=150</li>
          </ul>
        </div>
        <div className="bg-red-50 rounded-lg p-3">
          <h4 className="font-medium text-red-800 mb-2">✗ These Fail</h4>
          <ul className="text-sm text-red-700 space-y-1">
            <li>• Source says 7M, slide shows 9M</li>
            <li>• Swapped values (Q1 and Q2 reversed)</li>
            <li>• Hallucinated numbers not in source</li>
            <li>• Wrong calculations</li>
          </ul>
        </div>
      </div>
    </section>

    <section>
      <h2 className="text-lg font-semibold text-gray-800 mb-3">Cost & Usage</h2>
      <div className="bg-blue-50 rounded-lg p-4">
        <ul className="list-disc list-inside text-gray-700 space-y-2">
          <li>Verification runs <strong>automatically</strong> when slides are generated or edited</li>
          <li>Each verification makes one LLM call (using Claude via Databricks)</li>
          <li>Typical cost: ~$0.01-0.03 per slide verification</li>
          <li>Verification is efficient — only new or edited slides are verified</li>
        </ul>
      </div>
    </section>

    <section>
      <h2 className="text-lg font-semibold text-gray-800 mb-3">Feedback</h2>
      <p className="text-gray-600">
        After verification, you can provide feedback using 👍/👎 buttons in the verification popup. 
        Negative feedback asks for details to help improve accuracy. All feedback is logged to 
        MLflow for quality monitoring and model improvement.
      </p>
    </section>
  </div>
);

// Profiles Tab Content
const ProfilesTab: React.FC = () => (
  <div className="space-y-6">
    <section>
      <h2 className="text-lg font-semibold text-gray-800 mb-3">What are Profiles?</h2>
      <p className="text-gray-600">
        Profiles store your configuration for LLM settings, Genie space connections, and custom prompts.
      </p>
    </section>

    <section>
      <h2 className="text-lg font-semibold text-gray-800 mb-3">Profile Configuration Tabs</h2>
      <ul className="list-disc list-inside text-gray-600 space-y-2">
        <li><span className="font-medium">AI Infrastructure:</span> LLM endpoint, temperature, and token limits</li>
        <li><span className="font-medium">Genie Spaces:</span> Connect to your Databricks Genie data source</li>
        <li><span className="font-medium">Deck Prompt:</span> Select a presentation template from the library</li>
        <li><span className="font-medium">Slide Style:</span> Select a visual style for your slides</li>
        <li><span className="font-medium">Advanced:</span> System prompts for power users (rarely modified)</li>
      </ul>
    </section>

    <section>
      <h2 className="text-lg font-semibold text-gray-800 mb-3">Actions</h2>
      <ul className="list-disc list-inside text-gray-600 space-y-2">
        <li><span className="font-medium">View and Edit:</span> Modify profile settings and configuration</li>
        <li><span className="font-medium">Load:</span> Hot-swap configuration without restart</li>
        <li><span className="font-medium">Set Default:</span> Choose which profile loads at startup</li>
        <li><span className="font-medium">Duplicate:</span> Copy a profile to experiment with settings</li>
        <li><span className="font-medium">Delete:</span> Remove a profile (must have at least one)</li>
      </ul>
    </section>

    <section>
      <h2 className="text-lg font-semibold text-gray-800 mb-3">When to Use Profiles</h2>
      <div className="bg-purple-50 rounded-lg p-4">
        <ul className="list-disc list-inside text-gray-700 space-y-2">
          <li>Switch between different projects or data sources</li>
          <li>Test different LLM parameters and prompts</li>
          <li>Share configurations across team members</li>
          <li>Maintain separate dev/prod configurations</li>
        </ul>
      </div>
    </section>
  </div>
);

// Deck Prompts Tab Content
const DeckPromptsTab: React.FC = () => (
  <div className="space-y-6">
    <section>
      <h2 className="text-lg font-semibold text-gray-800 mb-3">What are Deck Prompts?</h2>
      <p className="text-gray-600 mb-3">
        Deck Prompts are reusable presentation templates that guide the AI in creating specific types of presentations.
        Instead of explaining what kind of deck you want each time, you can select a pre-built prompt that the AI follows.
      </p>
      <div className="bg-blue-50 rounded-lg p-4">
        <p className="text-blue-800 text-sm">
          <strong>Example:</strong> A "Quarterly Business Review" deck prompt tells the AI to structure slides with 
          executive summary, metrics deep-dive, achievements, challenges, and next quarter outlook.
        </p>
      </div>
    </section>

    <section>
      <h2 className="text-lg font-semibold text-gray-800 mb-3">How They Work</h2>
      <ol className="list-decimal list-inside text-gray-600 space-y-2">
        <li>Create deck prompts in the <strong>Deck Prompts</strong> page (top navigation)</li>
        <li>In a Profile, go to the <strong>Deck Prompt</strong> tab and select a prompt</li>
        <li>When you generate slides, the AI follows the selected prompt's structure</li>
        <li>You can still add your own instructions in the chat — they combine with the deck prompt</li>
      </ol>
    </section>

    <section>
      <h2 className="text-lg font-semibold text-gray-800 mb-3">Managing Deck Prompts</h2>
      <div className="bg-gray-50 rounded-lg p-4">
        <ul className="list-disc list-inside text-gray-700 space-y-2">
          <li><span className="font-medium">Create:</span> Click "+ Create Prompt" to add a new template</li>
          <li><span className="font-medium">Preview:</span> Expand any prompt to see its full content</li>
          <li><span className="font-medium">Edit:</span> Modify name, description, category, or content</li>
          <li><span className="font-medium">Delete:</span> Remove prompts you no longer need</li>
        </ul>
      </div>
    </section>

    <section>
      <h2 className="text-lg font-semibold text-gray-800 mb-3">Writing Good Deck Prompts</h2>
      <div className="grid md:grid-cols-2 gap-4">
        <div className="bg-green-50 rounded-lg p-3">
          <h4 className="font-medium text-green-800 mb-2">✓ Include</h4>
          <ul className="text-sm text-green-700 space-y-1">
            <li>• Clear presentation type name</li>
            <li>• Section structure and order</li>
            <li>• What data to query for</li>
            <li>• Specific metrics or KPIs to highlight</li>
            <li>• Chart type recommendations</li>
          </ul>
        </div>
        <div className="bg-red-50 rounded-lg p-3">
          <h4 className="font-medium text-red-800 mb-2">✗ Avoid</h4>
          <ul className="text-sm text-red-700 space-y-1">
            <li>• Hardcoded data values</li>
            <li>• Specific colors or fonts (use Advanced settings)</li>
            <li>• HTML formatting instructions</li>
            <li>• Too rigid structure that doesn't fit data</li>
          </ul>
        </div>
      </div>
    </section>

    <section>
      <h2 className="text-lg font-semibold text-gray-800 mb-3">Default Templates</h2>
      <p className="text-gray-600 mb-3">
        The system comes with several pre-built templates:
      </p>
      <ul className="list-disc list-inside text-gray-600 space-y-1">
        <li><span className="font-medium">Quarterly Business Review:</span> QBR structure with metrics, achievements, and outlook</li>
        <li><span className="font-medium">Executive Summary:</span> Concise 5-7 slide format for leadership</li>
      </ul>
    </section>

    <section>
      <h2 className="text-lg font-semibold text-gray-800 mb-3">Deck Prompts vs Advanced Settings</h2>
      <div className="bg-amber-50 rounded-lg p-4">
        <p className="text-gray-700 mb-2">
          <strong>Deck Prompts</strong> define <em>what kind of presentation</em> to create (structure, sections, data focus).
        </p>
        <p className="text-gray-700">
          <strong>Advanced Settings</strong> define <em>how</em> slides are generated (formatting rules, HTML structure, chart styling).
          Most users never need to modify Advanced settings.
        </p>
      </div>
    </section>
  </div>
);

// Slide Styles Tab Content
const SlideStylesTab: React.FC = () => (
  <div className="space-y-6">
    <section>
      <h2 className="text-lg font-semibold text-gray-800 mb-3">What are Slide Styles?</h2>
      <p className="text-gray-600 mb-3">
        Slide Styles control the visual appearance of your generated slides — typography, colors, spacing, and layout rules.
        They define <em>how</em> slides look, separate from <em>what</em> content they contain.
      </p>
      <div className="bg-blue-50 rounded-lg p-4">
        <p className="text-blue-800 text-sm">
          <strong>Tip:</strong> Create styles that specify fonts, colors, and palettes matching your corporate 
          guidelines for consistent, on-brand presentations.
        </p>
      </div>
    </section>

    <section>
      <h2 className="text-lg font-semibold text-gray-800 mb-3">How They Work</h2>
      <ol className="list-decimal list-inside text-gray-600 space-y-2">
        <li>Create slide styles in the <strong>Slide Styles</strong> page (top navigation)</li>
        <li>In a Profile, go to the <strong>Slide Style</strong> tab and select a style</li>
        <li>When you generate slides, the AI follows the selected style's visual rules</li>
        <li>Styles are applied consistently across all slides in the deck</li>
      </ol>
    </section>

    <section>
      <h2 className="text-lg font-semibold text-gray-800 mb-3">Managing Slide Styles</h2>
      <div className="bg-gray-50 rounded-lg p-4">
        <ul className="list-disc list-inside text-gray-700 space-y-2">
          <li><span className="font-medium">Create:</span> Click "+ Create Style" to add a new visual style</li>
          <li><span className="font-medium">Preview:</span> Expand any style to see its full configuration</li>
          <li><span className="font-medium">Edit:</span> Modify name, description, category, or style rules</li>
          <li><span className="font-medium">Delete:</span> Remove styles you no longer need</li>
        </ul>
      </div>
    </section>

    <section>
      <h2 className="text-lg font-semibold text-gray-800 mb-3">What Styles Control</h2>
      <div className="grid md:grid-cols-2 gap-4">
        <div className="bg-purple-50 rounded-lg p-3">
          <h4 className="font-medium text-purple-800 mb-2">Typography</h4>
          <ul className="text-sm text-purple-700 space-y-1">
            <li>• Font families for headings and body</li>
            <li>• Font sizes and weights</li>
            <li>• Line heights and letter spacing</li>
          </ul>
        </div>
        <div className="bg-green-50 rounded-lg p-3">
          <h4 className="font-medium text-green-800 mb-2">Colors</h4>
          <ul className="text-sm text-green-700 space-y-1">
            <li>• Primary and accent color palette</li>
            <li>• Background colors and gradients</li>
            <li>• Chart and visualization colors</li>
          </ul>
        </div>
        <div className="bg-amber-50 rounded-lg p-3">
          <h4 className="font-medium text-amber-800 mb-2">Layout</h4>
          <ul className="text-sm text-amber-700 space-y-1">
            <li>• Margins and padding rules</li>
            <li>• Content alignment preferences</li>
            <li>• Grid and spacing systems</li>
          </ul>
        </div>
        <div className="bg-blue-50 rounded-lg p-3">
          <h4 className="font-medium text-blue-800 mb-2">Components</h4>
          <ul className="text-sm text-blue-700 space-y-1">
            <li>• Table styling and borders</li>
            <li>• List bullet and numbering styles</li>
            <li>• Card and box shadow effects</li>
          </ul>
        </div>
      </div>
    </section>

    <section>
      <h2 className="text-lg font-semibold text-gray-800 mb-3">Writing Good Style Definitions</h2>
      <div className="grid md:grid-cols-2 gap-4">
        <div className="bg-green-50 rounded-lg p-3">
          <h4 className="font-medium text-green-800 mb-2">✓ Include</h4>
          <ul className="text-sm text-green-700 space-y-1">
            <li>• Specific font names and sizes</li>
            <li>• Hex or RGB color values</li>
            <li>• Consistent spacing units</li>
            <li>• Chart color sequences</li>
            <li>• Visual hierarchy rules</li>
          </ul>
        </div>
        <div className="bg-red-50 rounded-lg p-3">
          <h4 className="font-medium text-red-800 mb-2">✗ Avoid</h4>
          <ul className="text-sm text-red-700 space-y-1">
            <li>• Content or data instructions</li>
            <li>• Slide structure definitions</li>
            <li>• Conflicting style rules</li>
            <li>• Platform-specific features</li>
          </ul>
        </div>
      </div>
    </section>

    <section>
      <h2 className="text-lg font-semibold text-gray-800 mb-3">Slide Styles vs Deck Prompts</h2>
      <div className="bg-amber-50 rounded-lg p-4">
        <p className="text-gray-700 mb-2">
          <strong>Slide Styles</strong> define <em>how</em> slides look (fonts, colors, spacing, visual rules).
        </p>
        <p className="text-gray-700">
          <strong>Deck Prompts</strong> define <em>what</em> slides contain (sections, structure, data focus).
        </p>
        <p className="text-gray-600 text-sm mt-2">
          You can combine any style with any prompt — a "QBR" deck prompt works with both "Databricks Brand" 
          and "Minimal Dark" styles.
        </p>
      </div>
    </section>

  </div>
);
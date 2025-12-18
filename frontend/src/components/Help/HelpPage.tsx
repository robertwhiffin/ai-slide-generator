import React, { useState } from 'react';
import { FiArrowLeft, FiMessageSquare, FiClock, FiSettings, FiInfo, FiShield } from 'react-icons/fi';
import { FaGavel } from 'react-icons/fa';

type HelpTab = 'overview' | 'generator' | 'history' | 'settings' | 'verification';

interface HelpPageProps {
  onBack: () => void;
}

export const HelpPage: React.FC<HelpPageProps> = ({ onBack }) => {
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
      {/* Header with back button */}
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-800">How to Use AI Slide Generator</h1>
        <button
          onClick={onBack}
          className="flex items-center gap-2 px-4 py-2 text-sm text-gray-600 hover:text-gray-800 hover:bg-gray-100 rounded-lg transition-colors"
        >
          <FiArrowLeft size={16} />
          Back
        </button>
      </div>

      {/* Tab bar */}
      <div className="flex gap-2 mb-6 flex-wrap">
        <TabButton tab="overview" label="Overview" icon={FiInfo} />
        <TabButton tab="generator" label="Generator" icon={FiMessageSquare} />
        <TabButton tab="verification" label="Verification" icon={FiShield} />
        <TabButton tab="history" label="History" icon={FiClock} />
        <TabButton tab="settings" label="Settings" icon={FiSettings} />
      </div>

      {/* Content area */}
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 min-h-[400px]">
        {activeTab === 'overview' && <OverviewTab setActiveTab={setActiveTab} QuickLinkButton={QuickLinkButton} />}
        {activeTab === 'generator' && <GeneratorTab />}
        {activeTab === 'verification' && <VerificationTab />}
        {activeTab === 'history' && <HistoryTab />}
        {activeTab === 'settings' && <SettingsTab />}
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
      <h2 className="text-lg font-semibold text-gray-800 mb-3">What is AI Slide Generator?</h2>
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
        <QuickLinkButton tab="settings" label="Learn about Settings →" />
      </div>
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
      <div className="grid grid-cols-2 gap-3">
        <div className="flex items-center gap-2">
          <span className="px-2 py-1 text-xs font-medium rounded bg-green-100 text-green-800 border border-green-300">✓ 95%</span>
          <span className="text-sm text-gray-600"><strong>Excellent:</strong> All data accurate</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="px-2 py-1 text-xs font-medium rounded bg-emerald-100 text-emerald-700 border border-emerald-300">✓ 80%</span>
          <span className="text-sm text-gray-600"><strong>Good:</strong> Minor omissions only</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="px-2 py-1 text-xs font-medium rounded bg-yellow-100 text-yellow-800 border border-yellow-300">~ 60%</span>
          <span className="text-sm text-gray-600"><strong>Moderate:</strong> Some data missing</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="px-2 py-1 text-xs font-medium rounded bg-orange-100 text-orange-800 border border-orange-300">✗ 40%</span>
          <span className="text-sm text-gray-600"><strong>Poor:</strong> Errors or missing data</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="px-2 py-1 text-xs font-medium rounded bg-red-100 text-red-800 border border-red-300">✗ 15%</span>
          <span className="text-sm text-gray-600"><strong>Failing:</strong> Major inaccuracies</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="px-2 py-1 text-xs font-medium rounded bg-gray-100 text-gray-600 border border-gray-300">? Unknown</span>
          <span className="text-sm text-gray-600"><strong>Unknown:</strong> No source data available</span>
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

// Settings Tab Content
const SettingsTab: React.FC = () => (
  <div className="space-y-6">
    <section>
      <h2 className="text-lg font-semibold text-gray-800 mb-3">Profiles</h2>
      <p className="text-gray-600">
        Profiles store your configuration for LLM settings, Genie space connections, MLflow experiment tracking, and custom prompts.
      </p>
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


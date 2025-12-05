import React, { useState } from 'react';
import { FiArrowLeft, FiMessageSquare, FiClock, FiSettings, FiInfo } from 'react-icons/fi';

type HelpTab = 'overview' | 'generator' | 'history' | 'settings';

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
        <TabButton tab="history" label="History" icon={FiClock} />
        <TabButton tab="settings" label="Settings" icon={FiSettings} />
      </div>

      {/* Content area */}
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 min-h-[400px]">
        {activeTab === 'overview' && <OverviewTab setActiveTab={setActiveTab} QuickLinkButton={QuickLinkButton} />}
        {activeTab === 'generator' && <GeneratorTab />}
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


import { useState } from 'react';
import { X, Layers, Compass, MessageSquare, Wrench, Download, History } from 'lucide-react';
import { useTour } from '../../contexts/TourContext';

const FEATURES = [
  {
    icon: MessageSquare,
    title: 'AI-Powered Generation',
    description: 'Describe your slides in natural language. The AI creates a full deck — layout, content, and styling — in seconds.',
    color: 'text-blue-600 bg-blue-50',
  },
  {
    icon: Wrench,
    title: 'Smart Tool Integration',
    description: 'Connect Genie spaces, vector search, MCP tools, and model endpoints to build data-driven presentations.',
    color: 'text-purple-600 bg-purple-50',
  },
  {
    icon: Download,
    title: 'Export & Share',
    description: 'Download as PPTX, PDF, or export to Google Slides. Share with teammates or present directly from the browser.',
    color: 'text-emerald-600 bg-emerald-50',
  },
  {
    icon: History,
    title: 'Version History',
    description: 'Save points let you snapshot your work, browse past versions, and revert to any point in your editing history.',
    color: 'text-amber-600 bg-amber-50',
  },
];

type Tab = 'overview' | 'features';

export function WelcomeModal() {
  const { showWelcome, startTour, dismissWelcome } = useTour();
  const [activeTab, setActiveTab] = useState<Tab>('overview');
  const [dontShow, setDontShow] = useState(false);

  if (!showWelcome) return null;

  const handleDismiss = () => {
    if (dontShow) {
      dismissWelcome();
    } else {
      dismissWelcome();
    }
  };

  return (
    <div className="fixed inset-0 z-[10001] flex items-center justify-center bg-black/40 backdrop-blur-sm">
      <div className="w-full max-w-2xl mx-4 rounded-2xl bg-white shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-5 border-b border-gray-100">
          <div className="flex items-center gap-3">
            <div className="flex items-center justify-center w-10 h-10 rounded-xl bg-blue-600 text-white">
              <Layers className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-gray-900">Welcome to Tellr</h2>
              <p className="text-sm text-gray-500">AI slide generator</p>
            </div>
          </div>
          <button
            onClick={handleDismiss}
            className="p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-gray-100">
          <button
            onClick={() => setActiveTab('overview')}
            className={`flex-1 flex items-center justify-center gap-2 px-4 py-3 text-sm font-medium transition-colors ${
              activeTab === 'overview'
                ? 'text-blue-600 border-b-2 border-blue-600'
                : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            <Layers className="w-4 h-4" />
            Overview
          </button>
          <button
            onClick={() => setActiveTab('features')}
            className={`flex-1 flex items-center justify-center gap-2 px-4 py-3 text-sm font-medium transition-colors ${
              activeTab === 'features'
                ? 'text-blue-600 border-b-2 border-blue-600'
                : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            <Compass className="w-4 h-4" />
            Features
          </button>
        </div>

        {/* Content */}
        <div className="px-6 py-6">
          {activeTab === 'overview' && (
            <div>
              <h3 className="text-base font-semibold text-gray-900 mb-2">What is Tellr?</h3>
              <p className="text-sm text-gray-600 leading-relaxed mb-6">
                Tellr turns conversations into presentations. Describe your ideas to an AI agent and get 
                polished slide decks in seconds — powered by your Databricks workspace data, custom styles, 
                and reusable prompts. Collaborate with your team, iterate through chat, and export anywhere.
              </p>

              <div className="grid grid-cols-2 gap-3">
                {FEATURES.map((feature) => (
                  <div
                    key={feature.title}
                    className="rounded-xl border border-gray-150 p-4 hover:border-gray-200 transition-colors"
                  >
                    <div className="flex items-center gap-2.5 mb-2">
                      <div className={`flex items-center justify-center w-8 h-8 rounded-lg ${feature.color}`}>
                        <feature.icon className="w-4 h-4" />
                      </div>
                      <span className="text-sm font-semibold text-gray-900">{feature.title}</span>
                    </div>
                    <p className="text-xs text-gray-500 leading-relaxed">{feature.description}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {activeTab === 'features' && (
            <div className="space-y-4">
              <h3 className="text-base font-semibold text-gray-900 mb-1">Key Features</h3>
              <div className="space-y-3">
                {[
                  { label: 'Chat-based generation', desc: 'Describe your deck in plain language — the AI handles structure, content, and design.' },
                  { label: 'Configurable AI agent', desc: 'Attach tools like Genie spaces for live data, vector search for documents, and custom model endpoints.' },
                  { label: 'Slide styles & prompts', desc: 'Define visual themes and system prompts that standardize how decks look and feel.' },
                  { label: 'Agent profiles', desc: 'Save combinations of tools, styles, and prompts as profiles for instant reuse.' },
                  { label: 'Direct editing', desc: 'Click any slide to edit HTML inline. Drag to reorder. Duplicate, delete, or refine with AI.' },
                  { label: 'Multi-format export', desc: 'Download PPTX, PDF, or HTML. Export directly to Google Slides.' },
                  { label: 'Collaboration', desc: 'Share decks with teammates. Editing locks prevent conflicts. Copy a view-only link for stakeholders.' },
                  { label: 'Version history', desc: 'Save points snapshot your deck. Preview any version and revert with one click.' },
                ].map((item) => (
                  <div key={item.label} className="flex gap-3">
                    <div className="w-1.5 h-1.5 rounded-full bg-blue-500 mt-2 shrink-0" />
                    <div>
                      <span className="text-sm font-medium text-gray-900">{item.label}</span>
                      <span className="text-sm text-gray-500"> — {item.desc}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-6 py-4 border-t border-gray-100 bg-gray-50/50">
          <label className="flex items-center gap-2 text-sm text-gray-500 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={dontShow}
              onChange={(e) => setDontShow(e.target.checked)}
              className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
            />
            Don't show this again
          </label>
          <div className="flex items-center gap-2">
            <button
              onClick={startTour}
              className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors"
            >
              <Compass className="w-4 h-4" />
              Take the Tour
            </button>
            <button
              onClick={handleDismiss}
              className="px-5 py-2 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 transition-colors"
            >
              Get Started
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

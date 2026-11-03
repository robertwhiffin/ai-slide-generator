import React, { useState } from 'react';
import { FeedbackDashboard } from '../Feedback/FeedbackDashboard';
import { GoogleSlidesAuthForm } from '../config/GoogleSlidesAuthForm';
import { AdminDesignSystemDefault } from './AdminDesignSystemDefault';
import { AdminJudgeSettings } from './AdminJudgeSettings';
import { AdminSlideStyleDefault } from './AdminSlideStyleDefault';
import { UsageDashboard } from './UsageDashboard';
import { AgentDefinitionWorkbench } from './AgentDefinitionWorkbench';
import { AdminAdmins } from './AdminAdmins';
import { AdminConnections } from './AdminConnections';

type TabId =
  | 'usage'
  | 'feedback'
  | 'google_slides'
  | 'design_system'
  | 'slide_style'
  | 'judge'
  | 'agent_definitions'
  | 'connections'
  | 'admins';

export const AdminPage: React.FC = () => {
  const [activeTab, setActiveTab] = useState<TabId>('usage');
  const [hasVisitedAgentDefinitions, setHasVisitedAgentDefinitions] = useState(false);
  const [hasVisitedAdmins, setHasVisitedAdmins] = useState(false);

  return (
    <div className="min-h-screen bg-gray-50">
      <div className={`mx-auto p-6 ${activeTab === 'agent_definitions' ? 'max-w-[90rem]' : 'max-w-6xl'}`}>
        <header className="mb-6">
          <h1 className="text-2xl font-bold text-gray-900">Admin</h1>
          <p className="text-sm text-gray-500 mt-1">
            Usage analytics, feedback reports, Google Slides, design system and slide style
            defaults, and LLM judge backend.
          </p>
        </header>

        <div
          role="tablist"
          className="flex gap-1 border-b border-gray-200 mb-6"
        >
          <button
            role="tab"
            aria-selected={activeTab === 'usage'}
            aria-controls="usage-panel"
            id="usage-tab"
            onClick={() => setActiveTab('usage')}
            className={`px-4 py-2 font-medium text-sm border-b-2 transition-colors -mb-px ${
              activeTab === 'usage'
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-600 hover:text-gray-900 hover:border-gray-300'
            }`}
          >
            Usage
          </button>
          <button
            role="tab"
            aria-selected={activeTab === 'feedback'}
            aria-controls="feedback-panel"
            id="feedback-tab"
            onClick={() => setActiveTab('feedback')}
            className={`px-4 py-2 font-medium text-sm border-b-2 transition-colors -mb-px ${
              activeTab === 'feedback'
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-600 hover:text-gray-900 hover:border-gray-300'
            }`}
          >
            Feedback
          </button>
          <button
            role="tab"
            aria-selected={activeTab === 'google_slides'}
            aria-controls="google-slides-panel"
            id="google-slides-tab"
            onClick={() => setActiveTab('google_slides')}
            className={`px-4 py-2 font-medium text-sm border-b-2 transition-colors -mb-px ${
              activeTab === 'google_slides'
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-600 hover:text-gray-900 hover:border-gray-300'
            }`}
          >
            Google Slides
          </button>
          <button
            role="tab"
            aria-selected={activeTab === 'design_system'}
            aria-controls="design-system-panel"
            id="design-system-tab"
            onClick={() => setActiveTab('design_system')}
            className={`px-4 py-2 font-medium text-sm border-b-2 transition-colors -mb-px ${
              activeTab === 'design_system'
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-600 hover:text-gray-900 hover:border-gray-300'
            }`}
          >
            Design System
          </button>
          <button
            role="tab"
            aria-selected={activeTab === 'slide_style'}
            aria-controls="slide-style-panel"
            id="slide-style-tab"
            onClick={() => setActiveTab('slide_style')}
            className={`px-4 py-2 font-medium text-sm border-b-2 transition-colors -mb-px ${
              activeTab === 'slide_style'
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-600 hover:text-gray-900 hover:border-gray-300'
            }`}
          >
            Slide Style
          </button>
          <button
            role="tab"
            aria-selected={activeTab === 'judge'}
            aria-controls="judge-panel"
            id="judge-tab"
            onClick={() => setActiveTab('judge')}
            className={`px-4 py-2 font-medium text-sm border-b-2 transition-colors -mb-px ${
              activeTab === 'judge'
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-600 hover:text-gray-900 hover:border-gray-300'
            }`}
          >
            Judge
          </button>
          <button
            role="tab"
            aria-selected={activeTab === 'agent_definitions'}
            aria-controls="agent-definitions-panel"
            id="agent-definitions-tab"
            onClick={() => {
              setHasVisitedAgentDefinitions(true);
              setActiveTab('agent_definitions');
            }}
            className={`px-4 py-2 font-medium text-sm border-b-2 transition-colors -mb-px ${
              activeTab === 'agent_definitions'
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-600 hover:text-gray-900 hover:border-gray-300'
            }`}
          >
            Agent Definitions
          </button>
          <button
            role="tab"
            aria-selected={activeTab === 'connections'}
            aria-controls="connections-panel"
            id="connections-tab"
            onClick={() => setActiveTab('connections')}
            className={`px-4 py-2 font-medium text-sm border-b-2 transition-colors -mb-px ${
              activeTab === 'connections'
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-600 hover:text-gray-900 hover:border-gray-300'
            }`}
          >
            Connections
          </button>
          <button
            role="tab"
            aria-selected={activeTab === 'admins'}
            aria-controls="admins-panel"
            id="admins-tab"
            onClick={() => {
              setHasVisitedAdmins(true);
              setActiveTab('admins');
            }}
            className={`px-4 py-2 font-medium text-sm border-b-2 transition-colors -mb-px ${
              activeTab === 'admins'
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-600 hover:text-gray-900 hover:border-gray-300'
            }`}
          >
            Admins
          </button>
        </div>

        <div
          role="tabpanel"
          id="usage-panel"
          aria-labelledby="usage-tab"
          hidden={activeTab !== 'usage'}
          className={activeTab !== 'usage' ? 'sr-only' : ''}
        >
          <UsageDashboard />
        </div>

        <div
          role="tabpanel"
          id="feedback-panel"
          aria-labelledby="feedback-tab"
          hidden={activeTab !== 'feedback'}
          className={activeTab !== 'feedback' ? 'sr-only' : ''}
        >
          <FeedbackDashboard />
        </div>

        <div
          role="tabpanel"
          id="google-slides-panel"
          aria-labelledby="google-slides-tab"
          hidden={activeTab !== 'google_slides'}
          className={activeTab !== 'google_slides' ? 'sr-only' : ''}
        >
          <GoogleSlidesAuthForm />
        </div>

        <div
          role="tabpanel"
          id="design-system-panel"
          aria-labelledby="design-system-tab"
          hidden={activeTab !== 'design_system'}
          className={activeTab !== 'design_system' ? 'sr-only' : ''}
        >
          <AdminDesignSystemDefault />
        </div>

        <div
          role="tabpanel"
          id="slide-style-panel"
          aria-labelledby="slide-style-tab"
          hidden={activeTab !== 'slide_style'}
          className={activeTab !== 'slide_style' ? 'sr-only' : ''}
        >
          <AdminSlideStyleDefault />
        </div>

        <div
          role="tabpanel"
          id="judge-panel"
          aria-labelledby="judge-tab"
          hidden={activeTab !== 'judge'}
          className={activeTab !== 'judge' ? 'sr-only' : ''}
        >
          <AdminJudgeSettings />
        </div>

        <div
          role="tabpanel"
          id="agent-definitions-panel"
          aria-labelledby="agent-definitions-tab"
          hidden={activeTab !== 'agent_definitions'}
          className={activeTab !== 'agent_definitions' ? 'sr-only' : ''}
        >
          {hasVisitedAgentDefinitions && <AgentDefinitionWorkbench />}
        </div>

        <div
          role="tabpanel"
          id="connections-panel"
          aria-labelledby="connections-tab"
          hidden={activeTab !== 'connections'}
          className={activeTab !== 'connections' ? 'sr-only' : ''}
        >
          {activeTab === 'connections' && <AdminConnections />}
        </div>

        <div
          role="tabpanel"
          id="admins-panel"
          aria-labelledby="admins-tab"
          hidden={activeTab !== 'admins'}
          className={activeTab !== 'admins' ? 'sr-only' : ''}
        >
          {hasVisitedAdmins && <AdminAdmins />}
        </div>
      </div>
    </div>
  );
};

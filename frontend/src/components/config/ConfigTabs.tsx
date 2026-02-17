/**
 * Tabbed configuration editor.
 * 
 * Provides tabbed interface for editing all configuration domains:
 * - Genie Spaces
 * - Deck Prompt (presentation templates)
 * - Slide Style (visual appearance)
 * - AI Infrastructure
 * - Advanced (system prompts - debug mode only)
 */

import React, { useState, useMemo } from 'react';
import { useConfig } from '../../hooks/useConfig';
import { AIInfraForm } from './AIInfraForm';
import { GenieForm } from './GenieForm';
import { DeckPromptSelector } from './DeckPromptSelector';
import { SlideStyleSelector } from './SlideStyleSelector';
import { GoogleSlidesAuthForm } from './GoogleSlidesAuthForm';
import { AdvancedSettingsEditor } from './AdvancedSettingsEditor';

type TabId = 'ai_infra' | 'genie' | 'deck_prompt' | 'slide_style' | 'google_slides' | 'advanced';

interface Tab {
  id: TabId;
  label: string;
  icon: string;
  debugOnly?: boolean;
}

const isDebugMode = (): boolean => {
  const urlParams = new URLSearchParams(window.location.search);
  return urlParams.get('debug')?.toLowerCase() === 'true' || localStorage.getItem('debug')?.toLowerCase() === 'true';
};

const allTabs: Tab[] = [
  { id: 'genie', label: 'Genie Spaces', icon: '🧞' },
  { id: 'deck_prompt', label: 'Deck Prompt', icon: '📋' },
  { id: 'slide_style', label: 'Slide Style', icon: '🎨' },
  { id: 'ai_infra', label: 'AI Infrastructure', icon: '🤖' },
  { id: 'google_slides', label: 'Google Slides', icon: '📊' },
  { id: 'advanced', label: 'Advanced', icon: '⚙️', debugOnly: true },
];

interface ConfigTabsProps {
  profileId: number;
  profileName: string;
}

export const ConfigTabs: React.FC<ConfigTabsProps> = ({ profileId, profileName }) => {
  const [activeTab, setActiveTab] = useState<TabId>('genie');
  
  const {
    config,
    loading,
    error,
    saving,
    updateAIInfra,
    updatePrompts,
    reload,
  } = useConfig(profileId);

  // Filter tabs based on debug mode
  const tabs = useMemo(() => {
    const debugMode = isDebugMode();
    return allTabs.filter(tab => !tab.debugOnly || debugMode);
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-gray-600">Loading configuration...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4 bg-red-50 border border-red-200 rounded text-red-700">
        Error: {error}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="border-b pb-2">
        <h2 className="text-xl font-semibold text-gray-900">Configure: {profileName}</h2>
        <p className="text-sm text-gray-600 mt-1">
          Edit configuration settings for this profile. Changes are saved individually per section.
        </p>
      </div>

      {/* Tabs */}
      <div className="border-b">
        <nav className="flex gap-1">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`px-4 py-2 font-medium text-sm border-b-2 transition-colors ${
                activeTab === tab.id
                  ? 'border-blue-500 text-blue-600'
                  : 'border-transparent text-gray-600 hover:text-gray-900 hover:border-gray-300'
              }`}
            >
              <span className="mr-2">{tab.icon}</span>
              {tab.label}
            </button>
          ))}
        </nav>
      </div>

      {/* Tab Content */}
      <div className="py-4">
        {activeTab === 'ai_infra' && config.ai_infra && (
          <AIInfraForm
            config={config.ai_infra}
            onSave={updateAIInfra}
            saving={saving}
          />
        )}

        {activeTab === 'genie' && (
          <GenieForm
            profileId={profileId}
            onSave={reload}
            saving={saving}
          />
        )}

        {activeTab === 'deck_prompt' && config.prompts && (
          <DeckPromptSelector
            profileId={profileId}
            currentPrompts={config.prompts}
            onSave={reload}
            saving={saving}
          />
        )}

        {activeTab === 'slide_style' && config.prompts && (
          <SlideStyleSelector
            profileId={profileId}
            currentPrompts={config.prompts}
            onSave={reload}
            saving={saving}
          />
        )}

        {activeTab === 'google_slides' && (
          <GoogleSlidesAuthForm profileId={profileId} />
        )}

        {activeTab === 'advanced' && config.prompts && (
          <AdvancedSettingsEditor
            config={config.prompts}
            onSave={updatePrompts}
            saving={saving}
          />
        )}
      </div>
    </div>
  );
};


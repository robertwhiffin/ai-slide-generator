/**
 * Multi-step wizard for creating a complete profile.
 * 
 * Steps:
 * 1. Basic Info (Name, Description)
 * 2. Genie Space (Optional - enables data queries)
 * 3. Slide Style (Required)
 * 4. Deck Prompt (Optional)
 * 5. Review & Create
 * 
 * LLM settings use backend defaults (databricks-claude-sonnet-4-5).
 * Profiles without Genie run in prompt-only mode.
 */

import React, { useState, useEffect } from 'react';
import { FiCheck, FiChevronLeft, FiChevronRight, FiX, FiInfo } from 'react-icons/fi';
import { configApi, type DeckPrompt, type SlideStyle, type AvailableGenieSpaces } from '../../api/config';

// Wizard step definitions (5 steps - LLM uses backend defaults)
const STEPS = [
  { id: 'basic', title: 'Basic Info', description: 'Name and description' },
  { id: 'genie', title: 'Genie Space', description: 'Data source (optional)' },
  { id: 'slide-style', title: 'Slide Style', description: 'Visual appearance' },
  { id: 'deck-prompt', title: 'Deck Prompt', description: 'Optional template' },
  { id: 'review', title: 'Review', description: 'Confirm and create' },
] as const;

type StepId = typeof STEPS[number]['id'];

// Form data structure for the wizard
interface WizardFormData {
  // Basic info
  name: string;
  description: string;
  // Genie space
  genieSpaceId: string;
  genieSpaceName: string;
  genieDescription: string;
  // Slide style
  selectedSlideStyleId: number | null;
  // Deck prompt
  selectedDeckPromptId: number | null;
}

interface ProfileCreationWizardProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: (profileId: number) => void;
  currentUsername: string;
}

export const ProfileCreationWizard: React.FC<ProfileCreationWizardProps> = ({
  isOpen,
  onClose,
  onSuccess,
}) => {
  // Current step
  const [currentStep, setCurrentStep] = useState<StepId>('basic');
  
  // Form data
  const [formData, setFormData] = useState<WizardFormData>({
    name: '',
    description: '',
    genieSpaceId: '',
    genieSpaceName: '',
    genieDescription: '',
    selectedSlideStyleId: null,
    selectedDeckPromptId: null,
  });
  
  // Loading states
  const [availableSpaces, setAvailableSpaces] = useState<AvailableGenieSpaces['spaces']>({});
  const [loadingSpaces, setLoadingSpaces] = useState(false);
  const [slideStyles, setSlideStyles] = useState<SlideStyle[]>([]);
  const [loadingStyles, setLoadingStyles] = useState(false);
  const [deckPrompts, setDeckPrompts] = useState<DeckPrompt[]>([]);
  const [loadingPrompts, setLoadingPrompts] = useState(false);
  
  // Submission
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  // Manual Genie space lookup
  const [manualSpaceId, setManualSpaceId] = useState('');
  const [lookupError, setLookupError] = useState<string | null>(null);
  const [lookingUp, setLookingUp] = useState(false);
  
  // Filter for Genie spaces
  const [spaceFilter, setSpaceFilter] = useState('');

  // Initialize defaults when wizard opens
  useEffect(() => {
    if (isOpen) {
      setCurrentStep('basic');
      setFormData({
        name: '',
        description: '',
        genieSpaceId: '',
        genieSpaceName: '',
        genieDescription: '',
        selectedSlideStyleId: null,
        selectedDeckPromptId: null,
      });
      setError(null);
      loadSlideStyles();
      loadDeckPrompts();
    }
  }, [isOpen]);

  // Load available Genie spaces
  const loadGenieSpaces = async () => {
    if (Object.keys(availableSpaces).length > 0) return;
    setLoadingSpaces(true);
    try {
      const response = await configApi.getAvailableGenieSpaces();
      setAvailableSpaces(response.spaces);
    } catch (err) {
      console.error('Failed to load Genie spaces:', err);
    } finally {
      setLoadingSpaces(false);
    }
  };

  // Load slide styles
  const loadSlideStyles = async () => {
    setLoadingStyles(true);
    try {
      const response = await configApi.listSlideStyles();
      const activeStyles = response.styles.filter(s => s.is_active);
      setSlideStyles(activeStyles);
      // No auto-select - user must explicitly choose a style
    } catch (err) {
      console.error('Failed to load slide styles:', err);
    } finally {
      setLoadingStyles(false);
    }
  };

  // Load deck prompts
  const loadDeckPrompts = async () => {
    setLoadingPrompts(true);
    try {
      const response = await configApi.listDeckPrompts();
      setDeckPrompts(response.prompts.filter(p => p.is_active));
    } catch (err) {
      console.error('Failed to load deck prompts:', err);
    } finally {
      setLoadingPrompts(false);
    }
  };

  // Handle Genie space selection from dropdown
  const handleGenieSpaceSelect = (spaceId: string) => {
    if (spaceId && availableSpaces[spaceId]) {
      setFormData(prev => ({
        ...prev,
        genieSpaceId: spaceId,
        genieSpaceName: availableSpaces[spaceId].title,
        genieDescription: availableSpaces[spaceId].description || '',
      }));
    } else {
      setFormData(prev => ({
        ...prev,
        genieSpaceId: '',
        genieSpaceName: '',
        genieDescription: '',
      }));
    }
  };

  // Manual Genie space lookup
  const handleLookupSpace = async () => {
    if (!manualSpaceId.trim()) {
      setLookupError('Please enter a space ID');
      return;
    }
    setLookingUp(true);
    setLookupError(null);
    try {
      const response = await configApi.lookupGenieSpace(manualSpaceId.trim());
      setFormData(prev => ({
        ...prev,
        genieSpaceId: response.space_id,
        genieSpaceName: response.title,
        genieDescription: response.description || '',
      }));
      setManualSpaceId('');
    } catch (err) {
      setLookupError('Space not found or inaccessible');
    } finally {
      setLookingUp(false);
    }
  };

  // Validation for each step
  const isStepValid = (stepId: StepId): boolean => {
    switch (stepId) {
      case 'basic':
        return formData.name.trim().length > 0;
      case 'genie':
        // Genie is optional - profiles without Genie run in prompt-only mode
        // If a space is selected, description is required for AI context
        if (formData.genieSpaceId.trim().length > 0) {
          return formData.genieDescription.trim().length > 0;
        }
        return true; // Can skip Genie entirely
      case 'slide-style':
        return formData.selectedSlideStyleId !== null; // Required - must select a style
      case 'deck-prompt':
        return true; // Optional
      case 'review':
        return true;
      default:
        return false;
    }
  };

  // Check if we can proceed to the next step
  const canProceed = isStepValid(currentStep);

  // Navigate to next step
  const goNext = () => {
    const currentIndex = STEPS.findIndex(s => s.id === currentStep);
    if (currentIndex < STEPS.length - 1) {
      setCurrentStep(STEPS[currentIndex + 1].id);
    }
  };

  // Navigate to previous step
  const goBack = () => {
    const currentIndex = STEPS.findIndex(s => s.id === currentStep);
    if (currentIndex > 0) {
      setCurrentStep(STEPS[currentIndex - 1].id);
    }
  };

  // Submit the wizard
  const handleSubmit = async () => {
    setIsSubmitting(true);
    setError(null);
    
    try {
      // Create profile with inline configurations
      // ai_infra is omitted - backend uses defaults
      const promptsConfig = (formData.selectedDeckPromptId || formData.selectedSlideStyleId) ? {
        selected_deck_prompt_id: formData.selectedDeckPromptId,
        selected_slide_style_id: formData.selectedSlideStyleId,
      } : undefined;
      
      // Build genie_space only if a space was selected
      const genieSpaceConfig = formData.genieSpaceId.trim() ? {
        space_id: formData.genieSpaceId,
        space_name: formData.genieSpaceName,
        description: formData.genieDescription,
      } : undefined;
      
      const response = await configApi.createProfileWithConfig({
        name: formData.name.trim(),
        description: formData.description.trim() || null,
        genie_space: genieSpaceConfig,
        // ai_infra omitted - backend uses default (databricks-claude-sonnet-4-5)
        prompts: promptsConfig,
      });
      
      onSuccess(response.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create profile');
    } finally {
      setIsSubmitting(false);
    }
  };

  // Filter Genie spaces
  const filteredSpaces = Object.entries(availableSpaces)
    .filter(([_, details]) => 
      !spaceFilter || details.title.toLowerCase().includes(spaceFilter.toLowerCase())
    )
    .sort((a, b) => a[1].title.localeCompare(b[1].title));

  if (!isOpen) return null;

  // Find selected items for display
  const selectedSlideStyle = slideStyles.find(s => s.id === formData.selectedSlideStyleId);
  const selectedDeckPrompt = deckPrompts.find(p => p.id === formData.selectedDeckPromptId);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-50">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-3xl mx-4 max-h-[90vh] overflow-hidden flex flex-col">
        {/* Header */}
        <div className="px-6 py-4 border-b flex items-center justify-between bg-gradient-to-r from-purple-600 to-blue-600">
          <h2 className="text-xl font-semibold text-white">Create New Profile</h2>
          <button
            onClick={onClose}
            className="text-white hover:text-gray-200 transition-colors"
            disabled={isSubmitting}
          >
            <FiX size={24} />
          </button>
        </div>

        {/* Step indicator */}
        <div className="px-6 py-4 bg-gray-50 border-b">
          <div className="flex items-center justify-between">
            {STEPS.map((step, index) => {
              const stepIndex = STEPS.findIndex(s => s.id === currentStep);
              const isCompleted = index < stepIndex;
              const isCurrent = step.id === currentStep;
              
              return (
                <div key={step.id} className="flex items-center flex-1">
                  <div className="flex flex-col items-center">
                    <div 
                      className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-medium transition-colors ${
                        isCompleted 
                          ? 'bg-green-500 text-white' 
                          : isCurrent 
                            ? 'bg-purple-600 text-white' 
                            : 'bg-gray-200 text-gray-500'
                      }`}
                    >
                      {isCompleted ? <FiCheck /> : index + 1}
                    </div>
                    <span className={`text-xs mt-1 text-center ${isCurrent ? 'text-purple-600 font-medium' : 'text-gray-500'}`}>
                      {step.title}
                    </span>
                  </div>
                  {index < STEPS.length - 1 && (
                    <div className={`flex-1 h-0.5 mx-2 ${isCompleted ? 'bg-green-500' : 'bg-gray-200'}`} />
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6">
          {error && (
            <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded text-red-700 text-sm">
              {error}
            </div>
          )}

          {/* Step 1: Basic Info */}
          {currentStep === 'basic' && (
            <div className="space-y-4">
              <div>
                <h3 className="text-lg font-medium text-gray-900 mb-2">Profile Information</h3>
                <p className="text-sm text-gray-500 mb-4">
                  Give your profile a name and optional description.
                </p>
              </div>
              
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Name <span className="text-red-500">*</span>
                </label>
                <input
                  type="text"
                  value={formData.name}
                  onChange={(e) => setFormData(prev => ({ ...prev, name: e.target.value }))}
                  placeholder="e.g., Production Analytics, Sales Dashboard"
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-purple-500 focus:border-purple-500"
                  maxLength={100}
                />
                <p className="mt-1 text-xs text-gray-500">{formData.name.length}/100 characters</p>
              </div>
              
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Description
                </label>
                <textarea
                  value={formData.description}
                  onChange={(e) => setFormData(prev => ({ ...prev, description: e.target.value }))}
                  placeholder="Optional description for this profile"
                  rows={3}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-purple-500 focus:border-purple-500 resize-none"
                  maxLength={500}
                />
                <p className="mt-1 text-xs text-gray-500">{formData.description.length}/500 characters</p>
              </div>
            </div>
          )}

          {/* Step 2: Genie Space (Optional) */}
          {currentStep === 'genie' && (
            <div className="space-y-4">
              <div>
                <h3 className="text-lg font-medium text-gray-900 mb-2">Select Genie Space</h3>
                <p className="text-sm text-gray-500 mb-4">
                  Choose the Genie space that contains the data for your presentations.
                  <span className="block mt-1 text-purple-600 font-medium">
                    This step is optional. Skip to create a prompt-only profile without data queries.
                  </span>
                </p>
              </div>

              {/* Dropdown selection */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Available Genie Spaces
                </label>
                <input
                  type="text"
                  value={spaceFilter}
                  onChange={(e) => setSpaceFilter(e.target.value)}
                  onFocus={loadGenieSpaces}
                  placeholder="Type to filter spaces..."
                  className="w-full px-3 py-2 border border-gray-300 rounded-md mb-2 focus:ring-2 focus:ring-purple-500"
                />
                <select
                  value={formData.genieSpaceId}
                  onChange={(e) => handleGenieSpaceSelect(e.target.value)}
                  onFocus={loadGenieSpaces}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-purple-500"
                  disabled={loadingSpaces}
                >
                  <option value="">-- Select a Genie Space --</option>
                  {filteredSpaces.map(([spaceId, details]) => (
                    <option key={spaceId} value={spaceId}>
                      {details.title}
                    </option>
                  ))}
                </select>
                {loadingSpaces && (
                  <p className="mt-1 text-xs text-gray-500">Loading spaces...</p>
                )}
              </div>

              {/* Manual lookup */}
              <div className="border-t pt-4">
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Or enter Space ID manually
                </label>
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={manualSpaceId}
                    onChange={(e) => setManualSpaceId(e.target.value)}
                    placeholder="Enter Genie space ID"
                    className="flex-1 px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-purple-500"
                  />
                  <button
                    onClick={handleLookupSpace}
                    disabled={lookingUp || !manualSpaceId.trim()}
                    className="px-4 py-2 bg-gray-600 hover:bg-gray-700 text-white rounded-md disabled:bg-gray-400"
                  >
                    {lookingUp ? 'Looking up...' : 'Lookup'}
                  </button>
                </div>
                {lookupError && (
                  <p className="mt-1 text-xs text-red-500">{lookupError}</p>
                )}
              </div>

              {/* Selected space display */}
              {formData.genieSpaceId && (
                <div className="bg-purple-50 border border-purple-200 rounded-md p-4">
                  <h4 className="font-medium text-purple-900">{formData.genieSpaceName}</h4>
                  <p className="text-xs text-purple-600 mt-1">ID: {formData.genieSpaceId}</p>
                </div>
              )}

              {/* Description - required only when space is selected */}
              {formData.genieSpaceId && (
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Data Description (for AI Agent) <span className="text-red-500">*</span>
                  <span className="ml-2 inline-flex items-center" title="The AI agent needs this to understand what data it can query">
                    <FiInfo className="text-gray-400" />
                  </span>
                </label>
                <textarea
                  value={formData.genieDescription}
                  onChange={(e) => setFormData(prev => ({ ...prev, genieDescription: e.target.value }))}
                  placeholder={
                    formData.genieSpaceId && !formData.genieDescription
                      ? "No description set for this Genie space. Please provide one so the AI agent knows what data is available."
                      : "Describe what data is available in this Genie space..."
                  }
                  rows={4}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-purple-500 resize-none font-mono text-sm"
                />
                <p className="mt-1 text-xs text-gray-500">
                  The AI agent uses this to understand what queries it can make.
                </p>
              </div>
              )}

              {/* Prompt-only mode indicator when no space selected */}
              {!formData.genieSpaceId && (
                <div className="bg-blue-50 border border-blue-200 rounded-md p-4">
                  <h4 className="font-medium text-blue-900">Prompt-Only Mode</h4>
                  <p className="text-sm text-blue-700 mt-1">
                    No Genie space selected. This profile will generate slides from prompts only, without data queries.
                    You can add a Genie space later from the profile settings.
                  </p>
                </div>
              )}
            </div>
          )}

          {/* Step 3: Slide Style */}
          {currentStep === 'slide-style' && (
            <div className="space-y-4">
              <div>
                <h3 className="text-lg font-medium text-gray-900 mb-2">Slide Style <span className="text-red-500">*</span></h3>
                <p className="text-sm text-gray-500 mb-4">
                  Choose a visual style for your slides. This controls typography, colors, and layout.
                </p>
              </div>

              {loadingStyles ? (
                <p className="text-gray-500">Loading slide styles...</p>
              ) : slideStyles.length === 0 ? (
                <div className="bg-gray-50 border border-gray-200 rounded-md p-4 text-center text-gray-500">
                  <p>No slide styles available.</p>
                  <p className="text-sm mt-1">You can create them in the Slide Styles page.</p>
                </div>
              ) : (
                <div className="space-y-2 max-h-64 overflow-y-auto">
                  {slideStyles.map(style => (
                    <label 
                      key={style.id} 
                      className={`block p-4 border rounded-md cursor-pointer transition-colors ${
                        formData.selectedSlideStyleId === style.id 
                          ? 'border-emerald-500 bg-emerald-50' 
                          : 'border-gray-200 hover:border-gray-300'
                      }`}
                    >
                      <input
                        type="radio"
                        name="slideStyle"
                        checked={formData.selectedSlideStyleId === style.id}
                        onChange={() => setFormData(prev => ({ ...prev, selectedSlideStyleId: style.id }))}
                        className="sr-only"
                      />
                      <div className="flex items-start justify-between">
                        <div>
                          <span className="font-medium text-gray-900">{style.name}</span>
                          {style.category && (
                            <span className="ml-2 text-xs px-2 py-0.5 bg-gray-100 rounded-full">
                              {style.category}
                            </span>
                          )}
                          {style.description && (
                            <p className="text-sm text-gray-500 mt-1">{style.description}</p>
                          )}
                        </div>
                        {formData.selectedSlideStyleId === style.id && (
                          <FiCheck className="text-emerald-600 flex-shrink-0" />
                        )}
                      </div>
                    </label>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Step 4: Deck Prompt */}
          {currentStep === 'deck-prompt' && (
            <div className="space-y-4">
              <div>
                <h3 className="text-lg font-medium text-gray-900 mb-2">Deck Prompt (Optional)</h3>
                <p className="text-sm text-gray-500 mb-4">
                  Optionally select a pre-built prompt template for specific presentation types.
                </p>
              </div>

              {loadingPrompts ? (
                <p className="text-gray-500">Loading deck prompts...</p>
              ) : deckPrompts.length === 0 ? (
                <div className="bg-gray-50 border border-gray-200 rounded-md p-4 text-center text-gray-500">
                  <p>No deck prompts available.</p>
                  <p className="text-sm mt-1">You can create them in the Deck Prompts page.</p>
                </div>
              ) : (
                <div className="space-y-2 max-h-64 overflow-y-auto">
                  {/* Option for no deck prompt */}
                  <label className={`block p-4 border rounded-md cursor-pointer transition-colors ${
                    formData.selectedDeckPromptId === null 
                      ? 'border-purple-500 bg-purple-50' 
                      : 'border-gray-200 hover:border-gray-300'
                  }`}>
                    <input
                      type="radio"
                      name="deckPrompt"
                      checked={formData.selectedDeckPromptId === null}
                      onChange={() => setFormData(prev => ({ ...prev, selectedDeckPromptId: null }))}
                      className="sr-only"
                    />
                    <span className="font-medium text-gray-900">No deck prompt</span>
                    <p className="text-sm text-gray-500">Use default system prompts only</p>
                  </label>

                  {deckPrompts.map(prompt => (
                    <label 
                      key={prompt.id} 
                      className={`block p-4 border rounded-md cursor-pointer transition-colors ${
                        formData.selectedDeckPromptId === prompt.id 
                          ? 'border-purple-500 bg-purple-50' 
                          : 'border-gray-200 hover:border-gray-300'
                      }`}
                    >
                      <input
                        type="radio"
                        name="deckPrompt"
                        checked={formData.selectedDeckPromptId === prompt.id}
                        onChange={() => setFormData(prev => ({ ...prev, selectedDeckPromptId: prompt.id }))}
                        className="sr-only"
                      />
                      <div className="flex items-start justify-between">
                        <div>
                          <span className="font-medium text-gray-900">{prompt.name}</span>
                          {prompt.category && (
                            <span className="ml-2 text-xs px-2 py-0.5 bg-gray-100 rounded-full">
                              {prompt.category}
                            </span>
                          )}
                          {prompt.description && (
                            <p className="text-sm text-gray-500 mt-1">{prompt.description}</p>
                          )}
                        </div>
                        {formData.selectedDeckPromptId === prompt.id && (
                          <FiCheck className="text-purple-600 flex-shrink-0" />
                        )}
                      </div>
                    </label>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Step 4: Review */}
          {currentStep === 'review' && (
            <div className="space-y-4">
              <div>
                <h3 className="text-lg font-medium text-gray-900 mb-2">Review & Create</h3>
                <p className="text-sm text-gray-500 mb-4">
                  Review your profile configuration before creating.
                </p>
              </div>

              <div className="space-y-4">
                {/* Basic Info */}
                <div className="bg-gray-50 rounded-md p-4">
                  <h4 className="text-sm font-medium text-gray-700 mb-2">Basic Info</h4>
                  <dl className="grid grid-cols-2 gap-2 text-sm">
                    <dt className="text-gray-500">Name:</dt>
                    <dd className="font-medium">{formData.name}</dd>
                    <dt className="text-gray-500">Description:</dt>
                    <dd className="font-medium">{formData.description || '—'}</dd>
                  </dl>
                </div>

                {/* Genie Space */}
                <div className={`rounded-md p-4 ${formData.genieSpaceId ? 'bg-purple-50' : 'bg-blue-50'}`}>
                  <h4 className={`text-sm font-medium mb-2 ${formData.genieSpaceId ? 'text-purple-700' : 'text-blue-700'}`}>
                    Genie Space {!formData.genieSpaceId && '(Prompt-Only Mode)'}
                  </h4>
                  {formData.genieSpaceId ? (
                    <dl className="grid grid-cols-2 gap-2 text-sm">
                      <dt className="text-purple-500">Space:</dt>
                      <dd className="font-medium text-purple-900">{formData.genieSpaceName}</dd>
                      <dt className="text-purple-500">Description:</dt>
                      <dd className="font-medium text-purple-900 col-span-2 whitespace-pre-wrap">{formData.genieDescription}</dd>
                    </dl>
                  ) : (
                    <p className="text-sm text-blue-600">
                      No Genie space configured. Slides will be generated from prompts only. 
                      You can add a Genie space later from the profile settings.
                    </p>
                  )}
                </div>

                {/* Slide Style */}
                <div className="bg-emerald-50 rounded-md p-4">
                  <h4 className="text-sm font-medium text-emerald-700 mb-2">Slide Style</h4>
                  <dl className="grid grid-cols-2 gap-2 text-sm">
                    <dt className="text-emerald-500">Style:</dt>
                    <dd className="font-medium text-emerald-900">
                      {selectedSlideStyle ? selectedSlideStyle.name : 'None selected'}
                    </dd>
                  </dl>
                </div>

                {/* Deck Prompt */}
                <div className="bg-amber-50 rounded-md p-4">
                  <h4 className="text-sm font-medium text-amber-700 mb-2">Deck Prompt</h4>
                  <dl className="grid grid-cols-2 gap-2 text-sm">
                    <dt className="text-amber-500">Template:</dt>
                    <dd className="font-medium text-amber-900">
                      {selectedDeckPrompt ? selectedDeckPrompt.name : 'None selected'}
                    </dd>
                  </dl>
                </div>

                {/* Defaults note */}
                <div className="bg-blue-50 rounded-md p-4">
                  <h4 className="text-sm font-medium text-blue-700 mb-2">Defaults Applied</h4>
                  <p className="text-sm text-blue-600">
                    LLM settings will use system defaults. You can customize these after profile creation in the profile settings.
                  </p>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Footer with navigation */}
        <div className="px-6 py-4 border-t bg-gray-50 flex items-center justify-between">
          <button
            onClick={currentStep === 'basic' ? onClose : goBack}
            className="px-4 py-2 text-gray-700 hover:text-gray-900 transition-colors"
            disabled={isSubmitting}
          >
            <span className="flex items-center gap-1">
              <FiChevronLeft />
              {currentStep === 'basic' ? 'Cancel' : 'Back'}
            </span>
          </button>

          {currentStep === 'review' ? (
            <button
              onClick={handleSubmit}
              disabled={isSubmitting}
              className="px-6 py-2 bg-purple-600 hover:bg-purple-700 text-white rounded-md transition-colors disabled:bg-purple-400 flex items-center gap-2"
            >
              {isSubmitting ? (
                <>
                  <span className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  Creating...
                </>
              ) : (
                <>
                  <FiCheck />
                  Create Profile
                </>
              )}
            </button>
          ) : (
            <button
              onClick={goNext}
              disabled={!canProceed}
              className="px-4 py-2 bg-purple-600 hover:bg-purple-700 text-white rounded-md transition-colors disabled:bg-gray-400 flex items-center gap-1"
            >
              Next
              <FiChevronRight />
            </button>
          )}
        </div>
      </div>
    </div>
  );
};

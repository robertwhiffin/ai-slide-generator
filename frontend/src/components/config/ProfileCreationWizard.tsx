/**
 * Multi-step wizard for creating a complete profile.
 * 
 * Steps:
 * 1. Basic Info (Name, Description)
 * 2. Genie Space (Required)
 * 3. LLM Configuration (Defaults pre-populated)
 * 4. MLflow (Auto-populated)
 * 5. Deck Prompt (Optional)
 * 6. Review & Create
 */

import React, { useState, useEffect } from 'react';
import { FiCheck, FiChevronLeft, FiChevronRight, FiX, FiInfo } from 'react-icons/fi';
import { configApi, type DeckPrompt, type AvailableGenieSpaces } from '../../api/config';

// Wizard step definitions
const STEPS = [
  { id: 'basic', title: 'Basic Info', description: 'Name and description' },
  { id: 'genie', title: 'Genie Space', description: 'Data source (required)' },
  { id: 'llm', title: 'LLM Settings', description: 'AI model configuration' },
  { id: 'mlflow', title: 'MLflow', description: 'Experiment tracking' },
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
  // LLM
  llmEndpoint: string;
  llmTemperature: number;
  llmMaxTokens: number;
  // MLflow
  mlflowExperimentName: string;
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
  currentUsername,
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
    llmEndpoint: '',
    llmTemperature: 0.7,
    llmMaxTokens: 4096,
    mlflowExperimentName: '',
    selectedDeckPromptId: null,
  });
  
  // Loading states
  const [availableSpaces, setAvailableSpaces] = useState<AvailableGenieSpaces['spaces']>({});
  const [loadingSpaces, setLoadingSpaces] = useState(false);
  const [availableEndpoints, setAvailableEndpoints] = useState<string[]>([]);
  const [loadingEndpoints, setLoadingEndpoints] = useState(false);
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

  // Default LLM endpoint
  const DEFAULT_LLM_ENDPOINT = 'databricks-claude-sonnet-4-5';
  const DEFAULT_MAX_TOKENS = 60000;

  // Initialize defaults when wizard opens
  useEffect(() => {
    if (isOpen) {
      setCurrentStep('basic');
      // Fetch actual username from backend
      fetchUsername();
      setFormData({
        name: '',
        description: '',
        genieSpaceId: '',
        genieSpaceName: '',
        genieDescription: '',
        llmEndpoint: DEFAULT_LLM_ENDPOINT,
        llmTemperature: 0.7,
        llmMaxTokens: DEFAULT_MAX_TOKENS,
        mlflowExperimentName: `/Workspace/Users/${currentUsername}/ai-slide-generator`,
        selectedDeckPromptId: null,
      });
      setError(null);
      loadEndpoints();
      loadDeckPrompts();
    }
  }, [isOpen, currentUsername]);

  // Fetch actual username from Databricks
  const fetchUsername = async () => {
    try {
      // Use environment-aware URL
      const apiBase = import.meta.env.VITE_API_URL || (
        import.meta.env.MODE === 'production' ? '' : 'http://localhost:8000'
      );
      const response = await fetch(`${apiBase}/api/user/current`);
      if (response.ok) {
        const data = await response.json();
        const username = data.username || currentUsername;
        setFormData(prev => ({
          ...prev,
          mlflowExperimentName: `/Workspace/Users/${username}/ai-slide-generator`,
        }));
      }
    } catch {
      // Use prop value as fallback
    }
  };

  // Load available LLM endpoints
  const loadEndpoints = async () => {
    setLoadingEndpoints(true);
    try {
      const response = await configApi.getAvailableEndpoints();
      setAvailableEndpoints(response.endpoints);
      // Prefer the default endpoint if available, otherwise use first available
      if (response.endpoints.length > 0) {
        const preferredEndpoint = response.endpoints.includes(DEFAULT_LLM_ENDPOINT)
          ? DEFAULT_LLM_ENDPOINT
          : response.endpoints[0];
        setFormData(prev => ({ ...prev, llmEndpoint: preferredEndpoint }));
      }
    } catch (err) {
      console.error('Failed to load endpoints:', err);
    } finally {
      setLoadingEndpoints(false);
    }
  };

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
        return formData.genieSpaceId.trim().length > 0 && formData.genieDescription.trim().length > 0;
      case 'llm':
        return formData.llmEndpoint.length > 0;
      case 'mlflow':
        return formData.mlflowExperimentName.startsWith('/');
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
      const response = await configApi.createProfileWithConfig({
        name: formData.name.trim(),
        description: formData.description.trim() || null,
        genie_space: {
          space_id: formData.genieSpaceId,
          space_name: formData.genieSpaceName,
          description: formData.genieDescription,
        },
        ai_infra: {
          llm_endpoint: formData.llmEndpoint,
          llm_temperature: formData.llmTemperature,
          llm_max_tokens: formData.llmMaxTokens,
        },
        mlflow: {
          experiment_name: formData.mlflowExperimentName,
        },
        prompts: formData.selectedDeckPromptId ? {
          selected_deck_prompt_id: formData.selectedDeckPromptId,
        } : undefined,
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

  // Find selected deck prompt for display
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

          {/* Step 2: Genie Space */}
          {currentStep === 'genie' && (
            <div className="space-y-4">
              <div>
                <h3 className="text-lg font-medium text-gray-900 mb-2">Select Genie Space</h3>
                <p className="text-sm text-gray-500 mb-4">
                  Choose the Genie space that contains the data for your presentations.
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

              {/* Description - required */}
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
            </div>
          )}

          {/* Step 3: LLM Settings */}
          {currentStep === 'llm' && (
            <div className="space-y-4">
              <div>
                <h3 className="text-lg font-medium text-gray-900 mb-2">LLM Configuration</h3>
                <p className="text-sm text-gray-500 mb-4">
                  Configure the language model used for slide generation.
                </p>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  LLM Endpoint <span className="text-red-500">*</span>
                </label>
                <select
                  value={formData.llmEndpoint}
                  onChange={(e) => setFormData(prev => ({ ...prev, llmEndpoint: e.target.value }))}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-purple-500"
                  disabled={loadingEndpoints}
                >
                  <option value="">-- Select an endpoint --</option>
                  {availableEndpoints.map(endpoint => (
                    <option key={endpoint} value={endpoint}>
                      {endpoint}
                    </option>
                  ))}
                </select>
                {loadingEndpoints && (
                  <p className="mt-1 text-xs text-gray-500">Loading endpoints...</p>
                )}
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Temperature: {formData.llmTemperature.toFixed(2)}
                </label>
                <input
                  type="range"
                  min="0"
                  max="1"
                  step="0.05"
                  value={formData.llmTemperature}
                  onChange={(e) => setFormData(prev => ({ ...prev, llmTemperature: parseFloat(e.target.value) }))}
                  className="w-full"
                />
                <p className="mt-1 text-xs text-gray-500">
                  Lower = more deterministic, Higher = more creative
                </p>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Max Tokens
                </label>
                <input
                  type="number"
                  value={formData.llmMaxTokens}
                  onChange={(e) => setFormData(prev => ({ ...prev, llmMaxTokens: parseInt(e.target.value) || 4096 }))}
                  min={100}
                  max={100000}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-purple-500"
                />
              </div>
            </div>
          )}

          {/* Step 4: MLflow */}
          {currentStep === 'mlflow' && (
            <div className="space-y-4">
              <div>
                <h3 className="text-lg font-medium text-gray-900 mb-2">MLflow Configuration</h3>
                <p className="text-sm text-gray-500 mb-4">
                  Configure experiment tracking. This is auto-populated based on your username.
                </p>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Experiment Name <span className="text-red-500">*</span>
                </label>
                <input
                  type="text"
                  value={formData.mlflowExperimentName}
                  onChange={(e) => setFormData(prev => ({ ...prev, mlflowExperimentName: e.target.value }))}
                  placeholder="/Workspace/Users/username/experiment-name"
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-purple-500 font-mono text-sm"
                />
                <p className="mt-1 text-xs text-gray-500">
                  Must start with /. Recommended format: /Workspace/Users/your-username/experiment-name
                </p>
                {!formData.mlflowExperimentName.startsWith('/') && formData.mlflowExperimentName.length > 0 && (
                  <p className="mt-1 text-xs text-red-500">
                    Experiment name must start with /
                  </p>
                )}
              </div>
            </div>
          )}

          {/* Step 5: Deck Prompt */}
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

          {/* Step 6: Review */}
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
                <div className="bg-purple-50 rounded-md p-4">
                  <h4 className="text-sm font-medium text-purple-700 mb-2">Genie Space</h4>
                  <dl className="grid grid-cols-2 gap-2 text-sm">
                    <dt className="text-purple-500">Space:</dt>
                    <dd className="font-medium text-purple-900">{formData.genieSpaceName}</dd>
                    <dt className="text-purple-500">Description:</dt>
                    <dd className="font-medium text-purple-900 col-span-2 whitespace-pre-wrap">{formData.genieDescription}</dd>
                  </dl>
                </div>

                {/* LLM */}
                <div className="bg-blue-50 rounded-md p-4">
                  <h4 className="text-sm font-medium text-blue-700 mb-2">LLM Settings</h4>
                  <dl className="grid grid-cols-2 gap-2 text-sm">
                    <dt className="text-blue-500">Endpoint:</dt>
                    <dd className="font-medium text-blue-900">{formData.llmEndpoint}</dd>
                    <dt className="text-blue-500">Temperature:</dt>
                    <dd className="font-medium text-blue-900">{formData.llmTemperature}</dd>
                    <dt className="text-blue-500">Max Tokens:</dt>
                    <dd className="font-medium text-blue-900">{formData.llmMaxTokens}</dd>
                  </dl>
                </div>

                {/* MLflow */}
                <div className="bg-green-50 rounded-md p-4">
                  <h4 className="text-sm font-medium text-green-700 mb-2">MLflow</h4>
                  <dl className="grid grid-cols-2 gap-2 text-sm">
                    <dt className="text-green-500">Experiment:</dt>
                    <dd className="font-medium text-green-900 font-mono text-xs">{formData.mlflowExperimentName}</dd>
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


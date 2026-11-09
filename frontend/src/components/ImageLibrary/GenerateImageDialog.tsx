import React, { useCallback, useEffect, useRef, useState } from 'react';
import { FiX } from 'react-icons/fi';
import type {
  ImageAsset,
  ImageGenerationOptions,
  ImageModelOption,
} from '../../types/image';
import { api } from '../../services/api';

interface GenerateImageDialogProps {
  isOpen: boolean;
  onClose: () => void;
  onCreated: (image: ImageAsset) => void;
  options: ImageGenerationOptions;
  /** When set, the dialog edits a copy of this image instead of generating from scratch. */
  source?: ImageAsset;
}

interface Choices {
  presetId: string;
  models: ImageModelOption[];
  qualities: string[];
  model: string;
  quality: string;
}

function choicesFor(options: ImageGenerationOptions, presetId: string | undefined): Choices {
  if (presetId === undefined) {
    const edit = options.edit;
    return {
      presetId: '',
      models: edit?.models ?? [],
      qualities: edit?.qualities ?? [],
      model: edit?.default_model ?? '',
      quality: edit?.default_quality ?? '',
    };
  }
  const preset =
    options.presets.find((p) => p.id === presetId) ??
    options.presets.find((p) => p.id === options.default_preset) ??
    options.presets[0];
  return {
    presetId: preset?.id ?? '',
    models: preset?.models ?? [],
    qualities: preset?.qualities ?? [],
    model: preset?.default_model ?? '',
    quality: preset?.default_quality ?? '',
  };
}

const CHECKERBOARD_STYLE: React.CSSProperties = {
  backgroundColor: '#ffffff',
  backgroundImage:
    'linear-gradient(45deg, #e5e7eb 25%, transparent 25%, transparent 75%, #e5e7eb 75%), ' +
    'linear-gradient(45deg, #e5e7eb 25%, transparent 25%, transparent 75%, #e5e7eb 75%)',
  backgroundSize: '16px 16px',
  backgroundPosition: '0 0, 8px 8px',
};

export const GenerateImageDialog: React.FC<GenerateImageDialogProps> = ({
  isOpen,
  onClose,
  onCreated,
  options,
  source,
}) => {
  const isEdit = source !== undefined;
  const initialChoices = () => choicesFor(options, isEdit ? undefined : options.default_preset ?? undefined);

  const [choices, setChoices] = useState<Choices>(initialChoices);
  const [prompt, setPrompt] = useState('');
  const [running, setRunning] = useState(false);
  const [status, setStatus] = useState('');
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ImageAsset | null>(null);
  const [copied, setCopied] = useState(false);
  const runningRef = useRef(false);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  // Start from a clean form each time the dialog opens (or its source changes).
  const sourceId = source?.id;
  useEffect(() => {
    if (!isOpen || runningRef.current) return;
    setChoices(choicesFor(options, sourceId === undefined ? options.default_preset ?? undefined : undefined));
    setPrompt('');
    setError(null);
    setResult(null);
    setStatus('');
    setCopied(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, sourceId]);

  useEffect(() => {
    if (!running) return;
    const startedAt = Date.now();
    setElapsed(0);
    const timer = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startedAt) / 1000));
    }, 500);
    return () => clearInterval(timer);
  }, [running]);

  const trimmed = prompt.trim();
  const overLimit = trimmed.length > options.max_prompt_chars;
  const canSubmit = trimmed.length > 0 && !overLimit && !running;

  const handlePreset = (presetId: string) => {
    setChoices(choicesFor(options, presetId));
  };

  const handleSubmit = useCallback(async () => {
    if (!canSubmit || runningRef.current) return;
    runningRef.current = true;
    setRunning(true);
    setError(null);
    setStatus('');
    const onProgress = (_progress: number, _total: number, text: string) => {
      if (mountedRef.current) setStatus(text);
    };
    try {
      const created = source
        ? await api.editImageWithPrompt(
            source.id,
            { prompt: trimmed, model: choices.model, quality: choices.quality },
            onProgress,
          )
        : await api.generateImage(
            { prompt: trimmed, preset: choices.presetId, model: choices.model, quality: choices.quality },
            onProgress,
          );
      if (!mountedRef.current) return;
      setResult(created);
      onCreated(created);
    } catch (err) {
      if (!mountedRef.current) return;
      setError(err instanceof Error && err.message ? err.message : 'Image generation failed');
    } finally {
      runningRef.current = false;
      if (mountedRef.current) setRunning(false);
    }
  }, [canSubmit, source, trimmed, choices, onCreated]);

  const handleCopy = async () => {
    if (!result) return;
    try {
      await navigator.clipboard.writeText(`{{image:${result.id}}}`);
      setCopied(true);
    } catch {
      setError('Could not copy to the clipboard');
    }
  };

  const handleAnother = () => {
    setResult(null);
    setError(null);
    setStatus('');
    setCopied(false);
  };

  if (!isOpen) return null;

  const inputsDisabled = running;
  // "When to choose" explainers for the current picks (model ones come with the model list).
  const modelHelp = choices.models.find((m) => m.id === choices.model)?.description;
  const qualityHelp = options.quality_descriptions?.[choices.quality];
  const selectClass =
    'w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100';

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50" role="presentation">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="generate-image-title"
        className="bg-white rounded-xl shadow-xl w-full max-w-2xl max-h-[85vh] flex flex-col mx-4"
      >
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200">
          <div>
            <h3 id="generate-image-title" className="text-lg font-semibold text-gray-900">
              {isEdit ? 'Edit with prompt' : 'Generate image'}
            </h3>
            {source && (
              <p className="text-xs text-gray-500 mt-0.5">Source: {source.original_filename}</p>
            )}
          </div>
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            className="p-1 text-gray-400 hover:text-gray-600"
          >
            <FiX size={20} />
          </button>
        </div>

        <div className="p-5 overflow-y-auto space-y-4">
          {result ? (
            <div className="space-y-4">
              <div
                className="flex items-center justify-center rounded-lg border border-gray-200 p-2"
                style={CHECKERBOARD_STYLE}
              >
                {result.thumbnail_base64 ? (
                  <img
                    src={result.thumbnail_base64}
                    alt={result.description || result.original_filename}
                    className="max-w-full max-h-72 object-contain"
                  />
                ) : (
                  <span className="text-sm text-gray-500 py-8">{result.original_filename}</span>
                )}
              </div>
              <p className="text-sm text-gray-600">
                Saved to the Image Library as {result.original_filename}.
                {copied && <span className="ml-1 text-green-600">Copied.</span>}
              </p>
              {error && (
                <div role="alert" className="p-3 bg-red-50 text-red-700 rounded-lg text-sm">
                  {error}
                </div>
              )}
              <div className="flex gap-2 justify-end">
                <button
                  type="button"
                  onClick={handleCopy}
                  className="px-4 py-2 text-sm bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200"
                >
                  Copy reference
                </button>
                <button
                  type="button"
                  onClick={handleAnother}
                  className="px-4 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700"
                >
                  Generate another
                </button>
              </div>
            </div>
          ) : (
            <>
              {!isEdit && (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                  {options.presets.map((preset) => {
                    const selected = preset.id === choices.presetId;
                    return (
                      <button
                        key={preset.id}
                        type="button"
                        aria-pressed={selected}
                        disabled={inputsDisabled}
                        onClick={() => handlePreset(preset.id)}
                        className={`text-left p-3 rounded-lg border text-sm transition-colors disabled:opacity-60 ${
                          selected
                            ? 'border-blue-500 bg-blue-50'
                            : 'border-gray-200 hover:border-gray-300'
                        }`}
                      >
                        <span className="block font-medium text-gray-900">{preset.label}</span>
                        <span className="block text-xs text-gray-500 mt-0.5">{preset.description}</span>
                      </button>
                    );
                  })}
                </div>
              )}

              <div>
                <textarea
                  aria-label="Prompt"
                  value={prompt}
                  maxLength={options.max_prompt_chars}
                  disabled={inputsDisabled}
                  onChange={(e) => setPrompt(e.target.value)}
                  rows={4}
                  placeholder={isEdit ? 'Describe the change to make...' : 'Describe the image...'}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100"
                />
                <p className={`text-xs mt-1 text-right ${overLimit ? 'text-red-600' : 'text-gray-400'}`}>
                  {prompt.length} / {options.max_prompt_chars}
                </p>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <select
                  aria-label="Model"
                  value={choices.model}
                  disabled={inputsDisabled}
                  onChange={(e) => setChoices((c) => ({ ...c, model: e.target.value }))}
                  className={selectClass}
                >
                  {choices.models.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.label}
                    </option>
                  ))}
                </select>
                <select
                  aria-label="Quality"
                  value={choices.quality}
                  disabled={inputsDisabled}
                  onChange={(e) => setChoices((c) => ({ ...c, quality: e.target.value }))}
                  className={`${selectClass} capitalize`}
                >
                  {choices.qualities.map((q) => (
                    <option key={q} value={q}>
                      {q}
                    </option>
                  ))}
                </select>
              </div>

              {(modelHelp || qualityHelp) && (
                <div className="grid grid-cols-2 gap-3 -mt-1 text-xs text-gray-500">
                  <p>{modelHelp}</p>
                  <p>{qualityHelp}</p>
                </div>
              )}

              {running && (
                <div className="flex items-center justify-between text-sm text-gray-600" aria-live="polite">
                  <span>{status || 'Starting...'}</span>
                  <span>{elapsed}s</span>
                </div>
              )}

              {error && (
                <div role="alert" className="p-3 bg-red-50 text-red-700 rounded-lg text-sm">
                  {error}
                </div>
              )}

              <div className="flex justify-end">
                <button
                  type="button"
                  onClick={handleSubmit}
                  disabled={!canSubmit}
                  className="px-4 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {isEdit ? 'Create edited copy' : 'Generate'}
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
};

export default GenerateImageDialog;

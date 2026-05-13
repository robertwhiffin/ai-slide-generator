import React, { useEffect, useState } from 'react';
import { adminApi, type LlmJudgeBackend } from '../../api/admin';
import { useToast } from '../../contexts/ToastContext';

export const AdminJudgeSettings: React.FC = () => {
  const [backend, setBackend] = useState<LlmJudgeBackend>('mlflow');
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { showToast } = useToast();

  useEffect(() => {
    let cancelled = false;
    adminApi
      .getJudgeBackend()
      .then((res) => {
        if (!cancelled) {
          setBackend(res.backend === 'direct' ? 'direct' : 'mlflow');
          setLoaded(true);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
          setLoaded(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleSave = async () => {
    setSaving(true);
    try {
      const res = await adminApi.setJudgeBackend(backend);
      setBackend(res.backend === 'direct' ? 'direct' : 'mlflow');
      showToast('Judge backend updated', 'success');
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      showToast(`Failed to save: ${message}`, 'error');
    } finally {
      setSaving(false);
    }
  };

  if (!loaded && !error) {
    return <div className="text-sm text-gray-500">Loading judge settings…</div>;
  }
  if (error) {
    return <div className="text-sm text-red-600">Failed to load: {error}</div>;
  }

  return (
    <div>
      <h2 className="text-lg font-semibold text-gray-900 mb-2">LLM judge backend</h2>
      <p className="text-sm text-gray-500 mb-4">
        Controls how slide verification scores slides against tool/source data.{' '}
        <strong>MLflow</strong> logs Evaluation Runs in MLflow (requires MLflow tracking and may use
        regional Databricks storage). <strong>Direct</strong> calls the model endpoint only via
        ChatDatabricks (no MLflow Evaluation Run; use when egress to storage hosts is blocked). When
        Direct is saved, Tellr also skips MLflow <code>start_span</code> around Genie/chat slide
        generation so tool runs do not upload trace artifacts to regional storage (set{' '}
        <code>TELLR_MLFLOW_DISABLE_AGENT_SPANS=0</code> to keep agent spans while using Direct
        verification).
      </p>
      <fieldset className="rounded border border-gray-200 bg-white p-4 space-y-3">
        <legend className="sr-only">Choose judge backend</legend>
        <label className="flex items-start gap-3 cursor-pointer">
          <input
            type="radio"
            name="judge-backend"
            className="mt-1"
            checked={backend === 'mlflow'}
            onChange={() => setBackend('mlflow')}
            data-testid="judge-backend-mlflow"
          />
          <span>
            <span className="font-medium text-gray-900">MLflow LLM judge</span>
            <span className="block text-xs text-gray-500 mt-0.5">
              Default — uses mlflow.genai.evaluate and your per-session experiment (Evaluation
              Runs).
            </span>
          </span>
        </label>
        <label className="flex items-start gap-3 cursor-pointer">
          <input
            type="radio"
            name="judge-backend"
            className="mt-1"
            checked={backend === 'direct'}
            onChange={() => setBackend('direct')}
            data-testid="judge-backend-direct"
          />
          <span>
            <span className="font-medium text-gray-900">Direct ChatDatabricks judge</span>
            <span className="block text-xs text-gray-500 mt-0.5">
              Same green / amber / red / unknown rules; calls the model endpoint only (no MLflow
              Evaluation Run; run_id empty). Use when egress to regional storage is blocked or
              MLflow evaluate is unreliable.
            </span>
          </span>
        </label>
      </fieldset>
      <div className="mt-4">
        <button
          type="button"
          onClick={() => void handleSave()}
          disabled={saving}
          className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-blue-300"
          data-testid="judge-backend-save"
        >
          {saving ? 'Saving…' : 'Save'}
        </button>
      </div>
    </div>
  );
};

/**
 * Admin API (app-wide settings under /api/admin).
 */

const API_BASE_URL = import.meta.env.VITE_API_URL || (
  import.meta.env.MODE === 'production' ? '' : 'http://127.0.0.1:8000'
);

const ADMIN_BASE = `${API_BASE_URL}/api/admin`;

export type LlmJudgeBackend = 'mlflow' | 'direct';

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers || {}),
    },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export const adminApi = {
  getJudgeBackend: (): Promise<{ backend: LlmJudgeBackend }> =>
    fetchJson(`${ADMIN_BASE}/judge-backend`),

  setJudgeBackend: (backend: LlmJudgeBackend): Promise<{ backend: LlmJudgeBackend }> =>
    fetchJson(`${ADMIN_BASE}/judge-backend`, {
      method: 'PUT',
      body: JSON.stringify({ backend }),
    }),
};

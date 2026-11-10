/**
 * Admin API (app-wide settings under /api/admin).
 */

const API_BASE_URL = import.meta.env.VITE_API_URL || (
  import.meta.env.MODE === 'production' ? '' : 'http://127.0.0.1:8000'
);

const ADMIN_BASE = `${API_BASE_URL}/api/admin`;

export type LlmJudgeBackend = 'mlflow' | 'direct';

function errorMessage(status: number, statusText: string, text: string): string {
  if (text) {
    try {
      const body: unknown = JSON.parse(text);
      const detail = (body as { detail?: unknown } | null)?.detail;
      if (typeof detail === 'string' && detail) return detail;
      if (Array.isArray(detail)) {
        const msgs = detail
          .map(d => (d && typeof (d as { msg?: unknown }).msg === 'string' ? (d as { msg: string }).msg : ''))
          .filter(Boolean);
        return msgs.length > 0 ? msgs.join('; ') : `Request rejected (${status})`;
      }
      if (detail !== undefined) return `Request rejected (${status})`;
    } catch {
      // Not JSON: fall through to the raw text.
    }
    return text;
  }
  return `${status} ${statusText}`;
}

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
    throw new Error(errorMessage(res.status, res.statusText, text));
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export type AdminSource = 'can_manage_sync' | 'manual';

export interface AppAdminEntry {
  identity_type: 'USER' | 'GROUP';
  identity_name: string;
  identity_id: string | null;
  sources: AdminSource[];
  manual_permission_id: number | null;
  added_by: string | null;
  added_at: string | null;
}

export interface AdminSyncStatus {
  last_attempt_at: string | null;
  last_success_at: string | null;
  last_error: string | null;
}

export interface AppAdminsResponse {
  admins: AppAdminEntry[];
  sync: AdminSyncStatus;
}

export const adminApi = {
  getJudgeBackend: (): Promise<{ backend: LlmJudgeBackend }> =>
    fetchJson(`${ADMIN_BASE}/judge-backend`),

  setJudgeBackend: (backend: LlmJudgeBackend): Promise<{ backend: LlmJudgeBackend }> =>
    fetchJson(`${ADMIN_BASE}/judge-backend`, {
      method: 'PUT',
      body: JSON.stringify({ backend }),
    }),

  getGenieOneDefault: (): Promise<{ enabled: boolean }> =>
    fetchJson(`${ADMIN_BASE}/genie-one-default`),

  setGenieOneDefault: (enabled: boolean): Promise<{ enabled: boolean }> =>
    fetchJson(`${ADMIN_BASE}/genie-one-default`, {
      method: 'PUT',
      body: JSON.stringify({ enabled }),
    }),

  getImageGeneration: (): Promise<{ available: boolean; enabled: boolean }> =>
    fetchJson(`${ADMIN_BASE}/image-generation`),

  setImageGeneration: (enabled: boolean): Promise<{ available: boolean; enabled: boolean }> =>
    fetchJson(`${ADMIN_BASE}/image-generation`, {
      method: 'PUT',
      body: JSON.stringify({ enabled }),
    }),

  listAdmins: (): Promise<AppAdminsResponse> => fetchJson(`${ADMIN_BASE}/admins`),

  addAdmin: (body: {
    identity_type: 'USER' | 'GROUP';
    identity_name: string;
    identity_id: string | null;
  }): Promise<{ permission_id: number }> =>
    fetchJson(`${ADMIN_BASE}/admins`, { method: 'POST', body: JSON.stringify(body) }),

  removeAdmin: (permissionId: number): Promise<void> =>
    fetchJson(`${ADMIN_BASE}/admins/${permissionId}`, { method: 'DELETE' }),
};

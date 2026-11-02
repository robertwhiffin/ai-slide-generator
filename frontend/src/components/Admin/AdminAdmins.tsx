import React, { useCallback, useEffect, useState } from 'react';
import { FiLock, FiUser, FiUsers } from 'react-icons/fi';
import { adminApi } from '../../api/admin';
import type { AdminSource, AdminSyncStatus, AppAdminEntry } from '../../api/admin';
import { configApi } from '../../api/config';
import type { Identity } from '../../api/config';
import { useToast } from '../../contexts/ToastContext';

const AMBER_COPY =
  "Tellr can't read this app's permissions. Run tellr.update to grant the app access.";
const LOCK_TITLE = "Change this in the app's Permissions in Databricks";

const BADGES: Record<AdminSource, { label: string; className: string }> = {
  can_manage_sync: { label: 'CAN_MANAGE on app', className: 'bg-indigo-50 text-indigo-800' },
  manual: { label: 'Added in Tellr', className: 'bg-amber-100 text-amber-800' },
};

function formatAge(iso: string): string {
  const minutes = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 60000));
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes} min ago`;
  return `${Math.floor(minutes / 60)} h ago`;
}

function formatDay(iso: string): string {
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
}

const SyncStatus: React.FC<{ sync: AdminSyncStatus }> = ({ sync }) => {
  const ok = Boolean(sync.last_success_at) && !sync.last_error;
  return (
    <div
      data-testid="admin-sync-status"
      data-state={ok ? 'ok' : 'warn'}
      className={`mb-4 rounded-md border px-3 py-2 text-xs ${
        ok
          ? 'border-green-200 bg-green-50 text-green-800'
          : 'border-amber-200 bg-amber-50 text-amber-800'
      }`}
    >
      {ok && sync.last_success_at ? (
        <>Synced from app permissions {formatAge(sync.last_success_at)}</>
      ) : (
        <>
          <div>{AMBER_COPY}</div>
          {sync.last_error && <div className="mt-1 font-mono text-[11px]">{sync.last_error}</div>}
        </>
      )}
    </div>
  );
};

export const AdminAdmins: React.FC = () => {
  const { showToast } = useToast();
  const [admins, setAdmins] = useState<AppAdminEntry[]>([]);
  const [sync, setSync] = useState<AdminSyncStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<Identity[]>([]);
  const [selected, setSelected] = useState<Identity | null>(null);
  const [adding, setAdding] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await adminApi.listAdmins();
      setAdmins(res.admins);
      setSync(res.sync);
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      showToast(`Failed to load admins: ${message}`, 'error');
    } finally {
      setLoading(false);
    }
  }, [showToast]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const q = query.trim();
    if (q.length < 2) {
      setResults([]);
      return;
    }
    let cancelled = false;
    const timer = setTimeout(() => {
      configApi
        .searchIdentities(q)
        .then(res => {
          if (!cancelled) setResults(res.identities);
        })
        .catch(err => {
          console.error('Identity search failed:', err);
          if (!cancelled) setResults([]);
        });
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [query]);

  const pick = (identity: Identity) => {
    setSelected(identity);
    setQuery('');
    setResults([]);
  };

  const handleAdd = async () => {
    if (!selected) return;
    setAdding(true);
    try {
      await adminApi.addAdmin({
        identity_type: selected.type === 'GROUP' ? 'GROUP' : 'USER',
        identity_name:
          selected.type === 'GROUP'
            ? selected.display_name
            : (selected.user_name ?? selected.display_name),
        identity_id: selected.id,
      });
      setSelected(null);
      await load();
      showToast('Admin added', 'success');
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      showToast(`Failed to add admin: ${message}`, 'error');
    } finally {
      setAdding(false);
    }
  };

  const handleRemove = async (entry: AppAdminEntry) => {
    if (entry.manual_permission_id == null) return;
    try {
      await adminApi.removeAdmin(entry.manual_permission_id);
      await load();
      showToast('Admin removed', 'success');
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      showToast(`Failed to remove admin: ${message}`, 'error');
    }
  };

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-6">
      <h2 className="text-lg font-semibold text-gray-900">Admins</h2>
      <p className="mb-4 mt-1 text-sm text-gray-500">
        Admins can open this page. Anyone with CAN_MANAGE on the app is an admin automatically;
        you can also add users and groups here.
      </p>

      {sync && <SyncStatus sync={sync} />}

      <div className="mb-4">
        <div className="flex gap-2">
          <input
            type="text"
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Search users or groups to make admin…"
            aria-label="Search users or groups to make admin"
            className="flex-1 rounded border border-gray-300 px-3 py-1.5 text-sm"
          />
          <button
            type="button"
            onClick={() => void handleAdd()}
            disabled={!selected || adding}
            className="rounded bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Add admin
          </button>
        </div>
        {selected && (
          <div className="mt-2 text-xs text-gray-600">
            Selected: <span className="font-medium">{selected.user_name ?? selected.display_name}</span>
            {selected.type === 'GROUP' && ' (group)'}
          </div>
        )}
        {results.length > 0 && (
          <ul className="mt-2 max-h-48 overflow-auto rounded border border-gray-200">
            {results.map(r => (
              <li key={`${r.type}-${r.id}`}>
                <button
                  type="button"
                  onClick={() => pick(r)}
                  className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-gray-50"
                >
                  {r.type === 'GROUP' ? <FiUsers className="text-gray-500" /> : <FiUser className="text-gray-500" />}
                  <span>{r.display_name}</span>
                  {r.user_name && r.user_name !== r.display_name && (
                    <span className="text-xs text-gray-400">{r.user_name}</span>
                  )}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {loading ? (
        <div className="text-sm text-gray-500">Loading…</div>
      ) : (
        <div>
          {admins.map(entry => {
            const manual = entry.manual_permission_id != null;
            return (
              <div
                key={`${entry.identity_type}-${entry.identity_name}`}
                data-testid={`admin-row-${entry.identity_type}-${entry.identity_name}`}
                className="flex items-center gap-2 border-b border-gray-100 px-1 py-2 text-sm"
              >
                <span className="w-4 text-gray-500">
                  {entry.identity_type === 'GROUP' ? <FiUsers /> : <FiUser />}
                </span>
                <span className="flex-1">
                  {entry.identity_name}
                  {entry.identity_type === 'GROUP' && (
                    <small className="block text-[10px] text-gray-400">group</small>
                  )}
                  {manual && entry.added_by && entry.added_at && (
                    <small className="block text-[10px] text-gray-400">
                      added by {entry.added_by} · {formatDay(entry.added_at)}
                    </small>
                  )}
                </span>
                {entry.sources.map(s => (
                  <span
                    key={s}
                    className={`whitespace-nowrap rounded-full px-2 py-0.5 text-[10px] ${BADGES[s].className}`}
                  >
                    {BADGES[s].label}
                  </span>
                ))}
                {manual ? (
                  <button
                    type="button"
                    aria-label={`Remove ${entry.identity_name}`}
                    onClick={() => void handleRemove(entry)}
                    className="w-14 text-right text-xs text-red-600 hover:text-red-800"
                  >
                    Remove
                  </button>
                ) : (
                  <span title={LOCK_TITLE} className="flex w-14 justify-end text-gray-400">
                    <FiLock />
                  </span>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

import React, { useState, useEffect, useCallback } from 'react';
import {
  ResponsiveContainer, LineChart, Line, BarChart, Bar,
  XAxis, YAxis, Tooltip, Legend, CartesianGrid, ReferenceLine,
} from 'recharts';
import { api } from '../../services/api';
import type {
  UsageSummary, UsageDailyRow, UsageTopUser,
  UsageFunnel, UsageRetentionRow, UsageHeatmap, UsageWindowParams,
} from '../../services/api';

const WINDOW_OPTIONS = [7, 14, 21, 28];
const DAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

/** Human label for the applied window, used in card/section titles. */
function windowLabel(w: UsageWindowParams): string {
  if (w.all) return 'all time';
  if (w.start && w.end) {
    const fmt = (d: string) =>
      new Date(d + 'T00:00:00').toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
    return `${fmt(w.start)} – ${fmt(w.end)}`;
  }
  return `${w.days ?? 7}d`;
}

export const UsageDashboard: React.FC = () => {
  // Applied window (drives fetches) vs. selector UI state
  const [window_, setWindow] = useState<UsageWindowParams>({ days: 7 });
  const [selectValue, setSelectValue] = useState('7');
  const [customStart, setCustomStart] = useState('');
  const [customEnd, setCustomEnd] = useState('');
  const [summary, setSummary] = useState<UsageSummary | null>(null);
  const [daily, setDaily] = useState<UsageDailyRow[]>([]);
  const [boundary, setBoundary] = useState<string | null>(null);
  const [topUsers, setTopUsers] = useState<UsageTopUser[]>([]);
  const [funnel, setFunnel] = useState<UsageFunnel | null>(null);
  const [retention, setRetention] = useState<UsageRetentionRow[]>([]);
  const [heatmap, setHeatmap] = useState<UsageHeatmap | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [s, d, t, f, r, h] = await Promise.all([
        api.getUsageSummary(window_),
        api.getUsageDaily(window_),
        api.getUsageTopUsers(window_),
        api.getUsageFunnel(window_),
        api.getUsageRetention(),
        api.getUsageHeatmap(window_),
      ]);
      setSummary(s);
      setDaily(d.days);
      setBoundary(d.history_boundary);
      setTopUsers(t);
      setFunnel(f);
      setRetention(r);
      setHeatmap(h);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load usage data');
    } finally {
      setLoading(false);
    }
  }, [window_]);

  useEffect(() => { loadAll(); }, [loadAll]);

  const onSelectWindow = (value: string) => {
    setSelectValue(value);
    if (value === 'all') {
      setWindow({ all: true });
    } else if (value !== 'custom') {
      setWindow({ days: Number(value) });
    }
    // 'custom' waits for Apply
  };

  const applyCustomRange = () => {
    if (customStart && customEnd && customStart <= customEnd) {
      setWindow({ start: customStart, end: customEnd });
    }
  };

  const label = windowLabel(window_);
  const hasProxyDays = daily.some((r) => r.logins_proxy);
  const formatDate = (d: string) =>
    new Date(d + 'T00:00:00').toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
  const formatTooltipLabel = (label: React.ReactNode) =>
    typeof label === 'string' ? formatDate(label) : label;

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-gray-900">Usage</h2>
          <p className="text-sm text-gray-500">Who is using Tellr and how.</p>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          <label htmlFor="usage-window" className="text-sm text-gray-600">Window:</label>
          <select
            id="usage-window"
            value={selectValue}
            onChange={(e) => onSelectWindow(e.target.value)}
            className="text-sm border border-gray-300 rounded px-2 py-1"
          >
            {WINDOW_OPTIONS.map((d) => <option key={d} value={String(d)}>{d} days</option>)}
            <option value="all">All data</option>
            <option value="custom">Custom range…</option>
          </select>
          {selectValue === 'custom' && (
            <span className="flex items-center gap-1">
              <input
                type="date"
                aria-label="Range start"
                value={customStart}
                onChange={(e) => setCustomStart(e.target.value)}
                className="text-sm border border-gray-300 rounded px-2 py-1"
              />
              <span className="text-sm text-gray-500">to</span>
              <input
                type="date"
                aria-label="Range end"
                value={customEnd}
                onChange={(e) => setCustomEnd(e.target.value)}
                className="text-sm border border-gray-300 rounded px-2 py-1"
              />
              <button
                type="button"
                onClick={applyCustomRange}
                disabled={!customStart || !customEnd || customStart > customEnd}
                className="text-sm px-3 py-1 rounded bg-blue-600 text-white disabled:opacity-40"
              >
                Apply
              </button>
            </span>
          )}
        </div>
      </div>

      {loading && <p className="text-sm text-gray-500">Loading usage data...</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}

      {!loading && !error && summary && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
            <StatCard label="Total Users Ever" value={String(summary.total_users_ever)} />
            <StatCard label="Total Decks Ever" value={String(summary.total_decks_ever)} />
            <StatCard label={`Active Users (${label})`} value={String(summary.window.active_users)} />
            <StatCard label={`Decks (${label})`} value={String(summary.window.decks_created)} />
            <StatCard
              label="Decks / Active User"
              value={summary.window.avg_decks_per_active_user !== null
                ? String(summary.window.avg_decks_per_active_user) : '-'}
            />
            <StatCard label={`Logins (${label})`} value={String(summary.window.logins)} />
          </div>

          <ChartSection
            title="Daily Logins"
            subtitle={hasProxyDays
              ? 'Days before event tracking (left of the marked line) use sessions-created as a proxy.'
              : undefined}
          >
            <ResponsiveContainer width="100%" height={260}>
              <LineChart data={daily}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                <XAxis dataKey="date" tickFormatter={formatDate} fontSize={12} />
                <YAxis allowDecimals={false} fontSize={12} />
                <Tooltip labelFormatter={formatTooltipLabel} />
                <Line type="monotone" dataKey="logins" stroke="#2563eb" strokeWidth={2} dot={false} name="Logins" />
                {boundary && (
                  <ReferenceLine x={boundary} stroke="#9ca3af" strokeDasharray="4 4"
                    label={{ value: 'event tracking enabled', fontSize: 11, fill: '#6b7280' }} />
                )}
              </LineChart>
            </ResponsiveContainer>
          </ChartSection>

          <ChartSection title="Daily Distinct Users (new vs returning)">
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={daily}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                <XAxis dataKey="date" tickFormatter={formatDate} fontSize={12} />
                <YAxis allowDecimals={false} fontSize={12} />
                <Tooltip labelFormatter={formatTooltipLabel} />
                <Legend />
                <Bar dataKey="returning_users" stackId="u" fill="#2563eb" name="Returning" />
                <Bar dataKey="new_users" stackId="u" fill="#10b981" name="New" />
              </BarChart>
            </ResponsiveContainer>
          </ChartSection>

          <ChartSection title="Decks Generated per Day">
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={daily}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                <XAxis dataKey="date" tickFormatter={formatDate} fontSize={12} />
                <YAxis allowDecimals={false} fontSize={12} />
                <Tooltip labelFormatter={formatTooltipLabel} />
                <Bar dataKey="decks_created" fill="#7c3aed" name="Decks" />
              </BarChart>
            </ResponsiveContainer>
          </ChartSection>

          {funnel && (
            <ChartSection
              title={`Funnel (${label})`}
              subtitle={funnel.proxy ? 'No login events in window — using session creations as proxy.' : undefined}
            >
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <StatCard label="Logins" value={String(funnel.logins)} />
                <StatCard label="Users Logged In" value={String(funnel.users_who_logged_in)} />
                <StatCard label="Users Created a Deck" value={String(funnel.users_who_created_deck)} />
                <StatCard label="Decks Created" value={String(funnel.decks_created)} />
              </div>
            </ChartSection>
          )}

          <ChartSection title={`Top Users (${label})`}>
            {topUsers.length === 0
              ? <p className="text-sm text-gray-500">No user activity in this window.</p>
              : (
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-200 text-left text-gray-600">
                      <th className="pb-2 pr-4 font-medium">User</th>
                      <th className="pb-2 pr-4 font-medium text-right">Logins</th>
                      <th className="pb-2 pr-4 font-medium text-right">Sessions</th>
                      <th className="pb-2 font-medium text-right">Decks</th>
                    </tr>
                  </thead>
                  <tbody>
                    {topUsers.map((u) => (
                      <tr key={u.username} className="border-b border-gray-100">
                        <td className="py-2 pr-4 text-gray-800">{u.username}</td>
                        <td className="py-2 pr-4 text-right text-gray-700">{u.logins}</td>
                        <td className="py-2 pr-4 text-right text-gray-700">{u.sessions_created}</td>
                        <td className="py-2 text-right text-gray-700">{u.decks_created}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
          </ChartSection>

          <ChartSection title="Weekly Retention (last 8 weeks)">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200 text-left text-gray-600">
                  <th className="pb-2 pr-4 font-medium">Week</th>
                  <th className="pb-2 pr-4 font-medium text-right">Active Users</th>
                  <th className="pb-2 pr-4 font-medium text-right">Retained</th>
                  <th className="pb-2 font-medium text-right">Retention %</th>
                </tr>
              </thead>
              <tbody>
                {retention.map((w) => (
                  <tr key={w.week_start} className="border-b border-gray-100">
                    <td className="py-2 pr-4 text-gray-800">{formatDate(w.week_start)}</td>
                    <td className="py-2 pr-4 text-right text-gray-700">{w.active_users}</td>
                    <td className="py-2 pr-4 text-right text-gray-700">{w.retained_from_prev ?? '-'}</td>
                    <td className="py-2 text-right text-gray-700">
                      {w.retention_pct !== null ? `${w.retention_pct}%` : '-'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </ChartSection>

          {heatmap && (
            <ChartSection title={`Activity Heatmap (${label}, UTC)`}>
              <div className="overflow-x-auto">
                <table className="text-xs border-collapse">
                  <thead>
                    <tr>
                      <th className="pr-2 text-left text-gray-500 font-normal" />
                      {Array.from({ length: 24 }, (_, h) => (
                        <th key={h} className="px-1 text-gray-400 font-normal">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {heatmap.matrix.map((row, dayIdx) => (
                      <tr key={dayIdx}>
                        <td className="pr-2 text-gray-500">{DAY_LABELS[dayIdx]}</td>
                        {row.map((count, hour) => (
                          <td
                            key={hour}
                            title={`${DAY_LABELS[dayIdx]} ${hour}:00 — ${count} events`}
                            className="w-5 h-5 border border-white rounded-sm"
                            style={{
                              backgroundColor: count === 0
                                ? '#f3f4f6'
                                : `rgba(37, 99, 235, ${0.15 + 0.85 * (count / Math.max(heatmap.max, 1))})`,
                            }}
                          />
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </ChartSection>
          )}
        </>
      )}
    </div>
  );
};

const StatCard: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4">
    <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">{label}</p>
    <p className="mt-1 text-xl font-semibold text-gray-900">{value}</p>
  </div>
);

const ChartSection: React.FC<{ title: string; subtitle?: string; children: React.ReactNode }> = (
  { title, subtitle, children },
) => (
  <section className="bg-white rounded-lg shadow-sm border border-gray-200">
    <div className="px-6 py-4 border-b border-gray-200">
      <h3 className="text-base font-semibold text-gray-900">{title}</h3>
      {subtitle && <p className="text-xs text-gray-500 mt-0.5">{subtitle}</p>}
    </div>
    <div className="p-6">{children}</div>
  </section>
);

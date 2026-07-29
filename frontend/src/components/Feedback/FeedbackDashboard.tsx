import React, { useState, useEffect, useCallback } from 'react';
import { api, type FeedbackItem } from '../../services/api';

const CATEGORIES = ['Bug Report', 'Feature Request', 'UX Issue', 'Performance', 'Content Quality', 'Other'];
const SEVERITIES = ['Low', 'Medium', 'High'];
const PAGE_SIZE = 20;

interface WeekStats {
  week_start: string;
  week_end: string;
  responses: number;
  avg_star_rating: number | null;
  avg_nps_score: number | null;
  total_time_saved_minutes: number;
  time_saved_display: string;
}

interface Totals {
  total_responses: number;
  avg_star_rating: number | null;
  avg_nps_score: number | null;
  total_time_saved_minutes: number;
  time_saved_display: string;
}

interface Usage {
  total_sessions: number;
  distinct_users: number;
}

interface FeedbackSummary {
  period: string;
  feedback_count: number;
  summary: string;
  category_breakdown: Record<string, number>;
  top_themes: string[];
}

export const FeedbackDashboard: React.FC = () => {
  const [weeks, setWeeks] = useState<WeekStats[]>([]);
  const [totals, setTotals] = useState<Totals | null>(null);
  const [usage, setUsage] = useState<Usage | null>(null);
  const [summary, setSummary] = useState<FeedbackSummary | null>(null);
  const [statsLoading, setStatsLoading] = useState(true);
  const [summaryLoading, setSummaryLoading] = useState(true);
  const [statsError, setStatsError] = useState<string | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [statsWeeks, setStatsWeeks] = useState(12);
  const [summaryWeeks, setSummaryWeeks] = useState(4);

  const [items, setItems] = useState<FeedbackItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [category, setCategory] = useState('');
  const [severity, setSeverity] = useState('');
  const [browserWeeks, setBrowserWeeks] = useState(12);
  const [browserLoading, setBrowserLoading] = useState(true);
  const [browserError, setBrowserError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [summaryOpen, setSummaryOpen] = useState(false);
  const [summaryLoaded, setSummaryLoaded] = useState(false);

  const loadStats = useCallback(async () => {
    setStatsLoading(true);
    setStatsError(null);
    try {
      const data = await api.getReportStats(statsWeeks);
      setWeeks(data.weeks);
      setTotals(data.totals);
      setUsage(data.usage);
    } catch (err) {
      setStatsError(err instanceof Error ? err.message : 'Failed to load stats');
    } finally {
      setStatsLoading(false);
    }
  }, [statsWeeks]);

  const loadSummary = useCallback(async () => {
    setSummaryLoading(true);
    setSummaryError(null);
    try {
      const data = await api.getReportSummary(summaryWeeks);
      setSummary(data);
    } catch (err) {
      setSummaryError(err instanceof Error ? err.message : 'Failed to load summary');
    } finally {
      setSummaryLoading(false);
    }
  }, [summaryWeeks]);

  const loadFeedback = useCallback(async () => {
    setBrowserLoading(true);
    setBrowserError(null);
    try {
      const data = await api.listFeedback({
        weeks: browserWeeks,
        category: category || undefined,
        severity: severity || undefined,
        page,
        pageSize: PAGE_SIZE,
      });
      setItems(data.items);
      setTotal(data.total);
    } catch (err) {
      setBrowserError(err instanceof Error ? err.message : 'Failed to load feedback');
    } finally {
      setBrowserLoading(false);
    }
  }, [browserWeeks, category, severity, page]);

  useEffect(() => { loadStats(); }, [loadStats]);
  useEffect(() => { loadFeedback(); }, [loadFeedback]);
  // Reset to page 1 when filters change
  useEffect(() => { setPage(1); }, [browserWeeks, category, severity]);
  // The AI summary is expensive: load it only after first expand (summaryLoaded),
  // and reload when summaryWeeks changes (via loadSummary identity).
  useEffect(() => { if (summaryLoaded) loadSummary(); }, [loadSummary, summaryLoaded]);

  const openSummary = () => {
    setSummaryOpen((open) => !open);
    if (!summaryLoaded) {
      setSummaryLoaded(true); // triggers the gated effect above to load the summary
    }
  };

  /** If the summary field is a JSON string, parse out the text and themes. */
  const parsedSummary = (() => {
    if (!summary) return null;
    let text = summary.summary;
    let themes = summary.top_themes;
    if (typeof text === 'string' && text.trimStart().startsWith('{')) {
      try {
        const inner = JSON.parse(text);
        text = inner.summary ?? text;
        if (Array.isArray(inner.top_themes) && inner.top_themes.length > 0) {
          themes = inner.top_themes;
        }
      } catch { /* use as-is */ }
    }
    return { ...summary, summary: text, top_themes: themes };
  })();

  const formatDate = (dateStr: string) => {
    const d = new Date(dateStr + 'T00:00:00');
    return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
  };

  const npsLabel = (score: number | null) => {
    if (score === null) return '-';
    if (score >= 9) return `${score} (Promoter)`;
    if (score >= 7) return `${score} (Passive)`;
    return `${score} (Detractor)`;
  };

  return (
    <div className="max-w-6xl mx-auto p-6 space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Feedback Dashboard</h1>
        <p className="text-sm text-gray-500 mt-1">Survey responses and feedback summary from the reporting API.</p>
      </div>

      {/* Totals Cards */}
      {totals && !statsLoading && (
        <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
          <StatCard label="Distinct Users" value={usage ? String(usage.distinct_users) : '-'} />
          <StatCard label="Total Sessions" value={usage ? String(usage.total_sessions) : '-'} />
          <StatCard label="Survey Responses" value={String(totals.total_responses)} />
          <StatCard label="Avg Star Rating" value={totals.avg_star_rating !== null ? `${totals.avg_star_rating} / 5` : '-'} />
          <StatCard label="Avg NPS Score" value={totals.avg_nps_score !== null ? npsLabel(totals.avg_nps_score) : '-'} />
          <StatCard label="Total Time Saved" value={totals.time_saved_display || '-'} />
        </div>
      )}

      {/* Weekly Stats */}
      <section className="bg-white rounded-lg shadow-sm border border-gray-200">
        <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-gray-900">Weekly Survey Stats</h2>
          <div className="flex items-center gap-2">
            <label htmlFor="stats-weeks" className="text-sm text-gray-600">Weeks:</label>
            <select
              id="stats-weeks"
              value={statsWeeks}
              onChange={(e) => setStatsWeeks(Number(e.target.value))}
              className="text-sm border border-gray-300 rounded px-2 py-1"
            >
              {[4, 8, 12, 26, 52].map(w => (
                <option key={w} value={w}>{w}</option>
              ))}
            </select>
          </div>
        </div>

        <div className="p-6">
          {statsLoading && <p className="text-sm text-gray-500">Loading stats...</p>}
          {statsError && <p className="text-sm text-red-600">{statsError}</p>}

          {!statsLoading && !statsError && weeks.length === 0 && (
            <p className="text-sm text-gray-500">No survey data yet.</p>
          )}

          {!statsLoading && !statsError && weeks.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-200 text-left text-gray-600">
                    <th className="pb-2 pr-4 font-medium">Week</th>
                    <th className="pb-2 pr-4 font-medium text-right">Responses</th>
                    <th className="pb-2 pr-4 font-medium text-right">Avg Stars</th>
                    <th className="pb-2 pr-4 font-medium text-right">Avg NPS</th>
                    <th className="pb-2 font-medium text-right">Time Saved</th>
                  </tr>
                </thead>
                <tbody>
                  {weeks.map((w) => (
                    <tr key={w.week_start} className="border-b border-gray-100">
                      <td className="py-2 pr-4 text-gray-800">
                        {formatDate(w.week_start)} – {formatDate(w.week_end)}
                      </td>
                      <td className="py-2 pr-4 text-right text-gray-700">{w.responses}</td>
                      <td className="py-2 pr-4 text-right text-gray-700">
                        {w.avg_star_rating !== null ? w.avg_star_rating.toFixed(1) : '-'}
                      </td>
                      <td className="py-2 pr-4 text-right text-gray-700">
                        {w.avg_nps_score !== null ? w.avg_nps_score.toFixed(1) : '-'}
                      </td>
                      <td className="py-2 text-right text-gray-700">{w.time_saved_display || '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </section>

      {/* Raw Feedback Browser */}
      <section className="bg-white rounded-lg shadow-sm border border-gray-200">
        <div className="px-6 py-4 border-b border-gray-200 flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-lg font-semibold text-gray-900">Feedback Browser</h2>
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <select value={category} onChange={(e) => setCategory(e.target.value)}
              className="border border-gray-300 rounded px-2 py-1" aria-label="Filter by category">
              <option value="">All categories</option>
              {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
            <select value={severity} onChange={(e) => setSeverity(e.target.value)}
              className="border border-gray-300 rounded px-2 py-1" aria-label="Filter by severity">
              <option value="">All severities</option>
              {SEVERITIES.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
            <select value={browserWeeks} onChange={(e) => setBrowserWeeks(Number(e.target.value))}
              className="border border-gray-300 rounded px-2 py-1" aria-label="Weeks window">
              {[4, 8, 12, 26, 52].map((w) => <option key={w} value={w}>{w} weeks</option>)}
            </select>
          </div>
        </div>

        <div className="p-6">
          {browserLoading && <p className="text-sm text-gray-500">Loading feedback...</p>}
          {browserError && <p className="text-sm text-red-600">{browserError}</p>}
          {!browserLoading && !browserError && items.length === 0 && (
            <p className="text-sm text-gray-500">No feedback in this window.</p>
          )}

          {!browserLoading && !browserError && items.length > 0 && (
            <>
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-200 text-left text-gray-600">
                    <th className="pb-2 pr-4 font-medium">Date</th>
                    <th className="pb-2 pr-4 font-medium">Category</th>
                    <th className="pb-2 pr-4 font-medium">Severity</th>
                    <th className="pb-2 font-medium">Summary</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((item) => (
                    <React.Fragment key={item.id}>
                      <tr
                        className="border-b border-gray-100 cursor-pointer hover:bg-gray-50"
                        onClick={() => setExpandedId(expandedId === item.id ? null : item.id)}
                      >
                        <td className="py-2 pr-4 text-gray-700 whitespace-nowrap align-top">
                          {new Date(item.created_at).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })}
                        </td>
                        <td className="py-2 pr-4 align-top">
                          <span className="inline-block px-2 py-0.5 rounded-full text-xs font-medium bg-blue-50 text-blue-700">
                            {item.category}
                          </span>
                        </td>
                        <td className="py-2 pr-4 align-top">
                          <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${
                            item.severity === 'High' ? 'bg-red-50 text-red-700'
                              : item.severity === 'Medium' ? 'bg-amber-50 text-amber-700'
                              : 'bg-gray-100 text-gray-600'
                          }`}>
                            {item.severity}
                          </span>
                        </td>
                        <td className="py-2 text-gray-800 align-top">{item.summary}</td>
                      </tr>
                      {expandedId === item.id && (
                        <tr className="border-b border-gray-100 bg-gray-50">
                          <td colSpan={4} className="p-4">
                            <h4 className="text-xs font-medium text-gray-500 uppercase mb-2">Full conversation</h4>
                            <div className="space-y-2">
                              {item.raw_conversation.map((msg, i) => (
                                <div key={i} className={`text-sm rounded-lg px-3 py-2 max-w-3xl ${
                                  msg.role === 'user' ? 'bg-blue-50 text-blue-900' : 'bg-white border border-gray-200 text-gray-700'
                                }`}>
                                  <span className="text-xs font-semibold uppercase text-gray-400 mr-2">{msg.role}</span>
                                  {msg.content}
                                </div>
                              ))}
                            </div>
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  ))}
                </tbody>
              </table>

              <div className="flex items-center justify-between mt-4 text-sm text-gray-600">
                <span>{total} item{total === 1 ? '' : 's'}</span>
                <div className="flex items-center gap-2">
                  <button
                    disabled={page <= 1}
                    onClick={() => setPage((p) => p - 1)}
                    className="px-3 py-1 border border-gray-300 rounded disabled:opacity-40"
                  >
                    Previous
                  </button>
                  <span>Page {page} of {Math.max(1, Math.ceil(total / PAGE_SIZE))}</span>
                  <button
                    disabled={page >= Math.ceil(total / PAGE_SIZE)}
                    onClick={() => setPage((p) => p + 1)}
                    className="px-3 py-1 border border-gray-300 rounded disabled:opacity-40"
                  >
                    Next
                  </button>
                </div>
              </div>
            </>
          )}
        </div>
      </section>

      {/* AI Summary (collapsed by default; loads only on first expand) */}
      <section className="bg-white rounded-lg shadow-sm border border-gray-200">
        <button
          type="button"
          onClick={openSummary}
          className="w-full px-6 py-4 flex items-center justify-between text-left"
          aria-expanded={summaryOpen}
        >
          <h2 className="text-lg font-semibold text-gray-900">AI Summary (optional)</h2>
          <span className="text-gray-400 text-sm">{summaryOpen ? 'Hide' : 'Show'}</span>
        </button>

        {summaryOpen && (
        <div className="px-6 pb-6 space-y-4 border-t border-gray-200 pt-4">
          <div className="flex items-center gap-2">
            <label htmlFor="summary-weeks" className="text-sm text-gray-600">Weeks:</label>
            <select
              id="summary-weeks"
              value={summaryWeeks}
              onChange={(e) => setSummaryWeeks(Number(e.target.value))}
              className="text-sm border border-gray-300 rounded px-2 py-1"
            >
              {[2, 4, 8, 12].map(w => (
                <option key={w} value={w}>{w}</option>
              ))}
            </select>
          </div>
          {summaryLoading && <p className="text-sm text-gray-500">Generating summary...</p>}
          {summaryError && <p className="text-sm text-red-600">{summaryError}</p>}

          {!summaryLoading && !summaryError && parsedSummary && (
            <>
              <div className="flex items-center gap-4 text-sm text-gray-500">
                <span>Period: {parsedSummary.period}</span>
                <span>Feedback items: {parsedSummary.feedback_count}</span>
              </div>

              <p className="text-gray-800 leading-relaxed">{parsedSummary.summary}</p>

              {parsedSummary.top_themes.length > 0 && (
                <div>
                  <h3 className="text-sm font-medium text-gray-700 mb-2">Top Themes</h3>
                  <ul className="list-disc list-inside text-sm text-gray-700 space-y-1">
                    {parsedSummary.top_themes.map((theme, i) => (
                      <li key={i}>{theme}</li>
                    ))}
                  </ul>
                </div>
              )}

              {Object.keys(parsedSummary.category_breakdown).length > 0 && (
                <div>
                  <h3 className="text-sm font-medium text-gray-700 mb-2">Category Breakdown</h3>
                  <div className="flex flex-wrap gap-2">
                    {Object.entries(parsedSummary.category_breakdown)
                      .sort(([, a], [, b]) => b - a)
                      .map(([cat, count]) => (
                        <span
                          key={cat}
                          className="inline-flex items-center gap-1 px-3 py-1 rounded-full text-xs font-medium bg-blue-50 text-blue-700"
                        >
                          {cat} <span className="font-semibold">{count}</span>
                        </span>
                      ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
        )}
      </section>
    </div>
  );
};

const StatCard: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4">
    <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">{label}</p>
    <p className="mt-1 text-xl font-semibold text-gray-900">{value}</p>
  </div>
);

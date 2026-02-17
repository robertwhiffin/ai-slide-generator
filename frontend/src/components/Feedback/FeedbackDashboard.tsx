import React, { useState, useEffect, useCallback } from 'react';
import { api } from '../../services/api';

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
  const [summary, setSummary] = useState<FeedbackSummary | null>(null);
  const [statsLoading, setStatsLoading] = useState(true);
  const [summaryLoading, setSummaryLoading] = useState(true);
  const [statsError, setStatsError] = useState<string | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [statsWeeks, setStatsWeeks] = useState(12);
  const [summaryWeeks, setSummaryWeeks] = useState(4);

  const loadStats = useCallback(async () => {
    setStatsLoading(true);
    setStatsError(null);
    try {
      const data = await api.getReportStats(statsWeeks);
      setWeeks(data.weeks);
      setTotals(data.totals);
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

  useEffect(() => { loadStats(); }, [loadStats]);
  useEffect(() => { loadSummary(); }, [loadSummary]);

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
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <StatCard label="Avg Star Rating" value={totals.avg_star_rating !== null ? `${totals.avg_star_rating} / 5` : '-'} />
          <StatCard label="Avg NPS Score" value={totals.avg_nps_score !== null ? npsLabel(totals.avg_nps_score) : '-'} />
          <StatCard label="Total Time Saved" value={totals.time_saved_display || '-'} />
          <StatCard label="Total Responses" value={String(totals.total_responses)} />
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

      {/* AI Summary */}
      <section className="bg-white rounded-lg shadow-sm border border-gray-200">
        <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-gray-900">AI Feedback Summary</h2>
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
        </div>

        <div className="p-6 space-y-4">
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

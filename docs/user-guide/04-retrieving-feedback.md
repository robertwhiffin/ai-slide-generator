# Retrieving User Feedback

This guide explains how to access and analyse user feedback and satisfaction survey data collected by Tellr.

## Overview

Tellr collects two types of user feedback:

- **Feedback conversations** — Structured summaries from the AI feedback widget, categorised by type (Bug Report, Feature Request, UX Issue, Performance, Content Quality, Other) and severity (Low, Medium, High).
- **Survey responses** — Star ratings (1-5), time-saved estimates, and NPS scores (0-10) from the post-generation satisfaction survey.

Both are stored anonymously in the database and accessible via the reporting API.

## Prerequisites

- Access to the Tellr application (or direct API access)
- For direct API calls: a tool like `curl`, Postman, or a Python script

---

## Option 1: Weekly Stats Report

The stats endpoint returns weekly aggregated metrics, useful for dashboards and trend tracking.

### Request

```
GET /api/feedback/report/stats?weeks=12
```

The `weeks` parameter is optional and defaults to 12 (returns the last 12 weeks of data).

### Response

```json
{
  "weeks": [
    {
      "week_start": "2026-02-09T00:00:00",
      "avg_star_rating": 4.3,
      "avg_nps_score": 8.1,
      "total_time_saved_minutes": 960,
      "survey_count": 15,
      "feedback_count": 7
    }
  ],
  "totals": {
    "avg_star_rating": 4.2,
    "avg_nps_score": 7.8,
    "total_time_saved_minutes": 5400,
    "total_surveys": 87,
    "total_feedback": 34
  }
}
```

### Key Metrics

| Metric | Description | How to use it |
|--------|-------------|---------------|
| `avg_star_rating` | Average out of 5 | Overall satisfaction score |
| `avg_nps_score` | Average 0-10 | Net Promoter Score (detractors: 0-6, passives: 7-8, promoters: 9-10) |
| `total_time_saved_minutes` | Sum of self-reported time savings | Quantify productivity impact |
| `survey_count` | Number of survey submissions that week | Track engagement |
| `feedback_count` | Number of feedback conversations submitted | Track issue volume |

---

## Option 2: AI-Generated Feedback Summary

The summary endpoint uses an LLM to analyse recent feedback conversations and produce a narrative summary of themes, common issues, and suggestions.

### Request

```
GET /api/feedback/report/summary?weeks=4
```

The `weeks` parameter is optional and defaults to 4.

### Response

```json
{
  "summary": "Over the past 4 weeks, users submitted 12 feedback items. The most common theme was Feature Requests (5), primarily asking for template customisation options. Three Bug Reports mentioned text overflow on chart slides. Two UX Issues related to the profile switcher being hard to find. Overall sentiment is positive with users particularly appreciating the speed of generation.",
  "feedback_count": 12,
  "period_weeks": 4
}
```

---

## Option 3: Direct Database Queries

For advanced analysis, query the database tables directly.

### Feedback Conversations Table

```sql
SELECT category, severity, summary, created_at
FROM feedback_conversations
ORDER BY created_at DESC
LIMIT 50;
```

### Survey Responses Table

```sql
SELECT star_rating, time_saved_minutes, nps_score, created_at
FROM survey_responses
ORDER BY created_at DESC
LIMIT 50;
```

### Example: Monthly NPS Breakdown

```sql
SELECT
  DATE_TRUNC('month', created_at) AS month,
  COUNT(*) AS responses,
  ROUND(AVG(nps_score), 1) AS avg_nps,
  COUNT(CASE WHEN nps_score >= 9 THEN 1 END) AS promoters,
  COUNT(CASE WHEN nps_score BETWEEN 7 AND 8 THEN 1 END) AS passives,
  COUNT(CASE WHEN nps_score <= 6 THEN 1 END) AS detractors
FROM survey_responses
WHERE nps_score IS NOT NULL
GROUP BY DATE_TRUNC('month', created_at)
ORDER BY month DESC;
```

### Example: Feedback by Category

```sql
SELECT
  category,
  severity,
  COUNT(*) AS count
FROM feedback_conversations
GROUP BY category, severity
ORDER BY count DESC;
```

---

## Tips

- **Automate weekly reports** — Call `GET /api/feedback/report/stats` from a scheduled job and post results to Slack or email.
- **Track trends** — The `weeks` array in the stats response is chronologically ordered, making it easy to chart trends over time.
- **NPS calculation** — NPS = % Promoters (9-10) minus % Detractors (0-6). Use the direct SQL query for precise calculations.
- **Time savings ROI** — Multiply `total_time_saved_minutes` by an average hourly rate to quantify ROI in monetary terms.
- **Combine both endpoints** — Use the stats endpoint for numbers and the summary endpoint for qualitative insights in management reports.

## Related Guides

- [Generating Slides](./01-generating-slides.md) — The workflow that triggers the satisfaction survey
- [Advanced Configuration](./03-advanced-configuration.md) — Configure profiles and styles

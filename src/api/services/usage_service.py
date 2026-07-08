"""On-the-fly usage analytics for the admin dashboard.

All aggregation happens in Python over time-filtered queries. This is a
deliberate choice (small data, SQLite-compatible tests) mirroring
FeedbackService.get_stats_report.

History semantics: `usage_events` provides literal login/retrieval events
from its first row onward (`history_boundary`). Days before the boundary
use `user_sessions` as a labeled proxy.
"""

from collections import defaultdict
from datetime import datetime, timedelta
from datetime import time as dt_time

from sqlalchemy.orm import Session

from src.database.models import (
    AppIdentity,
    RequestLog,
    SessionSlideDeck,
    UsageEvent,
    UserSession,
)
from src.database.models.usage_event import (
    EVENT_DECK_CREATED,
    EVENT_DECK_RETRIEVED,
    EVENT_LOGIN,
)

ALLOWED_WINDOWS = {7, 14, 21, 28}

# Route template logged by the request-logging middleware for deck opens
_DECK_OPEN_ROUTE = "/api/sessions/{session_id}"


def _login_visit_count(events) -> int:
    """Collapse raw login events into visits: distinct (username, 30-min bucket).

    Dedup caches are per-worker, so one visit can write several login rows
    (one per uvicorn worker). Counting distinct 30-minute buckets per user
    reconstructs visit counts from raw rows, including historical ones.
    """
    buckets = set()
    for e in events:
        bucket = e.ts.replace(minute=(e.ts.minute // 30) * 30, second=0, microsecond=0)
        buckets.add((e.username, bucket))
    return len(buckets)


def _day_key(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%d")


def _window_start(days: int) -> datetime:
    """Midnight UTC at the start of the window (last `days` calendar days incl. today)."""
    today = datetime.utcnow().date()
    return datetime.combine(today - timedelta(days=days - 1), dt_time.min)


def _day_list(days: int) -> list[str]:
    today = datetime.utcnow().date()
    return [
        (today - timedelta(days=offset)).strftime("%Y-%m-%d")
        for offset in range(days - 1, -1, -1)
    ]


class UsageService:
    """Aggregates usage metrics for /api/admin/usage endpoints."""

    # ---------- shared helpers ----------

    def _events_in_window(self, db: Session, start: datetime) -> list[UsageEvent]:
        return db.query(UsageEvent).filter(UsageEvent.ts >= start).all()

    def _sessions_in_window(self, db: Session, start: datetime) -> list[UserSession]:
        return (
            db.query(UserSession)
            .filter(UserSession.created_at >= start)
            .all()
        )

    def _decks_in_window(self, db: Session, start: datetime) -> list[SessionSlideDeck]:
        return (
            db.query(SessionSlideDeck)
            .filter(SessionSlideDeck.created_at >= start)
            .all()
        )

    def _history_boundary(self, db: Session) -> datetime | None:
        first = (
            db.query(UsageEvent.ts)
            .filter(UsageEvent.event_type == EVENT_LOGIN)
            .order_by(UsageEvent.ts.asc())
            .first()
        )
        return first[0] if first else None

    def _first_seen_map(self, db: Session) -> dict[str, datetime]:
        """Earliest known appearance per username across all sources."""
        first_seen: dict[str, datetime] = {}

        def _merge(name, ts):
            if not name or ts is None:
                return
            if name not in first_seen or ts < first_seen[name]:
                first_seen[name] = ts

        for name, ts in db.query(
            AppIdentity.identity_name, AppIdentity.first_seen_at
        ).filter(AppIdentity.identity_type == "USER"):
            _merge(name, ts)
        for name, ts in db.query(UserSession.created_by, UserSession.created_at):
            _merge(name, ts)
        for name, ts in db.query(UsageEvent.username, UsageEvent.ts):
            _merge(name, ts)
        return first_seen

    # ---------- endpoints ----------

    def get_summary(self, db: Session, days: int) -> dict:
        start = _window_start(days)

        identity_users = {
            name
            for (name,) in db.query(AppIdentity.identity_name).filter(
                AppIdentity.identity_type == "USER"
            )
        }
        session_users = {
            name
            for (name,) in db.query(UserSession.created_by).filter(
                UserSession.created_by.isnot(None)
            )
        }
        total_users_ever = len(identity_users | session_users)

        live_deck_session_ids = {
            sid for (sid,) in db.query(SessionSlideDeck.session_id)
        }
        orphaned_deck_events = {
            sid
            for (sid,) in db.query(UsageEvent.session_id).filter(
                UsageEvent.event_type == EVENT_DECK_CREATED,
                UsageEvent.session_id.isnot(None),
            )
            if sid not in live_deck_session_ids
        }
        total_decks_ever = len(live_deck_session_ids) + len(orphaned_deck_events)

        events = self._events_in_window(db, start)
        sessions = self._sessions_in_window(db, start)
        active_from_last_activity = {
            name
            for (name,) in db.query(UserSession.created_by).filter(
                UserSession.last_activity >= start,
                UserSession.created_by.isnot(None),
            )
        }
        active_users = (
            {e.username for e in events}
            | {s.created_by for s in sessions if s.created_by}
            | active_from_last_activity
        )
        decks_created = (
            db.query(SessionSlideDeck)
            .filter(SessionSlideDeck.created_at >= start)
            .count()
        )
        logins = _login_visit_count(
            e for e in events if e.event_type == EVENT_LOGIN
        )

        avg = round(decks_created / len(active_users), 1) if active_users else None
        return {
            "total_users_ever": total_users_ever,
            "total_decks_ever": total_decks_ever,
            "window": {
                "days": days,
                "active_users": len(active_users),
                "decks_created": decks_created,
                "avg_decks_per_active_user": avg,
                "logins": logins,
            },
        }

    def get_daily(self, db: Session, days: int) -> dict:
        start = _window_start(days)
        boundary = self._history_boundary(db)
        boundary_day = _day_key(boundary) if boundary else None

        events = self._events_in_window(db, start)
        sessions = self._sessions_in_window(db, start)
        decks = self._decks_in_window(db, start)
        first_seen = self._first_seen_map(db)

        login_events_by_day: dict[str, list[UsageEvent]] = defaultdict(list)
        users_by_day: dict[str, set] = defaultdict(set)
        retrieved_by_day: dict[str, int] = defaultdict(int)
        for e in events:
            day = _day_key(e.ts)
            users_by_day[day].add(e.username)
            if e.event_type == EVENT_LOGIN:
                login_events_by_day[day].append(e)
            elif e.event_type == EVENT_DECK_RETRIEVED:
                retrieved_by_day[day] += 1
        # Collapse duplicate per-worker login rows into visits per day
        logins_by_day = {
            day: _login_visit_count(evts)
            for day, evts in login_events_by_day.items()
        }

        sessions_by_day: dict[str, int] = defaultdict(int)
        session_users_by_day: dict[str, set] = defaultdict(set)
        for s in sessions:
            day = _day_key(s.created_at)
            sessions_by_day[day] += 1
            if s.created_by:
                session_users_by_day[day].add(s.created_by)

        decks_by_day: dict[str, int] = defaultdict(int)
        for d in decks:
            decks_by_day[_day_key(d.created_at)] += 1

        # Anonymous deck-open volume proxy from request_logs (30-day retention)
        proxy_retrievals_by_day: dict[str, int] = defaultdict(int)
        for (ts,) in db.query(RequestLog.timestamp).filter(
            RequestLog.timestamp >= start,
            RequestLog.method == "GET",
            RequestLog.path == _DECK_OPEN_ROUTE,
            RequestLog.status_code < 400,
        ):
            proxy_retrievals_by_day[_day_key(ts)] += 1

        rows = []
        for day in _day_list(days):
            pre_boundary = boundary_day is None or day < boundary_day
            if pre_boundary:
                logins = sessions_by_day.get(day, 0)
                day_users = session_users_by_day.get(day, set())
            else:
                logins = logins_by_day.get(day, 0)
                day_users = users_by_day.get(day, set())

            new_users = sum(
                1
                for u in day_users
                if u in first_seen and _day_key(first_seen[u]) == day
            )
            rows.append(
                {
                    "date": day,
                    "logins": logins,
                    "logins_proxy": pre_boundary,
                    "distinct_users": len(day_users),
                    "new_users": new_users,
                    "returning_users": len(day_users) - new_users,
                    "decks_created": decks_by_day.get(day, 0),
                    "decks_retrieved": retrieved_by_day.get(day, 0),
                    "retrievals_proxy": (
                        proxy_retrievals_by_day.get(day, 0) if pre_boundary else None
                    ),
                }
            )
        return {"history_boundary": boundary_day, "days": rows}

    def get_top_users(self, db: Session, days: int) -> list[dict]:
        start = _window_start(days)
        stats: dict[str, dict] = defaultdict(
            lambda: {"logins": 0, "sessions_created": 0, "decks_created": 0}
        )

        login_events_by_user: dict[str, list[UsageEvent]] = defaultdict(list)
        for e in self._events_in_window(db, start):
            if e.event_type == EVENT_LOGIN:
                login_events_by_user[e.username].append(e)
        for name, user_events in login_events_by_user.items():
            # Collapse duplicate per-worker login rows into visits
            stats[name]["logins"] = _login_visit_count(user_events)

        for s in self._sessions_in_window(db, start):
            if s.created_by:
                stats[s.created_by]["sessions_created"] += 1

        deck_rows = (
            db.query(UserSession.created_by)
            .join(SessionSlideDeck, SessionSlideDeck.session_id == UserSession.id)
            .filter(
                SessionSlideDeck.created_at >= start,
                UserSession.created_by.isnot(None),
            )
            .all()
        )
        for (name,) in deck_rows:
            stats[name]["decks_created"] += 1

        ranked = sorted(
            (
                {"username": name, **vals}
                for name, vals in stats.items()
            ),
            key=lambda r: (r["logins"], r["sessions_created"]),
            reverse=True,
        )
        return ranked[:20]

    def get_funnel(self, db: Session, days: int) -> dict:
        start = _window_start(days)
        events = self._events_in_window(db, start)

        login_events = [e for e in events if e.event_type == EVENT_LOGIN]
        proxy = len(login_events) == 0

        if proxy:
            sessions = self._sessions_in_window(db, start)
            logins = len(sessions)
            logged_in_users = {s.created_by for s in sessions if s.created_by}
        else:
            logins = _login_visit_count(login_events)
            logged_in_users = {e.username for e in login_events}

        deck_event_users = {
            e.username for e in events if e.event_type == EVENT_DECK_CREATED
        }
        deck_session_users = {
            name
            for (name,) in db.query(UserSession.created_by)
            .join(SessionSlideDeck, SessionSlideDeck.session_id == UserSession.id)
            .filter(
                SessionSlideDeck.created_at >= start,
                UserSession.created_by.isnot(None),
            )
        }
        decks_created = (
            db.query(SessionSlideDeck)
            .filter(SessionSlideDeck.created_at >= start)
            .count()
        )
        return {
            "logins": logins,
            "users_who_logged_in": len(logged_in_users),
            "users_who_created_deck": len(deck_event_users | deck_session_users),
            "decks_created": decks_created,
            "proxy": proxy,
        }

    def get_retention(self, db: Session) -> list[dict]:
        today = datetime.utcnow().date()
        current_week_start = today - timedelta(days=today.weekday())
        # 9 week-starts, oldest first; we emit rows for the last 8
        week_starts = [
            current_week_start - timedelta(weeks=offset) for offset in range(8, -1, -1)
        ]
        window_start = datetime.combine(week_starts[0], dt_time.min)

        active_by_week: dict[str, set] = defaultdict(set)

        def _week_key(ts: datetime) -> str:
            d = ts.date()
            return (d - timedelta(days=d.weekday())).strftime("%Y-%m-%d")

        for e in db.query(UsageEvent).filter(UsageEvent.ts >= window_start):
            active_by_week[_week_key(e.ts)].add(e.username)
        for s in db.query(UserSession).filter(UserSession.created_at >= window_start):
            if s.created_by:
                active_by_week[_week_key(s.created_at)].add(s.created_by)

        rows = []
        for prev_start, week_start in zip(week_starts, week_starts[1:]):
            prev_key = prev_start.strftime("%Y-%m-%d")
            key = week_start.strftime("%Y-%m-%d")
            active = active_by_week.get(key, set())
            prev_active = active_by_week.get(prev_key, set())
            retained = len(active & prev_active) if prev_active else None
            pct = (
                round(100.0 * retained / len(prev_active), 1)
                if prev_active and retained is not None
                else None
            )
            rows.append(
                {
                    "week_start": key,
                    "active_users": len(active),
                    "retained_from_prev": retained,
                    "retention_pct": pct,
                }
            )
        return rows

    def get_heatmap(self, db: Session, days: int) -> dict:
        start = _window_start(days)
        matrix = [[0] * 24 for _ in range(7)]

        for e in self._events_in_window(db, start):
            matrix[e.ts.weekday()][e.ts.hour] += 1
        for s in self._sessions_in_window(db, start):
            matrix[s.created_at.weekday()][s.created_at.hour] += 1

        return {"matrix": matrix, "max": max(max(row) for row in matrix)}

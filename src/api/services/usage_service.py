"""On-the-fly usage analytics for the admin dashboard.

All aggregation happens in Python over time-filtered queries. This is a
deliberate choice (small data, SQLite-compatible tests) mirroring
FeedbackService.get_stats_report.

History semantics: `usage_events` provides literal login/retrieval events
from its first row onward (`history_boundary`). Days before the boundary
use `user_sessions` as a labeled proxy.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date as dt_date
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

# Preset windows offered by the UI; the API accepts any 1..MAX_WINDOW_DAYS,
# an explicit start/end date range, or all=true for the full history.
ALLOWED_WINDOWS = {7, 14, 21, 28}
MAX_WINDOW_DAYS = 365
# Hard cap on rows returned by get_daily in all-data/range mode
MAX_DAILY_ROWS = 730


@dataclass(frozen=True)
class Window:
    """Resolved reporting window.

    ``start`` is an inclusive datetime lower bound (None = beginning of data);
    ``end`` is an exclusive upper bound. ``days`` is set only in preset/days
    mode and is echoed back in responses for backward compatibility.
    """

    start: datetime | None
    end: datetime
    days: int | None
    all_data: bool

    def to_meta(self) -> dict:
        return {
            "days": self.days,
            "start": self.start.strftime("%Y-%m-%d") if self.start else None,
            "end": (self.end - timedelta(days=1)).strftime("%Y-%m-%d"),
            "all": self.all_data,
        }


def resolve_window(
    days: int | None = None,
    start: dt_date | None = None,
    end: dt_date | None = None,
    all_data: bool = False,
) -> Window:
    """Resolve query params into a concrete Window.

    Precedence: all_data > explicit start/end range > days > default 7 days.
    ``end`` is inclusive as a date (callers pass the last day they want to
    see); internally it becomes an exclusive midnight bound.
    """
    tomorrow = datetime.combine(
        datetime.utcnow().date() + timedelta(days=1), dt_time.min
    )
    if all_data:
        return Window(start=None, end=tomorrow, days=None, all_data=True)
    if start is not None and end is not None:
        return Window(
            start=datetime.combine(start, dt_time.min),
            end=datetime.combine(end + timedelta(days=1), dt_time.min),
            days=None,
            all_data=False,
        )
    resolved_days = days if days is not None else 7
    return Window(
        start=_window_start(resolved_days),
        end=tomorrow,
        days=resolved_days,
        all_data=False,
    )

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


class UsageService:
    """Aggregates usage metrics for /api/admin/usage endpoints."""

    # ---------- shared helpers ----------

    def _events_in_window(self, db: Session, w: Window) -> list[UsageEvent]:
        query = db.query(UsageEvent).filter(UsageEvent.ts < w.end)
        if w.start is not None:
            query = query.filter(UsageEvent.ts >= w.start)
        return query.all()

    def _sessions_in_window(self, db: Session, w: Window) -> list[UserSession]:
        query = db.query(UserSession).filter(UserSession.created_at < w.end)
        if w.start is not None:
            query = query.filter(UserSession.created_at >= w.start)
        return query.all()

    def _decks_in_window(self, db: Session, w: Window) -> list[SessionSlideDeck]:
        query = db.query(SessionSlideDeck).filter(SessionSlideDeck.created_at < w.end)
        if w.start is not None:
            query = query.filter(SessionSlideDeck.created_at >= w.start)
        return query.all()

    def _window_day_list(self, w: Window, earliest: datetime | None) -> list[str]:
        """Calendar days covered by the window, oldest first, capped.

        In all-data mode the range starts at the earliest observed data point
        (or today when the database is empty).
        """
        last_day = (w.end - timedelta(days=1)).date()
        if w.start is not None:
            first_day = w.start.date()
        elif earliest is not None:
            first_day = earliest.date()
        else:
            first_day = last_day
        total = (last_day - first_day).days + 1
        if total > MAX_DAILY_ROWS:
            first_day = last_day - timedelta(days=MAX_DAILY_ROWS - 1)
            total = MAX_DAILY_ROWS
        return [
            (first_day + timedelta(days=offset)).strftime("%Y-%m-%d")
            for offset in range(total)
        ]

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

    def get_summary(
        self,
        db: Session,
        days: int | None = None,
        start: dt_date | None = None,
        end: dt_date | None = None,
        all_data: bool = False,
    ) -> dict:
        w = resolve_window(days=days, start=start, end=end, all_data=all_data)

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

        events = self._events_in_window(db, w)
        sessions = self._sessions_in_window(db, w)
        activity_query = db.query(UserSession.created_by).filter(
            UserSession.last_activity < w.end,
            UserSession.created_by.isnot(None),
        )
        if w.start is not None:
            activity_query = activity_query.filter(
                UserSession.last_activity >= w.start
            )
        active_from_last_activity = {name for (name,) in activity_query}
        active_users = (
            {e.username for e in events}
            | {s.created_by for s in sessions if s.created_by}
            | active_from_last_activity
        )
        decks_created = len(self._decks_in_window(db, w))
        logins = _login_visit_count(
            e for e in events if e.event_type == EVENT_LOGIN
        )

        avg = round(decks_created / len(active_users), 1) if active_users else None
        return {
            "total_users_ever": total_users_ever,
            "total_decks_ever": total_decks_ever,
            "window": {
                **w.to_meta(),
                "active_users": len(active_users),
                "decks_created": decks_created,
                "avg_decks_per_active_user": avg,
                "logins": logins,
            },
        }

    def get_daily(
        self,
        db: Session,
        days: int | None = None,
        start: dt_date | None = None,
        end: dt_date | None = None,
        all_data: bool = False,
    ) -> dict:
        w = resolve_window(days=days, start=start, end=end, all_data=all_data)
        boundary = self._history_boundary(db)
        boundary_day = _day_key(boundary) if boundary else None

        events = self._events_in_window(db, w)
        sessions = self._sessions_in_window(db, w)
        decks = self._decks_in_window(db, w)
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
        proxy_query = db.query(RequestLog.timestamp).filter(
            RequestLog.timestamp < w.end,
            RequestLog.method == "GET",
            RequestLog.path == _DECK_OPEN_ROUTE,
            RequestLog.status_code < 400,
        )
        if w.start is not None:
            proxy_query = proxy_query.filter(RequestLog.timestamp >= w.start)
        for (ts,) in proxy_query:
            proxy_retrievals_by_day[_day_key(ts)] += 1

        earliest = min(
            (
                ts
                for ts in (
                    min((e.ts for e in events), default=None),
                    min((s.created_at for s in sessions), default=None),
                    min((d.created_at for d in decks), default=None),
                )
                if ts is not None
            ),
            default=None,
        )
        rows = []
        for day in self._window_day_list(w, earliest):
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
        return {
            "history_boundary": boundary_day,
            "window": w.to_meta(),
            "days": rows,
        }

    def _deck_creator_rows(self, db: Session, w: Window) -> list:
        query = (
            db.query(UserSession.created_by)
            .join(SessionSlideDeck, SessionSlideDeck.session_id == UserSession.id)
            .filter(
                SessionSlideDeck.created_at < w.end,
                UserSession.created_by.isnot(None),
            )
        )
        if w.start is not None:
            query = query.filter(SessionSlideDeck.created_at >= w.start)
        return query.all()

    def get_top_users(
        self,
        db: Session,
        days: int | None = None,
        start: dt_date | None = None,
        end: dt_date | None = None,
        all_data: bool = False,
    ) -> list[dict]:
        w = resolve_window(days=days, start=start, end=end, all_data=all_data)
        stats: dict[str, dict] = defaultdict(
            lambda: {"logins": 0, "sessions_created": 0, "decks_created": 0}
        )

        login_events_by_user: dict[str, list[UsageEvent]] = defaultdict(list)
        for e in self._events_in_window(db, w):
            if e.event_type == EVENT_LOGIN:
                login_events_by_user[e.username].append(e)
        for name, user_events in login_events_by_user.items():
            # Collapse duplicate per-worker login rows into visits
            stats[name]["logins"] = _login_visit_count(user_events)

        for s in self._sessions_in_window(db, w):
            if s.created_by:
                stats[s.created_by]["sessions_created"] += 1

        for (name,) in self._deck_creator_rows(db, w):
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

    def get_funnel(
        self,
        db: Session,
        days: int | None = None,
        start: dt_date | None = None,
        end: dt_date | None = None,
        all_data: bool = False,
    ) -> dict:
        w = resolve_window(days=days, start=start, end=end, all_data=all_data)
        events = self._events_in_window(db, w)

        login_events = [e for e in events if e.event_type == EVENT_LOGIN]
        proxy = len(login_events) == 0

        if proxy:
            sessions = self._sessions_in_window(db, w)
            logins = len(sessions)
            logged_in_users = {s.created_by for s in sessions if s.created_by}
        else:
            logins = _login_visit_count(login_events)
            logged_in_users = {e.username for e in login_events}

        deck_event_users = {
            e.username for e in events if e.event_type == EVENT_DECK_CREATED
        }
        deck_session_users = {name for (name,) in self._deck_creator_rows(db, w)}
        decks_created = len(self._decks_in_window(db, w))
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

    def get_heatmap(
        self,
        db: Session,
        days: int | None = None,
        start: dt_date | None = None,
        end: dt_date | None = None,
        all_data: bool = False,
    ) -> dict:
        w = resolve_window(days=days, start=start, end=end, all_data=all_data)
        matrix = [[0] * 24 for _ in range(7)]

        for e in self._events_in_window(db, w):
            matrix[e.ts.weekday()][e.ts.hour] += 1
        for s in self._sessions_in_window(db, w):
            matrix[s.created_at.weekday()][s.created_at.hour] += 1

        return {"matrix": matrix, "max": max(max(row) for row in matrix)}

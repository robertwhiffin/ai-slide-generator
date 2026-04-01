"""Request logging database model for performance monitoring."""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, Index, Integer, String

from src.core.database import Base


class RequestLog(Base):
    """Stores per-request metrics for performance monitoring."""

    __tablename__ = "request_logs"

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    method = Column(String(10), nullable=False)
    path = Column(String(500), nullable=False)
    status_code = Column(Integer, nullable=False)
    duration_ms = Column(Float, nullable=False)
    request_id = Column(String(36), nullable=True)

    __table_args__ = (
        Index("ix_request_logs_timestamp", "timestamp"),
    )

    def __repr__(self):
        return (
            f"<RequestLog(id={self.id}, method='{self.method}', "
            f"path='{self.path}', status_code={self.status_code}, "
            f"duration_ms={self.duration_ms})>"
        )

"""Deck contributor model for sharing decks with Databricks UC identities."""
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship

from src.core.database import Base
from src.database.models.profile_contributor import PermissionLevel


class DeckContributor(Base):
    """
    Deck contributor - users/groups with access to a deck (user session).

    Each contributor entry represents a Databricks UC identity (user or group)
    with a specific permission level on a deck.

    Foreign key references user_sessions.id with CASCADE delete.
    """

    __tablename__ = "deck_contributors"

    id = Column(Integer, primary_key=True)
    user_session_id = Column(
        Integer,
        ForeignKey("user_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Databricks identity info
    identity_type = Column(String(10), nullable=False)  # USER or GROUP
    identity_id = Column(String(255), nullable=False, index=True)  # Databricks user/group ID
    identity_name = Column(String(255), nullable=False)  # Display name (email or group name)

    # Permission level
    permission_level = Column(String(20), nullable=False, default=PermissionLevel.CAN_VIEW.value)

    # Audit fields
    created_by = Column(String(255), nullable=True)  # Who added this contributor
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    user_session = relationship("UserSession", backref="deck_contributors")

    # Constraints
    __table_args__ = (
        UniqueConstraint("user_session_id", "identity_id", name="uq_deck_contributor_session_identity"),
    )

    def __repr__(self):
        return (
            f"<DeckContributor(id={self.id}, user_session_id={self.user_session_id}, "
            f"identity_name='{self.identity_name}', permission='{self.permission_level}')>"
        )

"""Application-managed encryption key storage (SDR-4437 CRITICAL-3).

Holds the Fernet master key for OAuth credential/token encryption in the
ACL-governed Lakebase data schema instead of app.yaml. Single-row table
(id = 1). Deliberately shares the data schema's grants: the key carries
the same ACLs as the ciphertext it protects — an explicitly accepted risk
in the SDR-4437 remediation design. Do NOT add key-specific grant
tightening here.
"""

from sqlalchemy import Column, DateTime, Integer, Text

from src.core.database import Base


class EncryptionKey(Base):
    """Fernet master key for OAuth credential/token encryption."""

    __tablename__ = "encryption_keys"

    id = Column(Integer, primary_key=True, autoincrement=False)
    key_value = Column(Text, nullable=False)
    # No Python-side default: every insert path (the app's raw-SQL seed and
    # the deploy migration DDL) supplies CURRENT_TIMESTAMP explicitly, so a
    # default would be dead code — and the codebase-conventional
    # datetime.utcnow is deprecated on Python 3.12+.
    created_at = Column(DateTime, nullable=False)

    def __repr__(self) -> str:  # never print key material
        return f"<EncryptionKey(id={self.id}, created_at={self.created_at})>"

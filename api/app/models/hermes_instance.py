"""One managed Hermes container per customer (docs/TARGET_ARCHITECTURE.md §9)."""
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from app.database import Base


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class HermesInstance(Base):
    __tablename__ = "hermes_instances"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    container_name = Column(String(100), nullable=False)
    volume_name = Column(String(100), nullable=False)
    image = Column(String(255), nullable=False)
    api_port = Column(Integer, nullable=True)              # host port of the Hermes API server
    api_server_key_encrypted = Column(Text, nullable=False)
    # provisioning | running | sleeping | upgrading | stopped | error
    status = Column(String(20), nullable=False, default="provisioning")
    last_error = Column(Text, nullable=True)
    last_active_at = Column(DateTime, default=utcnow)
    last_backup_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    container_id = Column(Integer, ForeignKey("containers.id"), nullable=True)
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    priority = Column(String(20), default="normal")  # low, normal, high, urgent
    status = Column(String(20), default="pending")  # pending, in_progress, completed, cancelled
    assigned_to = Column(String(100), nullable=True)  # agent_name or null
    created_by_agent = Column(String(100), nullable=True)  # which agent created this
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    # Relationships
    client = relationship("Client", back_populates="tasks")

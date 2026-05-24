from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from app.database import Base


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Container(Base):
    __tablename__ = "containers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    name = Column(String(255), default="StaffBot 1")
    container_name = Column(String(255), nullable=True)
    image = Column(String(255), default="staffbot-core:latest")
    port = Column(Integer, nullable=True)
    env_vars = Column(JSON, nullable=True)
    status = Column(String(50), default="pending")
    skills = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    # Relationships
    client = relationship("Client", back_populates="containers")

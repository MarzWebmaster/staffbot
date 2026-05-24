from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class NotificationChannel(Base):
    __tablename__ = "notification_channels"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    channel = Column(String(50), nullable=False)  # whatsapp / email / sms / in-app
    value = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    is_primary = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow)

    # Relationships
    client = relationship("Client", back_populates="notification_channels")


class NotificationLog(Base):
    __tablename__ = "notifications_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    type = Column(String(50), nullable=False)
    channel = Column(String(50), nullable=False)
    subject = Column(String(255), nullable=True)
    body = Column(Text)
    status = Column(String(50), default="pending")
    error_message = Column(Text, nullable=True)
    sent_at = Column(DateTime, default=utcnow)

    # Relationships
    client = relationship("Client", back_populates="notifications_log")

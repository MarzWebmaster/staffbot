from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Client(Base):
    __tablename__ = "clients"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False, unique=True, index=True)
    password_hash = Column(String(255), nullable=True)
    company = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    package = Column(String(50), default="basic")
    status = Column(String(50), default="pending")
    subdomain = Column(String(255), nullable=True, unique=True)
    container_port = Column(Integer, nullable=True)
    container_id = Column(String(255), nullable=True)
    telegram_token_encrypted = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    # Relationships
    subscription = relationship("Subscription", back_populates="client", uselist=False)
    containers = relationship("Container", back_populates="client")
    api_keys = relationship("ApiKey", back_populates="client")
    notification_channels = relationship("NotificationChannel", back_populates="client")
    notifications_log = relationship("NotificationLog", back_populates="client")

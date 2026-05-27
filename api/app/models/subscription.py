from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, Float, JSON, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("clients.id"), unique=True, nullable=False)
    stripe_subscription_id = Column(String(255), nullable=True)
    stripe_session_id = Column(String(255), nullable=True)
    package = Column(String(50), default="basic")
    status = Column(String(50), default="active")
    managed_token_quota = Column(Float, default=0.0)
    managed_token_used = Column(Float, default=0.0)
    provider_token_usage = Column(JSON, default=dict)  # {"openrouter": 1000, "ilmui": 500}
    start_date = Column(DateTime, default=utcnow)
    end_date = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    # Relationships
    client = relationship("Client", back_populates="subscription")

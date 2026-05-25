"""Token Top-Up models."""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, BigInteger, DateTime, Boolean, Float, Text, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TokenTopupPackage(Base):
    """Admin-defined token top-up packages (e.g. 10M tokens = RM35)."""
    __tablename__ = "token_topup_packages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, default="")
    tokens = Column(BigInteger, nullable=False)
    price_myr = Column(Float, nullable=False)
    is_active = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=utcnow)


class TokenTopup(Base):
    """Record of a user purchasing token top-up."""
    __tablename__ = "token_topups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    package_id = Column(Integer, ForeignKey("token_topup_packages.id"), nullable=True)
    tokens = Column(BigInteger, nullable=False)
    amount_paid = Column(Float, nullable=False)
    stripe_session_id = Column(String(255), nullable=True)
    status = Column(String(50), default="pending")
    created_at = Column(DateTime, default=utcnow)
    completed_at = Column(DateTime, nullable=True)

    client = relationship("Client")

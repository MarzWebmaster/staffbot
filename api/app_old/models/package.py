from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, Boolean, Float, Text, JSON
from app.database import Base


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Package(Base):
    __tablename__ = "packages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), unique=True, nullable=False)
    display_name = Column(String(100))
    price_monthly = Column(Float)
    price_yearly = Column(Float, nullable=True)
    description = Column(Text)
    features = Column(JSON)
    bot_limit = Column(Integer, default=1)
    managed_tokens = Column(Float, default=0.0)
    sort_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)

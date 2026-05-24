from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text
from app.database import Base


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Setting(Base):
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(255), unique=True, nullable=False)
    value = Column(Text)
    encrypted = Column(Boolean, default=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

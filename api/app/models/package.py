from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, Boolean, Float, Text, JSON, ARRAY
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
    sub_ejen_limit = Column(Integer, default=0)
    managed_tokens = Column(Float, default=0.0)
    cpu_limit = Column(Float, default=1.0)
    memory_limit_mb = Column(Integer, default=512)
    storage_limit_gb = Column(Integer, default=10)
    skill_category_ids = Column(ARRAY(Integer), default=[])
    tool_category_ids = Column(ARRAY(Integer), default=[])
    allowed_skill_categories = Column(JSON, default=list)
    allowed_tool_categories = Column(JSON, default=list)
    enabled_skills = Column(JSON, default=list)
    enabled_tools = Column(JSON, default=list)
    sort_order = Column(Integer, default=0)
    trial_days = Column(Integer, default=0)
    is_public = Column(Boolean, default=True)
    is_active = Column(Boolean, default=True)
    badge = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.now)

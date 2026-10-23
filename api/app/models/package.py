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
    # NOTE: allowed_skill_categories (JSON) duplicates skill_category_ids (ARRAY).
    # Keep both for backward compat — prefer skill_category_ids for new code.
    allowed_skill_categories = Column(JSON, default=list)
    allowed_tool_categories = Column(JSON, default=list)
    enabled_skills = Column(JSON, default=list)
    enabled_tools = Column(JSON, default=list)
    sort_order = Column(Integer, default=0)
    trial_days = Column(Integer, default=0)
    is_public = Column(Boolean, default=True)
    is_active = Column(Boolean, default=True)
    badge = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=utcnow)

    # Memory limits (used by routers/memory.py; previously only in the live DB)
    memory_retention_days = Column(Integer, default=7)
    memory_item_limit = Column(Integer, default=50)
    knowledge_item_limit = Column(Integer, default=50)

    # Managed Hermes (docs/TARGET_ARCHITECTURE.md §7). bot_limit = AI Staff limit.
    allowed_models = Column(JSON, default=list)          # [] = models of providers assigned to the package; ["*"] = any
    channel_limits = Column(JSON, default=dict)          # {"web": true, "whatsapp": 1, "telegram": 1}
    byok_allowed = Column(Boolean, default=True)
    console_mode = Column(String(20), default="none")    # none | hermes | shell
    agent_terminal = Column(Boolean, default=False)      # agent may use terminal/code toolsets
    catalog_tier = Column(String(20), default="basic")   # basic | all
    custom_code_allowed = Column(Boolean, default=False) # custom code / MCP servers
    idle_sleep_minutes = Column(Integer, default=30)     # 0 = always on
    backup_retention_days = Column(Integer, default=7)
    upgrade_window = Column(Boolean, default=False)      # customer may choose upgrade time
    support_level = Column(String(20), default="email")  # none | email | email_whatsapp | priority

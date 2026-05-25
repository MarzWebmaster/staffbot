from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, JSON, Float, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class LlmProvider(Base):
    """Managed LLM provider configurations (OpenRouter, Ilmu AI, etc.)."""
    __tablename__ = "llm_providers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), unique=True, nullable=False)          # slug: openrouter, ilmui
    display_name = Column(String(100), nullable=False)               # OpenRouter, Ilmu AI
    base_url = Column(String(255), nullable=False)                   # API base URL
    api_key_encrypted = Column(Text, nullable=True)                  # Managed API key (encrypted)
    models = Column(JSON, default=list)                              # Available models: ["model-a", "model-b"]
    default_model = Column(String(100), nullable=True)               # Default model for this provider
    description = Column(Text, nullable=True)
    logo_url = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    # Relationships
    package_providers = relationship("PackageProvider", back_populates="provider")


class PackageProvider(Base):
    """Junction: which LLM providers are included in which package + token quota."""
    __tablename__ = "package_providers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    package_id = Column(Integer, ForeignKey("packages.id"), nullable=False)
    provider_id = Column(Integer, ForeignKey("llm_providers.id"), nullable=False)
    token_quota = Column(Float, default=0.0)                         # Per-provider token quota
    is_available = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utcnow)

    # Relationships
    package = relationship("Package", backref="provider_assignments")
    provider = relationship("LlmProvider", back_populates="package_providers")

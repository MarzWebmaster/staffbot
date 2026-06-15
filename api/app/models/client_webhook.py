"""Client webhook configurations for 3rd-party API access.

Each client can define multiple webhook endpoints (WordPress, HubSpot, CRM, etc.).
Auth values are encrypted with STAFFBOT_SECRET_KEY at rest.
"""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from datetime import datetime, timezone

from app.database import Base


class ClientWebhook(Base):
    __tablename__ = "client_webhooks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    base_url = Column(String(500), nullable=False)
    auth_type = Column(String(20), nullable=False, default="none")  # none, bearer, api_key, basic
    auth_header = Column(String(50), nullable=True)  # X-API-Key, Authorization, etc.
    auth_value = Column(Text, nullable=True)  # ENCRYPTED token/key
    default_headers = Column(JSONB, nullable=False, default=dict, server_default='{}')
    is_active = Column(Boolean, nullable=False, default=True)
    rate_limit = Column(Integer, nullable=False, default=10)  # max calls per minute
    max_timeout = Column(Integer, nullable=False, default=30)  # seconds
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    # Relationships
    client = relationship("Client", back_populates="webhooks")

    def __repr__(self):
        return f"<ClientWebhook id={self.id} client={self.client_id} name='{self.name}'>"

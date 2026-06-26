"""Audit Trail model — records all significant transactions in the system."""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB
from app.database import Base


class AuditTrail(Base):
    __tablename__ = "audit_trail"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    action = Column(String(50), nullable=False)
    # e.g. 'chat_request', 'login', 'logout', 'payment', 'settings_change',
    #      'provider_call', 'token_topup', 'api_key_rotate', 'admin_action'
    resource = Column(String(100), nullable=True)
    # e.g. 'chat', 'subscription', 'provider:deepseek-pchp17', 'settings:general'
    detail = Column(JSONB, nullable=False, server_default='{}')
    # Flexible: {"model": "deepseek-chat", "input_tokens": 150, "output_tokens": 30, ...}
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)
    status = Column(String(20), default="success")  # success, failure, blocked
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), index=True)

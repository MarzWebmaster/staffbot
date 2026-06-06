"""Policy Violation Log — tracks content moderation violations per client."""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean
from app.database import Base


class PolicyViolation(Base):
    __tablename__ = 'policy_violations'
    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey('clients.id'), nullable=False, index=True)
    category = Column(String(100), nullable=False)  # blocked category matched
    severity = Column(String(20), default='warning')  # warning, block, suspend
    user_message = Column(Text, nullable=False)  # original message (truncated)
    matched_patterns = Column(Text, nullable=True)  # JSON list of matched patterns
    action_taken = Column(String(50), default='blocked')  # blocked, warned, suspended
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

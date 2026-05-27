"""Usage tracking model for token consumption and API calls per client."""
from sqlalchemy import Column, Integer, String, DateTime, BigInteger, func
from app.database import Base


class UsageLog(Base):
    __tablename__ = "usage_logs"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    client_id = Column(Integer, nullable=False, index=True)
    client_name = Column(String(255), default="")
    container_id = Column(Integer, nullable=True)
    package = Column(String(50), default="basic")
    tokens_in = Column(Integer, default=0)
    tokens_out = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    model = Column(String(100), default="")
    endpoint = Column(String(100), default="chat")
    status = Column(String(20), default="success")
    created_at = Column(DateTime(timezone=False), server_default=func.now(), index=True)

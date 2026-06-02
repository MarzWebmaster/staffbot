from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey
from app.database import Base


class Subdomain(Base):
    __tablename__ = "subdomains"

    id = Column(Integer, primary_key=True, autoincrement=True)
    subdomain = Column(String(100), unique=True, nullable=False)
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(20), default="available")
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

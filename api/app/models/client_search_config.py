"""Client search provider configurations for web search tools.

Each client can register their own API key for search providers
(Brave, SerpAPI, etc.) or use free providers like DuckDuckGo.
"""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean, Text
from sqlalchemy.orm import relationship
from datetime import datetime, timezone

from app.database import Base


class ClientSearchConfig(Base):
    __tablename__ = "client_search_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    provider = Column(String(30), nullable=False)  # brave, google, serpapi, duckduckgo
    api_key = Column(Text, nullable=True)  # ENCRYPTED — NULL for duckduckgo
    base_url = Column(String(500), nullable=True)  # optional custom endpoint
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    # Relationships
    client = relationship("Client", back_populates="search_configs")

    def __repr__(self):
        return f"<ClientSearchConfig id={self.id} client={self.client_id} provider='{self.provider}'>"

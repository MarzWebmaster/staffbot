"""Client email/SMTP configurations for send_email tool.

Each client can configure their own SMTP server (Gmail, SendGrid, Brevo, etc.).
SMTP password is encrypted with STAFFBOT_SECRET_KEY at rest.
"""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean, Text
from sqlalchemy.orm import relationship
from datetime import datetime, timezone

from app.database import Base


class ClientEmailConfig(Base):
    __tablename__ = "client_email_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    smtp_host = Column(String(255), nullable=False)
    smtp_port = Column(Integer, nullable=False, default=587)
    smtp_user = Column(String(255), nullable=False)
    smtp_pass = Column(Text, nullable=False)  # ENCRYPTED
    use_tls = Column(Boolean, nullable=False, default=True)
    from_email = Column(String(255), nullable=True)
    from_name = Column(String(100), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    # Relationships
    client = relationship("Client", back_populates="email_configs")

    def __repr__(self):
        return f"<ClientEmailConfig id={self.id} client={self.client_id} host='{self.smtp_host}'>"

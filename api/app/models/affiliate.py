from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, Boolean, Float, Text, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Affiliate(Base):
    """Affiliate / referral program — one profile per client."""
    __tablename__ = "affiliates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="CASCADE"), unique=True, nullable=False)
    referral_code = Column(String(50), unique=True, nullable=False, index=True)
    commission_rate = Column(Float, default=10.0)            # Percentage (e.g. 10 = 10%)
    total_earnings = Column(Float, default=0.0)
    pending_earnings = Column(Float, default=0.0)
    paid_earnings = Column(Float, default=0.0)
    total_referrals = Column(Integer, default=0)
    total_clicks = Column(Integer, default=0)
    status = Column(String(50), default="active")            # active / suspended
    is_auto_approve = Column(Boolean, default=True)          # Auto-approve referrals?
    min_payout = Column(Float, default=50.0)                 # Minimum before can withdraw
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    # Relationships
    client = relationship("Client", backref="affiliate_profile")
    referrals = relationship("AffiliateReferral", back_populates="affiliate")
    commissions = relationship("AffiliateCommission", back_populates="affiliate")
    clicks = relationship("AffiliateClick", back_populates="affiliate")


class AffiliateReferral(Base):
    """Track each referral made by an affiliate."""
    __tablename__ = "affiliate_referrals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    affiliate_id = Column(Integer, ForeignKey("affiliates.id"), nullable=False)
    referred_client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    referred_email = Column(String(255), nullable=True)
    referred_name = Column(String(255), nullable=True)
    status = Column(String(50), default="pending")           # pending / active / expired / cancelled
    commission_earned = Column(Float, default=0.0)
    package_signed = Column(String(50), nullable=True)
    ip_address = Column(String(50), nullable=True)
    user_agent = Column(Text, nullable=True)
    converted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)

    # Relationships
    affiliate = relationship("Affiliate", back_populates="referrals")
    referred_client = relationship("Client", backref="referred_by")


class AffiliateCommission(Base):
    """Commission earned by affiliates."""
    __tablename__ = "affiliate_commissions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    affiliate_id = Column(Integer, ForeignKey("affiliates.id"), nullable=False)
    referral_id = Column(Integer, ForeignKey("affiliate_referrals.id"), nullable=True)
    amount = Column(Float, default=0.0)
    description = Column(String(255), nullable=True)
    status = Column(String(50), default="pending")           # pending / paid / cancelled
    paid_at = Column(DateTime, nullable=True)
    payout_id = Column(Integer, ForeignKey("affiliate_payouts.id"), nullable=True)
    created_at = Column(DateTime, default=utcnow)

    # Relationships
    affiliate = relationship("Affiliate", back_populates="commissions")
    referral = relationship("AffiliateReferral", backref="commissions")
    payout = relationship("AffiliatePayout", backref="commissions")


class AffiliatePayout(Base):
    """Payout requests and history."""
    __tablename__ = "affiliate_payouts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    affiliate_id = Column(Integer, ForeignKey("affiliates.id"), nullable=False)
    amount = Column(Float, default=0.0)
    method = Column(String(50), default="bank_transfer")     # bank_transfer / tng / auto
    account_details = Column(Text, nullable=True)            # Bank name, account no, etc.
    status = Column(String(50), default="pending")           # pending / processing / completed / rejected
    admin_notes = Column(Text, nullable=True)
    processed_by = Column(Integer, ForeignKey("clients.id"), nullable=True)
    processed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)

    # Relationships
    affiliate = relationship("Affiliate", backref="payouts")
    processor = relationship("Client", backref="processed_payouts")


class AffiliateClick(Base):
    """Track referral link clicks."""
    __tablename__ = "affiliate_clicks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    affiliate_id = Column(Integer, ForeignKey("affiliates.id"), nullable=False)
    ip_address = Column(String(50), nullable=True)
    user_agent = Column(Text, nullable=True)
    referrer_url = Column(Text, nullable=True)
    landing_page = Column(String(255), nullable=True)
    converted = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow)

    # Relationships
    affiliate = relationship("Affiliate", back_populates="clicks")

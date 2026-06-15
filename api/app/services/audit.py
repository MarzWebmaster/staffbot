"""Audit Trail Service — write audit entries from anywhere in the system."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional, Any, Dict
from sqlalchemy import text
from app.database import async_session_factory
from app.models.audit_trail import AuditTrail


async def log_audit(
    client_id: int,
    action: str,
    resource: Optional[str] = None,
    detail: Optional[Dict[str, Any]] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    status: str = "success",
) -> Optional[int]:
    """Write an audit trail entry. Returns the new entry ID or None on failure.

    Args:
        client_id: The client performing the action
        action: Short action name (e.g. 'chat_request', 'login', 'payment')
        resource: What was affected (e.g. 'chat', 'subscription', 'provider:deepseek')
        detail: Flexible JSON with action-specific data
        ip_address: Request IP
        user_agent: Request User-Agent
        status: 'success', 'failure', or 'blocked'
    """
    try:
        async with async_session_factory() as session:
            entry = AuditTrail(
                client_id=client_id,
                action=action,
                resource=resource,
                detail=detail or {},
                ip_address=ip_address,
                user_agent=user_agent,
                status=status,
            )
            session.add(entry)
            await session.commit()
            return entry.id
    except Exception:
        # Audit should never break the main flow
        return None


async def create_audit_table():
    """Create the audit_trail table if it doesn't exist (idempotent)."""
    async with async_session_factory() as session:
        statements = [
            """CREATE TABLE IF NOT EXISTS audit_trail (
                id SERIAL PRIMARY KEY,
                client_id INTEGER NOT NULL REFERENCES clients(id),
                action VARCHAR(50) NOT NULL,
                resource VARCHAR(100),
                detail JSONB DEFAULT '{}',
                ip_address VARCHAR(45),
                user_agent TEXT,
                status VARCHAR(20) DEFAULT 'success',
                created_at TIMESTAMP DEFAULT NOW()
            )""",
            "CREATE INDEX IF NOT EXISTS idx_audit_trail_client ON audit_trail(client_id, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_audit_trail_action ON audit_trail(action, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_audit_trail_status ON audit_trail(status)",
            "CREATE INDEX IF NOT EXISTS idx_audit_trail_created ON audit_trail(created_at DESC)",
        ]
        for stmt in statements:
            await session.execute(text(stmt))
        await session.commit()

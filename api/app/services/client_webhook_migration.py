"""Create client_webhooks table (idempotent)."""
from sqlalchemy import text
from app.database import async_session_factory


async def create_client_webhooks_table():
    """Create the client_webhooks table and indexes if they don't exist."""
    async with async_session_factory() as session:
        statements = [
            """CREATE TABLE IF NOT EXISTS client_webhooks (
                id SERIAL PRIMARY KEY,
                client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
                name VARCHAR(100) NOT NULL,
                base_url VARCHAR(500) NOT NULL,
                auth_type VARCHAR(20) NOT NULL DEFAULT 'none',
                auth_header VARCHAR(50),
                auth_value TEXT,
                default_headers JSONB NOT NULL DEFAULT '{}'::jsonb,
                is_active BOOLEAN NOT NULL DEFAULT true,
                rate_limit INTEGER NOT NULL DEFAULT 10,
                max_timeout INTEGER NOT NULL DEFAULT 30,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )""",
            "CREATE INDEX IF NOT EXISTS idx_webhooks_client ON client_webhooks(client_id)",
            "CREATE INDEX IF NOT EXISTS idx_webhooks_active ON client_webhooks(client_id, is_active)",
        ]
        for stmt in statements:
            await session.execute(text(stmt))
        await session.commit()

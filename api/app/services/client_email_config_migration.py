"""Create client_email_configs table (idempotent)."""
from sqlalchemy import text
from app.database import async_session_factory


async def create_client_email_configs_table():
    """Create the client_email_configs table and indexes if they don't exist."""
    async with async_session_factory() as session:
        statements = [
            """CREATE TABLE IF NOT EXISTS client_email_configs (
                id SERIAL PRIMARY KEY,
                client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
                smtp_host VARCHAR(255) NOT NULL,
                smtp_port INTEGER NOT NULL DEFAULT 587,
                smtp_user VARCHAR(255) NOT NULL,
                smtp_pass TEXT NOT NULL,
                use_tls BOOLEAN NOT NULL DEFAULT TRUE,
                from_email VARCHAR(255),
                from_name VARCHAR(100),
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )""",
            "CREATE INDEX IF NOT EXISTS idx_email_configs_client ON client_email_configs(client_id)",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_email_configs_unique ON client_email_configs(client_id) WHERE is_active = TRUE",
        ]
        for stmt in statements:
            await session.execute(text(stmt))
        await session.commit()

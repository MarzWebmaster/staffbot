"""Create client_search_configs table (idempotent)."""
from sqlalchemy import text
from app.database import async_session_factory


async def create_client_search_configs_table():
    """Create the client_search_configs table and indexes if they don't exist."""
    async with async_session_factory() as session:
        statements = [
            """CREATE TABLE IF NOT EXISTS client_search_configs (
                id SERIAL PRIMARY KEY,
                client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
                provider VARCHAR(30) NOT NULL DEFAULT 'brave',
                api_key TEXT,
                base_url VARCHAR(500),
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )""",
            "CREATE INDEX IF NOT EXISTS idx_search_configs_client ON client_search_configs(client_id)",
            "CREATE INDEX IF NOT EXISTS idx_search_configs_active ON client_search_configs(client_id, is_active)",
        ]
        for stmt in statements:
            await session.execute(text(stmt))
        await session.commit()

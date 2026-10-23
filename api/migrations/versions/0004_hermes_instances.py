"""hermes_instances: one managed Hermes container per customer.

Revision ID: 0004_hermes_instances
Revises: 0003_client_llm_token_version
Create Date: 2026-10-23
"""
from alembic import op

revision = "0004_hermes_instances"
down_revision = "0003_client_llm_token_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS hermes_instances (
            id SERIAL PRIMARY KEY,
            client_id INTEGER NOT NULL UNIQUE REFERENCES clients(id) ON DELETE CASCADE,
            container_name VARCHAR(100) NOT NULL,
            volume_name VARCHAR(100) NOT NULL,
            image VARCHAR(255) NOT NULL,
            api_port INTEGER,
            api_server_key_encrypted TEXT NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'provisioning',
            last_error TEXT,
            last_active_at TIMESTAMP DEFAULT NOW(),
            last_backup_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_hermes_instances_client_id ON hermes_instances (client_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS hermes_instances")

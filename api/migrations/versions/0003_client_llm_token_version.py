"""clients.llm_token_version — revocation counter for LLM proxy tokens.

Revision ID: 0003_client_llm_token_version
Revises: 0002_package_managed_hermes
Create Date: 2026-10-23
"""
from alembic import op

revision = "0003_client_llm_token_version"
down_revision = "0002_package_managed_hermes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE clients ADD COLUMN IF NOT EXISTS llm_token_version INTEGER DEFAULT 1")


def downgrade() -> None:
    op.execute("ALTER TABLE clients DROP COLUMN IF EXISTS llm_token_version")

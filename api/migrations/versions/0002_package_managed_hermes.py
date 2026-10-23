"""Package fields for managed Hermes (docs/TARGET_ARCHITECTURE.md §7.1).

Also adds the memory_* columns the code already used but no migration created
(bug B-11). Idempotent: safe on databases created by create_all().

Revision ID: 0002_package_managed_hermes
Revises: 0001_baseline
Create Date: 2026-10-23
"""
from alembic import op

revision = "0002_package_managed_hermes"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None

COLUMNS = [
    ("memory_retention_days", "INTEGER DEFAULT 7"),
    ("memory_item_limit", "INTEGER DEFAULT 50"),
    ("knowledge_item_limit", "INTEGER DEFAULT 50"),
    ("allowed_models", "JSON DEFAULT '[]'"),
    ("channel_limits", "JSON DEFAULT '{}'"),
    ("byok_allowed", "BOOLEAN DEFAULT TRUE"),
    ("console_mode", "VARCHAR(20) DEFAULT 'none'"),
    ("agent_terminal", "BOOLEAN DEFAULT FALSE"),
    ("catalog_tier", "VARCHAR(20) DEFAULT 'basic'"),
    ("custom_code_allowed", "BOOLEAN DEFAULT FALSE"),
    ("idle_sleep_minutes", "INTEGER DEFAULT 30"),
    ("backup_retention_days", "INTEGER DEFAULT 7"),
    ("upgrade_window", "BOOLEAN DEFAULT FALSE"),
    ("support_level", "VARCHAR(20) DEFAULT 'email'"),
]


def upgrade() -> None:
    for name, ddl in COLUMNS:
        op.execute(f"ALTER TABLE packages ADD COLUMN IF NOT EXISTS {name} {ddl}")


def downgrade() -> None:
    for name, _ in reversed(COLUMNS):
        op.execute(f"ALTER TABLE packages DROP COLUMN IF EXISTS {name}")

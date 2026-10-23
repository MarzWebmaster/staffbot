"""Baseline: schema as it existed before Alembic (Oct 2026).

Existing production databases are stamped at this revision
(`alembic stamp 0001_baseline`) and then upgraded. No schema changes.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-10-23
"""

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

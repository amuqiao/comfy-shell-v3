"""create items table

Revision ID: 0001_create_items
Revises:
Create Date: 2026-07-22
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0001_create_items"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "items",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.String(length=64), nullable=True),
        sa.CheckConstraint("status IN ('draft', 'active', 'archived')", name="ck_items_status"),
        sa.CheckConstraint("version >= 1", name="ck_items_version_positive"),
    )
    op.create_index("ix_items_deleted_at", "items", ["deleted_at"])
    op.create_index("ix_items_owner_status_created_id", "items", ["owner_id", "status", "created_at", "id"])
    op.create_index(
        "uq_items_owner_name_active",
        "items",
        ["owner_id", "name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_items_owner_name_active", table_name="items", postgresql_where=sa.text("deleted_at IS NULL"))
    op.drop_index("ix_items_owner_status_created_id", table_name="items")
    op.drop_index("ix_items_deleted_at", table_name="items")
    op.drop_table("items")


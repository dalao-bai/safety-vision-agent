"""reviews and remediations

Revision ID: 20260603_0002
Revises: 20260603_0001
Create Date: 2026-06-03
"""

from alembic import op
import sqlalchemy as sa


revision = "20260603_0002"
down_revision = "20260603_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("human_reviews", sa.Column("item_type", sa.String(length=32), nullable=False, server_default="hazard"))
    op.add_column("human_reviews", sa.Column("item_index", sa.Integer(), nullable=False, server_default="0"))
    op.create_table(
        "remediation_tasks",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("conversation_id", sa.String(length=64), nullable=True),
        sa.Column("analysis_id", sa.String(length=64), nullable=False),
        sa.Column("hazard_index", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("recommendation", sa.Text(), nullable=False),
        sa.Column("responsible_person", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("hazard_json", sa.JSON(), nullable=False),
        sa.Column("due_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_remediation_tasks_analysis_id", "remediation_tasks", ["analysis_id"])
    op.create_table(
        "remediation_evidence",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("remediation_task_id", sa.String(length=64), nullable=False),
        sa.Column("image_path", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_remediation_evidence_task_id", "remediation_evidence", ["remediation_task_id"])


def downgrade() -> None:
    op.drop_index("ix_remediation_evidence_task_id", table_name="remediation_evidence")
    op.drop_table("remediation_evidence")
    op.drop_index("ix_remediation_tasks_analysis_id", table_name="remediation_tasks")
    op.drop_table("remediation_tasks")
    op.drop_column("human_reviews", "item_index")
    op.drop_column("human_reviews", "item_type")

"""annotation feedback loop

Revision ID: 20260603_0003
Revises: 20260603_0002
Create Date: 2026-06-03
"""

from alembic import op
import sqlalchemy as sa


revision = "20260603_0003"
down_revision = "20260603_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "annotation_batches",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "annotation_samples",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("batch_id", sa.String(length=64), nullable=True),
        sa.Column("analysis_id", sa.String(length=64), nullable=True),
        sa.Column("conversation_id", sa.String(length=64), nullable=True),
        sa.Column("image_path", sa.Text(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("model_output_json", sa.JSON(), nullable=False),
        sa.Column("yolo_output_json", sa.JSON(), nullable=False),
        sa.Column("fused_result_json", sa.JSON(), nullable=False),
        sa.Column("draft_json", sa.JSON(), nullable=False),
        sa.Column("review_json", sa.JSON(), nullable=False),
        sa.Column("accepted_record_json", sa.JSON(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_annotation_samples_batch_id", "annotation_samples", ["batch_id"])
    op.create_index("ix_annotation_samples_analysis_id", "annotation_samples", ["analysis_id"])
    op.create_table(
        "annotation_object_drafts",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("sample_id", sa.String(length=64), nullable=False),
        sa.Column("draft_object_index", sa.Integer(), nullable=False),
        sa.Column("object_json", sa.JSON(), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("revised_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_annotation_object_drafts_sample_id", "annotation_object_drafts", ["sample_id"])
    op.create_table(
        "training_candidates",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("sample_id", sa.String(length=64), nullable=False),
        sa.Column("analysis_id", sa.String(length=64), nullable=True),
        sa.Column("candidate_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("source_reason", sa.String(length=128), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_training_candidates_sample_id", "training_candidates", ["sample_id"])


def downgrade() -> None:
    op.drop_index("ix_training_candidates_sample_id", table_name="training_candidates")
    op.drop_table("training_candidates")
    op.drop_index("ix_annotation_object_drafts_sample_id", table_name="annotation_object_drafts")
    op.drop_table("annotation_object_drafts")
    op.drop_index("ix_annotation_samples_analysis_id", table_name="annotation_samples")
    op.drop_index("ix_annotation_samples_batch_id", table_name="annotation_samples")
    op.drop_table("annotation_samples")
    op.drop_table("annotation_batches")

"""Add vision_events and vision_benchmark_results tables.

Revision ID: 020_add_vision_events
Revises: 019_add_public_registration_token
Create Date: 2026-08-18 12:40:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '020_add_vision_events'
down_revision = '019_add_public_registration_token'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'vision_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('match_id', sa.Integer(), nullable=True),
        sa.Column('rally_id', sa.String(), nullable=True),
        sa.Column('candidate_id', sa.String(), nullable=True),
        sa.Column('action_id', sa.String(), nullable=True),
        sa.Column('event_type', sa.String(), nullable=True),
        sa.Column('suggested_winner', sa.String(), nullable=True),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('status', sa.String(), nullable=True),
        sa.Column('ball_x', sa.Float(), nullable=True),
        sa.Column('ball_y', sa.Float(), nullable=True),
        sa.Column('monotonic_timestamp', sa.Float(), nullable=True),
        sa.Column('utc_timestamp', sa.DateTime(), nullable=True),
        sa.Column('detected_events_json', sa.Text(), nullable=True),
        sa.Column('source', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['match_id'], ['matches.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('vision_events', schema=None) as batch_op:
        batch_op.create_index('ix_vision_events_match_id', ['match_id'], unique=False)
        batch_op.create_index('ix_vision_events_rally_id', ['rally_id'], unique=False)
        batch_op.create_index('ix_vision_events_candidate_id', ['candidate_id'], unique=False)
        batch_op.create_index('ix_vision_events_action_id', ['action_id'], unique=False)
        batch_op.create_index('ix_vision_events_event_type', ['event_type'], unique=False)
        batch_op.create_index('ix_vision_events_utc_timestamp', ['utc_timestamp'], unique=False)
        batch_op.create_index('ix_vision_events_created_at', ['created_at'], unique=False)

    op.create_table(
        'vision_benchmark_results',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('model_version', sa.String(), nullable=True),
        sa.Column('detector_backend', sa.String(), nullable=True),
        sa.Column('algorithm_version', sa.String(), nullable=True),
        sa.Column('dataset_version', sa.String(), nullable=True),
        sa.Column('sample_count', sa.Integer(), nullable=True),
        sa.Column('precision', sa.Float(), nullable=True),
        sa.Column('recall', sa.Float(), nullable=True),
        sa.Column('wrong_award_count', sa.Integer(), nullable=True),
        sa.Column('wrong_award_rate', sa.Float(), nullable=True),
        sa.Column('tested_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('vision_benchmark_results', schema=None) as batch_op:
        batch_op.create_index('ix_vision_benchmark_results_detector_backend', ['detector_backend'], unique=False)
        batch_op.create_index('ix_vision_benchmark_results_tested_at', ['tested_at'], unique=False)
        batch_op.create_index('ix_vision_benchmark_results_created_at', ['created_at'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('vision_benchmark_results', schema=None) as batch_op:
        batch_op.drop_index('ix_vision_benchmark_results_created_at')
        batch_op.drop_index('ix_vision_benchmark_results_tested_at')
        batch_op.drop_index('ix_vision_benchmark_results_detector_backend')

    op.drop_table('vision_benchmark_results')

    with op.batch_alter_table('vision_events', schema=None) as batch_op:
        batch_op.drop_index('ix_vision_events_created_at')
        batch_op.drop_index('ix_vision_events_utc_timestamp')
        batch_op.drop_index('ix_vision_events_event_type')
        batch_op.drop_index('ix_vision_events_action_id')
        batch_op.drop_index('ix_vision_events_candidate_id')
        batch_op.drop_index('ix_vision_events_rally_id')
        batch_op.drop_index('ix_vision_events_match_id')

    op.drop_table('vision_events')

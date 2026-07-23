"""Add match_point_events table for advanced analytics

Revision ID: 016_add_match_point_events
Revises: 015_add_tournament_archive
Create Date: 2026-07-22 10:50:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '016_add_match_point_events'
down_revision = '015_add_tournament_archive'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'match_point_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('match_id', sa.Integer(), nullable=True),
        sa.Column('game_index', sa.Integer(), nullable=False),
        sa.Column('point_index', sa.Integer(), nullable=False),
        sa.Column('scorer_side', sa.String(), nullable=False),
        sa.Column('player_a_id', sa.Integer(), nullable=True),
        sa.Column('player_b_id', sa.Integer(), nullable=True),
        sa.Column('score_a_before', sa.Integer(), nullable=False),
        sa.Column('score_b_before', sa.Integer(), nullable=False),
        sa.Column('score_a_after', sa.Integer(), nullable=False),
        sa.Column('score_b_after', sa.Integer(), nullable=False),
        sa.Column('games_a_before', sa.Integer(), nullable=False),
        sa.Column('games_b_before', sa.Integer(), nullable=False),
        sa.Column('games_a_after', sa.Integer(), nullable=False),
        sa.Column('games_b_after', sa.Integer(), nullable=False),
        sa.Column('game_target', sa.Integer(), nullable=False),
        sa.Column('best_of', sa.Integer(), nullable=False),
        sa.Column('is_game_winning_point', sa.Boolean(), default=False),
        sa.Column('is_match_winning_point', sa.Boolean(), default=False),
        sa.Column('timestamp', sa.Float(), nullable=True),
        sa.Column('source', sa.String(), nullable=True),
        sa.Column('server_id', sa.String(), nullable=True),
        sa.Column('rally_length', sa.Integer(), nullable=True),
        sa.Column('end_reason', sa.String(), nullable=True),
        sa.Column('shot_type', sa.String(), nullable=True),
        sa.Column('placement', sa.String(), nullable=True),
        sa.Column('notes', sa.String(), nullable=True),
        sa.Column('event_json', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['match_id'], ['matches.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_match_point_events_id', 'match_point_events', ['id'], unique=False)
    op.create_index('ix_match_point_events_match_id', 'match_point_events', ['match_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_match_point_events_match_id', table_name='match_point_events')
    op.drop_index('ix_match_point_events_id', table_name='match_point_events')
    op.drop_table('match_point_events')

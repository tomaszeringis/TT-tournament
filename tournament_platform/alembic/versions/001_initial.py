"""Initial migration: Create Player, Tournament, and Match tables

Revision ID: 001_initial
Revises:
Create Date: 2026-06-17 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '001_initial'
down_revision = None
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Create Player table
    op.create_table(
        'players',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=True),
        sa.Column('email', sa.String(), nullable=True),
        sa.Column('rating', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )
    op.create_index('ix_players_id', 'players', ['id'], unique=False)
    op.create_index('ix_players_name', 'players', ['name'], unique=False)

    # Create Tournament table
    op.create_table(
        'tournaments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=True),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )
    op.create_index('ix_tournaments_id', 'tournaments', ['id'], unique=False)
    op.create_index('ix_tournaments_name', 'tournaments', ['name'], unique=False)

    # Create Match table with foreign key to Tournament
    op.create_table(
        'matches',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('player1', sa.String(), nullable=True),
        sa.Column('player2', sa.String(), nullable=True),
        sa.Column('winner', sa.String(), nullable=True),
        sa.Column('score', sa.String(), nullable=True),
        sa.Column('status', sa.Enum('pending', 'active', 'completed', name='matchstatus'), nullable=True),
        sa.Column('tournament_id', sa.Integer(), nullable=True),
        sa.Column('scheduled_time', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['tournament_id'], ['tournaments.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_matches_id', 'matches', ['id'], unique=False)

def downgrade() -> None:
    op.drop_index('ix_matches_id', table_name='matches')
    op.drop_table('matches')
    op.drop_index('ix_tournaments_name', table_name='tournaments')
    op.drop_index('ix_tournaments_id', table_name='tournaments')
    op.drop_table('tournaments')
    op.drop_index('ix_players_name', table_name='players')
    op.drop_index('ix_players_id', table_name='players')
    op.drop_table('players')


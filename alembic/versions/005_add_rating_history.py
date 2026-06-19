"""Add rating_history table

Revision ID: 005
Revises: 004
Create Date: 2026-06-19 11:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '005'
down_revision = '004'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        'rating_history',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('player_id', sa.Integer(), nullable=True),
        sa.Column('rating', sa.Integer(), nullable=True),
        sa.Column('timestamp', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['player_id'], ['players.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_rating_history_id'), 'rating_history', ['id'], unique=False)
    
    # Initialize history for existing players
    op.execute("INSERT INTO rating_history (player_id, rating, timestamp) SELECT id, rating, DATETIME('now') FROM players")

def downgrade() -> None:
    op.drop_index(op.f('ix_rating_history_id'), table_name='rating_history')
    op.drop_table('rating_history')

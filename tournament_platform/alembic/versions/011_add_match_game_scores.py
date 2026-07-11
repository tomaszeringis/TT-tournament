"""Add game_scores column to Match

Revision ID: 011_add_match_game_scores
Revises: 010_add_voice_event_models
Create Date: 2026-07-11 15:09:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '011_add_match_game_scores'
down_revision = '010_add_voice_event_models'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('matches', schema=None) as batch_op:
        batch_op.add_column(sa.Column('game_scores', sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('matches', schema=None) as batch_op:
        batch_op.drop_column('game_scores')

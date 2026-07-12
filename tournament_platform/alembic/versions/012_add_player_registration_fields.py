"""Add player registration fields for onboarding workflow

Revision ID: 012_add_player_registration_fields
Revises: 011_add_match_game_scores
Create Date: 2026-07-12 09:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '012_add_player_registration_fields'
down_revision = '011_add_match_game_scores'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('players', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('import_source', sa.String(), nullable=True)
        )
        batch_op.add_column(
            sa.Column('registration_status', sa.String(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table('players', schema=None) as batch_op:
        batch_op.drop_column('registration_status')
        batch_op.drop_column('import_source')

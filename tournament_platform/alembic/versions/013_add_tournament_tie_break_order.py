"""Add tie_break_order column to tournaments

Revision ID: 013_add_tournament_tie_break_order
Revises: 012_add_player_registration_fields
Create Date: 2026-07-13 10:35:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '013_add_tournament_tie_break_order'
down_revision = '012_add_player_registration_fields'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('tournaments', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('tie_break_order', sa.Text(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table('tournaments', schema=None) as batch_op:
        batch_op.drop_column('tie_break_order')

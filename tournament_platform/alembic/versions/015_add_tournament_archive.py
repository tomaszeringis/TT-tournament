"""Add is_archived column to tournaments

Revision ID: 015_add_tournament_archive
Revises: 014_add_commentary_events
Create Date: 2026-07-17 10:15:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '015_add_tournament_archive'
down_revision = '014_add_commentary_events'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('tournaments', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('is_archived', sa.Boolean(), server_default='0', nullable=False)
        )


def downgrade() -> None:
    with op.batch_alter_table('tournaments', schema=None) as batch_op:
        batch_op.drop_column('is_archived')

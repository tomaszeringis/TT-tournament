"""Add public_registration_token to tournaments table.

Revision ID: 019_add_public_registration_token
Revises: 018_make_stage_entry_event_id_nullable
Create Date: 2026-07-24 13:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '019_add_public_registration_token'
down_revision = '018_make_stage_entry_event_id_nullable'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('tournaments', schema=None) as batch_op:
        batch_op.add_column(sa.Column('public_registration_token', sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('tournaments', schema=None) as batch_op:
        batch_op.drop_column('public_registration_token')
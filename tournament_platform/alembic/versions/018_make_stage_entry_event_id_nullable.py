"""Make stage and entry event_id nullable.

Revision ID: 018_make_stage_entry_event_id_nullable
Revises: 017_add_registration_and_checkin
Create Date: 2026-07-24 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '018_make_stage_entry_event_id_nullable'
down_revision = '017_add_registration_and_checkin'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('stages', schema=None) as batch_op:
        batch_op.alter_column('event_id', existing_type=sa.Integer(), nullable=True)

    with op.batch_alter_table('entries', schema=None) as batch_op:
        batch_op.alter_column('event_id', existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    with op.batch_alter_table('entries', schema=None) as batch_op:
        batch_op.alter_column('event_id', existing_type=sa.Integer(), nullable=False)

    with op.batch_alter_table('stages', schema=None) as batch_op:
        batch_op.alter_column('event_id', existing_type=sa.Integer(), nullable=False)

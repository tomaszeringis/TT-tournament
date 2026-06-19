"""Add bracket fields

Revision ID: 002
Revises: 001_initial
Create Date: 2026-06-18 16:50:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '002'
down_revision = '001_initial'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Use batch_alter_table for SQLite compatibility
    with op.batch_alter_table('matches') as batch_op:
        batch_op.add_column(sa.Column('round_number', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('bracket_index', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('next_match_id', sa.Integer(), sa.ForeignKey('matches.id', name='fk_match_next_match'), nullable=True))

def downgrade() -> None:
    # SQLite doesn't support dropping columns easily (needs table recreation)
    # But Alembic's batch_alter_table can handle it.
    with op.batch_alter_table('matches') as batch_op:
        batch_op.drop_column('next_match_id')
        batch_op.drop_column('bracket_index')
        batch_op.drop_column('round_number')

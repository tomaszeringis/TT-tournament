"""Add location to Match

Revision ID: 003_add_location
Revises: 002_add_bracket_fields
Create Date: 2026-06-18 17:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '003_add_location'
down_revision = '002_add_bracket_fields'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column('matches', sa.Column('location', sa.String(), nullable=True))

def downgrade() -> None:
    with op.batch_alter_table('matches') as batch_op:
        batch_op.drop_column('location')

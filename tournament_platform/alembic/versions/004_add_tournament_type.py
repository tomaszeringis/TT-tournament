"""Add tournament_type to Tournament

Revision ID: 004_add_tournament_type
Revises: 003_add_location
Create Date: 2026-06-19 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '004_add_tournament_type'
down_revision = '003_add_location'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Use batch_alter_table for SQLite compatibility
    with op.batch_alter_table('tournaments') as batch_op:
        batch_op.add_column(sa.Column('tournament_type', sa.Enum('knockout', 'round-robin', name='tournamenttype'), nullable=True))
    
    # Update existing rows to 'knockout'
    op.execute("UPDATE tournaments SET tournament_type = 'knockout' WHERE tournament_type IS NULL")

def downgrade() -> None:
    with op.batch_alter_table('tournaments') as batch_op:
        batch_op.drop_column('tournament_type')

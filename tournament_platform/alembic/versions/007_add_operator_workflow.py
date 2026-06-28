"""Add operator workflow models: VenueTable, Match operator fields, Announcement, AuditLog

Revision ID: 007
Revises: 006
Create Date: 2026-06-27 14:54:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '007'
down_revision = '006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create venue_tables table
    op.create_table(
        'venue_tables',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=True),
        sa.Column('is_active', sa.Integer(), nullable=True, server_default='1'),
        sa.Column('notes', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )
    op.create_index('ix_venue_tables_id', 'venue_tables', ['id'], unique=False)

    # Create announcements table
    op.create_table(
        'announcements',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('match_id', sa.Integer(), nullable=True),
        sa.Column('tournament_id', sa.Integer(), nullable=True),
        sa.Column('message', sa.String(), nullable=True),
        sa.Column('channel', sa.String(), nullable=True, server_default='local'),
        sa.Column('sent_status', sa.String(), nullable=True, server_default='pending'),
        sa.Column('error', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['match_id'], ['matches.id'], ),
        sa.ForeignKeyConstraint(['tournament_id'], ['tournaments.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_announcements_id', 'announcements', ['id'], unique=False)

    # Create audit_log table
    op.create_table(
        'audit_log',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('actor', sa.String(), nullable=True, server_default='operator'),
        sa.Column('action', sa.String(), nullable=True),
        sa.Column('entity_type', sa.String(), nullable=True),
        sa.Column('entity_id', sa.Integer(), nullable=True),
        sa.Column('payload_json', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_audit_log_id', 'audit_log', ['id'], unique=False)

    # Add operator workflow fields to matches table
    # Use batch_alter_table for SQLite compatibility
    with op.batch_alter_table('matches') as batch_op:
        batch_op.add_column(sa.Column('call_status', sa.String(), nullable=True, server_default='not_called'))
        batch_op.add_column(sa.Column('called_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('started_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('completed_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('delayed_until', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('operator_note', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('updated_at', sa.DateTime(), nullable=True, server_default=sa.func.now()))


def downgrade() -> None:
    # Remove operator workflow fields from matches table
    with op.batch_alter_table('matches') as batch_op:
        batch_op.drop_column('operator_note')
        batch_op.drop_column('delayed_until')
        batch_op.drop_column('completed_at')
        batch_op.drop_column('started_at')
        batch_op.drop_column('called_at')
        batch_op.drop_column('call_status')
        batch_op.drop_column('updated_at')

    # Drop tables
    op.drop_index('ix_audit_log_id', table_name='audit_log')
    op.drop_table('audit_log')

    op.drop_index('ix_announcements_id', table_name='announcements')
    op.drop_table('announcements')

    op.drop_index('ix_venue_tables_id', table_name='venue_tables')
    op.drop_table('venue_tables')
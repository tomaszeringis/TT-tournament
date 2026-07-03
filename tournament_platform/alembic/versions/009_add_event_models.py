"""Add event and stage models for multi-phase tournaments

Revision ID: 009_add_event_models
Revises: 008_add_multimodal_models
Create Date: 2026-07-02 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '009_add_event_models'
down_revision = '008_add_multimodal_models'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create events table
    op.create_table(
        'events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=True),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('event_type', sa.String(), nullable=True, server_default='knockout'),
        sa.Column('num_groups', sa.Integer(), nullable=True),
        sa.Column('qualifiers_per_group', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )
    op.create_index('ix_events_id', 'events', ['id'], unique=False)

    # Create stages table
    op.create_table(
        'stages',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('event_id', sa.Integer(), nullable=True),
        sa.Column('stage_type', sa.String(), nullable=True),
        sa.Column('name', sa.String(), nullable=True),
        sa.Column('order_index', sa.Integer(), nullable=True, server_default='0'),
        sa.ForeignKeyConstraint(['event_id'], ['events.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_stages_id', 'stages', ['id'], unique=False)

    # Create groups table
    op.create_table(
        'groups',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('stage_id', sa.Integer(), nullable=True),
        sa.Column('name', sa.String(), nullable=True),
        sa.Column('order_index', sa.Integer(), nullable=True, server_default='0'),
        sa.ForeignKeyConstraint(['stage_id'], ['stages.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_groups_id', 'groups', ['id'], unique=False)

    # Create entries table
    op.create_table(
        'entries',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('event_id', sa.Integer(), nullable=True),
        sa.Column('group_id', sa.Integer(), nullable=True),
        sa.Column('player1_id', sa.Integer(), nullable=True),
        sa.Column('player2_id', sa.Integer(), nullable=True),
        sa.Column('seed_position', sa.Integer(), nullable=True),
        sa.Column('club', sa.String(), nullable=True),
        sa.Column('division', sa.String(), nullable=True),
        sa.ForeignKeyConstraint(['event_id'], ['events.id'], ),
        sa.ForeignKeyConstraint(['group_id'], ['groups.id'], ),
        sa.ForeignKeyConstraint(['player1_id'], ['players.id'], ),
        sa.ForeignKeyConstraint(['player2_id'], ['players.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_entries_id', 'entries', ['id'], unique=False)

    # Create scorer_tokens table
    op.create_table(
        'scorer_tokens',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('token', sa.String(), nullable=True),
        sa.Column('match_id', sa.Integer(), nullable=True),
        sa.Column('table_id', sa.Integer(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('revoked', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['match_id'], ['matches.id'], ),
        sa.ForeignKeyConstraint(['table_id'], ['venue_tables.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token')
    )
    op.create_index('ix_scorer_tokens_id', 'scorer_tokens', ['id'], unique=False)

    # Add stage_id to matches table using batch mode for SQLite
    with op.batch_alter_table('matches') as batch_op:
        batch_op.add_column(sa.Column('stage_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('matches_stage_id_fkey', 'stages', ['stage_id'], ['id'])


def downgrade() -> None:
    # Remove stage_id from matches using batch mode for SQLite
    with op.batch_alter_table('matches') as batch_op:
        batch_op.drop_constraint('matches_stage_id_fkey', type_='foreignkey')
        batch_op.drop_column('stage_id')

    # Drop tables in reverse order
    op.drop_index('ix_scorer_tokens_id', table_name='scorer_tokens')
    op.drop_table('scorer_tokens')

    op.drop_index('ix_entries_id', table_name='entries')
    op.drop_table('entries')

    op.drop_index('ix_groups_id', table_name='groups')
    op.drop_table('groups')

    op.drop_index('ix_stages_id', table_name='stages')
    op.drop_table('stages')

    op.drop_index('ix_events_id', table_name='events')
    op.drop_table('events')
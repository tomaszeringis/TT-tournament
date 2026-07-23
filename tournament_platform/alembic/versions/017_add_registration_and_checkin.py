"""Add tournament_participants table and registration fields to tournaments.

This is the forward migration for Phase 1A:
- Add `registration_open` (Boolean, default False) to tournaments.
- Add `public_registration_token_hash` (String(64), nullable, indexed) to tournaments.
- Create `tournament_participants` table with status, check-in, duplicate, and bracket fields.

Revision ID: 017_add_registration_and_checkin
Revises: 016_add_match_point_events
Create Date: 2026-07-22 17:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '017_add_registration_and_checkin'
down_revision = '016_add_match_point_events'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('tournaments', schema=None) as batch_op:
        batch_op.add_column(sa.Column('registration_open', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('public_registration_token_hash', sa.String(length=64), nullable=True))
        batch_op.create_index('ix_tournaments_public_registration_token_hash', ['public_registration_token_hash'], unique=False)

    op.create_table(
        'tournament_participants',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tournament_id', sa.Integer(), nullable=False),
        sa.Column('player_id', sa.Integer(), nullable=False),
        sa.Column('display_name', sa.String(), nullable=False),
        sa.Column('department', sa.String(), nullable=True),
        sa.Column('email_hash', sa.String(length=64), nullable=True),
        sa.Column('employee_id_hash', sa.String(length=64), nullable=True),
        sa.Column('checked_in', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('checked_in_at', sa.DateTime(), nullable=True),
        sa.Column('registration_source', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('duplicate_status', sa.String(), nullable=True),
        sa.Column('duplicate_of_participant_id', sa.Integer(), nullable=True),
        sa.Column('bracket_eligible', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['duplicate_of_participant_id'], ['tournament_participants.id'], ),
        sa.ForeignKeyConstraint(['player_id'], ['players.id'], ),
        sa.ForeignKeyConstraint(['tournament_id'], ['tournaments.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_tournament_participants_tournament_id', 'tournament_participants', ['tournament_id'], unique=False)
    op.create_index('ix_tournament_participants_checked_in', 'tournament_participants', ['tournament_id', 'checked_in'], unique=False)
    op.create_index('ix_tournament_participants_duplicate_status', 'tournament_participants', ['tournament_id', 'duplicate_status'], unique=False)
    op.create_index('ix_tournament_participants_email_hash', 'tournament_participants', ['email_hash'], unique=False)
    op.create_index('ix_tournament_participants_player_id', 'tournament_participants', ['player_id'], unique=False)
    op.create_index('ix_tournament_participants_tournament_player', 'tournament_participants', ['tournament_id', 'player_id'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_tournament_participants_tournament_player', table_name='tournament_participants')
    op.drop_index('ix_tournament_participants_player_id', table_name='tournament_participants')
    op.drop_index('ix_tournament_participants_email_hash', table_name='tournament_participants')
    op.drop_index('ix_tournament_participants_duplicate_status', table_name='tournament_participants')
    op.drop_index('ix_tournament_participants_checked_in', table_name='tournament_participants')
    op.drop_index('ix_tournament_participants_tournament_id', table_name='tournament_participants')
    op.drop_table('tournament_participants')

    with op.batch_alter_table('tournaments', schema=None) as batch_op:
        batch_op.drop_index('ix_tournaments_public_registration_token_hash')
        batch_op.drop_column('public_registration_token_hash')
        batch_op.drop_column('registration_open')

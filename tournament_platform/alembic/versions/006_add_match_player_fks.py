"""Add player foreign keys to Match

 Revision ID: 006
 Revises: 005
 Create Date: 2026-06-26 08:34:00.000000

 """
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '006'
down_revision = '005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Check if columns already exist (for idempotent migration)
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [col['name'] for col in inspector.get_columns('matches')]
    
    # Add columns if they don't exist
    with op.batch_alter_table('matches', schema=None) as batch_op:
        if 'player1_id' not in columns:
            batch_op.add_column(sa.Column('player1_id', sa.Integer(), nullable=True))
        if 'player2_id' not in columns:
            batch_op.add_column(sa.Column('player2_id', sa.Integer(), nullable=True))
        if 'winner_id' not in columns:
            batch_op.add_column(sa.Column('winner_id', sa.Integer(), nullable=True))
    
    # Check existing foreign keys
    existing_fks = inspector.get_foreign_keys('matches')
    existing_fk_names = {fk['name'] for fk in existing_fks if fk['name']}
    
    # Create foreign key constraints if they don't exist
    with op.batch_alter_table('matches', schema=None) as batch_op:
        if 'fk_match_player1' not in existing_fk_names:
            batch_op.create_foreign_key('fk_match_player1', 'players', ['player1_id'], ['id'])
        if 'fk_match_player2' not in existing_fk_names:
            batch_op.create_foreign_key('fk_match_player2', 'players', ['player2_id'], ['id'])
        if 'fk_match_winner' not in existing_fk_names:
            batch_op.create_foreign_key('fk_match_winner', 'players', ['winner_id'], ['id'])


def downgrade() -> None:
    # Check existing foreign keys
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_fks = inspector.get_foreign_keys('matches')
    existing_fk_names = {fk['name'] for fk in existing_fks if fk['name']}
    
    with op.batch_alter_table('matches', schema=None) as batch_op:
        if 'fk_match_winner' in existing_fk_names:
            batch_op.drop_constraint('fk_match_winner', type_='foreignkey')
        if 'fk_match_player2' in existing_fk_names:
            batch_op.drop_constraint('fk_match_player2', type_='foreignkey')
        if 'fk_match_player1' in existing_fk_names:
            batch_op.drop_constraint('fk_match_player1', type_='foreignkey')
        
        # Only drop columns if they exist
        columns = [col['name'] for col in inspector.get_columns('matches')]
        if 'winner_id' in columns:
            batch_op.drop_column('winner_id')
        if 'player2_id' in columns:
            batch_op.drop_column('player2_id')
        if 'player1_id' in columns:
            batch_op.drop_column('player1_id')

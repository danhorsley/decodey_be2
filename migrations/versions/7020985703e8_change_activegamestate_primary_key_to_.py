
"""Change ActiveGameState primary key to auto-increment ID

Revision ID: 7020985703e8
Revises: 53f9ed7981ee
Create Date: 2024-04-21 14:18:38.123456

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '7020985703e8'
down_revision = '53f9ed7981ee'
branch_labels = None
depends_on = None

def upgrade():
    # Create sequence for ID
    op.execute('CREATE SEQUENCE IF NOT EXISTS active_game_state_id_seq')
    
    # Add ID column with sequence
    op.add_column('active_game_state',
        sa.Column('id', sa.Integer(), sa.Sequence('active_game_state_id_seq'), nullable=False)
    )
    
    # Drop the primary key constraint on user_id
    op.drop_constraint('active_game_state_pkey', 'active_game_state')
    
    # Create new primary key on id
    op.create_primary_key('active_game_state_pkey', 'active_game_state', ['id'])
    
    # Create index on user_id
    op.create_index('idx_active_game_userid', 'active_game_state', ['user_id'])

def downgrade():
    op.drop_constraint('active_game_state_pkey', 'active_game_state')
    op.drop_column('active_game_state', 'id')
    op.create_primary_key('active_game_state_pkey', 'active_game_state', ['user_id'])
    op.drop_index('idx_active_game_userid')

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
    # Try dropping the primary key first if it exists
    try:
        op.drop_constraint('active_game_state_pkey', 'active_game_state', type_='primary')
    except:
        pass

    # Check if ID column exists and create it if it doesn't
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c['name'] for c in inspector.get_columns('active_game_state')]

    if 'id' not in columns:
        op.add_column('active_game_state', sa.Column('id', sa.Integer(), nullable=False))

    # Create primary key
    op.create_primary_key('active_game_state_pkey', 'active_game_state', ['id'])

def downgrade():
    op.drop_constraint('active_game_state_pkey', 'active_game_state', type_='primary')
    op.drop_column('active_game_state', 'id')
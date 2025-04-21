"""Change ActiveGameState primary key to auto-increment ID

Revision ID: 9d43019cd49c
Revises: 53f9ed7981ee
Create Date: 2025-04-21 13:32:16.542431

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '9d43019cd49c'
down_revision = '7020985703e8'
branch_labels = None
depends_on = None

def upgrade():
    # Create sequence and ID column
    op.execute("CREATE SEQUENCE IF NOT EXISTS active_game_state_id_seq")
    op.add_column('active_game_state', sa.Column('id', sa.Integer(), nullable=True))

    # Populate IDs
    op.execute("UPDATE active_game_state SET id = nextval('active_game_state_id_seq')")

    # Make ID not nullable and set as primary key
    op.alter_column('active_game_state', 'id', nullable=False)
    op.execute("ALTER TABLE active_game_state ALTER COLUMN id SET DEFAULT nextval('active_game_state_id_seq')")
    op.execute("ALTER SEQUENCE active_game_state_id_seq OWNED BY active_game_state.id")

def downgrade():
    op.drop_column('active_game_state', 'id')
    op.execute("DROP SEQUENCE IF EXISTS active_game_state_id_seq")
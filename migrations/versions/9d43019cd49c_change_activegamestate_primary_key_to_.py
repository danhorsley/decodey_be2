"""Change ActiveGameState primary key to auto-increment ID

Revision ID: 9d43019cd49c
Revises: e6a99aee04dd
Create Date: 2025-04-21 13:32:16.542431

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9d43019cd49c'
down_revision = 'e6a99aee04dd'
branch_labels = None
depends_on = None


def upgrade():
    # Drop the sequence if it exists
    op.execute("DROP SEQUENCE IF EXISTS active_game_state_id_seq CASCADE")
    
    # Create a new sequence
    op.execute("CREATE SEQUENCE active_game_state_id_seq")
    
    # Set the sequence as the default for the id column
    op.execute("ALTER TABLE active_game_state ALTER COLUMN id SET DEFAULT nextval('active_game_state_id_seq')")
    
    # Set the sequence ownership
    op.execute("ALTER SEQUENCE active_game_state_id_seq OWNED BY active_game_state.id")
    
    # Set the sequence to start after the highest existing id
    op.execute("""
    SELECT setval('active_game_state_id_seq', COALESCE((SELECT MAX(id) FROM active_game_state), 0) + 1)
    """)


def downgrade():
    pass

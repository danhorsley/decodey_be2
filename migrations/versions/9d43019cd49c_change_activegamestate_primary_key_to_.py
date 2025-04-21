
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
    # Drop existing constraints and sequence
    op.execute("ALTER TABLE active_game_state DROP CONSTRAINT IF EXISTS active_game_state_pkey CASCADE")
    op.execute("DROP SEQUENCE IF EXISTS active_game_state_id_seq CASCADE")
    
    # Create new sequence
    op.execute("CREATE SEQUENCE active_game_state_id_seq")
    
    # Ensure the sequence starts after any existing IDs
    op.execute("SELECT setval('active_game_state_id_seq', COALESCE((SELECT MAX(id) FROM active_game_state), 0) + 1, false)")
    
    # Drop and recreate id column
    op.execute("ALTER TABLE active_game_state DROP COLUMN IF EXISTS id CASCADE")
    op.execute("ALTER TABLE active_game_state ADD COLUMN id INTEGER")
    op.execute("ALTER TABLE active_game_state ALTER COLUMN id SET DEFAULT nextval('active_game_state_id_seq')")
    op.execute("ALTER TABLE active_game_state ALTER COLUMN id SET NOT NULL")
    
    # Update sequence ownership
    op.execute("ALTER SEQUENCE active_game_state_id_seq OWNED BY active_game_state.id")
    
    # Add primary key constraint
    op.execute("ALTER TABLE active_game_state ADD PRIMARY KEY (id)")


def downgrade():
    op.execute("ALTER TABLE active_game_state DROP CONSTRAINT IF EXISTS active_game_state_pkey")
    op.execute("ALTER TABLE active_game_state DROP COLUMN id")
    op.execute("DROP SEQUENCE IF EXISTS active_game_state_id_seq")

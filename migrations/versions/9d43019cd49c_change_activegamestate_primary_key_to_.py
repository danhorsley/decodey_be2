
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
    # Drop existing constraints and id column
    op.execute("ALTER TABLE active_game_state DROP CONSTRAINT IF EXISTS active_game_state_pkey CASCADE")
    op.execute("ALTER TABLE active_game_state DROP COLUMN IF EXISTS id CASCADE")
    
    # Create new id column with identity
    op.execute("ALTER TABLE active_game_state ADD COLUMN id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY")


def downgrade():
    op.execute("ALTER TABLE active_game_state DROP COLUMN id")

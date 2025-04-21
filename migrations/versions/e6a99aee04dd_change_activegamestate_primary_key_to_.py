
"""Change ActiveGameState primary key to auto-increment ID

Revision ID: e6a99aee04dd
Revises: 7020985703e8
Create Date: 2025-04-21 13:25:04.572266

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e6a99aee04dd'
down_revision = '9d43019cd49c'
branch_labels = None
depends_on = None


def upgrade():
    # Drop the existing sequence if it exists
    op.execute("DROP SEQUENCE IF EXISTS active_game_state_id_seq")
    
    # Create a new sequence
    op.execute("CREATE SEQUENCE active_game_state_id_seq")
    
    # Set the sequence as owned by the id column
    op.execute("ALTER SEQUENCE active_game_state_id_seq OWNED BY active_game_state.id")
    
    # Set the default value for the id column
    op.execute("ALTER TABLE active_game_state ALTER COLUMN id SET DEFAULT nextval('active_game_state_id_seq')")


def downgrade():
    op.execute("ALTER TABLE active_game_state ALTER COLUMN id DROP DEFAULT")
    op.execute("DROP SEQUENCE IF EXISTS active_game_state_id_seq")

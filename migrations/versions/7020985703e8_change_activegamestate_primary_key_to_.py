"""Change ActiveGameState primary key to auto-increment ID

Revision ID: 7020985703e8
Revises: 53f9ed7981ee
Create Date: 2025-04-21 13:22:43.783644

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7020985703e8'
down_revision = '53f9ed7981ee'
branch_labels = None
depends_on = None


def upgrade():
    # Create sequence first
    op.execute("CREATE SEQUENCE IF NOT EXISTS active_game_state_id_seq")

    # Add the id column as nullable initially
    with op.batch_alter_table('active_game_state', schema=None) as batch_op:
        batch_op.add_column(sa.Column('id', sa.Integer(), nullable=True))

    # Populate the ID column for all existing records using a direct SQL update
    op.execute("""
    UPDATE active_game_state 
    SET id = nextval('active_game_state_id_seq')
    """)

    # Make the ID column non-nullable after populating it
    with op.batch_alter_table('active_game_state', schema=None) as batch_op:
        batch_op.alter_column('id', existing_type=sa.Integer(), nullable=False)

    # Link the sequence to the ID column and set it as default
    op.execute("ALTER TABLE active_game_state ALTER COLUMN id SET DEFAULT nextval('active_game_state_id_seq')")
    op.execute("ALTER SEQUENCE active_game_state_id_seq OWNED BY active_game_state.id")

    # Drop the old primary key and add the new one
    with op.batch_alter_table('active_game_state', schema=None) as batch_op:
        batch_op.drop_constraint('active_game_state_pkey', type_='primary')
        batch_op.create_primary_key('active_game_state_pkey', ['id'])
        batch_op.create_index('idx_active_game_userid', ['user_id'], unique=False)

    # ### end Alembic commands ###


def downgrade():
    with op.batch_alter_table('active_game_state', schema=None) as batch_op:
        batch_op.drop_index('idx_active_game_userid')
        batch_op.drop_constraint('active_game_state_pkey', type_='primary')
        batch_op.create_primary_key('active_game_state_pkey', ['user_id'])
        batch_op.drop_column('id')

    op.execute("DROP SEQUENCE IF EXISTS active_game_state_id_seq")

    # ### end Alembic commands ###

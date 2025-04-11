"""empty message

Revision ID: 0409c118946a
Revises: d617f733a98b
Create Date: 2025-04-11 14:34:07.499728

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0409c118946a'
down_revision = 'd617f733a98b'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('quote', schema=None) as batch_op:
        batch_op.add_column(sa.Column('_daily_date', sa.Date(), nullable=True))
        batch_op.drop_constraint('quote_daily_date_key', type_='unique')
        batch_op.create_unique_constraint(None, ['_daily_date'])
        batch_op.drop_column('daily_date')

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('quote', schema=None) as batch_op:
        batch_op.add_column(sa.Column('daily_date', sa.DATE(), autoincrement=False, nullable=True))
        batch_op.drop_constraint(None, type_='unique')
        batch_op.create_unique_constraint('quote_daily_date_key', ['daily_date'])
        batch_op.drop_column('_daily_date')

    # ### end Alembic commands ###

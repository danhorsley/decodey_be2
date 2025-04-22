
"""Generate unsubscribe tokens for existing users

Revision ID: generate_unsubscribe_tokens
Revises: 7020985703e8
Create Date: 2025-04-22 13:05:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'generate_unsubscribe_tokens'
down_revision = '7020985703e8'
branch_labels = None
depends_on = None

def upgrade():
    # Add unsubscribe_token column
    op.add_column('user', sa.Column('unsubscribe_token', sa.String(100), nullable=True))
    op.create_unique_constraint('uq_user_unsubscribe_token', 'user', ['unsubscribe_token'])

def downgrade():
    op.drop_constraint('uq_user_unsubscribe_token', 'user', type_='unique')
    op.drop_column('user', 'unsubscribe_token')

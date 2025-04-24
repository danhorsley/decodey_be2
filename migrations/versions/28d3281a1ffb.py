"""dummy migration

Revision ID: 28d3281a1ffb
Revises: generate_unsubscribe_tokens
Create Date: 2025-04-24 08:30:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '28d3281a1ffb'
down_revision = 'generate_unsubscribe_tokens'
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass

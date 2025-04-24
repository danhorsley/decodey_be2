
"""Add subadmin column and backdoor table

Revision ID: add_subadmin_and_backdoor
Revises: generate_unsubscribe_tokens
Create Date: 2025-04-23 15:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'add_subadmin_and_backdoor'
down_revision = 'generate_unsubscribe_tokens'
branch_labels = None
depends_on = None

def upgrade():
    # Add subadmin column to user table
    op.add_column('user', sa.Column('subadmin', sa.Boolean(), nullable=True, server_default='false'))

    # Create backdoor table
    op.create_table('backdoor',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('author', sa.String(length=255), nullable=False),
        sa.Column('minor_attribution', sa.String(length=255), nullable=True),
        sa.Column('difficulty', sa.Float(), nullable=True),
        sa.Column('daily_date', sa.Date().with_variant(postgresql.DATE(), 'postgresql'), nullable=True),
        sa.Column('times_used', sa.Integer(), nullable=True),
        sa.Column('unique_letters', sa.Integer(), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('daily_date')
    )

def downgrade():
    op.drop_column('user', 'subadmin')
    op.drop_table('backdoor')

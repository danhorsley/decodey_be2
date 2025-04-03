
"""fix daily date time info

Revision ID: fix_daily_date_time
Revises: 2677feefef63
Create Date: 2025-04-03 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'fix_daily_date_time'
down_revision = '2677feefef63'
branch_labels = None
depends_on = None

def upgrade():
    # Temporarily drop the unique constraint
    op.drop_constraint('quote_daily_date_key', 'quote')
    
    # Convert column to date without time info
    op.execute("ALTER TABLE quote ALTER COLUMN daily_date TYPE date USING daily_date::date")
    
    # Re-add the unique constraint
    op.create_unique_constraint('quote_daily_date_key', 'quote', ['daily_date'])

def downgrade():
    pass

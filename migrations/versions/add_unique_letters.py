
"""add unique letters column

Revision ID: 2677feefef64
Revises: fix_daily_date_time
Create Date: 2025-04-09 12:10:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = '2677feefef64'
down_revision = 'fix_daily_date_time'
branch_labels = None
depends_on = None

def upgrade():
    # Add column
    op.add_column('quote', sa.Column('unique_letters', sa.Integer(), nullable=True))
    
    # Update existing records
    conn = op.get_bind()
    conn.execute(text("""
        UPDATE quote 
        SET unique_letters = (
            SELECT COUNT(DISTINCT letter) 
            FROM regexp_split_to_table(
                upper(regexp_replace(text, '[^A-Za-z]', '', 'g')), 
                ''
            ) AS letter
        )
    """))
    
    # Make column not nullable
    op.alter_column('quote', 'unique_letters', nullable=False)

def downgrade():
    op.drop_column('quote', 'unique_letters')

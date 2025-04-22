
"""Generate unsubscribe tokens for existing users

Revision ID: generate_unsubscribe_tokens
Revises: 7020985703e8
Create Date: 2025-04-22 13:05:00.000000
"""
from alembic import op
import sqlalchemy as sa
import secrets

# revision identifiers, used by Alembic.
revision = 'generate_unsubscribe_tokens'
down_revision = '7020985703e8'
branch_labels = None
depends_on = None

def upgrade():
    connection = op.get_bind()
    users = connection.execute("SELECT user_id FROM \"user\" WHERE unsubscribe_token IS NULL")
    
    for user in users:
        token = secrets.token_urlsafe(32)
        connection.execute(
            "UPDATE \"user\" SET unsubscribe_token = :token WHERE user_id = :user_id",
            {"token": token, "user_id": user[0]}
        )

def downgrade():
    connection = op.get_bind()
    connection.execute("UPDATE \"user\" SET unsubscribe_token = NULL")

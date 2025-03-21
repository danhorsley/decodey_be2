# Add this to app/routes/commands.py or create if it doesn't exist

import click
from flask.cli import with_appcontext
from app.models import db, User
from datetime import datetime


@click.command('create-admin')
@click.argument('username')
@click.option('--email', prompt=True)
@click.option('--password',
              prompt=True,
              hide_input=True,
              confirmation_prompt=True)
@click.option('--admin-password',
              prompt=True,
              hide_input=True,
              confirmation_prompt=True)
@with_appcontext
def create_admin_command(username, email, password, admin_password):
    """Create an admin user."""
    try:
        user = User.query.filter_by(username=username).first()

        if user:
            # Update existing user
            click.echo(
                f"User {username} already exists. Updating admin privileges.")
            user.is_admin = True
            user.set_password(password)
            user.set_admin_password(admin_password)
        else:
            # Create new user with admin privileges
            click.echo(f"Creating new admin user: {username}")
            user = User(username=username, email=email, password=password)
            user.is_admin = True
            user.set_admin_password(admin_password)
            user.created_at = datetime.utcnow()
            db.session.add(user)

        db.session.commit()
        click.echo(f"Admin user {username} created/updated successfully.")

    except Exception as e:
        db.session.rollback()
        click.echo(f"Error creating admin user: {str(e)}", err=True)


# Make sure this is registered in the app
def register_commands(app):
    app.cli.add_command(create_admin_command)

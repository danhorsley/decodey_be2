# app/commands.py or similar
import click
from flask.cli import with_appcontext
from app.models import db, User


@click.command('create-admin')
@click.argument('username')
@click.option('--password',
              prompt=True,
              hide_input=True,
              confirmation_prompt=True)
@click.option('--admin-password',
              prompt=True,
              hide_input=True,
              confirmation_prompt=True)
@with_appcontext
def create_admin_command(username, password, admin_password):
    """Create an admin user."""
    user = User.query.filter_by(username=username).first()

    if not user:
        # Create new user with admin privileges
        user = User(username=username, email=f"{username}@example.com")
        user.set_password(password)
        user.is_admin = True
        user.set_admin_password(admin_password)
        db.session.add(user)
    else:
        # Update existing user
        user.is_admin = True
        user.set_admin_password(admin_password)
        user.set_password(password)

    db.session.commit()
    click.echo(f"Admin user {username} created successfully.")


# Register in app
def register_commands(app):
    app.cli.add_command(create_admin_command)

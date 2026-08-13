from flask.cli import FlaskGroup
from app import create_app, drop_all_tables, db
from app.models.user import User
from werkzeug.security import generate_password_hash

cli = FlaskGroup(create_app=create_app)

@cli.command("drop-tables")
def drop_tables():
    """Drop all database tables."""
    print("Dropping all tables...")
    drop_all_tables()
    print("All tables dropped!")

@cli.command("create-tables")
def create_tables():
    """Create all database tables."""
    print("Creating all tables...")
    db.create_all()
    print("All tables created!")

@cli.command("reset-db")
def reset_db():
    """Reset the database (drop all tables and create new ones)."""
    print("Resetting database...")
    drop_all_tables()
    db.create_all()
    print("Database reset complete!")

@cli.command("reset-db-with-test-user")
def reset_db_with_test_user():
    """Reset the database and create a test user with username='1' and password='1'."""
    print("Resetting database...")
    drop_all_tables()
    db.create_all()
    
    # Hash the password before creating the test user
    hashed_password = generate_password_hash('1', method='pbkdf2:sha256')
    test_user = User(username='1', password=hashed_password)
    db.session.add(test_user)
    db.session.commit()
    
    print("Database reset complete!")
    print("Test user created with username='1' and password='1'")

@cli.command("migrate-phase-prompt")
def migrate_phase_prompt():
    """Migrate Phase.description column to Phase.prompt."""
    try:
        from app.migrations import migrate_phase_description_to_prompt
    except ModuleNotFoundError:
        print("Skipped: app.migrations is not in this repo.")
        return
    print("Migrating Phase.description to Phase.prompt...")
    migrate_phase_description_to_prompt()
    print("Migration completed!")

if __name__ == "__main__":
    cli()

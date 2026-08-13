from datetime import date, datetime, timedelta

from flask.cli import FlaskGroup
from werkzeug.security import generate_password_hash

from app import create_app, drop_all_tables, db
from app.models.user import CRMCustomer, ServiceAppointment, ServiceWorkOrder, User, VoiceCall

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

@cli.command("seed-test-data")
def seed_test_data():
    """Create missing tables, a test login, and sample CRM records."""
    db.create_all()

    email = "a@gmail.com"
    password = "1"
    user = User.query.filter_by(username=email).first()
    if not user:
        user = User(
            username=email,
            email=email,
            password=generate_password_hash(password, method="pbkdf2:sha256"),
            is_admin=True,
        )
        db.session.add(user)
        db.session.flush()
        print(f"Created test user {email}")
    else:
        print(f"Test user {email} already exists")

    if CRMCustomer.query.count() == 0:
        lead = CRMCustomer(
            name="Taylor Green",
            phone="+14165550111",
            email="taylor.green@example.com",
            service_address="210 King St W",
            city="Toronto",
            province="ON",
            postal_code="M5V 2T6",
            pest_issue="Ants in kitchen",
            property_type="apartment",
            status="lead",
            source="voice_agent",
            notes="Wants a callback for a quote.",
        )
        customer = CRMCustomer(
            name="Jordan Lee",
            phone="+19055550122",
            email="jordan.lee@example.com",
            service_address="88 Maple Ave",
            city="Burlington",
            province="ON",
            postal_code="L7M 2R4",
            pest_issue="Rodents in attic",
            property_type="house",
            status="customer",
            source="voice_agent",
            notes="Confirmed booking from Avery.",
        )
        db.session.add_all([lead, customer])
        db.session.flush()

        appointment = ServiceAppointment(
            customer_name=customer.name,
            phone=customer.phone,
            email=customer.email,
            postal_code=customer.postal_code,
            pest_issue=customer.pest_issue,
            preferred_date=date.today() + timedelta(days=2),
            preferred_time="9:00 AM–11:00 AM",
            notes="Attic access through garage.",
            source="voice_agent",
            status="requested",
            twilio_call_sid="CA_test_seed",
        )
        db.session.add(appointment)
        db.session.flush()

        work_order = ServiceWorkOrder(
            customer_id=customer.id,
            appointment_id=appointment.id,
            service=customer.pest_issue,
            scheduled_date=appointment.preferred_date,
            scheduled_time=appointment.preferred_time,
            technician="Alex Rivera",
            priority="routine",
            status="scheduled",
            source="voice_agent",
            notes=appointment.notes,
        )
        db.session.add(work_order)
        db.session.flush()

        db.session.add(VoiceCall(
            twilio_call_sid="CA_test_seed",
            direction="inbound",
            from_number=customer.phone,
            to_number="+12362057547",
            status="completed",
            intent="appointment",
            resolution="appointment_requested",
            summary="Caller booked an attic rodent treatment.",
            duration_seconds=186,
            customer_id=customer.id,
            appointment_id=appointment.id,
            work_order_id=work_order.id,
            started_at=datetime.utcnow() - timedelta(hours=2),
            ended_at=datetime.utcnow() - timedelta(hours=2, minutes=-3),
        ))
        print("Seeded sample CRM customers, appointment, work order, and call")
    else:
        print("CRM sample data already present")

    db.session.commit()
    print("Test database is ready. Login with a@gmail.com / 1")


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

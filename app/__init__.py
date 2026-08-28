from flask import Flask
from flask_cors import CORS
from .config import DevelopmentConfig
from .models import db
from dotenv import load_dotenv
from sqlalchemy import inspect
from werkzeug.security import generate_password_hash
import psycopg2
from psycopg2 import sql
from urllib.parse import urlparse
from app.models.user import User
import os
import re

# from app.routes.routes_googleauth.routes_googleauth import api_googlecalendar_Page
from .routes.routes_auth import api_login
from .routes.routes_Dashboard_Page.routes_Dashboard_Page import api_Dashboard_Page
from .routes.routes_utilities import api_bp
from .routes.routes_Gym_Page.routes_Gym_Page import api_Gym_Page
from .routes.routes_Diet_Page.routes_Diet_Page import api_Diet_Page
from .routes.routes_Programming_Page.routes_Programming_Page import api_Programming_Page
from .routes.routes_Singing_Page.routes_Singing_Page import api_Singing_Page
from .routes.routes_Language_Page.routes_Language_Page import api_Language_Page
from .routes.routes_Language_Subroute_Page.routes_Language_Subroute_Page import api_Language_Subroute_Page
from app.routes.routes_Language_Subroute_Page.routes_Language_Stories import api_Language_Stories
from flask_sock import Sock
from app.routes.routes_VoiceAgent import api_voice_agent, init_voice_socket
from app.routes.routes_Paces import api_paces
from app.greptile import initialize_greptile_schema, register_greptile
from app.anglera import initialize_anglera_schema, register_anglera
from app.taxgpt import initialize_taxgpt_schema, register_taxgpt
from app.openmart import initialize_openmart_schema, register_openmart

def drop_all_tables():
    load_dotenv()
    if os.getenv('APP_ENV') == 'staging':
        uri = os.getenv('SQLALCHEMY_DATABASE_URI_STAGING')
    else:
        uri = os.getenv('SQLALCHEMY_DATABASE_URI')
    result = urlparse(uri)
    conn_params = {
        'dbname': result.path.lstrip('/'),
        'user': result.username,
        'password': result.password,
        'host': result.hostname,
        'port': result.port
    }

    try:
        # Connect to the database
        with psycopg2.connect(**conn_params) as conn:
            with conn.cursor() as cursor:
                # Disable foreign key checks
                cursor.execute("SET CONSTRAINTS ALL DEFERRED;")

                # Get all tables in the public schema
                cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public';")
                tables = cursor.fetchall()

                # Drop each table
                for table in tables:
                    cursor.execute(sql.SQL("DROP TABLE IF EXISTS {} CASCADE;").format(sql.Identifier(table[0])))
                    print(f"Dropped table: {table[0]}")

                # Re-enable foreign key checks
                cursor.execute("SET CONSTRAINTS ALL IMMEDIATE;")

            # Commit the changes
            conn.commit()
        print("All tables have been dropped successfully.")
    except psycopg2.Error as e:
        print(f"An error occurred while dropping tables: {e}")

def check_schema_changes(app):
    """
    Checks if there are any differences between the models and database schema.
    Returns True if changes are detected, False otherwise.
    """
    try:
        with app.app_context():
            inspector = inspect(db.engine)
            existing_tables = set(inspector.get_table_names())  # Convert list to set
            system_tables = {'alembic_version'}
            existing_tables = existing_tables - system_tables
            # Get all models from db.Model
            models = db.Model.__subclasses__()
            model_tables = [model.__tablename__ for model in models]
            
            # Check for missing or extra tables
            missing_tables = set(model_tables) - existing_tables
            extra_tables = existing_tables - set(model_tables)
            
            if missing_tables or extra_tables:
                print("Schema changes detected:")
                if missing_tables:
                    print(f"Missing tables: {missing_tables}")
                if extra_tables:
                    print(f"Extra tables: {extra_tables}")
                return True
                
            # Check columns for each model
            for model in models:
                if model.__tablename__ in existing_tables:
                    columns = {c['name'] for c in inspector.get_columns(model.__tablename__)}
                    model_columns = {c.key for c in model.__table__.columns}
                    
                    if columns != model_columns:
                        print(f"Column differences detected in table {model.__tablename__}:")
                        print(f"Missing columns: {model_columns - columns}")
                        print(f"Extra columns: {columns - model_columns}")
                        return True
            
            print("No schema changes detected.")
            return False
            
    except Exception as e:
        print(f"Error checking schema changes: {e}")
        return None

def initialize_default_user():
    # Create default user
    default_email = "a@gmail.com"
    default_password = "1"
    hashed_password = generate_password_hash(default_password, method='pbkdf2:sha256')
    
    # Check if user already exists
    existing_user = User.query.filter_by(email=default_email).first()
    if existing_user:
        print(f"Default user {default_email} already exists")
        return
    
    default_user = User(
        username=default_email,
        email=default_email,
        password=hashed_password
    )
    
    db.session.add(default_user)
    db.session.flush()  # This will assign an ID to default_user
    
    # Create default workflows for the user
    
    db.session.commit()
    print(f"Created default user: {default_email} with default workflows")

def initialize_admin_user(email="admin@admin.com", password="admin"):
    """
    Create an admin user with the specified email and password
    """
    # Check if admin already exists
    admin = User.query.filter_by(email=email).first()
    if admin:
        print(f"Admin user with email {email} already exists.")
        # Update admin flag if needed
        if not admin.is_admin:
            admin.is_admin = True
            db.session.commit()
            print(f"Updated user {email} to have admin privileges.")
        return

    # Create new admin user
    hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
    new_admin = User(
        username=email,
        email=email,
        password=hashed_password,
        is_admin=True
    )
    
    db.session.add(new_admin)
    db.session.flush()  # Get the ID before creating related objects
    
    # Create default workflows for the admin user
    create_default_workflows(new_admin.id, "Admin Dashboard")
    
    db.session.commit()
    print(f"Admin user with email {email} created successfully with default workflows.")

def _cors_origins():
    configured = [
        origin.strip().rstrip('/')
        for origin in os.getenv('FRONTEND_ORIGINS', '').split(',')
        if origin.strip() and '*' not in origin
    ]
    defaults = [
        'http://localhost:3000',
        'http://localhost:3001',
        'http://localhost:3002',
        'http://127.0.0.1:3000',
        'http://127.0.0.1:3001',
        'http://127.0.0.1:3002',
    ]
    return list(dict.fromkeys(defaults + configured)) + [
        re.compile(r'^https://[a-zA-Z0-9.-]+\.vercel\.app$'),
        re.compile(r'^https://[a-zA-Z0-9.-]+\.vercel\.sh$'),
    ]


def _taxgpt_trusted_origins():
    configured = [
        origin.strip().rstrip('/')
        for origin in os.getenv('FRONTEND_ORIGINS', '').split(',')
        if origin.strip() and '*' not in origin
    ]
    local = [
        'http://localhost:3000',
        'http://localhost:3001',
        'http://localhost:3002',
        'http://127.0.0.1:3000',
        'http://127.0.0.1:3001',
        'http://127.0.0.1:3002',
    ]
    return tuple(dict.fromkeys(local + configured))


def _openmart_trusted_origins():
    # Reuse the shared FRONTEND_ORIGINS contract so existing deployments do
    # not need a second origin variable just for this bounded context.
    return _taxgpt_trusted_origins()


def create_app():
    load_dotenv()
    app = Flask(__name__)
    sock = Sock(app)
    allowed_origins = _cors_origins()
    CORS(
        app,
        resources={
            r"/api/*": {"origins": allowed_origins},
            r"/login": {"origins": allowed_origins},
            r"/signup": {"origins": allowed_origins},
        },
        supports_credentials=True,
        allow_headers=["Content-Type", "Authorization", "Idempotency-Key"],
    )

    app.config.from_object(DevelopmentConfig)  # Load development config
    if not app.config.get('SECRET_KEY'):
        if os.getenv('APP_ENV', 'development').lower() == 'production':
            raise RuntimeError('SECRET_KEY is required when APP_ENV=production')
        app.config['SECRET_KEY'] = os.urandom(32).hex()
    app.config['GREPTILE_DUMMY_PASSWORD_HASH'] = generate_password_hash(os.urandom(32).hex())
    app.config.update(
        TAXGPT_DUMMY_PASSWORD_HASH=generate_password_hash(os.urandom(32).hex()),
        TAXGPT_COOKIE_SECURE=(os.getenv('TAXGPT_COOKIE_SECURE', '').lower() == 'true') if os.getenv('TAXGPT_COOKIE_SECURE') is not None else None,
        TAXGPT_MAX_FILE_BYTES=min(int(os.getenv('TAXGPT_MAX_FILE_BYTES', str(10 * 1024 * 1024))), 10 * 1024 * 1024),
        TAXGPT_SESSION_HOURS=max(1, min(int(os.getenv('TAXGPT_SESSION_HOURS', '12')), 24)),
        TAXGPT_REMEMBER_DAYS=max(1, min(int(os.getenv('TAXGPT_REMEMBER_DAYS', '7')), 30)),
        TAXGPT_AUTH_RATE_LIMIT=max(3, min(int(os.getenv('TAXGPT_AUTH_RATE_LIMIT', '10')), 60)),
        TAXGPT_DEMO_RATE_LIMIT=max(1, min(int(os.getenv('TAXGPT_DEMO_RATE_LIMIT', '5')), 60)),
        TAXGPT_TRUST_PROXY_HEADERS=os.getenv('TAXGPT_TRUST_PROXY_HEADERS', 'false').lower() == 'true',
        TAXGPT_OPENAI_TIMEOUT_SECONDS=max(5, min(int(os.getenv('TAXGPT_OPENAI_TIMEOUT_SECONDS', '30')), 120)),
        TAXGPT_OPENAI_MAX_RETRIES=max(0, min(int(os.getenv('TAXGPT_OPENAI_MAX_RETRIES', '2')), 5)),
        TAXGPT_TRUSTED_ORIGINS=_taxgpt_trusted_origins(),
        TAXGPT_AUTO_CREATE_TABLES=os.getenv('TAXGPT_AUTO_CREATE_TABLES', os.getenv('AUTO_CREATE_TABLES', 'true')).lower() == 'true',
        OPENMART_DUMMY_PASSWORD_HASH=generate_password_hash(os.urandom(32).hex()),
        OPENMART_COOKIE_SECURE=(os.getenv('OPENMART_COOKIE_SECURE', '').lower() == 'true') if os.getenv('OPENMART_COOKIE_SECURE') is not None else None,
        OPENMART_SESSION_HOURS=max(1, min(int(os.getenv('OPENMART_SESSION_HOURS', '12')), 24)),
        OPENMART_REMEMBER_DAYS=max(1, min(int(os.getenv('OPENMART_REMEMBER_DAYS', '7')), 30)),
        OPENMART_AUTH_RATE_LIMIT=max(3, min(int(os.getenv('OPENMART_AUTH_RATE_LIMIT', '10')), 60)),
        OPENMART_TRUST_PROXY_HEADERS=os.getenv('OPENMART_TRUST_PROXY_HEADERS', 'false').lower() == 'true',
        OPENMART_TRUSTED_ORIGINS=_openmart_trusted_origins(),
        OPENMART_MAX_BODY_BYTES=min(int(os.getenv('OPENMART_MAX_BODY_BYTES', str(1024 * 1024))), 2 * 1024 * 1024),
        OPENMART_AUTO_CREATE_TABLES=os.getenv('OPENMART_AUTO_CREATE_TABLES', os.getenv('AUTO_CREATE_TABLES', 'true')).lower() == 'true',
        OPENMART_SEED_ENABLED=os.getenv('OPENMART_SEED_ENABLED', 'false').lower() == 'true',
        OPENMART_SEED_EMAIL=os.getenv('OPENMART_SEED_EMAIL', ''),
        OPENMART_SEED_PASSWORD=os.getenv('OPENMART_SEED_PASSWORD', ''),
        OPENMART_SEED_DISPLAY_NAME=os.getenv('OPENMART_SEED_DISPLAY_NAME', 'Openmart Demo'),
        OPENMART_SEED_WORKSPACE=os.getenv('OPENMART_SEED_WORKSPACE', 'Openmart Demo'),
    )

    db.init_app(app)

    app.register_blueprint(api_login)
    app.register_blueprint(api_bp)
    app.register_blueprint(api_Dashboard_Page)
    app.register_blueprint(api_Gym_Page)
    app.register_blueprint(api_Diet_Page)
    app.register_blueprint(api_Programming_Page)
    app.register_blueprint(api_Singing_Page)
    app.register_blueprint(api_Language_Page)
    app.register_blueprint(api_Language_Subroute_Page)
    app.register_blueprint(api_Language_Stories)
    app.register_blueprint(api_voice_agent)
    app.register_blueprint(api_paces)
    register_greptile(app)
    register_anglera(app)
    register_taxgpt(app)
    register_openmart(app)
    init_voice_socket(sock)
    with app.app_context():
        if os.getenv('AUTO_CREATE_TABLES', 'true').lower() == 'true':
            db.create_all()
        # This is deliberately independent of AUTO_CREATE_TABLES: Greptile
        # creates only namespaced tables and does not alter existing data.
        initialize_greptile_schema()
        # Anglera is a separate additive bounded context. It reuses only the
        # authenticated workspace identity and never alters Paces/Greptile rows.
        initialize_anglera_schema()
        # TaxGPT is another additive bounded context and owns only taxgpt_*
        # tables, cookies, and routes inside the shared deployment.
        initialize_taxgpt_schema()
        # Openmart owns only openmart_* tables, cookies, and routes. This keeps
        # TaxGPT, Anglera, Paces, Greptile, and the legacy application isolated.
        initialize_openmart_schema()
    # try:
    #     with app.app_context():
    #         db.create_all()
    #         check_schema_changes(app)
    #         initialize_default_user()
    #         if check_schema_changes(app):

    #             drop_all_tables()
    #             db.drop_all()
    #             db.create_all()
    #         initialize_default_user()
    # except Exception as e:
    #     print(f"Error initializing users: {e}")

    return app

# app = create_app()

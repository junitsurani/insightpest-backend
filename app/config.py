import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY')
    SQLALCHEMY_TRACK_MODIFICATIONS = False


class DevelopmentConfig(Config):
    DEBUG = True
    if os.getenv('APP_ENV') == 'staging':
        database_url = os.getenv('SQLALCHEMY_DATABASE_URI_STAGING')
    else:
        database_url = os.getenv('SQLALCHEMY_DATABASE_URI')
    if database_url and database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    SQLALCHEMY_DATABASE_URI = database_url
    # SQLALCHEMY_DATABASE_URI = "postgresql://postgres:pEm8Y9yaYu1n1UDEV04K@autoapplier.cohuqar8xvwd.us-west-2.rds.amazonaws.com:5432/postgres"

class ProductionConfig(Config):
    DEBUG = False
    # SQLALCHEMY_DATABASE_URI for production DB
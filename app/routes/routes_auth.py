import os
import uuid
from random import choice
from flask import Blueprint, Flask, jsonify, request
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy.exc import SQLAlchemyError
from dotenv import load_dotenv
from app.models import db
from app.models.user import User
import jwt
from datetime import datetime, timedelta
from functools import wraps
from werkzeug.utils import secure_filename
import boto3
import hashlib


load_dotenv()  # This loads the environment variables from .env file

api_login = Blueprint("login", __name__, url_prefix="")


def jwt_signing_key():
    """Derive a fixed-length HS256 key without exposing the configured application secret."""
    return hashlib.sha256(os.environ['SECRET_KEY'].encode()).digest()


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        data = request.get_json()
        username = data.get('username')
        
        if not username:
            return jsonify({"error": "Authentication required"}), 401
            
        user = User.query.filter_by(username=username).first()
        
        if not user or not user.is_admin:
            return jsonify({"error": "Admin privileges required"}), 403
            
        return f(*args, **kwargs)
    return decorated_function


@api_login.route('/signup', methods=['POST'])
def signup():
    data = request.get_json()

    email = data.get('email')
    password = data.get('password')
    
    if not email or not password:
        return jsonify({"error": "Missing required fields"}), 400

    if User.query.filter_by(username=email).first():
        print("Email already exists")
        return jsonify({"error": "Email already registered"}), 400

    try:
        # Create the user
        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
        new_user = User(
            username=email, 
            email=email, 
            password=hashed_password,
            is_admin=False
        )
        
        db.session.add(new_user)
        db.session.flush()  # Get the user ID without committing
        
        # Commit all changes
        db.session.commit()
        
        return jsonify({
            "message": "User created successfully",
            "username": new_user.username
        }), 201
    except Exception as e:
        db.session.rollback()
        print(f"Error during signup: {str(e)}")
        return jsonify({"error": "An error occurred during registration"}), 500


@api_login.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data['username']
    password = data['password']

    user = User.query.filter_by(username=username).first()

    if not user or not check_password_hash(user.password, password):
        return jsonify({"error": "Invalid username or password"}), 400

    token = jwt.encode({
        "sub": user.username,
        "is_admin": user.is_admin,
        "exp": datetime.utcnow() + timedelta(hours=12),
    }, jwt_signing_key(), algorithm="HS256")

    return jsonify({
        "message": f"Welcome {user.username}!",
        "username": user.username,
        "success": True,
        "is_admin": user.is_admin,
        "token": token,
    }), 200

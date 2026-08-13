from flask import Blueprint, Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
import os
from sqlalchemy.exc import SQLAlchemyError
from app.models.user import User
from app.models import db
from app.utils.email_service import send_form_email


api_bp = Blueprint("api", __name__, url_prefix="")

load_dotenv()


@api_bp.route('/')
def hello_world():
    return 'Hello, World this is an update!!!!'

@api_bp.route('/form-submission', methods=['POST'])
def handle_form_submission():
    try:
        data = request.get_json()
        
        # Extract form data
        name = data.get('name')
        email = data.get('email')
        phone = data.get('phone')
        
        if not all([name, email, phone]):
            return jsonify({'error': 'Missing required fields'}), 400
            
        # Create email body
        email_body = f"""
        New Form Submission:
        
        Name: {name}
        Email: {email}
        Phone: {phone}
        """
        
        # Send email
        email_sent = send_form_email(email_body)
        
        if email_sent:
            return jsonify({'message': 'Form submitted successfully'}), 200
        else:
            return jsonify({'error': 'Failed to send email notification'}), 500
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500


from . import db
from sqlalchemy import Boolean, String, Text, ForeignKey, func, Integer, DateTime, LargeBinary, Enum
from datetime import datetime
import enum
import json


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)
    parent_username = db.Column(db.String(150), ForeignKey('user.username'), nullable=True)
    is_subaccount = db.Column(db.Boolean, default=False)
    is_admin = db.Column(db.Boolean, default=False)
    subaccounts = db.relationship(
        'User',
        backref=db.backref('parent', remote_side=[username]),
        foreign_keys=[parent_username]
    )
    email = db.Column(db.String(150), unique=True, nullable=False)


class ServiceAppointment(db.Model):
    """Appointments created by staff or by the Insight voice agent."""

    __tablename__ = 'service_appointment'

    id = db.Column(db.Integer, primary_key=True)
    customer_name = db.Column(db.String(150), nullable=False)
    phone = db.Column(db.String(32), nullable=False)
    email = db.Column(db.String(150), nullable=True)
    postal_code = db.Column(db.String(16), nullable=False)
    pest_issue = db.Column(db.String(120), nullable=False)
    preferred_date = db.Column(db.Date, nullable=False)
    preferred_time = db.Column(db.String(24), nullable=False)
    notes = db.Column(db.Text, nullable=True)
    source = db.Column(db.String(32), nullable=False, default='voice_agent')
    status = db.Column(db.String(32), nullable=False, default='requested')
    twilio_call_sid = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'customer_name': self.customer_name,
            'phone': self.phone,
            'email': self.email,
            'postal_code': self.postal_code,
            'pest_issue': self.pest_issue,
            'preferred_date': self.preferred_date.isoformat(),
            'preferred_time': self.preferred_time,
            'notes': self.notes,
            'source': self.source,
            'status': self.status,
            'twilio_call_sid': self.twilio_call_sid,
            'created_at': self.created_at.isoformat(),
        }


class CRMCustomer(db.Model):
    """A customer or qualified lead captured by staff, web, or the voice agent."""

    __tablename__ = 'crm_customer'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    phone = db.Column(db.String(32), nullable=False, unique=True, index=True)
    email = db.Column(db.String(150), nullable=True)
    service_address = db.Column(db.String(255), nullable=True)
    city = db.Column(db.String(100), nullable=True)
    province = db.Column(db.String(32), nullable=True, default='ON')
    postal_code = db.Column(db.String(16), nullable=False)
    pest_issue = db.Column(db.String(160), nullable=False)
    property_type = db.Column(db.String(64), nullable=True)
    status = db.Column(db.String(32), nullable=False, default='lead')
    source = db.Column(db.String(32), nullable=False, default='voice_agent')
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        location = ', '.join(part for part in (self.city, self.province) if part)
        return {
            'id': self.id,
            'name': self.name,
            'phone': self.phone,
            'email': self.email,
            'service_address': self.service_address,
            'city': self.city,
            'province': self.province,
            'location': location or self.service_address or '',
            'postal_code': self.postal_code,
            'pest_issue': self.pest_issue,
            'property_type': self.property_type,
            'status': self.status,
            'source': self.source,
            'notes': self.notes,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
        }


class ServiceWorkOrder(db.Model):
    """Field-service work created transactionally with an appointment."""

    __tablename__ = 'service_work_order'

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('crm_customer.id'), nullable=False, index=True)
    appointment_id = db.Column(db.Integer, db.ForeignKey('service_appointment.id'), nullable=True, unique=True)
    service = db.Column(db.String(180), nullable=False)
    scheduled_date = db.Column(db.Date, nullable=True)
    scheduled_time = db.Column(db.String(32), nullable=True)
    technician = db.Column(db.String(120), nullable=True)
    priority = db.Column(db.String(24), nullable=False, default='routine')
    status = db.Column(db.String(32), nullable=False, default='unassigned')
    source = db.Column(db.String(32), nullable=False, default='voice_agent')
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    customer = db.relationship('CRMCustomer', backref=db.backref('work_orders', lazy=True))
    appointment = db.relationship('ServiceAppointment', backref=db.backref('work_order', uselist=False))

    def to_dict(self):
        return {
            'id': self.id,
            'reference': f'WO-{2000 + self.id}',
            'customer_id': self.customer_id,
            'customer': self.customer.name if self.customer else None,
            'phone': self.customer.phone if self.customer else None,
            'postal_code': self.customer.postal_code if self.customer else None,
            'location': self.customer.to_dict()['location'] if self.customer else '',
            'appointment_id': self.appointment_id,
            'service': self.service,
            'scheduled_date': self.scheduled_date.isoformat() if self.scheduled_date else None,
            'scheduled_time': self.scheduled_time,
            'technician': self.technician or 'Unassigned',
            'priority': self.priority,
            'status': self.status,
            'source': self.source,
            'notes': self.notes,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
        }


class VoiceCall(db.Model):
    """Inbound/outbound call observability and CRM attribution."""

    __tablename__ = 'voice_call'

    id = db.Column(db.Integer, primary_key=True)
    twilio_call_sid = db.Column(db.String(64), nullable=False, unique=True, index=True)
    direction = db.Column(db.String(16), nullable=False, default='inbound')
    from_number = db.Column(db.String(32), nullable=True)
    to_number = db.Column(db.String(32), nullable=True)
    status = db.Column(db.String(32), nullable=False, default='initiated')
    intent = db.Column(db.String(32), nullable=True)
    resolution = db.Column(db.String(32), nullable=True)
    summary = db.Column(db.Text, nullable=True)
    transcript = db.Column(db.Text, nullable=True)
    duration_seconds = db.Column(db.Integer, nullable=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('crm_customer.id'), nullable=True)
    appointment_id = db.Column(db.Integer, db.ForeignKey('service_appointment.id'), nullable=True)
    work_order_id = db.Column(db.Integer, db.ForeignKey('service_work_order.id'), nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    started_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    ended_at = db.Column(db.DateTime, nullable=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    customer = db.relationship('CRMCustomer')
    appointment = db.relationship('ServiceAppointment')
    work_order = db.relationship('ServiceWorkOrder')

    def to_dict(self):
        return {
            'id': self.id,
            'twilio_call_sid': self.twilio_call_sid,
            'direction': self.direction,
            'from_number': self.from_number,
            'to_number': self.to_number,
            'status': self.status,
            'intent': self.intent,
            'resolution': self.resolution,
            'summary': self.summary,
            'transcript': self.transcript,
            'duration_seconds': self.duration_seconds,
            'customer': self.customer.to_dict() if self.customer else None,
            'appointment': self.appointment.to_dict() if self.appointment else None,
            'work_order': self.work_order.to_dict() if self.work_order else None,
            'error_message': self.error_message,
            'started_at': self.started_at.isoformat(),
            'ended_at': self.ended_at.isoformat() if self.ended_at else None,
            'updated_at': self.updated_at.isoformat(),
        }
    


class SingingSession(db.Model):
    __tablename__ = 'singing_session'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), ForeignKey('user.username'), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    session_type = db.Column(db.String(100), nullable=False)  # Practice, Performance, Lesson, Recording, Warm-up
    start_time = db.Column(db.String(10), nullable=False)  # Format: "HH:MM"
    end_time = db.Column(db.String(10), nullable=False)  # Format: "HH:MM"
    duration = db.Column(db.Integer, nullable=False)  # Duration in minutes
    session_date = db.Column(db.Date, nullable=False)
    songs = db.Column(db.Text)  # Comma-separated songs practiced
    notes = db.Column(db.Text)
    rating = db.Column(db.Integer, default=3)  # 1-5 rating
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationship to user
    user = db.relationship('User', backref=db.backref('singing_sessions', lazy=True))

class SingingGoal(db.Model):
    __tablename__ = 'singing_goal'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), ForeignKey('user.username'), nullable=False)
    weekly_minutes_goal = db.Column(db.Integer, nullable=False)  # Weekly goal in minutes
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationship to user
    user = db.relationship('User', backref=db.backref('singing_goals', lazy=True)) 



class FoodData(db.Model):
    __tablename__ = 'food_data'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), ForeignKey('user.username'), nullable=False)
    week_start = db.Column(db.Date, nullable=False)  # Start date of the week (Monday)
    weekly_food_items = db.Column(db.Text)  # JSON string containing the weekly food data
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationship to user
    user = db.relationship('User', backref=db.backref('food_data', lazy=True))
    
    # Add unique constraint for username and week_start
    __table_args__ = (
        db.UniqueConstraint('username', 'week_start', name='unique_username_week'),
    )


class NutritionGoals(db.Model):
    __tablename__ = 'nutrition_goals'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), ForeignKey('user.username'), nullable=False)
    daily_calorie_goal = db.Column(db.Integer, nullable=False, default=2000)
    daily_budget_goal = db.Column(db.Float, nullable=False, default=50.0)  # Daily food budget in dollars
    protein_goal = db.Column(db.Integer, nullable=True)  # grams of protein
    carb_goal = db.Column(db.Integer, nullable=True)  # grams of carbs
    fat_goal = db.Column(db.Integer, nullable=True)  # grams of fat
    fiber_goal = db.Column(db.Integer, nullable=True)  # grams of fiber
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationship to user
    user = db.relationship('User', backref=db.backref('nutrition_goals', lazy=True))


class FoodFavorites(db.Model):
    __tablename__ = 'food_favorites'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), ForeignKey('user.username'), nullable=False)
    food_name = db.Column(db.String(255), nullable=False)
    calories = db.Column(db.Integer, nullable=False)
    cost = db.Column(db.Float, nullable=False)
    serving_size = db.Column(db.String(100))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationship to user
    user = db.relationship('User', backref=db.backref('food_favorites', lazy=True)) 

class Workout(db.Model):
    __tablename__ = 'workout'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), ForeignKey('user.username'), nullable=False)
    workout_date = db.Column(db.Date, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationship to user and workout items
    user = db.relationship('User', backref=db.backref('workouts', lazy=True))
    workout_items = db.relationship('WorkoutItem', backref='workout', lazy=True, cascade='all, delete-orphan')

class WorkoutItem(db.Model):
    __tablename__ = 'workout_item'
    
    id = db.Column(db.Integer, primary_key=True)
    workout_id = db.Column(db.Integer, ForeignKey('workout.id'), nullable=False)
    exercise = db.Column(db.String(100), nullable=False)
    weight = db.Column(db.Float, nullable=False)
    sets = db.Column(db.Integer, nullable=False)
    reps = db.Column(db.Integer, nullable=False)
    completed = db.Column(db.Boolean, default=False)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow) 

class ProgrammingTask(db.Model):
    __tablename__ = 'programming_task'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), ForeignKey('user.username'), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    category = db.Column(db.String(100))
    estimated_time = db.Column(db.Float)
    priority = db.Column(db.String(50))
    type = db.Column(db.String(50))  # 'daily' or 'weekly'
    completed = db.Column(db.Boolean, default=False)
    task_date = db.Column(db.Date, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationship to user
    user = db.relationship('User', backref=db.backref('programming_tasks', lazy=True))

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'title': self.title,
            'description': self.description,
            'category': self.category,
            'estimated_time': self.estimated_time,
            'priority': self.priority,
            'type': self.type,
            'completed': self.completed,
            'task_date': self.task_date.isoformat() if self.task_date else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

class LanguageSession(db.Model):
    __tablename__ = 'language_session'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), ForeignKey('user.username'), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    session_type = db.Column(db.String(100), nullable=False)  # Practice, Lesson, Conversation, Reading, Writing, Listening
    language = db.Column(db.String(50), nullable=False)  # e.g., Spanish, French, etc.
    start_time = db.Column(db.String(10), nullable=False)  # Format: "HH:MM"
    end_time = db.Column(db.String(10), nullable=False)  # Format: "HH:MM"
    duration = db.Column(db.Integer, nullable=False)  # Duration in minutes
    session_date = db.Column(db.Date, nullable=False)
    topics = db.Column(db.Text)  # Comma-separated topics covered
    notes = db.Column(db.Text)
    rating = db.Column(db.Integer, default=3)  # 1-5 rating
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationship to user
    user = db.relationship('User', backref=db.backref('language_sessions', lazy=True))

class LanguageGoal(db.Model):
    __tablename__ = 'language_goal'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), ForeignKey('user.username'), nullable=False)
    language = db.Column(db.String(50), nullable=False)  # e.g., Spanish, French, etc.
    weekly_minutes_goal = db.Column(db.Integer, nullable=False)  # Weekly goal in minutes
    proficiency_level = db.Column(db.String(50))  # e.g., A1, A2, B1, B2, C1, C2
    target_date = db.Column(db.Date)  # Target date to reach the goal
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationship to user
    user = db.relationship('User', backref=db.backref('language_goals', lazy=True)) 

class Flashcard(db.Model):
    __tablename__ = 'flashcard'
    
    id = db.Column(db.Integer, primary_key=True)
    set_id = db.Column(db.Integer, ForeignKey('flashcard_set.id'), nullable=False)
    word = db.Column(db.String(255), nullable=False)
    irregular_forms = db.Column(db.Text)  # JSON string of different forms
    sentence = db.Column(db.Text, nullable=False)
    word_translation = db.Column(db.String(255), nullable=False)
    sentence_translation = db.Column(db.Text, nullable=False)
    learned = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationship to set
    set = db.relationship('FlashcardSet', backref=db.backref('cards', lazy=True))

class FlashcardSet(db.Model):
    __tablename__ = 'flashcard_set'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), ForeignKey('user.username'), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    completed = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationship to user
    user = db.relationship('User', backref=db.backref('flashcard_sets', lazy=True))

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'completed': self.completed,
            'cards': [{
                'id': card.id,
                'word': card.word,
                'irregularForms': card.irregular_forms,
                'sentence': card.sentence,
                'wordTranslation': card.word_translation,
                'sentenceTranslation': card.sentence_translation,
                'learned': card.learned
            } for card in self.cards]
        }

class Story(db.Model):
    __tablename__ = 'story'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), ForeignKey('user.username'), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    level = db.Column(db.String(50), nullable=False)  # Beginner, Intermediate, Advanced
    read_time = db.Column(db.Integer, nullable=False)  # Time in minutes
    content = db.Column(db.Text, nullable=False)
    completed = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationship to user
    user = db.relationship('User', backref=db.backref('stories', lazy=True))

    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'description': self.description,
            'level': self.level,
            'readTime': self.read_time,
            'content': self.content,
            'completed': self.completed,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        } 

class GeneratedStory(db.Model):
    __tablename__ = 'generated_story'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), ForeignKey('user.username'), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    content = db.Column(db.Text, nullable=False)
    prompt = db.Column(db.Text)
    used_flashcard_sets = db.Column(db.Text)  # JSON string of flashcard set IDs used
    total_words_used = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), default='processing')  # processing, completed, failed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationship to user
    user = db.relationship('User', backref=db.backref('generated_stories', lazy=True))

    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'content': self.content,
            'prompt': self.prompt,
            'usedFlashcardSets': json.loads(self.used_flashcard_sets) if self.used_flashcard_sets else [],
            'totalWordsUsed': self.total_words_used,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

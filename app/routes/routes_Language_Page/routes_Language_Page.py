from flask import jsonify, Blueprint, request
from app.models import db
from app.models.user import User, LanguageSession, LanguageGoal
from datetime import datetime, timedelta

api_Language_Page = Blueprint("api_Language_Page", __name__, url_prefix="")

@api_Language_Page.route('/language/sessions', methods=['GET'])
def get_sessions():
    username = request.args.get('username')
    if not username:
        return jsonify({"error": "Username is required"}), 400
    
    try:
        sessions = LanguageSession.query.filter_by(username=username).all()
        return jsonify({
            "sessions": [{
                "id": session.id,
                "title": session.title,
                "type": session.session_type,
                "language": session.language,
                "startTime": session.start_time,
                "endTime": session.end_time,
                "duration": session.duration,
                "date": session.session_date.isoformat(),
                "topics": session.topics,
                "notes": session.notes,
                "rating": session.rating
            } for session in sessions]
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@api_Language_Page.route('/language/session', methods=['POST'])
def create_session():
    data = request.get_json()
    username = data.get('username')
    
    if not username:
        return jsonify({"error": "Username is required"}), 400
    
    try:
        new_session = LanguageSession(
            username=username,
            title=data.get('title'),
            session_type=data.get('type'),
            language=data.get('language', 'Default'),
            start_time=data.get('startTime'),
            end_time=data.get('endTime'),
            duration=data.get('duration'),
            session_date=datetime.strptime(data.get('date'), '%Y-%m-%d').date(),
            topics=data.get('topics'),
            notes=data.get('notes'),
            rating=data.get('rating', 3)
        )
        
        db.session.add(new_session)
        db.session.commit()
        
        return jsonify({
            "message": "Session created successfully",
            "session": {
                "id": new_session.id,
                "title": new_session.title,
                "type": new_session.session_type,
                "language": new_session.language,
                "startTime": new_session.start_time,
                "endTime": new_session.end_time,
                "duration": new_session.duration,
                "date": new_session.session_date.isoformat(),
                "topics": new_session.topics,
                "notes": new_session.notes,
                "rating": new_session.rating
            }
        }), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@api_Language_Page.route('/language/weekly-stats', methods=['GET'])
def get_weekly_stats():
    username = request.args.get('username')
    week_start = request.args.get('week_start')
    
    if not username or not week_start:
        return jsonify({"error": "Username and week_start are required"}), 400
    
    try:
        start_date = datetime.strptime(week_start, '%Y-%m-%d').date()
        end_date = start_date + timedelta(days=6)
        
        sessions = LanguageSession.query.filter(
            LanguageSession.username == username,
            LanguageSession.session_date >= start_date,
            LanguageSession.session_date <= end_date
        ).all()
        
        # Create daily stats
        daily_stats = []
        for i in range(7):
            current_date = start_date + timedelta(days=i)
            day_sessions = [s for s in sessions if s.session_date == current_date]
            total_minutes = sum(s.duration for s in day_sessions)
            
            daily_stats.append({
                "day": current_date.strftime('%a'),
                "minutes": total_minutes
            })
        
        return jsonify({"daily_stats": daily_stats}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@api_Language_Page.route('/language/goals', methods=['GET'])
def get_goals():
    username = request.args.get('username')
    if not username:
        return jsonify({"error": "Username is required"}), 400
    
    try:
        goals = LanguageGoal.query.filter_by(username=username).all()
        return jsonify({
            "goals": [{
                "id": goal.id,
                "language": goal.language,
                "weekly_minutes_goal": goal.weekly_minutes_goal,
                "proficiency_level": goal.proficiency_level,
                "target_date": goal.target_date.isoformat() if goal.target_date else None,
                "notes": goal.notes
            } for goal in goals]
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@api_Language_Page.route('/language/goals', methods=['POST'])
def create_goal():
    data = request.get_json()
    username = data.get('username')
    
    if not username:
        return jsonify({"error": "Username is required"}), 400
    
    try:
        new_goal = LanguageGoal(
            username=username,
            language=data.get('language', 'Default'),
            weekly_minutes_goal=data.get('weekly_minutes_goal'),
            proficiency_level=data.get('proficiency_level'),
            target_date=datetime.strptime(data.get('target_date'), '%Y-%m-%d').date() if data.get('target_date') else None,
            notes=data.get('notes')
        )
        
        db.session.add(new_goal)
        db.session.commit()
        
        return jsonify({
            "message": "Goal created successfully",
            "goal": {
                "id": new_goal.id,
                "language": new_goal.language,
                "weekly_minutes_goal": new_goal.weekly_minutes_goal,
                "proficiency_level": new_goal.proficiency_level,
                "target_date": new_goal.target_date.isoformat() if new_goal.target_date else None,
                "notes": new_goal.notes
            }
        }), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@api_Language_Page.route('/language/lesson', methods=['POST'])
def create_lesson():
    data = request.get_json()
    username = data.get('username')
    
    if not username:
        return jsonify({"error": "Username is required"}), 400
    
    # TODO: Implement lesson creation logic
    return jsonify({"message": "Lesson created successfully"}), 201

@api_Language_Page.route('/language/lesson/<int:lesson_id>', methods=['PUT'])
def update_lesson(lesson_id):
    data = request.get_json()
    
    # TODO: Implement lesson update logic
    return jsonify({"message": "Lesson updated successfully"}), 200

@api_Language_Page.route('/language/lesson/<int:lesson_id>', methods=['DELETE'])
def delete_lesson(lesson_id):
    # TODO: Implement lesson deletion logic
    return jsonify({"message": "Lesson deleted successfully"}), 200 
from flask import jsonify, Blueprint, request
from app.models import db
from app.models.user import User, SingingSession, SingingGoal
from datetime import datetime, date, timedelta
from sqlalchemy import func, and_

api_Singing_Page = Blueprint("api_Singing_Page", __name__, url_prefix="")

@api_Singing_Page.route('/singing/sessions', methods=['GET'])
def get_sessions():
    username = request.args.get('username')
    if not username:
        return jsonify({"error": "Username is required"}), 400
    
    # Get optional date filters
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    try:
        query = SingingSession.query.filter_by(username=username)
        
        if start_date:
            start_date_obj = datetime.strptime(start_date, '%Y-%m-%d').date()
            query = query.filter(SingingSession.session_date >= start_date_obj)
            
        if end_date:
            end_date_obj = datetime.strptime(end_date, '%Y-%m-%d').date()
            query = query.filter(SingingSession.session_date <= end_date_obj)
        
        sessions = query.order_by(SingingSession.session_date.desc(), SingingSession.start_time.desc()).all()
        
        sessions_data = []
        for session in sessions:
            sessions_data.append({
                'id': session.id,
                'title': session.title,
                'type': session.session_type,
                'startTime': session.start_time,
                'endTime': session.end_time,
                'duration': session.duration,
                'date': session.session_date.isoformat(),
                'songs': session.songs,
                'notes': session.notes,
                'rating': session.rating,
                'created_at': session.created_at.isoformat()
            })
        
        return jsonify({
            "sessions": sessions_data,
            "total": len(sessions_data)
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@api_Singing_Page.route('/singing/session', methods=['POST'])
def create_session():
    data = request.get_json()
    username = data.get('username')
    
    if not username:
        return jsonify({"error": "Username is required"}), 400
    
    # Verify user exists
    user = User.query.filter_by(username=username).first()
    if not user:
        return jsonify({"error": "User not found"}), 404
    
    try:
        # Parse the session date
        session_date = datetime.strptime(data.get('date'), '%Y-%m-%d').date()
        
        new_session = SingingSession(
            username=username,
            title=data.get('title'),
            session_type=data.get('type'),
            start_time=data.get('startTime'),
            end_time=data.get('endTime'),
            duration=data.get('duration'),
            session_date=session_date,
            songs=data.get('songs', ''),
            notes=data.get('notes', ''),
            rating=data.get('rating', 3)
        )
        
        db.session.add(new_session)
        db.session.commit()
        
        return jsonify({
            "message": "Session created successfully",
            "session": {
                'id': new_session.id,
                'title': new_session.title,
                'type': new_session.session_type,
                'startTime': new_session.start_time,
                'endTime': new_session.end_time,
                'duration': new_session.duration,
                'date': new_session.session_date.isoformat(),
                'songs': new_session.songs,
                'notes': new_session.notes,
                'rating': new_session.rating
            }
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@api_Singing_Page.route('/singing/weekly-stats', methods=['GET'])
def get_weekly_stats():
    username = request.args.get('username')
    if not username:
        return jsonify({"error": "Username is required"}), 400
    
    # Get week start date (Monday)
    week_start = request.args.get('week_start')
    if week_start:
        week_start_date = datetime.strptime(week_start, '%Y-%m-%d').date()
    else:
        today = date.today()
        week_start_date = today - timedelta(days=today.weekday())
    
    try:
        # Calculate weekly statistics
        week_end_date = week_start_date + timedelta(days=6)
        
        sessions = SingingSession.query.filter(
            and_(
                SingingSession.username == username,
                SingingSession.session_date >= week_start_date,
                SingingSession.session_date <= week_end_date
            )
        ).all()
        
        # Group by day
        daily_stats = {}
        days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
        
        for i, day in enumerate(days):
            current_date = week_start_date + timedelta(days=i)
            daily_sessions = [s for s in sessions if s.session_date == current_date]
            daily_minutes = sum(s.duration for s in daily_sessions)
            
            daily_stats[day] = {
                'day': day,
                'minutes': daily_minutes,
                'sessions': len(daily_sessions),
                'date': current_date.isoformat()
            }
        
        total_minutes = sum(s.duration for s in sessions)
        total_sessions = len(sessions)
        
        return jsonify({
            "daily_stats": [daily_stats[day] for day in days],
            "weekly_total": total_minutes,
            "total_sessions": total_sessions,
            "week_start": week_start_date.isoformat(),
            "week_end": week_end_date.isoformat()
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@api_Singing_Page.route('/singing/goals', methods=['GET'])
def get_goals():
    username = request.args.get('username')
    if not username:
        return jsonify({"error": "Username is required"}), 400
    
    try:
        # Get the most recent goal
        goal = SingingGoal.query.filter_by(username=username)\
                               .order_by(SingingGoal.created_at.desc())\
                               .first()
        
        if goal:
            return jsonify({
                "goal": {
                    'id': goal.id,
                    'weekly_minutes_goal': goal.weekly_minutes_goal,
                    'notes': goal.notes,
                    'created_at': goal.created_at.isoformat()
                }
            }), 200
        else:
            return jsonify({
                "goal": {
                    'weekly_minutes_goal': 420,  # Default 7 hours
                    'notes': ''
                }
            }), 200
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@api_Singing_Page.route('/singing/goals', methods=['POST'])
def create_or_update_goal():
    data = request.get_json()
    username = data.get('username')
    
    if not username:
        return jsonify({"error": "Username is required"}), 400
    
    # Verify user exists
    user = User.query.filter_by(username=username).first()
    if not user:
        return jsonify({"error": "User not found"}), 404
    
    try:
        new_goal = SingingGoal(
            username=username,
            weekly_minutes_goal=data.get('weekly_minutes_goal'),
            notes=data.get('notes', '')
        )
        
        db.session.add(new_goal)
        db.session.commit()
        
        return jsonify({
            "message": "Goal created successfully",
            "goal": {
                'id': new_goal.id,
                'weekly_minutes_goal': new_goal.weekly_minutes_goal,
                'notes': new_goal.notes,
                'created_at': new_goal.created_at.isoformat()
            }
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


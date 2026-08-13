from flask import jsonify, Blueprint, request
from app.models import db
from app.models.user import User, Workout, WorkoutItem
from datetime import datetime, timedelta

api_Gym_Page = Blueprint("api_Gym_Page", __name__, url_prefix="")

@api_Gym_Page.route('/gym/workouts', methods=['GET'])
def get_workouts():
    username = request.args.get('username')
    if not username:
        return jsonify({"error": "Username is required"}), 400
    
    # Get the start of the current week (Monday)
    today = datetime.now().date()
    monday = today - timedelta(days=today.weekday())
    
    # Get all workouts for the current week
    workouts = Workout.query.filter(
        Workout.username == username,
        Workout.workout_date >= monday,
        Workout.workout_date < monday + timedelta(days=7)
    ).all()
    
    # If no workouts found for current week, try to copy from previous week
    if not workouts:
        previous_monday = monday - timedelta(days=7)
        previous_workouts = Workout.query.filter(
            Workout.username == username,
            Workout.workout_date >= previous_monday,
            Workout.workout_date < previous_monday + timedelta(days=7)
        ).all()
        
        if previous_workouts:
            # Create new workouts based on previous week's data
            for prev_workout in previous_workouts:
                # Calculate new date (7 days later)
                new_date = prev_workout.workout_date + timedelta(days=7)
                
                # Create new workout
                new_workout = Workout(
                    username=username,
                    workout_date=new_date
                )
                db.session.add(new_workout)
                db.session.flush()  # Get the new workout ID
                
                # Copy workout items but set completed to False
                for prev_item in prev_workout.workout_items:
                    new_item = WorkoutItem(
                        workout_id=new_workout.id,
                        exercise=prev_item.exercise,
                        weight=prev_item.weight,
                        sets=prev_item.sets,
                        reps=prev_item.reps,
                        completed=False,  # Reset completed status
                        notes=prev_item.notes
                    )
                    db.session.add(new_item)
            
            db.session.commit()
            
            # Fetch the newly created workouts
            workouts = Workout.query.filter(
                Workout.username == username,
                Workout.workout_date >= monday,
                Workout.workout_date < monday + timedelta(days=7)
            ).all()
    
    # Format the response
    weekly_workouts = {i: [] for i in range(7)}  # Initialize empty arrays for each day
    
    for workout in workouts:
        day_index = (workout.workout_date - monday).days
        workout_items = [
            {
                "id": item.id,
                "exercise": item.exercise,
                "weight": item.weight,
                "sets": item.sets,
                "reps": item.reps,
                "completed": item.completed,
                "notes": item.notes
            }
            for item in workout.workout_items
        ]
        weekly_workouts[day_index] = workout_items
    
    return jsonify(weekly_workouts), 200

@api_Gym_Page.route('/gym/workout', methods=['POST'])
def create_workout():
    data = request.get_json()
    username = data.get('username')
    workout_date = datetime.strptime(data.get('workout_date'), '%Y-%m-%d').date()
    workout_items = data.get('workout_items', [])
    
    if not username:
        return jsonify({"error": "Username is required"}), 400
    
    # Create new workout
    workout = Workout(
        username=username,
        workout_date=workout_date
    )
    db.session.add(workout)
    db.session.flush()  # Get the workout ID
    
    # Add workout items
    for item in workout_items:
        workout_item = WorkoutItem(
            workout_id=workout.id,
            exercise=item['exercise'],
            weight=item['weight'],
            sets=item['sets'],
            reps=item['reps'],
            notes=item.get('notes', '')
        )
        db.session.add(workout_item)
    
    db.session.commit()
    return jsonify({"message": "Workout created successfully", "workout_id": workout.id}), 201

@api_Gym_Page.route('/gym/workout/<int:workout_id>', methods=['PUT'])
def update_workout(workout_id):
    data = request.get_json()
    username = data.get('username')
    
    if not username:
        return jsonify({"error": "Username is required"}), 400
    
    workout = Workout.query.filter_by(id=workout_id, username=username).first()
    if not workout:
        return jsonify({"error": "Workout not found"}), 404
    
    # Update workout items
    for item_data in data.get('workout_items', []):
        item = WorkoutItem.query.filter_by(id=item_data['id'], workout_id=workout_id).first()
        if item:
            item.exercise = item_data['exercise']
            item.weight = item_data['weight']
            item.sets = item_data['sets']
            item.reps = item_data['reps']
            item.completed = item_data.get('completed', False)
            item.notes = item_data.get('notes', '')
    
    db.session.commit()
    return jsonify({"message": "Workout updated successfully"}), 200

@api_Gym_Page.route('/gym/workout/<int:workout_id>', methods=['DELETE'])
def delete_workout(workout_id):
    data = request.get_json()
    username = data.get('username')
    
    if not username:
        return jsonify({"error": "Username is required"}), 400
    
    workout = Workout.query.filter_by(id=workout_id, username=username).first()
    if not workout:
        return jsonify({"error": "Workout not found"}), 404
    
    db.session.delete(workout)
    db.session.commit()
    return jsonify({"message": "Workout deleted successfully"}), 200

@api_Gym_Page.route('/gym/workout/item/<int:item_id>', methods=['DELETE'])
def delete_workout_item(item_id):
    """Delete a specific workout item"""
    try:
        data = request.get_json()
        username = data.get('username')
        
        if not username:
            return jsonify({"error": "Username is required"}), 400
        
        # Find the workout item and its associated workout
        workout_item = WorkoutItem.query.get(item_id)
        if not workout_item:
            return jsonify({"error": "Workout item not found"}), 404
            
        workout = Workout.query.get(workout_item.workout_id)
        if not workout or workout.username != username:
            return jsonify({"error": "Workout not found or unauthorized"}), 404
        
        # Delete the workout item
        db.session.delete(workout_item)
        db.session.commit()
        
        return jsonify({
            "message": "Workout item deleted successfully",
            "item_id": item_id
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Failed to delete workout item: {str(e)}"}), 500 
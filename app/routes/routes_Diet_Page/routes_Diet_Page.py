from flask import jsonify, Blueprint, request
from app.models import db
from app.models.user import User, FoodData, NutritionGoals, FoodFavorites
from datetime import datetime, timedelta
import json

api_Diet_Page = Blueprint("api_Diet_Page", __name__, url_prefix="")


@api_Diet_Page.route("/diet/sync", methods=["POST"])
def sync_food_data():
    """Sync user's food data to the database"""
    print("\n=== Starting Food Data Sync ===")
    try:
        data = request.get_json()
        print(f"Received request data: {data}")
        
        username = data.get('username')
        week_start = data.get('weekStart')
        weekly_food_items = data.get('weeklyFoodItems')
        
        print(f"Parsed data - Username: {username}, Week Start: {week_start}")
        print(f"Weekly Food Items: {weekly_food_items}")
        
        if not username or not week_start:
            print("Error: Missing required fields")
            return jsonify({'error': 'Username and week start date are required'}), 400
            
        # Check if user exists
        user = User.query.filter_by(username=username).first()
        if not user:
            print(f"Error: User not found - {username}")
            return jsonify({'error': 'User not found'}), 404
            
        # Parse the week start date
        try:
            week_start_date = datetime.strptime(week_start, '%Y-%m-%d').date()
            print(f"Parsed week start date: {week_start_date}")
        except ValueError as e:
            print(f"Error parsing date: {e}")
            return jsonify({'error': 'Invalid week start date format'}), 400
            
        # Check if food data entry exists for this user and week
        food_data_entry = FoodData.query.filter_by(
            username=username,
            week_start=week_start_date
        ).first()
        
        print(f"Existing food data entry found: {food_data_entry is not None}")
        
        try:
            if food_data_entry:
                # Update existing entry
                print("Updating existing food data entry")
                food_data_entry.weekly_food_items = json.dumps(weekly_food_items)
                food_data_entry.updated_at = datetime.utcnow()
            else:
                # Create new entry
                print("Creating new food data entry")
                food_data_entry = FoodData(
                    username=username,
                    week_start=week_start_date,
                    weekly_food_items=json.dumps(weekly_food_items),
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                db.session.add(food_data_entry)
                
            print("Committing changes to database")
            db.session.commit()
            print("Database commit successful")
            
            return jsonify({
                'message': 'Food data synced successfully',
                'username': username,
                'weekStart': week_start,
                'timestamp': datetime.utcnow().isoformat()
            }), 200
            
        except Exception as db_error:
            print(f"Database error: {str(db_error)}")
            db.session.rollback()
            raise db_error
        
    except Exception as e:
        print(f"Unexpected error in sync_food_data: {str(e)}")
        print(f"Error type: {type(e)}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")
        db.session.rollback()
        return jsonify({'error': f'Failed to sync food data: {str(e)}'}), 500
    finally:
        print("=== End of Food Data Sync ===\n")


@api_Diet_Page.route("/diet/data", methods=["GET"])
def get_food_data():
    """Get user's food data from the database"""
    try:
        username = request.args.get('username')
        week_start = request.args.get('weekStart')
        
        if not username or not week_start:
            return jsonify({'error': 'Username and week start date are required'}), 400
            
        # Check if user exists
        user = User.query.filter_by(username=username).first()
        if not user:
            return jsonify({'error': 'User not found'}), 404
            
        # Parse the week start date
        try:
            week_start_date = datetime.strptime(week_start, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'error': 'Invalid week start date format'}), 400
            
        # Get food data for this user and week
        food_data_entry = FoodData.query.filter_by(
            username=username,
            week_start=week_start_date
        ).first()
        
        if not food_data_entry:
            # Try to get the previous week's data
            previous_week_start = week_start_date - timedelta(days=7)
            previous_week_data = FoodData.query.filter_by(
                username=username,
                week_start=previous_week_start
            ).first()
            
            if previous_week_data:
                # Copy previous week's data but reset eaten status
                previous_items = json.loads(previous_week_data.weekly_food_items)
                new_items = {}
                
                for day, items in previous_items.items():
                    new_items[day] = [
                        {**item, 'eaten': False} 
                        for item in items
                    ]
                
                # Create new entry with copied data
                food_data_entry = FoodData(
                    username=username,
                    week_start=week_start_date,
                    weekly_food_items=json.dumps(new_items),
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                db.session.add(food_data_entry)
                db.session.commit()
                
                return jsonify({
                    'message': 'Previous week\'s food data copied successfully',
                    'username': username,
                    'weekStart': week_start,
                    'weeklyFoodItems': new_items,
                    'last_updated': food_data_entry.updated_at.isoformat()
                }), 200
            
            return jsonify({
                'message': 'No food data found for user and week',
                'username': username,
                'weekStart': week_start,
                'weeklyFoodItems': {}
            }), 200
            
        # Parse the JSON string back to dict
        weekly_food_items = json.loads(food_data_entry.weekly_food_items) if food_data_entry.weekly_food_items else {}
        
        return jsonify({
            'message': 'Food data retrieved successfully',
            'username': username,
            'weekStart': week_start,
            'weeklyFoodItems': weekly_food_items,
            'last_updated': food_data_entry.updated_at.isoformat() if food_data_entry.updated_at else None
        }), 200
        
    except Exception as e:
        return jsonify({'error': f'Failed to retrieve food data: {str(e)}'}), 500


@api_Diet_Page.route("/diet/user/<username>/weeks", methods=["GET"])
def get_user_weeks(username):
    """Get all weeks that have food data for a user"""
    try:
        # Check if user exists
        user = User.query.filter_by(username=username).first()
        if not user:
            return jsonify({'error': 'User not found'}), 404
            
        # Get all food data entries for this user
        food_data_entries = FoodData.query.filter_by(username=username).order_by(FoodData.week_start.desc()).all()
        
        weeks = []
        for entry in food_data_entries:
            weeks.append({
                'weekStart': entry.week_start.isoformat(),
                'lastUpdated': entry.updated_at.isoformat() if entry.updated_at else None,
                'daysWithData': len([day for day, items in json.loads(entry.weekly_food_items).items() if items])
            })
        
        return jsonify({
            'username': username,
            'weeks': weeks
        }), 200
        
    except Exception as e:
        return jsonify({'error': f'Failed to retrieve user weeks: {str(e)}'}), 500


@api_Diet_Page.route("/diet/food/<int:food_id>", methods=["DELETE"])
def delete_food_item(food_id):
    """Delete a food item from the database"""
    try:
        data = request.get_json()
        username = data.get('username')
        
        if not username:
            return jsonify({'error': 'Username is required'}), 400
            
        # Check if user exists
        user = User.query.filter_by(username=username).first()
        if not user:
            return jsonify({'error': 'User not found'}), 404
            
        # Get the current week's food data
        today = datetime.utcnow().date()
        monday = today - timedelta(days=today.weekday())
        
        food_data_entry = FoodData.query.filter_by(
            username=username,
            week_start=monday
        ).first()
        
        if not food_data_entry:
            return jsonify({'error': 'No food data found for this week'}), 404
            
        # Parse the weekly food items
        weekly_food_items = json.loads(food_data_entry.weekly_food_items)
        
        # Find and remove the food item from all days
        item_removed = False
        for day in weekly_food_items:
            weekly_food_items[day] = [
                item for item in weekly_food_items[day]
                if item.get('id') != food_id
            ]
            if len(weekly_food_items[day]) < len(weekly_food_items.get(day, [])):
                item_removed = True
        
        if not item_removed:
            return jsonify({'error': 'Food item not found'}), 404
            
        # Update the food data entry
        food_data_entry.weekly_food_items = json.dumps(weekly_food_items)
        food_data_entry.updated_at = datetime.utcnow()
        
        db.session.commit()
        
        return jsonify({
            'message': 'Food item deleted successfully',
            'username': username,
            'foodId': food_id,
            'timestamp': datetime.utcnow().isoformat()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to delete food item: {str(e)}'}), 500


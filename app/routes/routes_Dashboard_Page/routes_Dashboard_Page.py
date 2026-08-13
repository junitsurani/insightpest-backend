from app.models import db
from app.models.user import User, SingingSession, LanguageSession, Workout, ProgrammingTask, SingingGoal, LanguageGoal, FoodData, NutritionGoals
from flask import jsonify, Blueprint, request
from sqlalchemy import func, and_, desc
from datetime import datetime, timedelta
import stripe
import os
import boto3
from werkzeug.utils import secure_filename
import threading
from flask import Flask, jsonify, request, Blueprint, current_app
import io
import json

from dotenv import load_dotenv
import assemblyai as aai

load_dotenv()

aai.settings.api_key = os.getenv("ASSEMBLYAI_API_KEY")

api_Dashboard_Page = Blueprint("api_Dashboard_Page", __name__, url_prefix="")

@api_Dashboard_Page.route("/api/dashboard/<username>", methods=["GET"])
def get_dashboard_data(username):
    try:
        # Get user
        user = User.query.filter_by(username=username).first()
        if not user:
            return jsonify({"error": "User not found"}), 404

        # Get current week's start (Monday)
        today = datetime.now().date()
        week_start = today - timedelta(days=today.weekday())
        week_end = week_start + timedelta(days=6)
        
        print(f"Calculating data for week: {week_start} to {week_end}")

        # Calculate singing progress
        singing_sessions = SingingSession.query.filter(
            and_(
                SingingSession.username == username,
                SingingSession.session_date >= week_start,
                SingingSession.session_date <= week_end
            )
        ).order_by(SingingSession.session_date).all()
        
        print(f"Found {len(singing_sessions)} singing sessions this week")
        for session in singing_sessions:
            print(f"Singing session: date={session.session_date}, duration={session.duration}")
        
        # Get the most recent singing goal
        singing_goal = SingingGoal.query.filter_by(username=username).order_by(desc(SingingGoal.created_at)).first()
        singing_progress = 0
        if singing_goal:
            total_minutes = sum(session.duration for session in singing_sessions)
            singing_progress = min(100, (total_minutes / singing_goal.weekly_minutes_goal) * 100)
            print(f"Singing goal: {singing_goal.weekly_minutes_goal} minutes, Total minutes: {total_minutes}, Progress: {singing_progress}%")

        # Calculate diet progress
        food_data = FoodData.query.filter(
            and_(
                FoodData.username == username,
                FoodData.week_start == week_start
            )
        ).first()
        
        print(f"Found food data for week starting {week_start}: {food_data is not None}")
        if food_data:
            print(f"Raw food data structure: {food_data.weekly_food_items}")
            try:
                weekly_items = json.loads(food_data.weekly_food_items)
                print(f"Parsed weekly items structure: {json.dumps(weekly_items, indent=2)}")
            except json.JSONDecodeError as e:
                print(f"Error parsing food data JSON: {str(e)}")
        
        nutrition_goals = NutritionGoals.query.filter_by(username=username).first()
        diet_progress = 0
        if food_data:
            try:
                # Debug logging
                print(f"Raw food data: {food_data.weekly_food_items}")
                
                # Parse the weekly_food_items JSON string
                weekly_items = json.loads(food_data.weekly_food_items)
                print(f"Parsed weekly items: {weekly_items}")
                
                # Count total eaten items across all days
                total_eaten_items = 0
                total_food_items = 0
                for day_key, day_items in weekly_items.items():
                    print(f"Processing day {day_key}: {day_items}")
                    if isinstance(day_items, list):
                        for item in day_items:
                            print(f"Item: {item}")
                            if isinstance(item, dict):
                                total_food_items += 1
                                if item.get('eaten'):
                                    total_eaten_items += 1
                                    print(f"Found eaten item: {item.get('name')}")
                
                print(f"Total food items: {total_food_items}")
                print(f"Total eaten items: {total_eaten_items}")
                
                # Calculate progress based on percentage of eaten items
                diet_progress = min(100, (total_eaten_items / total_food_items * 100) if total_food_items > 0 else 0)
                print(f"Calculated diet progress: {diet_progress}%")
            except (json.JSONDecodeError, AttributeError) as e:
                print(f"Error processing food data: {str(e)}")
                diet_progress = 0

        # Calculate gym progress
        workouts = Workout.query.filter(
            and_(
                Workout.username == username,
                Workout.workout_date >= week_start,
                Workout.workout_date <= week_end
            )
        ).order_by(Workout.workout_date).all()
        
        print(f"Found {len(workouts)} workouts this week")
        for workout in workouts:
            print(f"Workout date: {workout.workout_date}")
        
        gym_progress = 0
        if workouts:
            # Assuming 5 workouts per week is the goal
            gym_progress = min(100, (len(workouts) / 5) * 100)
            print(f"Gym progress: {len(workouts)}/5 workouts = {gym_progress}%")

        # Calculate programming progress
        programming_tasks = ProgrammingTask.query.filter(
            and_(
                ProgrammingTask.username == username,
                ProgrammingTask.task_date >= week_start,
                ProgrammingTask.task_date <= week_end
            )
        ).order_by(ProgrammingTask.task_date).all()
        
        print(f"Found {len(programming_tasks)} programming tasks this week")
        
        programming_progress = 0
        if programming_tasks:
            completed_tasks = sum(1 for task in programming_tasks if task.completed)
            programming_progress = min(100, (completed_tasks / len(programming_tasks)) * 100)
            print(f"Programming progress: {completed_tasks}/{len(programming_tasks)} tasks = {programming_progress}%")

        # Calculate language progress
        language_sessions = LanguageSession.query.filter(
            and_(
                LanguageSession.username == username,
                LanguageSession.session_date >= week_start,
                LanguageSession.session_date <= week_end
            )
        ).order_by(LanguageSession.session_date).all()
        
        print(f"Found {len(language_sessions)} language sessions this week")
        for session in language_sessions:
            print(f"Language session: date={session.session_date}, duration={session.duration}")
        
        # Get the most recent language goal
        language_goal = LanguageGoal.query.filter_by(username=username).order_by(desc(LanguageGoal.created_at)).first()
        language_progress = 0
        if language_goal:
            total_minutes = sum(session.duration for session in language_sessions)
            language_progress = min(100, (total_minutes / language_goal.weekly_minutes_goal) * 100)
            print(f"Language goal: {language_goal.weekly_minutes_goal} minutes, Total minutes: {total_minutes}, Progress: {language_progress}%")

        # Calculate weekly progress data
        weekly_data = []
        for i in range(7):
            current_date = week_start + timedelta(days=i)
            
            # Get daily singing progress
            daily_singing = 0
            if singing_goal:
                daily_minutes = sum(
                    session.duration for session in singing_sessions 
                    if session.session_date == current_date
                )
                # Calculate progress based on weekly goal
                daily_singing = min(100, (daily_minutes / singing_goal.weekly_minutes_goal) * 100)
                print(f"Day {current_date} singing: {daily_minutes} minutes, goal: {singing_goal.weekly_minutes_goal}, progress: {daily_singing}%")
            
            # Get daily diet progress
            daily_diet = 0
            if food_data:
                try:
                    weekly_items = json.loads(food_data.weekly_food_items)
                    day_key = str(current_date.weekday())  # Use weekday index as key (Monday=0)
                    print(f"\nProcessing diet data for date: {current_date}")
                    print(f"Looking for day key: {day_key} (weekday index)")
                    print(f"Available keys in weekly_items: {list(weekly_items.keys())}")
                    day_items = weekly_items.get(day_key, [])
                    print(f"Found items for day {day_key}: {json.dumps(day_items, indent=2)}")
                    
                    if isinstance(day_items, list):
                        # Count total and eaten items for this day
                        total_day_items = sum(1 for item in day_items if isinstance(item, dict))
                        eaten_day_items = sum(1 for item in day_items if isinstance(item, dict) and item.get('eaten'))
                        print(f"Day {current_date} diet details - Total items: {total_day_items}, Eaten items: {eaten_day_items}")
                        # Calculate daily progress as percentage of eaten items
                        daily_diet = min(100, (eaten_day_items / total_day_items * 100) if total_day_items > 0 else 0)
                        print(f"Calculated daily diet progress: {daily_diet}%")
                except (json.JSONDecodeError, AttributeError) as e:
                    print(f"Error processing daily diet data: {str(e)}")
                    print(f"Error type: {type(e)}")
                    daily_diet = 0
            
            # Get daily gym progress
            daily_gym = 100 if any(w.workout_date == current_date for w in workouts) else 0
            print(f"Day {current_date} gym: {daily_gym}%")
            
            # Get daily programming progress
            daily_programming = 0
            daily_tasks = [task for task in programming_tasks if task.task_date == current_date]
            if daily_tasks:
                completed_tasks = sum(1 for task in daily_tasks if task.completed)
                daily_programming = min(100, (completed_tasks / len(daily_tasks)) * 100)
                print(f"Day {current_date} programming: {completed_tasks}/{len(daily_tasks)} tasks = {daily_programming}%")
            
            # Get daily language progress
            daily_language = 0
            if language_goal:
                daily_minutes = sum(
                    session.duration for session in language_sessions 
                    if session.session_date == current_date
                )
                # Calculate progress based on weekly goal
                daily_language = min(100, (daily_minutes / language_goal.weekly_minutes_goal) * 100)
                print(f"Day {current_date} language: {daily_minutes} minutes, goal: {language_goal.weekly_minutes_goal}, progress: {daily_language}%")
            
            weekly_data.append({
                "day": current_date.strftime("%a"),
                "singing": daily_singing,
                "diet": daily_diet,
                "gym": daily_gym,
                "programming": daily_programming,
                "language": daily_language
            })

        # Calculate current goals
        current_goals = [
            {
                "category": "Singing",
                "goal": f"Practice {singing_goal.weekly_minutes_goal} minutes weekly" if singing_goal else "Set a singing goal",
                "progress": int(singing_progress),
                "streak": 0  # You might want to implement streak calculation
            },
            {
                "category": "Diet",
                "goal": f"Track {nutrition_goals.daily_calorie_goal} calories daily" if nutrition_goals else "Set nutrition goals",
                "progress": int(diet_progress),
                "streak": 0
            },
            {
                "category": "Gym",
                "goal": "Workout 5x per week",
                "progress": int(gym_progress),
                "streak": 0
            },
            {
                "category": "Programming",
                "goal": "Complete daily tasks",
                "progress": int(programming_progress),
                "streak": 0
            },
            {
                "category": "Language",
                "goal": f"Study {language_goal.weekly_minutes_goal} minutes weekly" if language_goal else "Set a language goal",
                "progress": int(language_progress),
                "streak": 0
            }
        ]

        # Calculate overall weekly progress
        overall_progress = sum(goal["progress"] for goal in current_goals) / len(current_goals)
        print(f"Overall weekly progress: {overall_progress}%")

        return jsonify({
            "weeklyProgress": weekly_data,
            "currentGoals": current_goals,
            "overallProgress": round(overall_progress)
        })

    except Exception as e:
        print(f"Error in get_dashboard_data: {str(e)}")  # Add logging
        return jsonify({"error": str(e)}), 500



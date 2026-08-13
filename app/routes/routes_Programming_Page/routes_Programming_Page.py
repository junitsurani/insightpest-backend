from flask import jsonify, Blueprint, request
from app.models import db
from app.models.user import User, ProgrammingTask
from datetime import datetime, timezone
import logging

api_Programming_Page = Blueprint("api_Programming_Page", __name__, url_prefix="")

@api_Programming_Page.route('/programming/tasks', methods=['GET'])
def get_tasks():
    username = request.args.get('username')
    date = request.args.get('date')
    
    print(f"\n=== GET TASKS REQUEST ===")
    print(f"Username: {username}")
    print(f"Date: {date}")
    
    if not username:
        return jsonify({"error": "Username is required"}), 400
    
    try:
        # Parse the date and ensure it's in UTC
        date_obj = datetime.strptime(date, '%Y-%m-%d').date() if date else datetime.now(timezone.utc).date()
        print(f"Parsed date: {date_obj}")
        
        # Get daily tasks with explicit date comparison
        daily_tasks = ProgrammingTask.query.filter(
            ProgrammingTask.username == username,
            ProgrammingTask.type == 'daily',
            ProgrammingTask.task_date == date_obj
        ).all()
        
        # Get weekly tasks
        weekly_tasks = ProgrammingTask.query.filter(
            ProgrammingTask.username == username,
            ProgrammingTask.type == 'weekly'
        ).all()
        
        print(f"Found {len(daily_tasks)} daily tasks and {len(weekly_tasks)} weekly tasks")
        
        # Debug each task's date
        for task in daily_tasks:
            print(f"Task ID: {task.id}, Title: {task.title}, Date: {task.task_date}, Type: {task.type}")
        
        response_data = {
            "daily_tasks": [task.to_dict() for task in daily_tasks],
            "weekly_tasks": [task.to_dict() for task in weekly_tasks]
        }
        print(f"Response data: {response_data}")
        
        return jsonify(response_data), 200
        
    except Exception as e:
        print(f"Error in get_tasks: {str(e)}")
        return jsonify({"error": str(e)}), 500

@api_Programming_Page.route('/programming/task', methods=['POST'])
def create_task():
    print("\n=== CREATE TASK REQUEST ===")
    data = request.get_json()
    print(f"Received data: {data}")
    
    username = data.get('username')
    print(f"Username: {username}")
    
    if not username:
        print("Error: Username is missing")
        return jsonify({"error": "Username is required"}), 400
    
    try:
        # Convert date string to date object in UTC
        date_str = data.get('date')
        print(f"Date string: {date_str}")
        
        if not date_str:
            print("Error: Date is missing")
            return jsonify({"error": "Date is required"}), 400
            
        try:
            # Parse the date and ensure it's in UTC
            task_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            print(f"Parsed date: {task_date}")
        except ValueError as e:
            print(f"Error parsing date: {str(e)}")
            return jsonify({"error": "Invalid date format. Use YYYY-MM-DD"}), 400
        
        # Create new task
        task_data = {
            'username': username,
            'title': data.get('title'),
            'description': data.get('description'),
            'category': data.get('category'),
            'estimated_time': float(data.get('estimatedTime', 0)) if data.get('estimatedTime') else None,
            'priority': data.get('priority'),
            'type': data.get('type', 'daily'),
            'task_date': task_date
        }
        print(f"Task data to create: {task_data}")
        
        new_task = ProgrammingTask(**task_data)
        print(f"Created task object: {new_task.to_dict()}")
        
        db.session.add(new_task)
        db.session.commit()
        
        print(f"Task created successfully with ID: {new_task.id}")
        
        response_data = {
            "message": "Task created successfully",
            "task": new_task.to_dict()
        }
        print(f"Sending response: {response_data}")
        
        return jsonify(response_data), 201
        
    except Exception as e:
        db.session.rollback()
        print(f"Error creating task: {str(e)}")
        return jsonify({"error": str(e)}), 500

@api_Programming_Page.route('/programming/task/<int:task_id>', methods=['PUT'])
def update_task(task_id):
    print(f"\n=== UPDATE TASK REQUEST (ID: {task_id}) ===")
    data = request.get_json()
    print(f"Received data: {data}")
    
    try:
        task = ProgrammingTask.query.get_or_404(task_id)
        print(f"Found task: {task.to_dict()}")
        
        if data.get('title'):
            task.title = data['title']
        if data.get('description'):
            task.description = data['description']
        if data.get('category'):
            task.category = data['category']
        if data.get('estimatedTime'):
            task.estimated_time = float(data['estimatedTime'])
        if data.get('priority'):
            task.priority = data['priority']
        if data.get('completed') is not None:
            task.completed = data['completed']
        if data.get('date'):
            task.task_date = datetime.strptime(data['date'], '%Y-%m-%d').date()
            
        print(f"Updated task data: {task.to_dict()}")
        
        db.session.commit()
        print("Task updated successfully")
        
        return jsonify({
            "message": "Task updated successfully",
            "task": task.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        print(f"Error updating task: {str(e)}")
        return jsonify({"error": str(e)}), 500

@api_Programming_Page.route('/programming/task/<int:task_id>', methods=['DELETE'])
def delete_task(task_id):
    print(f"\n=== DELETE TASK REQUEST (ID: {task_id}) ===")
    try:
        task = ProgrammingTask.query.get_or_404(task_id)
        print(f"Found task to delete: {task.to_dict()}")
        
        db.session.delete(task)
        db.session.commit()
        print("Task deleted successfully")
        
        return jsonify({"message": "Task deleted successfully"}), 200
        
    except Exception as e:
        db.session.rollback()
        print(f"Error deleting task: {str(e)}")
        return jsonify({"error": str(e)}), 500 
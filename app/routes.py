# project_root/app/routes.py
from flask import Blueprint, render_template, request, jsonify
import os
import json
import uuid 

from .assistant_engine import get_assistant_response

bp = Blueprint('main', __name__)
insights_file_path = os.path.join(os.path.dirname(__file__), '..', 'insights.json')

DEFAULT_WORKPLACE_ID = "default_wp_001"
DEFAULT_WORKPLACE_NAME = "My General Insights"

def get_default_insights_structure():
    return {"workplaces": {DEFAULT_WORKPLACE_ID: {"name": DEFAULT_WORKPLACE_NAME, "insights": []}}, "activeWorkplaceId": DEFAULT_WORKPLACE_ID}

def initialize_insights_file():
    """Initializes insights.json robustly if it doesn't exist or is empty/invalid."""
    if not os.path.exists(insights_file_path):
        print(f"Insights file not found at {insights_file_path}. Creating with default structure.")
        save_insights_data(get_default_insights_structure())
        return
    try:
        with open(insights_file_path, 'r') as f:
            content = f.read()
            if not content.strip(): # Empty file
                print(f"Insights file at {insights_file_path} is empty. Initializing with default structure.")
                save_insights_data(get_default_insights_structure())
                return
            data = json.loads(content)
            # Check for the expected top-level 'workplaces' key and its type
            if not isinstance(data, dict) or "workplaces" not in data or not isinstance(data.get("workplaces"), dict):
                raise ValueError("Invalid root structure or missing 'workplaces' dictionary.")
            
            # Ensure default workplace exists if no workplaces are present or if default is missing
            if not data["workplaces"] or DEFAULT_WORKPLACE_ID not in data["workplaces"]:
                 data["workplaces"][DEFAULT_WORKPLACE_ID] = {"name": DEFAULT_WORKPLACE_NAME, "insights": []}
                 # If activeWorkplaceId is missing or invalid, set it to default
                 if "activeWorkplaceId" not in data or data.get("activeWorkplaceId") not in data["workplaces"]:
                     data["activeWorkplaceId"] = DEFAULT_WORKPLACE_ID
                 save_insights_data(data)
            # Ensure there's an activeWorkplaceId if workplaces exist and it's not set or invalid
            elif "activeWorkplaceId" not in data or data.get("activeWorkplaceId") not in data["workplaces"]:
                 data["activeWorkplaceId"] = next(iter(data["workplaces"]), DEFAULT_WORKPLACE_ID) # first workplace or default
                 save_insights_data(data)

    except (json.JSONDecodeError, ValueError, TypeError) as e:
        print(f"Warning: {insights_file_path} is invalid or has wrong structure ({e}). Re-initializing.")
        save_insights_data(get_default_insights_structure())
    except Exception as e: 
        print(f"Unexpected error during insights file initialization: {e}. Re-initializing.")
        save_insights_data(get_default_insights_structure())

def load_insights_data():
    initialize_insights_file() 
    try:
        with open(insights_file_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Critical error loading insights data: {e}. Returning default structure.")
        return get_default_insights_structure()

def save_insights_data(data):
    try:
        with open(insights_file_path, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Error saving insights data: {e}")

initialize_insights_file() 

@bp.route('/')
def index(): return render_template('chat.html', welcome_message="Welcome to RXO Logistics AI!")

@bp.route('/chat', methods=['GET', 'POST'])
def chat():
    if request.method == 'POST':
        payload = request.json; user_query = payload.get('query')
        conversation_history_raw = payload.get('conversation_history', [])
        if not user_query: return jsonify({"error": "No query provided"}), 400
        response_data = get_assistant_response(user_query, conversation_history_raw=conversation_history_raw)
        return jsonify(response_data)
    return render_template('chat.html', welcome_message="Welcome to RXO Logistics AI! Ask me anything.")

@bp.route('/insights')
def insights_page(): return render_template('insights.html')

@bp.route('/api/workplaces', methods=['GET'])
def get_workplaces():
    data = load_insights_data()
    workplaces_list = [{"id": wid, "name": wdata["name"]} for wid, wdata in data.get("workplaces", {}).items()]
    return jsonify(workplaces_list)

@bp.route('/api/workplaces', methods=['POST'])
def create_workplace():
    payload = request.json; workplace_name = payload.get('name')
    if not workplace_name: return jsonify({"error": "Workplace name required"}), 400
    data = load_insights_data()
    for w_data in data.get("workplaces", {}).values():
        if w_data["name"] == workplace_name: return jsonify({"error": f"Workplace '{workplace_name}' exists"}), 409
    workplace_id = "wp_" + str(uuid.uuid4().hex[:8])
    data.setdefault("workplaces", {})[workplace_id] = {"name": workplace_name, "insights": []}
    # Optionally set the new workplace as active, or let user select
    # data["activeWorkplaceId"] = workplace_id 
    save_insights_data(data)
    return jsonify({"message": "Workplace created", "id": workplace_id, "name": workplace_name}), 201

@bp.route('/api/workplaces/<workplace_id>', methods=['DELETE'])
def delete_workplace(workplace_id):
    data = load_insights_data()
    if workplace_id == DEFAULT_WORKPLACE_ID and len(data.get("workplaces", {})) <= 1 :
        return jsonify({"error": "Cannot delete the last default workplace."}), 403
    
    if workplace_id in data.get("workplaces", {}):
        deleted_wp_name = data["workplaces"][workplace_id].get("name", workplace_id)
        del data["workplaces"][workplace_id]
        
        if data.get("activeWorkplaceId") == workplace_id:
            # Set active to another existing workplace, or to default if it exists, or make a new default
            data["activeWorkplaceId"] = next(iter(data.get("workplaces", {})), None) 
            if not data["activeWorkplaceId"]: # No other workplaces left
                data["workplaces"][DEFAULT_WORKPLACE_ID] = {"name": DEFAULT_WORKPLACE_NAME, "insights": []}
                data["activeWorkplaceId"] = DEFAULT_WORKPLACE_ID
        
        save_insights_data(data)
        return jsonify({"message": f"Workplace '{deleted_wp_name}' deleted successfully"}), 200
    return jsonify({"error": f"Workplace {workplace_id} not found"}), 404

@bp.route('/api/workplaces/<workplace_id>/insights', methods=['GET'])
def get_insights_for_workplace(workplace_id):
    data = load_insights_data()
    workplace = data.get("workplaces", {}).get(workplace_id)
    if workplace: 
        return jsonify(workplace.get("insights", []))
    
    # Fallback or error if specific workplace not found
    # For now, let's be strict and return 404 if not found, rather than defaulting.
    # Client-side can then decide to load default if this fails.
    # default_wp_data = data.get("workplaces",{}).get(DEFAULT_WORKPLACE_ID, {"insights":[]})
    # print(f"Workplace {workplace_id} not found, attempting to return default insights for {DEFAULT_WORKPLACE_ID}.")
    # return jsonify(default_wp_data.get("insights",[])) 
    return jsonify({"error": f"Workplace {workplace_id} not found"}), 404


@bp.route('/api/workplaces/<workplace_id>/insights', methods=['POST'])
def save_insight_to_workplace(workplace_id):
    insight_data = request.json
    if not insight_data or not insight_data.get("id"): return jsonify({"error": "Insight data/ID missing"}), 400
    data = load_insights_data()
    
    if workplace_id not in data.get("workplaces", {}):
        # Option: create workplace if it doesn't exist, or error out
        # For now, error out if specific workplace ID is provided and not found
        return jsonify({"error": f"Target workplace {workplace_id} not found."}), 404

    workplace = data["workplaces"][workplace_id]
    existing_insight_index = next((i for i, insight in enumerate(workplace.get("insights",[])) if insight.get("id") == insight_data.get("id")), -1)
    if existing_insight_index != -1:
        print(f"Insight {insight_data.get('id')} already in {workplace_id}. Updating.")
        workplace["insights"][existing_insight_index] = insight_data
    else:
        workplace.setdefault("insights", []).append(insight_data)
    save_insights_data(data)
    return jsonify({"message": f"Insight saved to workplace '{workplace['name']}' successfully"}), 201

@bp.route('/api/workplaces/<workplace_id>/insights/<insight_id>', methods=['DELETE'])
def delete_insight_from_workplace(workplace_id, insight_id):
    data = load_insights_data(); workplace = data.get("workplaces", {}).get(workplace_id)
    if not workplace: return jsonify({"error": "Workplace not found"}), 404
    initial_len = len(workplace.get("insights", []))
    workplace["insights"] = [i for i in workplace.get("insights", []) if i.get("id") != insight_id]
    if len(workplace["insights"]) < initial_len:
        save_insights_data(data); return jsonify({"message": "Insight deleted"}), 200
    return jsonify({"error": "Insight not found"}), 404

@bp.route('/charts')
def charts_showcase_page():
    return render_template('charts_showcase.html', title="Chart.js Showcase")
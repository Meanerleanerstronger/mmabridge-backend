# ==============================================
# MMA BRIDGE - FLASK BACKEND (WITH DATABASE)
# ==============================================

from flask import Flask, jsonify, request
from flask_cors import CORS
import json
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Import database functions
from database import (
    get_all_fighters,
    get_fighter_by_id,
    get_all_events,
    get_upcoming_events
)

# Import chatbot
from chatbot import chat_with_lucas

# Create Flask app
app = Flask(__name__)

# Enable CORS with environment-based origins
allowed_origins = os.getenv('ALLOWED_ORIGINS', '*').split(',')
CORS(app, origins=allowed_origins)

# Path to your data files (for fallback)
DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')

# ==============================================
# HELPER FUNCTIONS
# ==============================================

def load_json(filename):
    """Load a JSON file from the data directory (FALLBACK ONLY)"""
    filepath = os.path.join(DATA_DIR, filename)
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except json.JSONDecodeError:
        return None

# ==============================================
# API ROUTES
# ==============================================

@app.route('/')
def home():
    """Homepage - just to check server is running"""
    return jsonify({
        'message': 'MMA Bridge API is running!',
        'version': '1.0',
        'endpoints': {
            'fighters': '/api/fighters',
            'events': '/api/events',
            'upcoming_events': '/api/events/upcoming',
            'news': '/api/news',
            'pfp_rankings': '/api/rankings/pfp'
        }
    })

@app.route('/api/fighters')
def get_fighters():
    """Get all fighters from database"""
    try:
        fighters = get_all_fighters()
        return jsonify(fighters)
    except Exception as e:
        print(f"Database error: {e}")
        # Fallback to JSON file if database fails
        fighters = load_json('fighters.json')
        if fighters is None:
            return jsonify({'error': 'Fighters data not found'}), 404
        return jsonify(fighters)

@app.route('/api/fighters/<fighter_id>')
def get_fighter(fighter_id):
    """Get a single fighter by ID from database"""
    try:
        fighter = get_fighter_by_id(fighter_id)
        
        if fighter is None:
            return jsonify({'error': 'Fighter not found'}), 404
        
        return jsonify(fighter)
    except Exception as e:
        print(f"Database error: {e}")
        # Fallback to JSON file if database fails
        fighters = load_json('fighters.json')
        
        if fighters is None:
            return jsonify({'error': 'Fighters data not found'}), 404
        
        fighter = fighters.get(fighter_id)
        
        if fighter is None:
            return jsonify({'error': 'Fighter not found'}), 404
        
        return jsonify(fighter)

@app.route('/api/events')
def get_events():
    """Get all events from database"""
    try:
        events = get_all_events()
        return jsonify(events)
    except Exception as e:
        print(f"Database error: {e}")
        # Fallback to JSON file if database fails
        events = load_json('events.json')
        if events is None:
            return jsonify({'error': 'Events data not found'}), 404
        return jsonify(events)

@app.route('/api/events/upcoming')
def get_upcoming_events_route():
    """Get upcoming events from database"""
    try:
        events = get_upcoming_events()
        return jsonify(events)
    except Exception as e:
        print(f"Database error: {e}")
        # Fallback to JSON file if database fails
        events = load_json('events.json')
        if events is None:
            return jsonify({'error': 'Events data not found'}), 404
        return jsonify(events)

@app.route('/api/news')
def get_news():
    """Get news data"""
    news = load_json('news.json')
    
    if news is None:
        return jsonify({'error': 'News data not found'}), 404
    
    return jsonify(news)

@app.route('/api/news/trending')
def get_trending_news():
    """Get trending news"""
    news = load_json('news.json')
    
    if news is None:
        return jsonify({'error': 'News data not found'}), 404
    
    # Return just the trending section
    return jsonify(news.get('trending', []))

@app.route('/api/rankings/pfp')
def get_pfp_rankings():
    """Get pound-for-pound rankings"""
    rankings = load_json('top_fighters.json')
    
    if rankings is None:
        return jsonify({'error': 'Rankings data not found'}), 404
    
    return jsonify(rankings)

@app.route('/api/chat', methods=['POST'])
def chat():
    """Chat with Lucas Bot"""
    try:
        data = request.get_json()
        
        if not data or 'message' not in data:
            return jsonify({'error': 'No message provided'}), 400
        
        user_message = data['message']
        conversation_history = data.get('history', [])
        page_context = data.get('page', 'general')  # Get page context
        
        # Get response from Lucas Bot with page context
        response = chat_with_lucas(user_message, conversation_history, page_context)
        
        @app.route('/api/news')
def get_all_news():
    """Get all news"""
    news = load_json('news.json')
    
    if news is None:
        return jsonify({'error': 'News data not found'}), 404
    
    return jsonify(news)
        
        return jsonify({
            'response': response,
            'success': True
        })
        
    except Exception as e:
        print(f"Chat error: {e}")
        return jsonify({
            'error': 'Failed to get response from Lucas Bot',
            'success': False
        }), 500

# ==============================================
# ERROR HANDLERS
# ==============================================

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Endpoint not found'}), 404

@app.errorhandler(500)
def server_error(error):
    return jsonify({'error': 'Internal server error'}), 500

# ==============================================
# RUN SERVER
# ==============================================

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5001))
    debug = os.getenv('FLASK_ENV', 'development') == 'development'
    
    if debug:
        print('=' * 50)
        print('🥊 MMA BRIDGE API SERVER')
        print('=' * 50)
        print(f'Server running at: http://localhost:{port}')
        print(f'API endpoints at: http://localhost:{port}/api/')
        print('Press CTRL+C to stop')
        print('=' * 50)
    
    # Run the server
    app.run(
        host='0.0.0.0',
        port=port,
        debug=debug
    )

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
    get_upcoming_events,
    save_event_rating,
    get_event_ratings,
    get_event_avg_rating
)

# Import scraper reader
try:
    from scrape_tapology import get_events_for_api, run as run_tapology_scraper
    SCRAPER_AVAILABLE = True
except ImportError:
    SCRAPER_AVAILABLE = False

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
        fighters = load_json('fighters.json')
        if fighters is None:
            return jsonify({'error': 'Fighters data not found'}), 404
        fighter = fighters.get(fighter_id)
        if fighter is None:
            return jsonify({'error': 'Fighter not found'}), 404
        return jsonify(fighter)

@app.route('/api/events')
def get_events():
    """Get all events — from Tapology scraper DB first, fallback to JSON"""
    try:
        if SCRAPER_AVAILABLE:
            events = get_events_for_api()
            if events:
                return jsonify(events)
        events = get_all_events()
        if events:
            return jsonify(events)
    except Exception as e:
        print(f"DB error: {e}")
    events = load_json('events.json')
    if events is None:
        return jsonify({'error': 'Events data not found'}), 404
    return jsonify(events)

@app.route('/api/events/upcoming')
def get_upcoming_events_route():
    """Get upcoming events only (date >= today)"""
    try:
        if SCRAPER_AVAILABLE:
            from datetime import date
            all_events = get_events_for_api()
            today = date.today().isoformat()
            upcoming = [e for e in all_events if (e.get('isoDate') or '9999') >= today]
            if upcoming:
                return jsonify(upcoming)
        events = get_upcoming_events()
        if events:
            return jsonify(events)
    except Exception as e:
        print(f"DB error: {e}")
    events = load_json('events.json')
    if events is None:
        return jsonify({'error': 'Events data not found'}), 404
    return jsonify(events)

@app.route('/api/events/past')
def get_past_events_route():
    """Get past events only (date < today)"""
    try:
        from datetime import date
        if SCRAPER_AVAILABLE:
            all_events = get_events_for_api()
        else:
            all_events = get_all_events()
        today = date.today().isoformat()
        past = [e for e in all_events if (e.get('isoDate') or '9999') < today]
        return jsonify(past)
    except Exception as e:
        print(f"Past events error: {e}")
        return jsonify([])

@app.route('/api/scrape', methods=['POST'])
def trigger_scrape():
    """Trigger Tapology scraper manually — protect with secret key"""
    secret = request.headers.get('X-Scrape-Key') or request.json.get('key','') if request.is_json else ''
    expected = os.getenv('SCRAPE_SECRET', 'mmabridge-scrape')
    if secret != expected:
        return jsonify({'error': 'Unauthorized'}), 401
    if not SCRAPER_AVAILABLE:
        return jsonify({'error': 'Scraper not available'}), 500
    try:
        import threading
        t = threading.Thread(target=run_tapology_scraper)
        t.daemon = True
        t.start()
        return jsonify({'success': True, 'message': 'Scraper started in background'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

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
        page_context = data.get('page', 'general')

        response = chat_with_lucas(user_message, conversation_history, page_context)

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

@app.route('/api/ratings', methods=['POST'])
def submit_rating():
    """Submit a pre-event hype rating and FOTN prediction"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        event_id = data.get('event_id')
        event_name = data.get('event_name')
        hype_rating = data.get('hype_rating')
        fotn_prediction = data.get('fotn_prediction')
        review_text = data.get('review_text')

        if not event_id or not event_name:
            return jsonify({'error': 'event_id and event_name are required'}), 400
        if hype_rating is None or not isinstance(hype_rating, int) or not (1 <= hype_rating <= 5):
            return jsonify({'error': 'hype_rating must be an integer between 1 and 5'}), 400

        rating_id = save_event_rating(event_id, event_name, hype_rating, fotn_prediction, review_text)
        return jsonify({'success': True, 'rating_id': rating_id}), 201

    except Exception as e:
        print(f"Rating error: {e}")
        return jsonify({'error': 'Failed to save rating'}), 500


@app.route('/api/ratings/<event_id>', methods=['GET'])
def get_ratings(event_id):
    """Get all ratings for an event"""
    try:
        summary = get_event_avg_rating(event_id)
        return jsonify(summary)
    except Exception as e:
        print(f"Rating fetch error: {e}")
        return jsonify({'error': 'Failed to fetch ratings'}), 500


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

    app.run(
        host='0.0.0.0',
        port=port,
        debug=debug
    )

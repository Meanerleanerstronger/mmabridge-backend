# ==============================================
# MMA BRIDGE - FLASK BACKEND (WITH DATABASE)
# ==============================================

from flask import Flask, jsonify, request, redirect
from flask_cors import CORS
from flask_jwt_extended import (
    JWTManager, create_access_token, jwt_required,
    get_jwt_identity, verify_jwt_in_request
)
from authlib.integrations.flask_client import OAuth
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
    update_event_rating,
    get_event_ratings,
    get_event_avg_rating,
    get_event_reviews,
    create_tables,
    get_or_create_user,
    get_user_by_id
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
app.secret_key = os.getenv('SECRET_KEY', os.getenv('JWT_SECRET', 'dev-secret-change-me'))

# JWT
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET', 'dev-jwt-secret-change-me')
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = False  # tokens don't expire (users can always edit)
jwt = JWTManager(app)

# Google OAuth via Authlib — safe even if credentials not yet configured
oauth = OAuth(app)
try:
    _g_client_id     = (os.getenv('GOOGLE_CLIENT_ID') or '').strip()
    _g_client_secret = (os.getenv('GOOGLE_CLIENT_SECRET') or '').strip()
    # Debug: print first/last chars and length so we can spot newlines/spaces
    print(f"[OAuth] CLIENT_ID loaded: len={len(_g_client_id)} first10={repr(_g_client_id[:10])} last10={repr(_g_client_id[-10:])}")
    print(f"[OAuth] CLIENT_SECRET loaded: len={len(_g_client_secret)} last4={repr(_g_client_secret[-4:])}")
    google = oauth.register(
        name='google',
        client_id=_g_client_id or None,
        client_secret=_g_client_secret or None,
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={'scope': 'openid email profile'},
    )
    print(f"[OAuth] Registration OK — client_id ends with: {repr(_g_client_id[-20:])}")
except Exception as _oauth_err:
    print(f"[OAuth] Registration ERROR: {_oauth_err}")
    google = None

# Enable CORS — allow all origins (frontend is a static GitHub Pages site)
CORS(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=False)

# Ensure DB tables exist on every startup (Render has ephemeral filesystem)
create_tables()

# ── In-memory visitor ring buffer (last 10) ──
import threading, time as _time
_visitors_lock = threading.Lock()
_visitors = []   # list of dicts: {flag, city, country, ts}

def _country_flag(code):
    """ISO 3166-1 alpha-2 code → flag emoji."""
    if not code or len(code) != 2:
        return '🌍'
    return ''.join(chr(0x1F1E6 + ord(c) - ord('A')) for c in code.upper())

def _record_visitor(ip, fallback=False):
    """Resolve IP → city/country via ip-api.com and append to ring buffer."""
    try:
        import requests as _req
        r = _req.get(f'http://ip-api.com/json/{ip}?fields=status,city,country,countryCode',
                     timeout=5)
        data = r.json()
        if data.get('status') == 'success':
            city    = data.get('city', 'Unknown')
            country = data.get('country', 'Unknown')
            code    = data.get('countryCode', '')
        else:
            city, country, code = 'Unknown', 'Unknown', ''
    except Exception:
        city, country, code = 'Unknown', 'Unknown', ''

    entry = {'flag': _country_flag(code), 'city': city, 'country': country,
             'ts': int(_time.time())}
    with _visitors_lock:
        # Don't add duplicate if same IP resolved within last 60s
        now = int(_time.time())
        recent = [v for v in _visitors if now - v['ts'] < 60
                  and v['city'] == city and v['country'] == country]
        if not recent:
            _visitors.insert(0, entry)
            del _visitors[10:]

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

@app.route('/api/health')
def health():
    return jsonify({'status': 'ok'})

@app.route('/api/visitors/ping', methods=['POST'])
def visitor_ping():
    """Record a page visit — resolves IP synchronously then returns visitor list."""
    ip = (request.headers.get('X-Forwarded-For', '') or '').split(',')[0].strip() \
         or request.remote_addr or ''
    if ip and ip not in ('127.0.0.1', '::1', 'localhost', ''):
        _record_visitor(ip)
    with _visitors_lock:
        return jsonify(list(_visitors))

@app.route('/api/visitors')
def get_visitors():
    """Return the last 10 resolved visitors."""
    with _visitors_lock:
        return jsonify(list(_visitors))

# ==============================================
# AUTH ROUTES
# ==============================================

REDIRECT_URI  = os.getenv('GOOGLE_REDIRECT_URI',  'https://mmabridge.com/api/auth/google/callback')
FRONTEND_URL  = os.getenv('FRONTEND_URL',          'https://mmabridge.com')

@app.route('/api/auth/google')
def google_login():
    if not google or not os.getenv('GOOGLE_CLIENT_ID'):
        return redirect(f"{FRONTEND_URL}/auth.html?error=not_configured")
    return google.authorize_redirect(REDIRECT_URI)

@app.route('/api/auth/google/callback')
def google_callback():
    if not google:
        return redirect(f"{FRONTEND_URL}/auth.html?error=not_configured")
    try:
        token     = google.authorize_access_token()
        userinfo  = token.get('userinfo') or google.userinfo()
        user      = get_or_create_user(
            email        = userinfo['email'],
            display_name = userinfo.get('name', userinfo['email'].split('@')[0]),
            avatar_url   = userinfo.get('picture', '')
        )
        jwt_token = create_access_token(identity=str(user['id']))
        return redirect(f"{FRONTEND_URL}/auth.html?token={jwt_token}")
    except Exception as e:
        print(f"OAuth callback error: {e}")
        return redirect(f"{FRONTEND_URL}/auth.html?error=auth_failed")

@app.route('/api/auth/me')
@jwt_required()
def auth_me():
    user_id = int(get_jwt_identity())
    user    = get_user_by_id(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    return jsonify({
        'id':           user['id'],
        'email':        user['email'],
        'display_name': user['display_name'],
        'avatar_url':   user['avatar_url'] or '',
    })

@app.route('/api/auth/logout', methods=['POST'])
def auth_logout():
    # JWTs are stateless — client just deletes the token
    return jsonify({'success': True})

@app.route('/api/dbcheck')
def dbcheck():
    """Debug: show which tables exist in the live SQLite DB"""
    import sqlite3 as _sq
    from database import DB_PATH
    try:
        conn = _sq.connect(DB_PATH)
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        conn.close()
        return jsonify({'db_path': DB_PATH, 'tables': [t[0] for t in tables]})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/news')
def get_news():
    """Get news — always fetch fresh from GNews, fallback key if first runs out"""
    GNEWS_KEYS = [
        os.getenv('GNEWS_API_KEY', '962d74e7eeb020eda44c20b170b4e82d'),
        '77ee2ae117e135e8bd15d69a52c15ccf',  # backup 1
        '2fb357ce1705d322109dc121c3997d65',  # backup 2
    ]
    news_path = os.path.join(DATA_DIR, 'news.json')

    for key in GNEWS_KEYS:
        try:
            import requests as req
            url = (
                f"https://gnews.io/api/v4/search"
                f"?q=%22UFC%22+OR+%22MMA%22+OR+%22Bellator%22"
                f"&lang=en&country=us&max=10&sortby=publishedAt"
                f"&apikey={key}"
            )
            r = req.get(url, timeout=8)
            if r.status_code == 200:
                data = r.json()
                articles = [
                    {
                        'title':       a.get('title', ''),
                        'description': a.get('description', ''),
                        'url':         a.get('url', ''),
                        'imageUrl':    a.get('image') or '',
                        'source':      a.get('source', {}).get('name', ''),
                        'publishedAt': a.get('publishedAt', ''),
                    }
                    for a in data.get('articles', [])
                    if a.get('title')
                    and not any(c in (a.get('title','') + a.get('description',''))
                               for c in ['«','»','¿','¡','ó','é','á','í','ú','ñ'])
                ]
                if articles:
                    news_data = {'trending': articles, 'updatedAt': 'fresh'}
                    os.makedirs(DATA_DIR, exist_ok=True)
                    with open(news_path, 'w') as f:
                        json.dump(news_data, f)
                    return jsonify(news_data)
            elif r.status_code == 429 or r.status_code == 403:
                print(f"GNews key exhausted, trying backup...")
                continue
        except Exception as e:
            print(f"GNews error: {e}")
            continue

    # Both keys failed — return cached file
    news = load_json('news.json')
    if news is None:
        return jsonify({'trending': []})
    return jsonify(news)

@app.route('/api/news/trending')
def get_trending_news():
    news = load_json('news.json')
    if news is None:
        return jsonify([])
    return jsonify(news.get('trending', []))

@app.route('/api/news/search')
def search_news():
    """Search news for a specific query (e.g. fighter or event name)"""
    query = request.args.get('q', '')
    if not query:
        return jsonify([])
    try:
        import requests as req
        NEWS_API_KEY = os.getenv('NEWS_API_KEY', 'f01a690184c04eb0bc8a5a779981e461')
        url = (f"https://newsapi.org/v2/everything"
               f"?q={req.utils.quote(query)}&language=en&sortBy=publishedAt"
               f"&pageSize=5&apiKey={NEWS_API_KEY}")
        r = req.get(url, timeout=8)
        data = r.json()
        articles = [
            {
                'title':       a.get('title',''),
                'description': a.get('description',''),
                'url':         a.get('url',''),
                'imageUrl':    a.get('urlToImage',''),
                'source':      a.get('source',{}).get('name',''),
                'publishedAt': a.get('publishedAt',''),
            }
            for a in data.get('articles',[])[:3]
            if a.get('title') and a['title'] != '[Removed]'
        ]
        return jsonify(articles)
    except Exception as e:
        print(f"News search error: {e}")
        return jsonify([])
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
        live_data = data.get('live_data', None)

        response = chat_with_lucas(user_message, conversation_history, page_context, live_data)

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
        if hype_rating is None or not isinstance(hype_rating, (int, float)) or not (1 <= hype_rating <= 5):
            return jsonify({'error': 'hype_rating must be a number between 1 and 5'}), 400

        # Attach user if JWT present (optional — anonymous allowed)
        user_id, display_name = None, None
        try:
            verify_jwt_in_request(optional=True)
            uid = get_jwt_identity()
            if uid:
                user = get_user_by_id(int(uid))
                if user:
                    user_id      = user['id']
                    display_name = user['display_name']
        except Exception:
            pass

        rating_id = save_event_rating(event_id, event_name, hype_rating, fotn_prediction, review_text, user_id, display_name)
        return jsonify({'success': True, 'rating_id': rating_id}), 201

    except Exception as e:
        print(f"Rating error: {e}")
        return jsonify({'error': 'Failed to save rating', 'detail': str(e)}), 500


@app.route('/api/ratings/<event_id>', methods=['GET'])
def get_ratings(event_id):
    """Get all ratings for an event"""
    try:
        summary = get_event_avg_rating(event_id)
        return jsonify(summary)
    except Exception as e:
        print(f"Rating fetch error: {e}")
        return jsonify({'error': 'Failed to fetch ratings'}), 500


@app.route('/api/ratings/<int:rating_id>', methods=['PUT'])
def edit_rating(rating_id):
    """Update an existing rating (edit flow)"""
    try:
        data = request.get_json()
        hype_rating = data.get('hype_rating')
        review_text = data.get('review_text')
        if hype_rating is None or not isinstance(hype_rating, (int, float)) or not (1 <= hype_rating <= 5):
            return jsonify({'error': 'hype_rating must be a number between 1 and 5'}), 400
        update_event_rating(rating_id, hype_rating, review_text)
        return jsonify({'success': True})
    except Exception as e:
        print(f"Rating update error: {e}")
        return jsonify({'error': 'Failed to update rating', 'detail': str(e)}), 500


@app.route('/api/reviews/<event_id>', methods=['GET'])
def get_reviews(event_id):
    """Get all fan reviews for an event"""
    try:
        reviews = get_event_reviews(event_id)
        return jsonify(reviews)
    except Exception as e:
        print(f"Reviews fetch error: {e}")
        return jsonify([]), 500


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

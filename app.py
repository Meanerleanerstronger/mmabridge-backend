# ==============================================
# MMA BRIDGE - FLASK BACKEND (WITH DATABASE)
# ==============================================

from flask import Flask, jsonify, request, redirect
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_jwt_extended import (
    JWTManager, create_access_token, jwt_required,
    get_jwt_identity, verify_jwt_in_request
)
from authlib.integrations.flask_client import OAuth
import json
import os
import re
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
    get_user_by_id,
    get_user_rating_for_event,
    toggle_review_like,
    get_review_likes,
    add_review_reply,
    get_review_replies,
    toggle_reply_like
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
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = False
jwt = JWTManager(app)

# ==============================================
# RATE LIMITING
# ==============================================

limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=["200 per minute"],
    storage_uri="memory://",
)

# ==============================================
# CORS — only allow our own origins
# ==============================================

_ALLOWED_ORIGINS = [
    "https://mmabridge.com",
    "https://www.mmabridge.com",
    "http://localhost:5001",
    "http://localhost:3000",
    "http://127.0.0.1:5001",
    "http://127.0.0.1:3000",
    # GitHub Pages (where the frontend is hosted)
    "https://meanerleanerstronger.github.io",
]

CORS(app, resources={r"/api/*": {"origins": _ALLOWED_ORIGINS}}, supports_credentials=False)

# ==============================================
# SECURITY HEADERS
# ==============================================

@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    return response

# ==============================================
# GOOGLE OAUTH
# ==============================================

oauth = OAuth(app)
try:
    _g_client_id     = (os.getenv('GOOGLE_CLIENT_ID') or '').strip()
    _g_client_secret = (os.getenv('GOOGLE_CLIENT_SECRET') or '').strip()
    google = oauth.register(
        name='google',
        client_id=_g_client_id or None,
        client_secret=_g_client_secret or None,
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={'scope': 'openid email profile'},
    )
except Exception as _oauth_err:
    print(f"[OAuth] Registration error (credentials not configured)")
    google = None

# Ensure DB tables exist on every startup
create_tables()

# ==============================================
# INPUT SANITIZATION HELPERS
# ==============================================

_HTML_RE = re.compile(r'<[^>]+>', re.IGNORECASE)
_SCRIPT_RE = re.compile(r'javascript\s*:', re.IGNORECASE)

def strip_html(s):
    """Remove HTML tags and reject javascript: URIs."""
    s = _HTML_RE.sub('', s)
    s = _SCRIPT_RE.sub('', s)
    return s.strip()

def validate_str(val, name, max_len, required=True):
    """Return (cleaned_value, error_string). error_string is None on success."""
    if val is None or val == '':
        if required:
            return None, f"'{name}' is required"
        return '', None
    if not isinstance(val, str):
        return None, f"'{name}' must be a string"
    cleaned = strip_html(val)
    if len(cleaned) > max_len:
        return None, f"'{name}' exceeds maximum length of {max_len} characters"
    return cleaned, None

# ==============================================
# IN-MEMORY VISITOR RING BUFFER (last 10)
# ==============================================

import threading, time as _time
_visitors_lock = threading.Lock()
_visitors = []

def _country_flag(code):
    if not code or len(code) != 2:
        return '🌍'
    return ''.join(chr(0x1F1E6 + ord(c) - ord('A')) for c in code.upper())

def _record_visitor(ip, fallback=False):
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
        now = int(_time.time())
        recent = [v for v in _visitors if now - v['ts'] < 60
                  and v['city'] == city and v['country'] == country]
        if not recent:
            _visitors.insert(0, entry)
            del _visitors[10:]

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')

# ==============================================
# HELPER FUNCTIONS
# ==============================================

def load_json(filename):
    filepath = os.path.join(DATA_DIR, filename)
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None

# ==============================================
# API ROUTES
# ==============================================

@app.route('/')
def home():
    return jsonify({
        'message': 'MMA Bridge API is running!',
        'version': '1.0',
    })

@app.route('/api/fighters')
def get_fighters():
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
    if not isinstance(fighter_id, str) or len(fighter_id) > 100:
        return jsonify({'error': 'Invalid fighter ID'}), 400
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
    """Trigger Tapology scraper manually — protected with secret key."""
    secret = request.headers.get('X-Scrape-Key', '')
    if request.is_json:
        body = request.get_json(silent=True) or {}
        secret = secret or body.get('key', '')
    expected = os.getenv('SCRAPE_SECRET', 'mmabridge-scrape')
    if not secret or secret != expected:
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
        print(f"Scraper error: {e}")
        return jsonify({'error': 'Failed to start scraper'}), 500

@app.route('/api/health')
def health():
    return jsonify({'status': 'ok'})

@app.route('/api/visitors/ping', methods=['POST'])
@limiter.limit("60 per minute")
def visitor_ping():
    ip = (request.headers.get('X-Forwarded-For', '') or '').split(',')[0].strip() \
         or request.remote_addr or ''
    if ip and ip not in ('127.0.0.1', '::1', 'localhost', ''):
        _record_visitor(ip)
    with _visitors_lock:
        return jsonify(list(_visitors))

@app.route('/api/visitors')
def get_visitors():
    with _visitors_lock:
        return jsonify(list(_visitors))

# ==============================================
# AUTH ROUTES
# ==============================================

REDIRECT_URI  = os.getenv('GOOGLE_REDIRECT_URI',  'https://mmabridge-backend.onrender.com/api/auth/google/callback')
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
    return jsonify({'success': True})

# ==============================================
# NEWS ROUTES
# ==============================================

@app.route('/api/news')
@limiter.limit("30 per minute")
def get_news():
    """Get news — try GNews keys in order, fall back to cached file."""
    GNEWS_KEYS = [
        k for k in [
            os.getenv('GNEWS_API_KEY'),
            os.getenv('GNEWS_API_KEY_BACKUP_1'),
            os.getenv('GNEWS_API_KEY_BACKUP_2'),
        ] if k
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
            elif r.status_code in (429, 403):
                print("GNews key exhausted, trying backup...")
                continue
        except Exception as e:
            print(f"GNews error: {e}")
            continue

    news = load_json('news.json')
    if news is None:
        return jsonify({'trending': []})
    return jsonify(news)

@app.route('/api/news/trending')
@limiter.limit("30 per minute")
def get_trending_news():
    news = load_json('news.json')
    if news is None:
        return jsonify([])
    return jsonify(news.get('trending', []))

@app.route('/api/news/search')
@limiter.limit("20 per minute")
def search_news():
    """Search news for a specific query."""
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify([])
    if len(query) > 200:
        return jsonify({'error': 'Query too long'}), 400
    NEWS_API_KEY = os.getenv('NEWS_API_KEY')
    if not NEWS_API_KEY:
        return jsonify([])
    try:
        import requests as req
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

# ==============================================
# CHAT ROUTE
# ==============================================

_ALLOWED_PAGE_CONTEXTS = {'general', 'pfp', 'events', 'home', 'lucas', 'widget', 'review'}

@app.route('/api/chat', methods=['POST'])
@limiter.limit("20 per minute")
def chat():
    """Chat with Lucas Bot."""
    if not request.is_json:
        return jsonify({'error': 'Content-Type must be application/json'}), 400

    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        return jsonify({'error': 'Invalid JSON body'}), 400

    # Validate message
    raw_message = data.get('message')
    user_message, err = validate_str(raw_message, 'message', max_len=500, required=True)
    if err:
        return jsonify({'error': err}), 400

    # Validate page context
    page_context = data.get('page', 'general')
    if not isinstance(page_context, str) or page_context not in _ALLOWED_PAGE_CONTEXTS:
        page_context = 'general'

    # Validate conversation history — accept up to 20 turns, each role+content string
    raw_history = data.get('history', [])
    if not isinstance(raw_history, list):
        raw_history = []
    conversation_history = []
    for item in raw_history[:20]:
        if not isinstance(item, dict):
            continue
        role = item.get('role', '')
        content = item.get('content', '')
        if role not in ('user', 'assistant') or not isinstance(content, str):
            continue
        conversation_history.append({'role': role, 'content': content[:500]})

    # live_data: accept only if it's a dict with expected keys, ignore otherwise
    raw_live = data.get('live_data')
    live_data = None
    if isinstance(raw_live, dict):
        live_data = {}
        if 'events' in raw_live and isinstance(raw_live['events'], list):
            live_data['events'] = raw_live['events']
        if 'fighters' in raw_live and isinstance(raw_live['fighters'], (list, dict)):
            live_data['fighters'] = raw_live['fighters']

    try:
        response = chat_with_lucas(user_message, conversation_history, page_context, live_data)
        return jsonify({'response': response, 'success': True})
    except Exception as e:
        print(f"Chat error: {e}")
        return jsonify({'error': 'Failed to get response from Lucas Bot', 'success': False}), 500

# ==============================================
# RATINGS / REVIEWS ROUTES
# ==============================================

@app.route('/api/ratings', methods=['POST'])
@limiter.limit("30 per minute")
def submit_rating():
    """Submit a pre-event hype rating and FOTN prediction."""
    if not request.is_json:
        return jsonify({'error': 'Content-Type must be application/json'}), 400

    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        return jsonify({'error': 'Invalid JSON body'}), 400

    event_id, err = validate_str(data.get('event_id'), 'event_id', max_len=100)
    if err:
        return jsonify({'error': err}), 400

    event_name, err = validate_str(data.get('event_name'), 'event_name', max_len=200)
    if err:
        return jsonify({'error': err}), 400

    hype_rating = data.get('hype_rating')
    if hype_rating is None or not isinstance(hype_rating, (int, float)) or not (1 <= hype_rating <= 5):
        return jsonify({'error': 'hype_rating must be a number between 1 and 5'}), 400

    fotn_prediction, err = validate_str(data.get('fotn_prediction'), 'fotn_prediction', max_len=200, required=False)
    if err:
        return jsonify({'error': err}), 400

    review_text, err = validate_str(data.get('review_text'), 'review_text', max_len=2000, required=False)
    if err:
        return jsonify({'error': err}), 400

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

    try:
        rating_id = save_event_rating(event_id, event_name, hype_rating, fotn_prediction, review_text, user_id, display_name)
        return jsonify({'success': True, 'rating_id': rating_id}), 201
    except Exception as e:
        print(f"Rating error: {e}")
        return jsonify({'error': 'Failed to save rating'}), 500


@app.route('/api/ratings/<event_id>', methods=['GET'])
def get_ratings(event_id):
    if not isinstance(event_id, str) or len(event_id) > 100:
        return jsonify({'error': 'Invalid event ID'}), 400
    try:
        summary = get_event_avg_rating(event_id)
        return jsonify(summary)
    except Exception as e:
        print(f"Rating fetch error: {e}")
        return jsonify({'error': 'Failed to fetch ratings'}), 500


@app.route('/api/ratings/<int:rating_id>', methods=['PUT'])
def edit_rating(rating_id):
    """Update an existing rating."""
    if not request.is_json:
        return jsonify({'error': 'Content-Type must be application/json'}), 400

    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        return jsonify({'error': 'Invalid JSON body'}), 400

    hype_rating = data.get('hype_rating')
    if hype_rating is None or not isinstance(hype_rating, (int, float)) or not (1 <= hype_rating <= 5):
        return jsonify({'error': 'hype_rating must be a number between 1 and 5'}), 400

    review_text, err = validate_str(data.get('review_text'), 'review_text', max_len=2000, required=False)
    if err:
        return jsonify({'error': err}), 400

    try:
        update_event_rating(rating_id, hype_rating, review_text)
        return jsonify({'success': True})
    except Exception as e:
        print(f"Rating update error: {e}")
        return jsonify({'error': 'Failed to update rating'}), 500


@app.route('/api/ratings/my/<event_id>', methods=['GET'])
@jwt_required()
def get_my_rating(event_id):
    if not isinstance(event_id, str) or len(event_id) > 100:
        return jsonify({'error': 'Invalid event ID'}), 400
    try:
        user_id = int(get_jwt_identity())
        row = get_user_rating_for_event(user_id, event_id)
        if not row:
            return jsonify({'error': 'Not found'}), 404
        return jsonify({
            'rating_id':   row['id'],
            'hype_rating': row['hype_rating'],
            'review_text': row['review_text'] or ''
        })
    except Exception as e:
        print(f"My-rating error: {e}")
        return jsonify({'error': 'Failed to fetch rating'}), 500


@app.route('/api/reviews/<event_id>', methods=['GET'])
def get_reviews(event_id):
    if not isinstance(event_id, str) or len(event_id) > 100:
        return jsonify({'error': 'Invalid event ID'}), 400
    try:
        reviews = get_event_reviews(event_id)
        current_user_id = None
        try:
            verify_jwt_in_request(optional=True)
            uid = get_jwt_identity()
            if uid:
                current_user_id = int(uid)
        except Exception:
            pass
        review_ids = [r['id'] for r in reviews]
        likes_map = get_review_likes(review_ids, current_user_id)
        for r in reviews:
            info = likes_map.get(r['id'], {})
            r['like_count'] = info.get('count', 0)
            r['user_liked'] = info.get('user_liked', False)
        return jsonify(reviews)
    except Exception as e:
        print(f"Reviews fetch error: {e}")
        return jsonify([]), 500


@app.route('/api/reviews/<int:review_id>/like', methods=['POST', 'DELETE'])
@jwt_required()
@limiter.limit("60 per minute")
def manage_review_like(review_id):
    try:
        user_id = int(get_jwt_identity())
        liked, count = toggle_review_like(review_id, user_id)
        return jsonify({'liked': liked, 'like_count': count})
    except Exception as e:
        print(f"Like error: {e}")
        return jsonify({'error': 'Failed to toggle like'}), 500


@app.route('/api/reviews/<int:review_id>/reply', methods=['POST'])
@jwt_required()
@limiter.limit("20 per minute")
def post_reply(review_id):
    if not request.is_json:
        return jsonify({'error': 'Content-Type must be application/json'}), 400

    data = request.get_json(silent=True) or {}
    reply_text, err = validate_str(data.get('reply_text'), 'reply_text', max_len=1000)
    if err:
        return jsonify({'error': err}), 400
    if not reply_text:
        return jsonify({'error': 'reply_text required'}), 400

    try:
        user_id = int(get_jwt_identity())
        user = get_user_by_id(user_id)
        if not user:
            return jsonify({'error': 'User not found'}), 404
        reply_id = add_review_reply(review_id, user_id, user['display_name'], reply_text)
        return jsonify({
            'success': True,
            'reply_id': reply_id,
            'user_id': user_id,
            'display_name': user['display_name'],
            'created_at': __import__('datetime').datetime.utcnow().isoformat()
        }), 201
    except Exception as e:
        print(f"Reply error: {e}")
        return jsonify({'error': 'Failed to post reply'}), 500


@app.route('/api/reviews/<int:review_id>/replies', methods=['GET'])
def fetch_replies(review_id):
    try:
        current_user_id = None
        try:
            verify_jwt_in_request(optional=True)
            uid = get_jwt_identity()
            if uid:
                current_user_id = int(uid)
        except Exception:
            pass
        replies = get_review_replies(review_id, current_user_id)
        return jsonify(replies)
    except Exception as e:
        print(f"Replies fetch error: {e}")
        return jsonify([]), 500


@app.route('/api/replies/<int:reply_id>/like', methods=['POST', 'DELETE'])
@jwt_required()
@limiter.limit("60 per minute")
def manage_reply_like(reply_id):
    try:
        user_id = int(get_jwt_identity())
        liked, count = toggle_reply_like(reply_id, user_id)
        return jsonify({'liked': liked, 'like_count': count})
    except Exception as e:
        print(f"Reply like error: {e}")
        return jsonify({'error': 'Failed to toggle like'}), 500


# ==============================================
# ERROR HANDLERS
# ==============================================

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Endpoint not found'}), 404

@app.errorhandler(429)
def ratelimit_handler(e):
    return jsonify({'error': 'Too many requests. Please slow down and try again shortly.'}), 429

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
        print('MMA BRIDGE API SERVER')
        print('=' * 50)
        print(f'Running at: http://localhost:{port}')
        print('Press CTRL+C to stop')
        print('=' * 50)

    app.run(
        host='0.0.0.0',
        port=port,
        debug=debug
    )

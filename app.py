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
from datetime import datetime, timezone, timedelta
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
ODDS_API_KEY = os.getenv('ODDS_API_KEY', '')

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

# ── Push notification module ─────────────────
from push_notifications import start_scheduler, check_starred_events, announce_fighters
from database import sb as _supabase_client
if _supabase_client:
    start_scheduler(_supabase_client)
else:
    print('[Push] Supabase not configured — push scheduler skipped')

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
    # Supabase is source of truth — scraper is fallback only
    try:
        events = get_all_events()
        if events:
            return jsonify(events)
    except Exception as e:
        print(f"Supabase error: {e}")
    try:
        if SCRAPER_AVAILABLE:
            events = get_events_for_api()
            if events:
                return jsonify(events)
    except Exception as e:
        print(f"Scraper error: {e}")
    events = load_json('events.json')
    if events is None:
        return jsonify({'error': 'Events data not found'}), 404
    return jsonify(events)

@app.route('/api/events/upcoming')
def get_upcoming_events_route():
    try:
        events = get_upcoming_events()
        if events:
            return jsonify(events)
    except Exception as e:
        print(f"Supabase error: {e}")
    try:
        if SCRAPER_AVAILABLE:
            from datetime import date
            all_events = get_events_for_api()
            today = date.today().isoformat()
            upcoming = [e for e in all_events if (e.get('isoDate') or '9999') >= today]
            if upcoming:
                return jsonify(upcoming)
    except Exception as e:
        print(f"Scraper error: {e}")
    events = load_json('events.json')
    if events is None:
        return jsonify({'error': 'Events data not found'}), 404
    return jsonify(events)

@app.route('/api/events/past')
def get_past_events_route():
    try:
        from datetime import date
        today = date.today().isoformat()
        all_events = get_all_events()
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

REDIRECT_URI     = os.getenv('GOOGLE_REDIRECT_URI',  'https://mmabridge-backend.onrender.com/api/auth/google/callback')
FRONTEND_URL     = os.getenv('FRONTEND_URL',          'https://mmabridge.com')
INTERNAL_SECRET  = os.getenv('INTERNAL_SECRET', '')

def _require_internal(req):
    """Returns None if authorized, or a JSON error response tuple."""
    secret = req.headers.get('X-Internal-Secret', '').strip()
    if not INTERNAL_SECRET or secret != INTERNAL_SECRET:
        return jsonify({'error': 'Unauthorized'}), 401
    return None

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
        return redirect(f"{FRONTEND_URL}/auth.html#token={jwt_token}")
    except Exception as e:
        print(f"OAuth callback error: {e}")
        return redirect(f"{FRONTEND_URL}/auth.html?error=auth_failed")

@app.route('/api/auth/me')
@jwt_required()
def auth_me():
    user_id = get_jwt_identity()
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
            user = get_user_by_id(uid)
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


@app.route('/api/ratings/<rating_id>', methods=['PUT'])
@jwt_required()
def edit_rating(rating_id):
    """Update an existing rating."""
    user_id = get_jwt_identity()

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
        # Verify ownership before updating
        existing = _supabase_client.table('event_ratings').select('user_id').eq('id', rating_id).execute()
        if not existing.data or existing.data[0].get('user_id') != user_id:
            return jsonify({'error': 'Not authorized to edit this rating'}), 403
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
        user_id = get_jwt_identity()
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
                current_user_id = uid
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


@app.route('/api/reviews/<review_id>/like', methods=['POST', 'DELETE'])
@jwt_required()
@limiter.limit("60 per minute")
def manage_review_like(review_id):
    try:
        user_id = get_jwt_identity()
        liked, count = toggle_review_like(review_id, user_id)
        return jsonify({'liked': liked, 'like_count': count})
    except Exception as e:
        print(f"Like error: {e}")
        return jsonify({'error': 'Failed to toggle like'}), 500


@app.route('/api/reviews/<review_id>/reply', methods=['POST'])
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
        user_id = get_jwt_identity()
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


@app.route('/api/reviews/<review_id>/replies', methods=['GET'])
def fetch_replies(review_id):
    try:
        current_user_id = None
        try:
            verify_jwt_in_request(optional=True)
            uid = get_jwt_identity()
            if uid:
                current_user_id = uid
        except Exception:
            pass
        replies = get_review_replies(review_id, current_user_id)
        return jsonify(replies)
    except Exception as e:
        print(f"Replies fetch error: {e}")
        return jsonify([]), 500


@app.route('/api/replies/<reply_id>/like', methods=['POST', 'DELETE'])
@jwt_required()
@limiter.limit("60 per minute")
def manage_reply_like(reply_id):
    try:
        user_id = get_jwt_identity()
        liked, count = toggle_reply_like(reply_id, user_id)
        return jsonify({'liked': liked, 'like_count': count})
    except Exception as e:
        print(f"Reply like error: {e}")
        return jsonify({'error': 'Failed to toggle like'}), 500


# ==============================================
# PUSH NOTIFICATION ROUTES
# ==============================================

@app.route('/api/push/announce-fighters', methods=['POST'])
def push_announce_fighters():
    """
    Call this when you add a new event to notify fav-fighter subscribers.
    Body: { "fighters": ["Jon Jones", "Stipe Miocic"], "eventName": "UFC 309", "eventId": "ufc-309" }
    """
    err = _require_internal(request)
    if err: return err
    try:
        data        = request.get_json(force=True) or {}
        fighters    = data.get('fighters') or []
        event_name  = data.get('eventName') or data.get('event_name') or ''
        event_id    = data.get('eventId')   or data.get('event_id')   or ''
        if not fighters or not event_id:
            return jsonify({'error': 'fighters and eventId required'}), 400
        announce_fighters(_supabase_client, fighters, event_name, event_id)
        return jsonify({'ok': True, 'notified_for': fighters})
    except Exception as e:
        print(f'[Push] announce-fighters error: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/push/test', methods=['POST'])
def push_test():
    """
    Send a test push to a specific browser. Body: { "browser_id": "..." }
    Find your browser_id in DevTools → Application → Local Storage → mma_browser_id
    """
    err = _require_internal(request)
    if err: return err
    try:
        data       = request.get_json(force=True) or {}
        browser_id = data.get('browser_id', '').strip()
        if not browser_id:
            return jsonify({'error': 'browser_id required'}), 400

        row = (
            _supabase_client.table('push_subscriptions')
            .select('endpoint, p256dh, auth')
            .eq('browser_id', browser_id)
            .single()
            .execute()
        )
        if not row.data:
            return jsonify({'error': 'Subscription not found — star an event first'}), 404

        sub    = row.data
        result = __import__('push_notifications').send_push(
            endpoint=sub['endpoint'],
            p256dh=sub['p256dh'],
            auth_key=sub['auth'],
            payload={
                'title': 'MMA Bridge — push works!',
                'body':  'You\'ll now get 1-week and day-before alerts for starred events.',
                'url':   '/events.html',
            },
        )
        return jsonify({'result': result})
    except Exception as e:
        print(f'[Push] test error: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/push/trigger-check', methods=['POST'])
def push_trigger_check():
    """Manual trigger for the daily starred-events check (for testing)."""
    err = _require_internal(request)
    if err: return err
    try:
        check_starred_events(_supabase_client)
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ==============================================
# LEADERBOARD ROUTE
# ==============================================

@app.route('/api/leaderboard', methods=['GET'])
def get_leaderboard():
    """Return leaderboard data filtered by period (all/week/month)."""
    period = request.args.get('period', 'all')
    try:
        query = _supabase_client.table('picks').select('user_id, event_id, fight_key, pick, method, created_at')
        if period == 'week':
            cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
            query = query.gte('created_at', cutoff)
        elif period == 'month':
            cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
            query = query.gte('created_at', cutoff)
        result = query.execute()
        return jsonify({'picks': result.data or [], 'period': period})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ==============================================
# FOLLOW SYSTEM
# ==============================================

# SQL to run in Supabase:
# CREATE TABLE IF NOT EXISTS follows (
#   follower_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
#   following_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
#   created_at TIMESTAMPTZ DEFAULT now(),
#   PRIMARY KEY (follower_id, following_id)
# );
# ALTER TABLE follows ENABLE ROW LEVEL SECURITY;
# CREATE POLICY "Users can manage own follows" ON follows FOR ALL USING (auth.uid() = follower_id);
# CREATE POLICY "Follow counts are public" ON follows FOR SELECT USING (true);

@app.route('/api/follow/<target_user_id>', methods=['POST'])
@jwt_required()
def follow_user(target_user_id):
    follower_id = get_jwt_identity()
    if follower_id == target_user_id:
        return jsonify({'error': 'Cannot follow yourself'}), 400
    try:
        _supabase_client.table('follows').upsert({
            'follower_id': follower_id,
            'following_id': target_user_id
        }, on_conflict='follower_id,following_id').execute()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/follow/<target_user_id>', methods=['DELETE'])
@jwt_required()
def unfollow_user(target_user_id):
    follower_id = get_jwt_identity()
    try:
        _supabase_client.table('follows').delete()\
            .eq('follower_id', follower_id)\
            .eq('following_id', target_user_id).execute()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/follow/counts/<user_id>', methods=['GET'])
def follow_counts(user_id):
    try:
        followers = _supabase_client.table('follows').select('follower_id', count='exact').eq('following_id', user_id).execute()
        following = _supabase_client.table('follows').select('following_id', count='exact').eq('follower_id', user_id).execute()
        return jsonify({
            'followers': followers.count or 0,
            'following': following.count or 0
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/follow/status/<target_user_id>', methods=['GET'])
@jwt_required()
def follow_status(target_user_id):
    follower_id = get_jwt_identity()
    try:
        row = _supabase_client.table('follows').select('follower_id').eq('follower_id', follower_id).eq('following_id', target_user_id).execute()
        return jsonify({'following': bool(row.data)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ==============================================
# ODDS ROUTE
# ==============================================

@app.route('/api/odds/<event_id>', methods=['GET'])
def get_odds(event_id):
    """
    Fetch UFC fight odds from The Odds API.
    Falls back to cached data if API key not set.
    Requires ODDS_API_KEY env var from https://the-odds-api.com (free tier: 500 req/mo)
    """
    if not ODDS_API_KEY:
        return jsonify({'odds': [], 'source': 'unavailable', 'message': 'Odds API key not configured'}), 200

    try:
        import requests as _odds_req
        # The Odds API — MMA fights
        resp = _odds_req.get(
            'https://api.the-odds-api.com/v4/sports/mma_mixed_martial_arts/odds',
            params={
                'apiKey': ODDS_API_KEY,
                'regions': 'us',
                'markets': 'h2h',
                'oddsFormat': 'american',
                'dateFormat': 'iso',
            },
            timeout=8
        )
        if not resp.ok:
            return jsonify({'odds': [], 'source': 'error'}), 200

        all_odds = resp.json()
        # Filter to matches relevant to this event_id by checking commence_time proximity
        # Return simplified structure
        fights = []
        for game in all_odds[:20]:  # limit results
            outcomes = game.get('bookmakers', [{}])[0].get('markets', [{}])[0].get('outcomes', [])
            if len(outcomes) >= 2:
                fights.append({
                    'a': outcomes[0].get('name', ''),
                    'b': outcomes[1].get('name', ''),
                    'odds_a': outcomes[0].get('price', 0),
                    'odds_b': outcomes[1].get('price', 0),
                    'commence_time': game.get('commence_time', ''),
                })
        return jsonify({'odds': fights, 'source': 'the-odds-api'})
    except Exception as e:
        print(f'[Odds] Fetch error: {e}')
        return jsonify({'odds': [], 'source': 'error'}), 200


# ==============================================
# ADMIN PANEL ENDPOINTS
# Set ADMIN_PASSWORD env var in Render dashboard.
# ==============================================

import hmac as _hmac
import hashlib as _hashlib
import secrets as _secrets

_ADMIN_TOKENS = set()  # in-memory; resets on dyno restart (fine for solo admin)

def _make_admin_token(password: str) -> str:
    secret = os.environ.get('ADMIN_PASSWORD', '')
    sig = _hmac.new(secret.encode(), password.encode(), _hashlib.sha256).hexdigest()
    tok = _secrets.token_hex(16) + sig[:8]
    _ADMIN_TOKENS.add(tok)
    return tok

def _verify_admin_token(tok: str) -> bool:
    return tok in _ADMIN_TOKENS


@app.route('/api/admin/auth', methods=['POST'])
def admin_auth():
    data = request.get_json(silent=True) or {}
    pw   = (data.get('password') or '').strip()
    expected = os.environ.get('ADMIN_PASSWORD', '')
    if not expected:
        return jsonify({'error': 'Admin not configured'}), 503
    if not pw or not _hmac.compare_digest(pw, expected):
        return jsonify({'error': 'Invalid password'}), 401
    return jsonify({'token': _make_admin_token(pw)})


@app.route('/api/admin/results', methods=['GET'])
def admin_get_results():
    tok = request.args.get('token', '')
    if not _verify_admin_token(tok):
        return jsonify({'error': 'Unauthorized'}), 401
    event_id = request.args.get('event_id', '')
    try:
        q = _supabase_client.table('fight_results').select('*')
        if event_id:
            q = q.eq('event_id', event_id)
        res = q.execute()
        return jsonify({'results': res.data or []})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/set-result', methods=['POST'])
def admin_set_result():
    data = request.get_json(silent=True) or {}
    tok  = (data.get('token') or '').strip()
    if not _verify_admin_token(tok):
        return jsonify({'error': 'Unauthorized'}), 401

    event_id  = (data.get('event_id')  or '').strip()
    fight_key = (data.get('fight_key') or '').strip()
    winner    = (data.get('winner')    or '').strip().lower()
    method    = (data.get('method')    or '').strip()
    fotn      = (data.get('fotn')      or '').strip().lower()

    if not event_id or not fight_key:
        return jsonify({'error': 'event_id and fight_key required'}), 400

    try:
        _supabase_client.table('fight_results').upsert(
            {
                'event_id':   event_id,
                'fight_key':  fight_key,
                'winner':     winner or None,
                'method':     method or None,
                'fotn':       fotn   or None,
                'updated_at': datetime.now(timezone.utc).isoformat(),
            },
            on_conflict='event_id,fight_key',
        ).execute()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ==============================================
# ADMIN — MARKETING CONTENT GENERATION
# ==============================================

@app.route('/api/admin/marketing/generate', methods=['POST'])
@limiter.limit("30 per minute")
def admin_marketing_generate():
    data = request.get_json(silent=True) or {}
    tok  = (data.get('token') or '').strip()
    if not _verify_admin_token(tok):
        return jsonify({'error': 'Unauthorized'}), 401

    platforms    = data.get('platforms', ['twitter'])
    content_type = (data.get('content_type') or 'event_promo').strip()
    context      = (data.get('context') or '').strip()[:800]

    if not context:
        return jsonify({'error': 'context is required'}), 400
    if not isinstance(platforms, list) or not platforms:
        return jsonify({'error': 'platforms must be a non-empty list'}), 400

    PLATFORM_RULES = {
        'twitter':   'Twitter/X: max 280 characters, punchy, use 2-3 relevant hashtags like #UFC #MMA #mmabets, no filler words. Write 1 tweet.',
        'instagram': 'Instagram: engaging caption up to 2200 chars, conversational, use line breaks for readability, end with 5-10 hashtags on a new line.',
        'reddit':    'Reddit (r/MMA or r/ufc): write a Reddit post title (max 100 chars) + body (markdown, conversational, no self-promotion language, feels organic). Format: TITLE: ...\n\nBODY: ...',
        'tiktok':    'TikTok: write a video caption/hook (first line must grab attention in under 5 words) + 3-5 hashtags. Max 150 chars total.',
        'email':     'Email: write Subject line + Body. Subject: punchy <60 chars. Body: 150-250 words, personal tone, clear CTA button text at the end. Format: SUBJECT: ...\n\nBODY: ...',
    }

    CONTENT_TYPE_CONTEXT = {
        'event_promo':    'You are hyping an upcoming UFC/MMA event to drive engagement on MMA Bridge (mmabridge.com), the fan picks & predictions platform.',
        'fight_highlight': 'You are sharing a fight result or highlight to generate discussion on MMA Bridge.',
        'pick_prediction': 'You are teasing a fight pick/prediction to bring fans to the picks page on MMA Bridge.',
        'weekly_recap':   'You are writing a weekly recap of results and leaderboard activity on MMA Bridge.',
        'platform_cta':   'You are promoting MMA Bridge (mmabridge.com) as a platform — fan picks, leaderboard, fight reviews, Lucas AI bot.',
    }

    system = (
        "You are a social media content writer for MMA Bridge (mmabridge.com), "
        "an MMA fan platform for fight picks, leaderboards, event reviews, and the Lucas AI chatbot. "
        "The brand voice is energetic, knowledgeable, authentic MMA fan — not corporate. "
        "Always include a link to mmabridge.com or a relevant subpage when it fits naturally. "
        f"Context: {CONTENT_TYPE_CONTEXT.get(content_type, '')}"
    )

    results = {}
    try:
        from chatbot import client as _openai_client
        for platform in platforms:
            rule = PLATFORM_RULES.get(platform)
            if not rule:
                continue
            prompt = f"{rule}\n\nWrite content about: {context}"
            resp = _openai_client.chat.completions.create(
                model='gpt-4o-mini',
                messages=[
                    {'role': 'system', 'content': system},
                    {'role': 'user',   'content': prompt},
                ],
                max_tokens=600,
                temperature=0.85,
            )
            results[platform] = resp.choices[0].message.content.strip()
        return jsonify({'results': results})
    except Exception as e:
        print(f'[Marketing] generate error: {e}')
        return jsonify({'error': str(e)}), 500


# ==============================================
# ADMIN — ANALYTICS
# ==============================================

@app.route('/api/admin/analytics', methods=['GET'])
def admin_analytics():
    tok = request.args.get('token', '')
    if not _verify_admin_token(tok):
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        sb = _supabase_client

        # Total users
        users_res   = sb.table('profiles').select('id, username, created_at', count='exact').execute()
        total_users = users_res.count or len(users_res.data or [])

        # Total picks (exclude fotn and dd specials)
        picks_res   = sb.table('picks').select('user_id, fight_key, created_at', count='exact').neq('fight_key', '__dd__').neq('fight_key', 'fotn').execute()
        total_picks = picks_res.count or len(picks_res.data or [])

        # Total reviews
        reviews_res   = sb.table('event_ratings').select('id', count='exact').execute()
        total_reviews = reviews_res.count or len(reviews_res.data or [])

        # Active users this week (picks in last 7 days)
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        active_res = sb.table('picks').select('user_id').gte('created_at', cutoff).execute()
        active_ids = set(r['user_id'] for r in (active_res.data or []))
        active_week = len(active_ids)

        # Recent signups (last 5)
        recent_users = sorted(
            (users_res.data or []),
            key=lambda x: x.get('created_at', ''),
            reverse=True
        )[:5]

        # Top pickers (most picks)
        from collections import Counter
        pick_counts = Counter(r['user_id'] for r in (picks_res.data or []))
        top_picker_ids = [uid for uid, _ in pick_counts.most_common(5)]
        top_pickers = []
        for uid in top_picker_ids:
            profile = next((u for u in (users_res.data or []) if u.get('id') == uid), None)
            name = (profile or {}).get('username') or uid[:8]
            top_pickers.append({'name': name, 'picks': pick_counts[uid]})

        return jsonify({
            'total_users':   total_users,
            'total_picks':   total_picks,
            'total_reviews': total_reviews,
            'active_week':   active_week,
            'recent_users':  recent_users,
            'top_pickers':   top_pickers,
        })
    except Exception as e:
        print(f'[Analytics] error: {e}')
        return jsonify({'error': str(e)}), 500


# ==============================================
# ADMIN — SOCIAL POSTING
# ==============================================

from marketing_poster import post_reddit, post_twitter, post_instagram, platform_status


@app.route('/api/admin/marketing/status', methods=['GET'])
def admin_marketing_status():
    tok = request.args.get('token', '')
    if not _verify_admin_token(tok):
        return jsonify({'error': 'Unauthorized'}), 401
    return jsonify(platform_status())


@app.route('/api/admin/marketing/post', methods=['POST'])
@limiter.limit("10 per minute")
def admin_marketing_post():
    data = request.get_json(silent=True) or {}
    tok  = (data.get('token') or '').strip()
    if not _verify_admin_token(tok):
        return jsonify({'error': 'Unauthorized'}), 401

    platform  = (data.get('platform') or '').strip().lower()
    content   = (data.get('content') or '').strip()
    image_url = (data.get('image_url') or '').strip()

    if not platform or not content:
        return jsonify({'error': 'platform and content required'}), 400

    if platform == 'reddit':
        # Expect content formatted as "TITLE: ...\n\nBODY: ..."
        title, body = content, ''
        if 'TITLE:' in content and 'BODY:' in content:
            try:
                parts = content.split('BODY:', 1)
                title = parts[0].replace('TITLE:', '').strip()
                body  = parts[1].strip()
            except Exception:
                pass
        subreddit = (data.get('subreddit') or 'test').strip()
        result = post_reddit(title, body, subreddit)

    elif platform == 'twitter':
        result = post_twitter(content)

    elif platform == 'instagram':
        result = post_instagram(content, image_url)

    else:
        return jsonify({'error': f'Unknown platform: {platform}'}), 400

    status_code = 200 if result.get('ok') else 502
    return jsonify(result), status_code


# ==============================================
# EMAIL UNSUBSCRIBE
# ==============================================

import hashlib as _hl

def _unsub_token(user_id: str) -> str:
    secret = os.environ.get('RESEND_API_KEY', 'unsub-secret')
    return _hmac.new(secret.encode(), user_id.encode(), _hl.sha256).hexdigest()[:32]


@app.route('/api/unsubscribe', methods=['GET'])
def unsubscribe():
    uid   = request.args.get('uid', '')
    token = request.args.get('token', '')
    if not uid or not token:
        return 'Missing parameters.', 400
    if not _hmac.compare_digest(token, _unsub_token(uid)):
        return 'Invalid unsubscribe link.', 400
    try:
        _supabase_client.table('profiles') \
            .update({'email_opt_out': True}) \
            .eq('id', uid) \
            .execute()
    except Exception as e:
        return f'Error updating preference: {e}', 500
    return '''<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Unsubscribed</title>
    <style>body{font-family:Inter,sans-serif;background:#0d0d10;color:#fff;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;}
    .box{text-align:center;max-width:380px;padding:40px 20px;}h2{font-family:Montserrat,sans-serif;color:#c8960c;}p{color:rgba(255,255,255,0.55);font-size:0.9rem;}
    a{color:rgba(0,229,255,0.7);text-decoration:none;}</style></head>
    <body><div class="box"><h2>Unsubscribed</h2>
    <p>You've been removed from the MMA Bridge weekly digest. No more emails.</p>
    <p style="margin-top:28px"><a href="https://mmabridge.com">Back to MMA Bridge</a></p></div></body></html>'''


# ==============================================
# ACCOUNT DELETION (GDPR / CCPA)
# ==============================================

@app.route('/api/account/delete', methods=['POST'])
def delete_account():
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        return jsonify({'error': 'Unauthorized'}), 401
    token = auth_header[7:]

    try:
        user_resp = _supabase_client.auth.get_user(token)
        user_id = user_resp.user.id if user_resp.user else None
    except Exception:
        user_id = None

    if not user_id:
        return jsonify({'error': 'Invalid or expired session'}), 401

    try:
        for table in ['picks', 'ratings', 'event_ratings', 'push_subscriptions', 'follows']:
            try:
                _supabase_client.table(table).delete().eq('user_id', user_id).execute()
            except Exception:
                pass
        try:
            _supabase_client.table('follows').delete().eq('follower_id', user_id).execute()
        except Exception:
            pass
        try:
            _supabase_client.table('profiles').delete().eq('id', user_id).execute()
        except Exception:
            pass
        _supabase_client.auth.admin.delete_user(user_id)
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ==============================================
# FIGHTER NEWS FEED (RSS)
# ==============================================

import time as _time
_news_cache = {}   # name_slug → (timestamp, articles_list)
_NEWS_TTL   = 3600  # 1-hour cache

def _fetch_fighter_news(name: str) -> list:
    from xml.etree import ElementTree as ET
    import urllib.parse

    # Google News RSS — no API key, reliable, fighter-specific query
    query     = urllib.parse.quote_plus(f'{name} UFC MMA')
    feed_url  = f'https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en'

    articles = []
    try:
        r = requests.get(
            feed_url,
            timeout=10,
            headers={
                'User-Agent': 'Mozilla/5.0 (compatible; MMABridge/1.0)',
                'Accept': 'application/rss+xml, application/xml, text/xml',
            },
        )
        if not r.ok:
            return []

        root = ET.fromstring(r.content)
        for item in root.iter('item'):
            title  = (item.findtext('title')   or '').strip()
            link   = (item.findtext('link')    or '').strip()
            pub    = (item.findtext('pubDate') or '').strip()
            source = ''
            # Google News wraps source in <source> tag
            src_el = item.find('source')
            if src_el is not None:
                source = (src_el.text or '').strip()

            if not title or not link:
                continue

            articles.append({
                'title':  title,
                'url':    link,
                'date':   pub,
                'source': source,
            })
            if len(articles) >= 8:
                break
    except Exception as e:
        print(f'[News] fetch error for "{name}": {e}')

    return articles


@app.route('/api/news/fighter', methods=['GET'])
def get_fighter_news():
    name = (request.args.get('name') or '').strip()
    if not name or len(name) < 3:
        return jsonify({'articles': []})

    slug = re.sub(r'[^a-z0-9]', '-', name.lower())
    cached = _news_cache.get(slug)
    if cached and (_time.time() - cached[0]) < _NEWS_TTL:
        return jsonify({'articles': cached[1]})

    articles = _fetch_fighter_news(name)
    _news_cache[slug] = (_time.time(), articles)
    return jsonify({'articles': articles})


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

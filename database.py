# ==============================================
# MMA BRIDGE - DATABASE (Supabase + SQLite)
# Events, ratings, reviews, users → Supabase
# Fighters → SQLite (scraped, website-only)
# ==============================================

import sqlite3
import json
import os
import re
from datetime import datetime

from supabase import create_client, Client

# ── Supabase client (service role for server-side) ────────────────────────────
SUPABASE_URL         = os.getenv('SUPABASE_URL', '')
SUPABASE_SERVICE_KEY = os.getenv('SUPABASE_SERVICE_KEY', '')

sb: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY) if SUPABASE_URL and SUPABASE_SERVICE_KEY else None

def _sb():
    if sb is None:
        raise RuntimeError('Supabase not configured — set SUPABASE_URL and SUPABASE_SERVICE_KEY in .env')
    return sb

# ── SQLite (fighters only) ────────────────────────────────────────────────────
DB_PATH = os.path.join(os.path.dirname(__file__), 'mma_bridge.db')

def create_tables():
    """Create SQLite tables (fighters only). All other tables live in Supabase."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS fighters (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            nickname TEXT,
            weight_class TEXT,
            record TEXT,
            wins INTEGER,
            losses INTEGER,
            draws INTEGER,
            height TEXT,
            weight TEXT,
            reach TEXT,
            stance TEXT,
            dob TEXT,
            country TEXT,
            fighting_out_of TEXT,
            image_url TEXT,
            last_five TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

# ==============================================
# IMPORT DATA FROM JSON FILES
# ==============================================

def import_fighters_from_json():
    json_path = os.path.join(os.path.dirname(__file__), 'data', 'fighters.json')
    if not os.path.exists(json_path):
        print('fighters.json not found')
        return
    with open(json_path, 'r') as f:
        fighters_data = json.load(f)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    count = 0
    for fighter_id, fighter in fighters_data.items():
        cursor.execute('''
            INSERT OR REPLACE INTO fighters
            (id, name, nickname, weight_class, record, wins, losses, draws,
             height, weight, reach, stance, dob, country, fighting_out_of,
             image_url, last_five)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            fighter_id,
            fighter.get('name', ''),
            fighter.get('nickname', ''),
            fighter.get('weightClass', ''),
            fighter.get('record', ''),
            fighter.get('wins', 0),
            fighter.get('losses', 0),
            fighter.get('draws', 0),
            fighter.get('height', ''),
            fighter.get('weight', ''),
            fighter.get('reach', ''),
            fighter.get('stance', ''),
            fighter.get('dob', ''),
            fighter.get('country', ''),
            fighter.get('fightingOutOf', ''),
            fighter.get('imageUrl', ''),
            json.dumps(fighter.get('lastFive', []))
        ))
        count += 1
    conn.commit()
    conn.close()
    print(f'Imported {count} fighters')

def import_events_from_json():
    """Import events from events.json into Supabase."""
    json_path = os.path.join(os.path.dirname(__file__), 'events.json')
    if not os.path.exists(json_path):
        print('events.json not found')
        return
    with open(json_path, 'r') as f:
        events = json.load(f)
    client = _sb()
    rows = [{
        'id':           e.get('id'),
        'name':         e.get('name'),
        'type':         e.get('type', 'FIGHT NIGHT'),
        'date':         e.get('date'),
        'iso_date':     e.get('isoDate'),
        'location':     e.get('location'),
        'venue':        e.get('venue'),
        'poster':       e.get('poster'),
        'status':       e.get('status', 'upcoming'),
        'main_card':    e.get('mainCard', []),
        'prelims':      e.get('prelims', []),
        'early_prelims': e.get('earlyPrelims', []),
    } for e in events if e.get('id')]
    client.from_('events').upsert(rows, on_conflict='id').execute()
    print(f'Imported {len(rows)} events into Supabase')

# ==============================================
# FIGHTERS (SQLite)
# ==============================================

def get_all_fighters():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM fighters')
    rows = cursor.fetchall()
    fighters = {}
    for row in rows:
        fighters[row['id']] = {
            'name':          row['name'],
            'nickname':      row['nickname'],
            'weightClass':   row['weight_class'],
            'record':        row['record'],
            'wins':          row['wins'],
            'losses':        row['losses'],
            'draws':         row['draws'],
            'height':        row['height'],
            'weight':        row['weight'],
            'reach':         row['reach'],
            'stance':        row['stance'],
            'dob':           row['dob'],
            'country':       row['country'],
            'fightingOutOf': row['fighting_out_of'],
            'imageUrl':      row['image_url'],
            'lastFive':      json.loads(row['last_five']) if row['last_five'] else [],
        }
    conn.close()
    return fighters

def get_fighter_by_id(fighter_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM fighters WHERE id = ?', (fighter_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    return {
        'name':          row['name'],
        'nickname':      row['nickname'],
        'weightClass':   row['weight_class'],
        'record':        row['record'],
        'wins':          row['wins'],
        'losses':        row['losses'],
        'draws':         row['draws'],
        'height':        row['height'],
        'weight':        row['weight'],
        'reach':         row['reach'],
        'stance':        row['stance'],
        'dob':           row['dob'],
        'country':       row['country'],
        'fightingOutOf': row['fighting_out_of'],
        'imageUrl':      row['image_url'],
        'lastFive':      json.loads(row['last_five']) if row['last_five'] else [],
    }

# ==============================================
# EVENTS (Supabase)
# ==============================================

def _row_to_event(e):
    return {
        'id':          e.get('id'),
        'eventName':   e.get('name'),
        'name':        e.get('name'),
        'type':        e.get('type'),
        'date':        e.get('date'),
        'isoDate':     e.get('iso_date'),
        'location':    e.get('location'),
        'venue':       e.get('venue'),
        'poster':      e.get('poster'),
        'status':      e.get('status'),
        'mainCard':    e.get('main_card') or [],
        'prelims':     e.get('prelims') or [],
        'earlyPrelims': e.get('early_prelims') or [],
    }

def get_all_events():
    try:
        res = _sb().from_('events').select('*').order('iso_date', desc=False).execute()
        return [_row_to_event(e) for e in (res.data or [])]
    except Exception as ex:
        print(f'get_all_events error: {ex}')
        return []

def get_upcoming_events():
    try:
        today = datetime.utcnow().date().isoformat()
        res = _sb().from_('events').select('*').gte('iso_date', today).order('iso_date', desc=False).execute()
        return [_row_to_event(e) for e in (res.data or [])]
    except Exception as ex:
        print(f'get_upcoming_events error: {ex}')
        return []

def upsert_event(event_dict):
    """Add or update a single event. event_dict uses camelCase keys (app format)."""
    row = {
        'id':           event_dict.get('id'),
        'name':         event_dict.get('name'),
        'type':         event_dict.get('type', 'FIGHT NIGHT'),
        'date':         event_dict.get('date'),
        'iso_date':     event_dict.get('isoDate'),
        'location':     event_dict.get('location'),
        'venue':        event_dict.get('venue'),
        'poster':       event_dict.get('poster'),
        'status':       event_dict.get('status', 'upcoming'),
        'main_card':    event_dict.get('mainCard', []),
        'prelims':      event_dict.get('prelims', []),
        'early_prelims': event_dict.get('earlyPrelims', []),
    }
    _sb().from_('events').upsert(row, on_conflict='id').execute()

# ==============================================
# USERS (Supabase auth + user_profiles)
# ==============================================

def get_or_create_user(email, display_name, avatar_url):
    """Find or create a user in Supabase. Returns dict with id (UUID str), email, display_name, avatar_url."""
    client = _sb()

    # Try to find existing profile by email
    res = client.from_('user_profiles').select('id, username, email, display_name, avatar_url').eq('email', email).limit(1).execute()
    if res.data:
        user_id = res.data[0]['id']
        # Update display_name / avatar in case they changed
        client.from_('user_profiles').update({
            'display_name': display_name,
            'avatar_url':   avatar_url,
        }).eq('id', user_id).execute()
        return {'id': user_id, 'email': email, 'display_name': display_name, 'avatar_url': avatar_url}

    # Create new Supabase auth user
    try:
        auth_res = client.auth.admin.create_user({
            'email':        email,
            'email_confirm': True,
            'user_metadata': {'display_name': display_name, 'avatar_url': avatar_url},
        })
        user_id = auth_res.user.id
    except Exception as ex:
        # User already exists in auth.users but not in user_profiles
        # Try listing to find them (fallback)
        print(f'create_user fallback: {ex}')
        raise

    # Generate unique username from display_name / email
    base = re.sub(r'[^a-z0-9_]', '', display_name.lower().replace(' ', '_'))[:18] or email.split('@')[0][:18]
    username = base
    i = 1
    while True:
        check = client.from_('user_profiles').select('id').eq('username', username).limit(1).execute()
        if not check.data:
            break
        username = f'{base}{i}'
        i += 1

    client.from_('user_profiles').insert({
        'id':           user_id,
        'username':     username,
        'email':        email,
        'display_name': display_name,
        'avatar_url':   avatar_url,
    }).execute()

    return {'id': user_id, 'email': email, 'display_name': display_name, 'avatar_url': avatar_url}

def get_user_by_id(user_id):
    """Return user dict by UUID string, or None."""
    try:
        res = _sb().from_('user_profiles').select('id, username, email, display_name, avatar_url').eq('id', user_id).limit(1).execute()
        if res.data:
            row = res.data[0]
            return {
                'id':           row['id'],
                'email':        row.get('email', ''),
                'display_name': row.get('display_name') or row.get('username', ''),
                'avatar_url':   row.get('avatar_url', ''),
            }
        return None
    except Exception as ex:
        print(f'get_user_by_id error: {ex}')
        return None

# ==============================================
# RATINGS / REVIEWS (Supabase)
# ==============================================

def save_event_rating(event_id, event_name, hype_rating, fotn_prediction=None, review_text=None, user_id=None, display_name=None):
    try:
        res = _sb().from_('ratings').insert({
            'event_id':       event_id,
            'event_name':     event_name,
            'hype_rating':    hype_rating,
            'fotn_prediction': fotn_prediction,
            'review_text':    review_text,
            'user_id':        user_id,
            'display_name':   display_name,
        }).execute()
        return res.data[0]['id'] if res.data else None
    except Exception as ex:
        print(f'save_event_rating error: {ex}')
        raise

def update_event_rating(rating_id, hype_rating, review_text=None):
    try:
        _sb().from_('ratings').update({
            'hype_rating':  hype_rating,
            'review_text':  review_text,
        }).eq('id', rating_id).execute()
    except Exception as ex:
        print(f'update_event_rating error: {ex}')
        raise

def get_user_rating_for_event(user_id, event_id):
    try:
        res = _sb().from_('ratings').select('id, hype_rating, review_text').eq('user_id', user_id).eq('event_id', event_id).order('created_at', desc=True).limit(1).execute()
        return res.data[0] if res.data else None
    except Exception as ex:
        print(f'get_user_rating_for_event error: {ex}')
        return None

def get_event_ratings(event_id):
    try:
        res = _sb().from_('ratings').select('*').eq('event_id', event_id).order('created_at', desc=True).execute()
        return [{
            'id':              r['id'],
            'event_id':        r['event_id'],
            'event_name':      r['event_name'],
            'hype_rating':     r['hype_rating'],
            'fotn_prediction': r['fotn_prediction'],
            'review_text':     r.get('review_text'),
            'created_at':      r['created_at'],
        } for r in (res.data or [])]
    except Exception as ex:
        print(f'get_event_ratings error: {ex}')
        return []

def get_event_reviews(event_id):
    try:
        res = _sb().from_('ratings').select('id, hype_rating, review_text, display_name, created_at, user_id').eq('event_id', event_id).order('created_at', desc=True).execute()
        rows = res.data or []
        # Fetch reply counts in one call
        rating_ids = [r['id'] for r in rows]
        reply_counts = {}
        if rating_ids:
            rc_res = _sb().from_('review_replies').select('review_id').in_('review_id', rating_ids).execute()
            for rc in (rc_res.data or []):
                reply_counts[rc['review_id']] = reply_counts.get(rc['review_id'], 0) + 1
        return [{
            'id':           r['id'],
            'hype_rating':  r['hype_rating'],
            'review_text':  r['review_text'],
            'display_name': r.get('display_name') or 'Anonymous',
            'created_at':   r['created_at'],
            'user_id':      r.get('user_id'),
            'reply_count':  reply_counts.get(r['id'], 0),
        } for r in rows]
    except Exception as ex:
        print(f'get_event_reviews error: {ex}')
        return []

def get_event_avg_rating(event_id):
    try:
        res = _sb().from_('ratings').select('hype_rating, fotn_prediction').eq('event_id', event_id).execute()
        rows = res.data or []
        if not rows:
            return {'total_ratings': 0, 'avg_hype': None, 'top_fotn': None}
        total = len(rows)
        avg   = round(sum(r['hype_rating'] for r in rows) / total, 1)
        fotn_votes = {}
        for r in rows:
            fp = r.get('fotn_prediction')
            if fp:
                fotn_votes[fp] = fotn_votes.get(fp, 0) + 1
        top_fotn = max(fotn_votes, key=fotn_votes.get) if fotn_votes else None
        return {'total_ratings': total, 'avg_hype': avg, 'top_fotn': top_fotn}
    except Exception as ex:
        print(f'get_event_avg_rating error: {ex}')
        return {'total_ratings': 0, 'avg_hype': None, 'top_fotn': None}

# ==============================================
# REVIEW SOCIAL: LIKES + REPLIES (Supabase)
# ==============================================

def toggle_review_like(review_id, user_id):
    client = _sb()
    check = client.from_('review_likes').select('id').eq('review_id', review_id).eq('user_id', user_id).limit(1).execute()
    if check.data:
        client.from_('review_likes').delete().eq('review_id', review_id).eq('user_id', user_id).execute()
        liked = False
    else:
        client.from_('review_likes').insert({'review_id': review_id, 'user_id': user_id}).execute()
        liked = True
    count_res = client.from_('review_likes').select('id', count='exact').eq('review_id', review_id).execute()
    count = count_res.count or 0
    return liked, count

def get_review_likes(review_ids, user_id=None):
    if not review_ids:
        return {}
    client = _sb()
    res = client.from_('review_likes').select('review_id, user_id').in_('review_id', list(review_ids)).execute()
    counts = {}
    liked_set = set()
    for row in (res.data or []):
        rid = row['review_id']
        counts[rid] = counts.get(rid, 0) + 1
        if user_id and row['user_id'] == user_id:
            liked_set.add(rid)
    return {rid: {'count': counts.get(rid, 0), 'user_liked': rid in liked_set} for rid in review_ids}

def add_review_reply(review_id, user_id, display_name, reply_text):
    res = _sb().from_('review_replies').insert({
        'review_id':    review_id,
        'user_id':      user_id,
        'display_name': display_name,
        'reply_text':   reply_text,
    }).execute()
    return res.data[0]['id'] if res.data else None

def get_review_replies(review_id, user_id=None):
    client = _sb()
    res = client.from_('review_replies').select('id, user_id, display_name, reply_text, created_at').eq('review_id', review_id).order('created_at', desc=False).execute()
    rows = res.data or []
    reply_ids = [r['id'] for r in rows]
    liked_set = set()
    counts = {}
    if reply_ids:
        like_res = client.from_('reply_likes').select('reply_id, user_id').in_('reply_id', reply_ids).execute()
        for row in (like_res.data or []):
            rid = row['reply_id']
            counts[rid] = counts.get(rid, 0) + 1
            if user_id and row['user_id'] == user_id:
                liked_set.add(rid)
    return [{
        'id':           r['id'],
        'user_id':      r['user_id'],
        'display_name': r['display_name'],
        'reply_text':   r['reply_text'],
        'created_at':   r['created_at'],
        'like_count':   counts.get(r['id'], 0),
        'user_liked':   r['id'] in liked_set,
    } for r in rows]

def toggle_reply_like(reply_id, user_id):
    client = _sb()
    check = client.from_('reply_likes').select('id').eq('reply_id', reply_id).eq('user_id', user_id).limit(1).execute()
    if check.data:
        client.from_('reply_likes').delete().eq('reply_id', reply_id).eq('user_id', user_id).execute()
        liked = False
    else:
        client.from_('reply_likes').insert({'reply_id': reply_id, 'user_id': user_id}).execute()
        liked = True
    count_res = client.from_('reply_likes').select('id', count='exact').eq('reply_id', reply_id).execute()
    count = count_res.count or 0
    return liked, count

# ==============================================
# INIT
# ==============================================

def init_database():
    print('=' * 50)
    print('INITIALIZING DATABASE')
    print('=' * 50)
    create_tables()
    import_fighters_from_json()
    print('=' * 50)
    print('DATABASE READY')
    print('=' * 50)

if __name__ == '__main__':
    init_database()

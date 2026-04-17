# ==============================================
# MMA BRIDGE - DATABASE SETUP
# ==============================================

import sqlite3
import json
import os
from datetime import datetime

# Database file path
DB_PATH = os.path.join(os.path.dirname(__file__), 'mma_bridge.db')

# ==============================================
# CREATE DATABASE TABLES
# ==============================================

def create_tables():
    """Create all database tables"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # FIGHTERS TABLE
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
    
    # EVENTS TABLE
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_name TEXT NOT NULL,
            event_date TEXT NOT NULL,
            location TEXT,
            venue TEXT,
            main_card TEXT,
            prelims TEXT,
            early_prelims TEXT,
            status TEXT DEFAULT 'upcoming',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # NEWS TABLE
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            summary TEXT,
            content TEXT,
            image_url TEXT,
            source TEXT,
            author TEXT,
            published_at TEXT,
            url TEXT,
            category TEXT DEFAULT 'general',
            is_trending INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # RANKINGS TABLE
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS rankings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fighter_id TEXT NOT NULL,
            rank INTEGER NOT NULL,
            weight_class TEXT DEFAULT 'pound_for_pound',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (fighter_id) REFERENCES fighters (id)
        )
    ''')
    
    # EVENT RATINGS TABLE
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS event_ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL,
            event_name TEXT NOT NULL,
            hype_rating INTEGER NOT NULL CHECK(hype_rating BETWEEN 1 AND 5),
            fotn_prediction TEXT,
            review_text TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    conn.commit()
    conn.close()

# ==============================================
# IMPORT DATA FROM JSON FILES
# ==============================================

def import_fighters_from_json():
    """Import fighters from fighters.json"""
    json_path = os.path.join(os.path.dirname(__file__), 'data', 'fighters.json')
    
    if not os.path.exists(json_path):
        print("❌ fighters.json not found")
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
    print(f"✅ Imported {count} fighters")

def import_events_from_json():
    """Import events from events.json"""
    json_path = os.path.join(os.path.dirname(__file__), 'data', 'events.json')
    
    if not os.path.exists(json_path):
        print("❌ events.json not found")
        return
    
    with open(json_path, 'r') as f:
        events_data = json.load(f)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    count = 0
    for event in events_data:
        cursor.execute('''
            INSERT OR REPLACE INTO events 
            (event_name, event_date, location, venue, main_card, prelims, early_prelims, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            event.get('eventName', ''),
            event.get('date', ''),
            event.get('location', ''),
            event.get('venue', ''),
            json.dumps(event.get('mainCard', [])),
            json.dumps(event.get('prelims', [])),
            json.dumps(event.get('earlyPrelims', [])),
            event.get('status', 'upcoming')
        ))
        count += 1
    
    conn.commit()
    conn.close()
    print(f"✅ Imported {count} events")

# ==============================================
# DATABASE QUERY FUNCTIONS
# ==============================================

def get_all_fighters():
    """Get all fighters from database"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM fighters')
    rows = cursor.fetchall()
    
    fighters = {}
    for row in rows:
        fighter_id = row['id']
        fighters[fighter_id] = {
            'name': row['name'],
            'nickname': row['nickname'],
            'weightClass': row['weight_class'],
            'record': row['record'],
            'wins': row['wins'],
            'losses': row['losses'],
            'draws': row['draws'],
            'height': row['height'],
            'weight': row['weight'],
            'reach': row['reach'],
            'stance': row['stance'],
            'dob': row['dob'],
            'country': row['country'],
            'fightingOutOf': row['fighting_out_of'],
            'imageUrl': row['image_url'],
            'lastFive': json.loads(row['last_five']) if row['last_five'] else []
        }
    
    conn.close()
    return fighters

def get_fighter_by_id(fighter_id):
    """Get a single fighter by ID"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM fighters WHERE id = ?', (fighter_id,))
    row = cursor.fetchone()
    
    if not row:
        conn.close()
        return None
    
    fighter = {
        'name': row['name'],
        'nickname': row['nickname'],
        'weightClass': row['weight_class'],
        'record': row['record'],
        'wins': row['wins'],
        'losses': row['losses'],
        'draws': row['draws'],
        'height': row['height'],
        'weight': row['weight'],
        'reach': row['reach'],
        'stance': row['stance'],
        'dob': row['dob'],
        'country': row['country'],
        'fightingOutOf': row['fighting_out_of'],
        'imageUrl': row['image_url'],
        'lastFive': json.loads(row['last_five']) if row['last_five'] else []
    }
    
    conn.close()
    return fighter

def get_all_events():
    """Get all events from database"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM events ORDER BY event_date ASC')
    rows = cursor.fetchall()
    
    events = []
    for row in rows:
        events.append({
            'eventName': row['event_name'],
            'date': row['event_date'],
            'location': row['location'],
            'venue': row['venue'],
            'mainCard': json.loads(row['main_card']) if row['main_card'] else [],
            'prelims': json.loads(row['prelims']) if row['prelims'] else [],
            'earlyPrelims': json.loads(row['early_prelims']) if row['early_prelims'] else [],
            'status': row['status']
        })
    
    conn.close()
    return events

def get_upcoming_events():
    """Get upcoming events"""
    # For now, just return all events
    # Later you can filter by date
    return get_all_events()

# ==============================================
# INITIALIZE DATABASE
# ==============================================

def init_database():
    """Initialize database with tables and data"""
    print("=" * 50)
    print("🗄️  INITIALIZING DATABASE")
    print("=" * 50)
    
    # Create tables
    create_tables()
    
    # Import data from JSON files
    import_fighters_from_json()
    import_events_from_json()
    
    print("=" * 50)
    print("✅ DATABASE READY!")
    print("=" * 50)

def save_event_rating(event_id, event_name, hype_rating, fotn_prediction=None, review_text=None):
    """Save an event rating to the database"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # Add column if missing (migration)
    try:
        cursor.execute('ALTER TABLE event_ratings ADD COLUMN review_text TEXT')
    except sqlite3.OperationalError:
        pass
    cursor.execute('''
        INSERT INTO event_ratings (event_id, event_name, hype_rating, fotn_prediction, review_text)
        VALUES (?, ?, ?, ?, ?)
    ''', (event_id, event_name, hype_rating, fotn_prediction, review_text))
    conn.commit()
    rating_id = cursor.lastrowid
    conn.close()
    return rating_id

def update_event_rating(rating_id, hype_rating, review_text=None):
    """Update an existing event rating"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE event_ratings SET hype_rating = ?, review_text = ? WHERE id = ?
    ''', (hype_rating, review_text, rating_id))
    conn.commit()
    conn.close()

def get_event_ratings(event_id):
    """Get all ratings for a specific event"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('''
        SELECT * FROM event_ratings WHERE event_id = ? ORDER BY created_at DESC
    ''', (event_id,))
    rows = cursor.fetchall()
    conn.close()
    ratings = []
    for row in rows:
        ratings.append({
            'id': row['id'],
            'event_id': row['event_id'],
            'event_name': row['event_name'],
            'hype_rating': row['hype_rating'],
            'fotn_prediction': row['fotn_prediction'],
            'review_text': row['review_text'] if 'review_text' in row.keys() else None,
            'created_at': row['created_at']
        })
    return ratings

def get_event_reviews(event_id):
    """Get all fan reviews (with text) for a specific event, newest first"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    # Ensure review_text column exists
    try:
        cursor.execute('ALTER TABLE event_ratings ADD COLUMN review_text TEXT')
        conn.commit()
    except sqlite3.OperationalError:
        pass
    cursor.execute('''
        SELECT id, hype_rating, review_text, created_at
        FROM event_ratings
        WHERE event_id = ?
        ORDER BY created_at DESC
    ''', (event_id,))
    rows = cursor.fetchall()
    conn.close()
    reviews = []
    for row in rows:
        reviews.append({
            'id': row['id'],
            'hype_rating': row['hype_rating'],
            'review_text': row['review_text'],
            'created_at': row['created_at']
        })
    return reviews

def get_event_avg_rating(event_id):
    """Get the average hype rating and FOTN predictions for an event"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('''
        SELECT 
            COUNT(*) as total_ratings,
            AVG(hype_rating) as avg_hype,
            fotn_prediction,
            COUNT(fotn_prediction) as fotn_votes
        FROM event_ratings
        WHERE event_id = ?
        GROUP BY fotn_prediction
        ORDER BY fotn_votes DESC
    ''', (event_id,))
    rows = cursor.fetchall()
    conn.close()
    if not rows:
        return {'total_ratings': 0, 'avg_hype': None, 'top_fotn': None}
    # First row has the top FOTN pick
    return {
        'total_ratings': rows[0]['total_ratings'],
        'avg_hype': round(rows[0]['avg_hype'], 1) if rows[0]['avg_hype'] else None,
        'top_fotn': rows[0]['fotn_prediction']
    }

# Run this when script is executed directly
if __name__ == '__main__':
    init_database()

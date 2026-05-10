"""
One-time migration: load events.json into Supabase.
Run once after creating the Supabase schema:
  python migrate_to_supabase.py
"""
import json, os
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL         = os.getenv('SUPABASE_URL')
SUPABASE_SERVICE_KEY = os.getenv('SUPABASE_SERVICE_KEY')

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    raise SystemExit('Set SUPABASE_URL and SUPABASE_SERVICE_KEY in .env first')

sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

events_path = os.path.join(os.path.dirname(__file__), 'events.json')
with open(events_path) as f:
    events = json.load(f)

rows = []
for e in events:
    if not e.get('id'):
        continue
    rows.append({
        'id':            e['id'],
        'name':          e.get('name', ''),
        'type':          e.get('type', 'FIGHT NIGHT'),
        'date':          e.get('date', ''),
        'iso_date':      e.get('isoDate', ''),
        'location':      e.get('location', ''),
        'venue':         e.get('venue', ''),
        'poster':        e.get('poster', ''),
        'status':        e.get('status', 'upcoming'),
        'main_card':     e.get('mainCard', []),
        'prelims':       e.get('prelims', []),
        'early_prelims': e.get('earlyPrelims', []),
    })

print(f'Migrating {len(rows)} events...')
res = sb.from_('events').upsert(rows, on_conflict='id').execute()
print(f'Done. {len(res.data or [])} rows upserted.')

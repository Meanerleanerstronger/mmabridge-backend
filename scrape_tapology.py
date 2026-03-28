# ==============================================
# MMA BRIDGE — TAPOLOGY SCRAPER (PLAYWRIGHT)
# Real UFC events, fight cards, posters.
#
# SETUP (run once):
#   pip3 install playwright beautifulsoup4
#   python3 -m playwright install chromium
#
# RUN:   python3 scrape_tapology.py
# DAILY: Set Render Cron Job → python3 run_scrapers.py
# ==============================================

import json, os, re, sqlite3, time
from datetime import date

DB_PATH  = os.path.join(os.path.dirname(__file__), 'mma_bridge.db')
DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')

# ── Real UFC events — past and upcoming ───────
# Format: (tapology_event_id, name, isoDate, location, venue, type)
# Poster auto-built from: images.tapology.com/poster_images/{id}/profile/
ALL_EVENTS = [
    # ── PAST (2025) ──
    ('125944', 'UFC Fight Night: Usman vs. Buckley',      '2025-04-26', 'Las Vegas, NV',    'Meta APEX',             'FIGHT NIGHT'),
    ('126286', 'UFC Fight Night: Lopes vs. Silva',         '2025-05-03', 'Las Vegas, NV',    'Meta APEX',             'FIGHT NIGHT'),
    ('127934', 'UFC Fight Night: Taira vs. Park',          '2025-06-14', 'Las Vegas, NV',    'Meta APEX',             'FIGHT NIGHT'),
    ('125838', 'UFC Fight Night: Hill vs. Rountree',       '2025-06-21', 'Baku, Azerbaijan', 'Baku Crystal Hall',     'FIGHT NIGHT'),
    ('127957', 'UFC Fight Night: Dolidze vs. Hernandez',   '2025-08-09', 'Las Vegas, NV',    'Meta APEX',             'FIGHT NIGHT'),
    ('129146', 'UFC Fight Night: Imavov vs. Borralho',     '2025-09-06', 'Paris, France',    'Accor Arena',           'FIGHT NIGHT'),
    ('128594', 'UFC Fight Night: Walker vs. Zhang',        '2025-09-20', 'Las Vegas, NV',    'Meta APEX',             'FIGHT NIGHT'),
    ('132058', 'UFC Fight Night: Garcia vs. Onama',        '2025-11-01', 'Las Vegas, NV',    'Meta APEX',             'FIGHT NIGHT'),
    ('132761', 'UFC Fight Night: Bonfim vs. Brown',        '2025-11-08', 'Las Vegas, NV',    'Meta APEX',             'FIGHT NIGHT'),

    # ── PAST (2026) ──
    ('135755', 'UFC 324: Gaethje vs. Pimblett',            '2026-01-24', 'Las Vegas, NV',    'T-Mobile Arena',        'PPV'),
    ('136872', 'UFC Fight Night: Strickland vs. Hernandez','2026-02-21', 'Houston, TX',      'Toyota Center',         'FIGHT NIGHT'),
    ('136874', 'UFC Fight Night: Emmett vs. Vallejos',     '2026-03-14', 'Las Vegas, NV',    'Meta APEX',             'FIGHT NIGHT'),
    ('136856', 'UFC Fight Night: Evloev vs. Murphy',       '2026-03-21', 'London, England',  'The O2',                'FIGHT NIGHT'),
    ('136873', 'UFC Fight Night: Adesanya vs. Pyfer',      '2026-03-28', 'Seattle, WA',      'Climate Pledge Arena',  'FIGHT NIGHT'),

    # ── UPCOMING ──
    ('138212', 'UFC Fight Night: Moicano vs. Duncan',      '2026-04-04', 'Las Vegas, NV',    'Meta APEX',             'FIGHT NIGHT'),
    ('137847', 'UFC 327: Procházka vs. Ulberg',            '2026-04-11', 'Miami, FL',        'Kaseya Center',         'PPV'),
    ('140458', 'UFC Fight Night: Allen vs. Costa',         '2026-05-16', 'Las Vegas, NV',    'Meta APEX',             'FIGHT NIGHT'),
    ('137848', 'UFC 250: Topuria vs. Gaethje',             '2026-06-14', 'Washington, D.C.', 'White House South Lawn','PPV'),
    ('141299', 'UFC Fight Night: Baku',                    '2026-06-27', 'Baku, Azerbaijan', 'Baku Crystal Hall',     'FIGHT NIGHT'),
]

TAPOLOGY_BASE = 'https://www.tapology.com/fightcenter/events'
POSTER_BASE   = 'https://images.tapology.com/poster_images'

def slugify(s):
    return re.sub(r'[^a-z0-9]+', '-', (s or '').lower()).strip('-')

def get_poster_url(event_id, html):
    """Extract poster URL from page HTML"""
    # Tapology pattern: /poster_images/EVENT_ID/profile/FILENAME.jpg
    m = re.search(rf'poster_images/{event_id}/profile/([^"?\s]+)', html)
    if m:
        return f"{POSTER_BASE}/{event_id}/profile/{m.group(1)}"
    # Fallback pattern
    m2 = re.search(r'poster_images/\d+/profile/([^"?\s]+\.jpg)', html)
    if m2:
        return f"{POSTER_BASE}/{event_id}/profile/{m2.group(1)}"
    return ''

def get_event_url(event_id, name):
    slug = slugify(name)
    return f"{TAPOLOGY_BASE}/{event_id}-{slug}"

# ── Playwright scraper ────────────────────────
def scrape_event(event_id, name, meta):
    """Scrape a Tapology event page using Playwright"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print('  ❌ Playwright not installed. Run: pip3 install playwright && python3 -m playwright install chromium')
        return '', [], [], []

    url = get_event_url(event_id, name)
    print(f"  🌐 {url}")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
                viewport={'width': 1280, 'height': 900},
            )
            page = ctx.new_page()
            page.goto(url, wait_until='domcontentloaded', timeout=30000)
            # Scroll to load all fights
            page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
            page.wait_for_timeout(3500)
            page.evaluate('window.scrollTo(0, 0)')
            page.wait_for_timeout(500)
            html = page.content()
            browser.close()

        poster = get_poster_url(event_id, html)
        main_card, prelims, early_prelims = parse_fights(html)
        return poster, main_card, prelims, early_prelims

    except Exception as e:
        print(f'  ⚠️  Playwright error: {e}')
        return '', [], [], []

def parse_fights(html):
    """Parse fight card from Tapology event HTML"""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')

    main_card, prelims, early_prelims = [], [], []
    current = 'main'

    # Find all fight list items
    rows = soup.select('li[class*="fightCard"], li[class*="bout"]')
    if not rows:
        rows = soup.select('li[data-bout-id]')
    if not rows:
        # Last resort — find by fighter link pairs
        rows = soup.select('li')

    for row in rows:
        classes = ' '.join(row.get('class', []))
        txt = row.get_text(' ', strip=True)

        # Detect section from class
        if any(x in classes for x in ['earlyPrelim', 'earlyPrelims', 'early_prelim']):
            current = 'early'
        elif 'prelim' in classes.lower() and 'main' not in classes.lower() and 'early' not in classes.lower():
            current = 'prelims'
        elif any(x in classes for x in ['mainCard', 'main_card']):
            current = 'main'
        # Detect section from heading text
        elif re.match(r'^\s*(early prelims?|early card)\s*$', txt, re.I):
            current = 'early'
            continue
        elif re.match(r'^\s*prelims?\s*$', txt, re.I):
            current = 'prelims'
            continue
        elif re.match(r'^\s*main card\s*$', txt, re.I):
            current = 'main'
            continue

        # Extract fighters from <a href="/fighters/...">
        fighter_links = row.select('a[href*="/fighters/"]')
        a_name, b_name = '', ''

        if len(fighter_links) >= 2:
            a_name = fighter_links[0].get_text(strip=True)
            b_name = fighter_links[1].get_text(strip=True)
        else:
            # Try ⤫ separator (Tapology's vs symbol)
            m = re.search(r'([A-Z][a-zA-Záéíóúñüàâãèêìîõùûç\'\.\-\s]{2,35}?)\s*(?:⤫|vs\.?)\s*([A-Z][a-zA-Záéíóúñüàâãèêìîõùûç\'\.\-\s]{2,35})', txt)
            if m:
                a_name = m.group(1).strip()
                b_name = m.group(2).strip()

        # Skip if empty, same name, or too short
        if not a_name or not b_name or a_name == b_name:
            continue
        if len(a_name) < 4 or len(b_name) < 4:
            continue
        # Skip obvious non-fight rows
        if any(x in a_name.lower() for x in ['main card', 'prelim', 'early', 'bout', 'fight']):
            continue

        # Weight class
        wt = ''
        for sel in ['[class*="weight"]', '[class*="division"]', '[class*="class"]']:
            el = row.select_one(sel)
            if el:
                wt = el.get_text(strip=True)
                # Clean up weight — keep "Lightweight", "170 lbs" etc
                wt = re.sub(r'\s+', ' ', wt).strip()
                break
        # If no element found, try to extract from text
        if not wt:
            wt_m = re.search(r'(\d{3}(?:\.\d)?\s*lbs?|Heavyweight|Light Heavyweight|Middleweight|Welterweight|Lightweight|Featherweight|Bantamweight|Flyweight|Strawweight|Women\'s)', txt, re.I)
            if wt_m:
                wt = wt_m.group(1)

        is_title  = any(x in txt.lower() for x in ['championship', 'title bout', 'title fight', 'vacant'])
        is_ranked = bool(re.search(r'#\d+', txt))

        fight = {
            'a': a_name, 'b': b_name,
            'weight': wt,
            'rounds': '5 Rds' if is_title else '3 Rds',
            'titleFight': is_title,
            'ranked': is_ranked,
        }

        if current == 'main':
            if not main_card:          fight['slot'] = 'main'
            elif len(main_card) == 1:  fight['slot'] = 'comain'
            main_card.append(fight)
        elif current == 'prelims':
            prelims.append(fight)
        else:
            early_prelims.append(fight)

    return main_card, prelims, early_prelims

# ── DB helpers ────────────────────────────────
def ensure_columns():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    for col in ['image_url TEXT', 'iso_date TEXT', 'event_slug TEXT', 'event_type TEXT']:
        try:
            cur.execute(f'ALTER TABLE events ADD COLUMN {col}')
        except sqlite3.OperationalError:
            pass
    conn.commit()
    conn.close()

def save_event(ev):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('SELECT id FROM events WHERE event_name = ?', (ev['name'],))
    exists = cur.fetchone()
    args = (
        ev['date'], ev['location'], ev['venue'],
        json.dumps(ev['mainCard']), json.dumps(ev['prelims']),
        json.dumps(ev['earlyPrelims']), ev['status'],
        ev.get('poster',''), ev['isoDate'], ev['id'], ev['type'],
    )
    if exists:
        cur.execute('''UPDATE events SET
            event_date=?, location=?, venue=?, main_card=?, prelims=?,
            early_prelims=?, status=?, image_url=?, iso_date=?,
            event_slug=?, event_type=?, updated_at=CURRENT_TIMESTAMP
            WHERE event_name=?''', args + (ev['name'],))
    else:
        cur.execute('''INSERT INTO events
            (event_name, event_date, location, venue, main_card, prelims,
             early_prelims, status, image_url, iso_date, event_slug, event_type)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
            (ev['name'],) + args)
    conn.commit()
    conn.close()

def save_json(events):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(os.path.join(DATA_DIR, 'events.json'), 'w') as f:
        json.dump(events, f, indent=2)
    print(f'  ✅ Saved → data/events.json ({len(events)} events)')

# ── API reader (used by app.py) ───────────────
def get_events_for_api():
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute('SELECT * FROM events ORDER BY iso_date ASC, event_date ASC')
        rows = cur.fetchall()
        conn.close()
    except Exception as e:
        print(f'DB read error: {e}')
        return []

    events = []
    for row in rows:
        try:
            cols = row.keys()
            slug   = (row['event_slug'] if 'event_slug' in cols and row['event_slug'] else slugify(row['event_name']))
            etype  = (row['event_type'] if 'event_type' in cols and row['event_type'] else ('PPV' if re.search(r'UFC\s+\d{3}', row['event_name'].upper()) else 'FIGHT NIGHT'))
            iso    = row['iso_date']  if 'iso_date'  in cols else ''
            poster = row['image_url'] if 'image_url' in cols else ''
            events.append({
                'id':           slug,
                'name':         row['event_name'],
                'type':         etype,
                'date':         row['event_date'],
                'isoDate':      iso or '',
                'location':     row['location'] or '',
                'venue':        row['venue'] or '',
                'poster':       poster or '',
                'mainCard':     json.loads(row['main_card'])     if row['main_card']     else [],
                'prelims':      json.loads(row['prelims'])       if row['prelims']       else [],
                'earlyPrelims': json.loads(row['early_prelims']) if row['early_prelims'] else [],
                'status':       row['status'] or 'upcoming',
            })
        except Exception as e:
            print(f'Row parse error: {e}')
    return events

# ── Main ──────────────────────────────────────
def run():
    print('=' * 58)
    print('🕷  MMA BRIDGE — TAPOLOGY SCRAPER')
    print(f'   {len(ALL_EVENTS)} events to process')
    print('=' * 58)

    ensure_columns()
    today = date.today().isoformat()
    saved = []

    for event_id, name, iso_date, location, venue, ev_type in ALL_EVENTS:
        print(f'\n📋 {name} ({iso_date})')
        status = 'upcoming' if iso_date >= today else 'completed'

        poster, main_card, prelims, early_prelims = scrape_event(event_id, name, None)

        print(f'   ✅ {len(main_card)} main  {len(prelims)} prelims  {len(early_prelims)} early  | poster: {"✓" if poster else "✗"}')

        ev = {
            'id':           slugify(name),
            'name':         name,
            'type':         ev_type,
            'date':         iso_date,
            'isoDate':      iso_date,
            'location':     location,
            'venue':        venue,
            'poster':       poster,
            'mainCard':     main_card,
            'prelims':      prelims,
            'earlyPrelims': early_prelims,
            'status':       status,
        }
        save_event(ev)
        saved.append(ev)
        time.sleep(1.5)

    save_json(saved)
    print(f'\n{"="*58}')
    print(f'✅ Done — {len(saved)} events processed')
    print(f'{"="*58}\n')

if __name__ == '__main__':
    run()

# ==============================================
# MMA BRIDGE - UFC EVENTS SCRAPER
# ==============================================

import requests
from bs4 import BeautifulSoup
import json
import sqlite3
import os
import time
from datetime import datetime

# Database path
DB_PATH = os.path.join(os.path.dirname(__file__), 'mma_bridge.db')

# ==============================================
# SCRAPE UFC EVENTS
# ==============================================

def scrape_event_details(event_url, headers):
    """
    Scrape detailed fight card from individual event page
    Returns fight card details
    """
    try:
        response = requests.get(event_url, headers=headers, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        main_card = []
        prelims = []
        early_prelims = []
        
        # Find fight listings
        fight_elements = soup.find_all('div', class_='c-listing-fight')
        
        for fight in fight_elements:
            try:
                # Get fighters
                fighter_elems = fight.find_all('div', class_='c-listing-fight__corner-name')
                if len(fighter_elems) >= 2:
                    fighter1 = fighter_elems[0].text.strip()
                    fighter2 = fighter_elems[1].text.strip()
                    
                    # Get weight class
                    weight_elem = fight.find('div', class_='c-listing-fight__class-text')
                    weight_class = weight_elem.text.strip() if weight_elem else ''
                    
                    fight_data = {
                        'fighter1': fighter1,
                        'fighter2': fighter2,
                        'weightClass': weight_class
                    }
                    
                    # Determine card type (main/prelims/early)
                    card_type_elem = fight.find_parent('div', class_='l-listing__group')
                    if card_type_elem:
                        header = card_type_elem.find('h2', class_='e-font-uppercut')
                        if header:
                            card_type = header.text.strip().lower()
                            if 'main card' in card_type:
                                main_card.append(fight_data)
                            elif 'prelims' in card_type and 'early' not in card_type:
                                prelims.append(fight_data)
                            elif 'early' in card_type:
                                early_prelims.append(fight_data)
                    else:
                        # Default to main card if can't determine
                        main_card.append(fight_data)
                        
            except Exception as e:
                continue
        
        return main_card, prelims, early_prelims
        
    except Exception as e:
        print(f"⚠️  Error scraping event details: {e}")
        return [], [], []

def scrape_ufc_events():
    """
    Scrape upcoming UFC events from UFC.com with full fight cards and images
    Returns list of events
    """
    print("🕷️  Scraping UFC events...")
    
    # UFC events page URL
    url = "https://www.ufc.com/events"
    
    try:
        # Set headers to avoid being blocked
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        # Fetch the page
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        # Parse HTML
        soup = BeautifulSoup(response.content, 'html.parser')
        
        events = []
        
        # Find event cards - try multiple selectors
        event_cards = soup.find_all('div', class_='c-card-event--result')
        
        if not event_cards:
            event_cards = soup.find_all('article', class_='c-listing-events__item')
        
        for card in event_cards[:10]:  # Limit to 10 events
            try:
                # Extract event link
                link_elem = card.find('a', href=True)
                event_link = link_elem['href'] if link_elem else None
                if event_link and not event_link.startswith('http'):
                    event_link = f"https://www.ufc.com{event_link}"
                
                # Extract event image
                img_elem = card.find('img')
                event_image = img_elem.get('src') or img_elem.get('data-src') if img_elem else ''
                
                # Extract event name
                title_elem = card.find('h3') or card.find('span', class_='c-card-event--result__headline')
                event_name = title_elem.text.strip() if title_elem else "Unknown Event"
                
                # Extract date
                date_elem = card.find('div', class_='c-card-event--result__date') or card.find('time')
                event_date = date_elem.text.strip() if date_elem else "TBA"
                
                # Extract location
                location_elem = card.find('div', class_='c-card-event--result__location')
                location = location_elem.text.strip() if location_elem else "TBA"
                
                # Initialize fight cards
                main_card = []
                prelims = []
                early_prelims = []
                
                # Try to get detailed fight card from event page
                if event_link:
                    print(f"  📋 Fetching fight card for: {event_name}")
                    main_card, prelims, early_prelims = scrape_event_details(event_link, headers)
                    time.sleep(1)  # Be nice to UFC servers
                
                events.append({
                    'eventName': event_name,
                    'date': event_date,
                    'location': location,
                    'venue': '',
                    'imageUrl': event_image,
                    'mainCard': main_card,
                    'prelims': prelims,
                    'earlyPrelims': early_prelims,
                    'status': 'upcoming'
                })
                
                print(f"  ✅ {event_name}: {len(main_card)} main card, {len(prelims)} prelims, {len(early_prelims)} early prelims")
                
            except Exception as e:
                print(f"⚠️  Error parsing event card: {e}")
                continue
        
        print(f"✅ Found {len(events)} UFC events")
        return events
        
    except requests.RequestException as e:
        print(f"❌ Error fetching UFC events: {e}")
        return []
    except Exception as e:
        print(f"❌ Error scraping UFC events: {e}")
        return []

# ==============================================
# SAVE EVENTS TO DATABASE
# ==============================================

def save_events_to_database(events):
    """Save scraped events to database"""
    if not events:
        print("❌ No events to save")
        return
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # First, add image_url column if it doesn't exist
    try:
        cursor.execute('ALTER TABLE events ADD COLUMN image_url TEXT')
        conn.commit()
    except sqlite3.OperationalError:
        # Column already exists
        pass
    
    count = 0
    for event in events:
        try:
            # Check if event already exists
            cursor.execute(
                'SELECT id FROM events WHERE event_name = ? AND event_date = ?',
                (event['eventName'], event['date'])
            )
            
            if cursor.fetchone():
                # Update existing event
                cursor.execute('''
                    UPDATE events 
                    SET location = ?, venue = ?, main_card = ?, prelims = ?, 
                        early_prelims = ?, status = ?, image_url = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE event_name = ? AND event_date = ?
                ''', (
                    event['location'],
                    event['venue'],
                    json.dumps(event['mainCard']),
                    json.dumps(event['prelims']),
                    json.dumps(event['earlyPrelims']),
                    event['status'],
                    event.get('imageUrl', ''),
                    event['eventName'],
                    event['date']
                ))
            else:
                # Insert new event
                cursor.execute('''
                    INSERT INTO events 
                    (event_name, event_date, location, venue, main_card, prelims, early_prelims, status, image_url)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    event['eventName'],
                    event['date'],
                    event['location'],
                    event['venue'],
                    json.dumps(event['mainCard']),
                    json.dumps(event['prelims']),
                    json.dumps(event['earlyPrelims']),
                    event['status'],
                    event.get('imageUrl', '')
                ))
            
            count += 1
            
        except Exception as e:
            print(f"⚠️  Error saving event: {e}")
            continue
    
    conn.commit()
    conn.close()
    
    print(f"✅ Saved {count} events to database")

# ==============================================
# MANUAL FALLBACK DATA
# ==============================================

def get_manual_ufc_events():
    """
    Fallback: Manual UFC events data
    Use this if scraping fails
    """
    return [
        {
            'eventName': 'UFC 313: Pereira vs. Hill',
            'date': 'March 8, 2025',
            'location': 'Las Vegas, Nevada',
            'venue': 'T-Mobile Arena',
            'mainCard': [
                {'fighter1': 'Alex Pereira', 'fighter2': 'Jamahal Hill', 'weightClass': 'Light Heavyweight'}
            ],
            'prelims': [],
            'earlyPrelims': [],
            'status': 'upcoming'
        },
        {
            'eventName': 'UFC 314: Makhachev vs. Oliveira 2',
            'date': 'March 22, 2025',
            'location': 'Miami, Florida',
            'venue': 'Kaseya Center',
            'mainCard': [
                {'fighter1': 'Islam Makhachev', 'fighter2': 'Charles Oliveira', 'weightClass': 'Lightweight'}
            ],
            'prelims': [],
            'earlyPrelims': [],
            'status': 'upcoming'
        },
        {
            'eventName': 'UFC 315: Jones vs. Aspinall',
            'date': 'April 5, 2025',
            'location': 'New York, New York',
            'venue': 'Madison Square Garden',
            'mainCard': [
                {'fighter1': 'Jon Jones', 'fighter2': 'Tom Aspinall', 'weightClass': 'Heavyweight'}
            ],
            'prelims': [],
            'earlyPrelims': [],
            'status': 'upcoming'
        }
    ]

# ==============================================
# MAIN SCRAPER FUNCTION
# ==============================================

def scrape_and_update_events():
    """Main function to scrape and update events"""
    print("=" * 50)
    print("🕷️  UFC EVENTS SCRAPER")
    print("=" * 50)
    
    # Try scraping UFC.com
    events = scrape_ufc_events()
    
    # If scraping fails, use manual data
    if not events:
        print("⚠️  Scraping failed, using manual fallback data")
        events = get_manual_ufc_events()
    
    # Save to database
    save_events_to_database(events)
    
    print("=" * 50)
    print("✅ EVENTS UPDATE COMPLETE!")
    print("=" * 50)

# ==============================================
# RUN SCRAPER
# ==============================================

if __name__ == '__main__':
    scrape_and_update_events()

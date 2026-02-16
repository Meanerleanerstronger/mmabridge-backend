# ==============================================
# MMA BRIDGE - FIGHTER STATS SCRAPER
# ==============================================

import requests
from bs4 import BeautifulSoup
import json
import sqlite3
import os
import time

# Database path
DB_PATH = os.path.join(os.path.dirname(__file__), 'mma_bridge.db')

# ==============================================
# SCRAPE UFC ROSTER
# ==============================================

def scrape_ufc_roster():
    """
    Scrape UFC roster from UFC.com
    Returns list of fighters with basic info
    """
    print("🕷️  Scraping UFC roster...")
    
    url = "https://www.ufc.com/athletes/all"
    
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        fighters = []
        
        # Find fighter cards (selector might need adjustment)
        fighter_cards = soup.find_all('div', class_='c-listing-athlete-flipcard__inner')
        
        if not fighter_cards:
            # Try alternative selector
            fighter_cards = soup.find_all('div', class_='views-row')
        
        for card in fighter_cards[:20]:  # Limit to 20 fighters per run
            try:
                # Extract fighter name
                name_elem = card.find('span', class_='c-listing-athlete-flipcard__name')
                if not name_elem:
                    name_elem = card.find('h3')
                
                name = name_elem.text.strip() if name_elem else None
                
                if not name:
                    continue
                
                # Extract nickname
                nickname_elem = card.find('span', class_='c-listing-athlete-flipcard__nickname')
                nickname = nickname_elem.text.strip() if nickname_elem else ""
                
                # Extract weight class
                weight_elem = card.find('div', class_='c-listing-athlete-flipcard__title')
                weight_class = weight_elem.text.strip() if weight_elem else ""
                
                # Extract record
                record_elem = card.find('span', class_='c-listing-athlete-flipcard__record')
                record = record_elem.text.strip() if record_elem else "0-0-0"
                
                # Parse wins/losses/draws from record
                wins, losses, draws = 0, 0, 0
                if record and '-' in record:
                    parts = record.split('-')
                    wins = int(parts[0]) if len(parts) > 0 and parts[0].isdigit() else 0
                    losses = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
                    draws = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
                
                # Create fighter ID (slug)
                fighter_id = name.lower().replace(' ', '-').replace("'", "")
                
                fighters.append({
                    'id': fighter_id,
                    'name': name,
                    'nickname': nickname,
                    'weightClass': weight_class,
                    'record': record,
                    'wins': wins,
                    'losses': losses,
                    'draws': draws
                })
                
            except Exception as e:
                print(f"⚠️  Error parsing fighter: {e}")
                continue
        
        print(f"✅ Found {len(fighters)} fighters")
        return fighters
        
    except requests.RequestException as e:
        print(f"❌ Error fetching UFC roster: {e}")
        return []
    except Exception as e:
        print(f"❌ Error scraping UFC roster: {e}")
        return []

# ==============================================
# UPDATE FIGHTER IN DATABASE
# ==============================================

def update_fighter_stats(fighters):
    """Update fighter stats in database"""
    if not fighters:
        print("❌ No fighters to update")
        return
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    updated = 0
    new = 0
    
    for fighter in fighters:
        try:
            # Check if fighter exists
            cursor.execute('SELECT id FROM fighters WHERE id = ?', (fighter['id'],))
            exists = cursor.fetchone()
            
            if exists:
                # Update existing fighter
                cursor.execute('''
                    UPDATE fighters 
                    SET record = ?, wins = ?, losses = ?, draws = ?, 
                        weight_class = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (
                    fighter['record'],
                    fighter['wins'],
                    fighter['losses'],
                    fighter['draws'],
                    fighter['weightClass'],
                    fighter['id']
                ))
                updated += 1
            else:
                # Insert new fighter
                cursor.execute('''
                    INSERT INTO fighters 
                    (id, name, nickname, weight_class, record, wins, losses, draws, last_five)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    fighter['id'],
                    fighter['name'],
                    fighter['nickname'],
                    fighter['weightClass'],
                    fighter['record'],
                    fighter['wins'],
                    fighter['losses'],
                    fighter['draws'],
                    '[]'
                ))
                new += 1
                
        except Exception as e:
            print(f"⚠️  Error updating fighter {fighter.get('name')}: {e}")
            continue
    
    conn.commit()
    conn.close()
    
    print(f"✅ Updated {updated} fighters, added {new} new fighters")

# ==============================================
# MANUAL TOP FIGHTERS (FALLBACK)
# ==============================================

def get_manual_top_fighters():
    """
    Fallback: Manual top fighters data
    Use this if scraping fails
    """
    return [
        {
            'id': 'islam-makhachev',
            'name': 'Islam Makhachev',
            'nickname': '',
            'weightClass': 'Lightweight',
            'record': '26-1-0',
            'wins': 26,
            'losses': 1,
            'draws': 0
        },
        {
            'id': 'alex-pereira',
            'name': 'Alex Pereira',
            'nickname': 'Poatan',
            'weightClass': 'Light Heavyweight',
            'record': '12-2-0',
            'wins': 12,
            'losses': 2,
            'draws': 0
        },
        {
            'id': 'jon-jones',
            'name': 'Jon Jones',
            'nickname': 'Bones',
            'weightClass': 'Heavyweight',
            'record': '28-1-0',
            'wins': 28,
            'losses': 1,
            'draws': 0
        },
        {
            'id': 'dricus-du-plessis',
            'name': 'Dricus Du Plessis',
            'nickname': 'Stillknocks',
            'weightClass': 'Middleweight',
            'record': '22-2-0',
            'wins': 22,
            'losses': 2,
            'draws': 0
        },
        {
            'id': 'belal-muhammad',
            'name': 'Belal Muhammad',
            'nickname': 'Remember the Name',
            'weightClass': 'Welterweight',
            'record': '24-3-0',
            'wins': 24,
            'losses': 3,
            'draws': 0
        }
    ]

# ==============================================
# MAIN SCRAPER FUNCTION
# ==============================================

def scrape_and_update_fighters():
    """Main function to scrape and update fighter stats"""
    print("=" * 50)
    print("🕷️  FIGHTER STATS SCRAPER")
    print("=" * 50)
    
    # Try scraping UFC.com
    fighters = scrape_ufc_roster()
    
    # If scraping fails, use manual data
    if not fighters:
        print("⚠️  Scraping failed, using manual fallback data")
        fighters = get_manual_top_fighters()
    
    # Update database
    update_fighter_stats(fighters)
    
    print("=" * 50)
    print("✅ FIGHTER STATS UPDATE COMPLETE!")
    print("=" * 50)

# ==============================================
# RUN SCRAPER
# ==============================================

if __name__ == '__main__':
    scrape_and_update_fighters()

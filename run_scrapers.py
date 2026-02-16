# ==============================================
# MMA BRIDGE - MASTER SCRAPER
# ==============================================

"""
This script runs all scrapers to update the database
Run this manually or set up a cron job to run daily
"""

from scrape_events import scrape_and_update_events
from scrape_fighters import scrape_and_update_fighters
import time

def run_all_scrapers():
    """Run all scrapers"""
    print("\n")
    print("=" * 60)
    print("🕷️  MMA BRIDGE - MASTER SCRAPER")
    print("=" * 60)
    print("\n")
    
    # Scrape events
    try:
        scrape_and_update_events()
        print("\n")
    except Exception as e:
        print(f"❌ Events scraper failed: {e}\n")
    
    # Wait a bit to avoid rate limiting
    time.sleep(2)
    
    # Scrape fighters
    try:
        scrape_and_update_fighters()
        print("\n")
    except Exception as e:
        print(f"❌ Fighter scraper failed: {e}\n")
    
    print("=" * 60)
    print("✅ ALL SCRAPERS COMPLETE!")
    print("=" * 60)
    print("\n")

if __name__ == '__main__':
    run_all_scrapers()

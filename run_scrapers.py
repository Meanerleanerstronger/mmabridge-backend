# ==============================================
# MMA BRIDGE — MASTER SCRAPER
# Run daily via Render Cron Job:
#   Command: python3 run_scrapers.py
#   Schedule: 0 6 * * *  (6am UTC daily)
# ==============================================

from scrape_tapology import run as scrape_events
from news_scraper import fetch_mma_news
import time

def run_all():
    print('\n' + '='*56)
    print('🕷  MMA BRIDGE — DAILY SCRAPER')
    print('='*56 + '\n')

    # 1. Events + fight cards from Tapology
    try:
        print('--- STEP 1: Events ---')
        scrape_events()
    except Exception as e:
        print(f'❌ Events scraper failed: {e}')

    time.sleep(3)

    # 2. MMA news from NewsAPI
    try:
        print('\n--- STEP 2: News ---')
        fetch_mma_news()
    except Exception as e:
        print(f'❌ News scraper failed: {e}')

    print('\n' + '='*56)
    print('✅ Daily scrape complete')
    print('='*56 + '\n')

if __name__ == '__main__':
    run_all()

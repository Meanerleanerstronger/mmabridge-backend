# ==============================================
# MMA BRIDGE — NEWS SCRAPER
# Fetches real MMA news from NewsAPI
# Runs daily via run_scrapers.py
# ==============================================

import requests
import json
import os
from datetime import datetime

NEWS_API_KEY = "f01a690184c04eb0bc8a5a779981e461"
DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')

def fetch_mma_news():
    """Fetch latest MMA/UFC news from NewsAPI"""
    print("📰 Fetching MMA news from NewsAPI...")

    url = (
        f"https://newsapi.org/v2/everything"
        f"?q=UFC+OR+MMA+OR+%22mixed+martial+arts%22"
        f"&language=en"
        f"&sortBy=publishedAt"
        f"&pageSize=20"
        f"&apiKey={NEWS_API_KEY}"
    )

    try:
        r = requests.get(url, timeout=10)
        data = r.json()

        if r.status_code != 200:
            print(f"❌ NewsAPI error: {data.get('message')}")
            return []

        articles = []
        for a in data.get('articles', [])[:15]:
            # Skip removed/null articles
            if not a.get('title') or a['title'] == '[Removed]':
                continue
            articles.append({
                'title':       a.get('title', ''),
                'description': a.get('description', ''),
                'url':         a.get('url', ''),
                'imageUrl':    a.get('urlToImage', ''),
                'source':      a.get('source', {}).get('name', ''),
                'publishedAt': a.get('publishedAt', ''),
            })

        os.makedirs(DATA_DIR, exist_ok=True)
        path = os.path.join(DATA_DIR, 'news.json')
        with open(path, 'w') as f:
            json.dump({
                'trending':    articles,
                'updatedAt':   datetime.utcnow().isoformat(),
            }, f, indent=2)

        print(f"✅ Saved {len(articles)} articles → data/news.json")
        return articles

    except Exception as e:
        print(f"❌ News fetch error: {e}")
        return []

if __name__ == '__main__':
    print("=" * 50)
    print("📰 MMA NEWS SCRAPER")
    print("=" * 50)
    fetch_mma_news()
    print("=" * 50)

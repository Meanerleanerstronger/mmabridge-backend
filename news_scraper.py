# ==============================================
# MMA BRIDGE — NEWS SCRAPER (GNews API)
# Real MMA/UFC news with images
# Free tier: 100 requests/day
# ==============================================

import requests
import json
import os
from datetime import datetime

GNEWS_API_KEY = "962d74e7eeb020eda44c20b170b4e82d"
DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')

def fetch_mma_news():
    print("📰 Fetching MMA news from GNews...")

    url = (
        f"https://gnews.io/api/v4/search"
        f"?q=UFC+OR+MMA+OR+%22mixed+martial+arts%22"
        f"&lang=en"
        f"&max=10"
        f"&sortby=publishedAt"
        f"&apikey={GNEWS_API_KEY}"
    )

    try:
        r = requests.get(url, timeout=10)
        data = r.json()

        if r.status_code != 200:
            print(f"❌ GNews error: {data}")
            return []

        articles = []
        for a in data.get('articles', []):
            if not a.get('title'):
                continue
            articles.append({
                'title':       a.get('title', ''),
                'description': a.get('description', ''),
                'url':         a.get('url', ''),
                'imageUrl':    a.get('image', ''),
                'source':      a.get('source', {}).get('name', ''),
                'publishedAt': a.get('publishedAt', ''),
            })

        os.makedirs(DATA_DIR, exist_ok=True)
        path = os.path.join(DATA_DIR, 'news.json')
        with open(path, 'w') as f:
            json.dump({
                'trending':  articles,
                'updatedAt': datetime.utcnow().isoformat(),
            }, f, indent=2)

        print(f"✅ Saved {len(articles)} articles → data/news.json")
        return articles

    except Exception as e:
        print(f"❌ News fetch error: {e}")
        return []

if __name__ == '__main__':
    fetch_mma_news()

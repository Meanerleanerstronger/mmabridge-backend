import requests
import json
from datetime import datetime

# ==============================================
# MMA BRIDGE - NEWS API SCRAPER
# ==============================================

NEWS_API_KEY = "f01a690184c04eb0bc8a5a779981e461"  # Replace with your actual key

def fetch_mma_news():
    """Fetch latest MMA news from NewsAPI"""
    
    url = f"https://newsapi.org/v2/everything?q=UFC OR MMA&sortBy=publishedAt&apiKey={NEWS_API_KEY}&pageSize=20"
    
    try:
        print("🔄 Fetching MMA news from NewsAPI...")
        response = requests.get(url)
        data = response.json()
        
        if response.status_code != 200:
            print(f"❌ Error: {data.get('message', 'Unknown error')}")
            return []
        
        news_articles = []
        for article in data.get('articles', [])[:10]:
            news_articles.append({
                'title': article.get('title'),
                'description': article.get('description'),
                'url': article.get('url'),
                'imageUrl': article.get('urlToImage'),
                'source': article.get('source', {}).get('name'),
                'publishedAt': article.get('publishedAt')
            })
        
        # Save to JSON
        with open('data/news.json', 'w') as f:
            json.dump({'trending': news_articles}, f, indent=2)
        
        print(f"✅ Fetched {len(news_articles)} news articles!")
        print(f"📝 Saved to data/news.json")
        
        return news_articles
        
    except Exception as e:
        print(f"❌ Error fetching news: {e}")
        return []

if __name__ == '__main__':
    print("=" * 50)
    print("📰 MMA NEWS SCRAPER")
    print("=" * 50)
    fetch_mma_news()
    print("=" * 50)

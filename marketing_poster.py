"""
MMA Bridge — Social Media Poster
Handles posting to Reddit and Twitter/X.
Instagram posting is done via Meta Graph API (requires a business account).
All functions return {"ok": True} or {"ok": False, "error": "..."}.
Credentials are read from environment variables — add them in Render dashboard.
"""

import os
import json
import requests as _req


# ── Reddit ──────────────────────────────────────────────────────────────────

def _reddit_token():
    cid  = os.getenv("REDDIT_CLIENT_ID", "")
    csec = os.getenv("REDDIT_CLIENT_SECRET", "")
    user = os.getenv("REDDIT_USERNAME", "")
    pw   = os.getenv("REDDIT_PASSWORD", "")
    if not all([cid, csec, user, pw]):
        return None, "Reddit credentials not configured"
    try:
        r = _req.post(
            "https://www.reddit.com/api/v1/access_token",
            auth=(cid, csec),
            data={"grant_type": "password", "username": user, "password": pw},
            headers={"User-Agent": "MMABridge/1.0"},
            timeout=10,
        )
        r.raise_for_status()
        return r.json().get("access_token"), None
    except Exception as e:
        return None, str(e)


def post_reddit(title: str, body: str, subreddit: str = "test") -> dict:
    """Post a text post to Reddit. subreddit = 'MMA' or 'ufc' in production."""
    token, err = _reddit_token()
    if err:
        return {"ok": False, "error": err}
    try:
        r = _req.post(
            "https://oauth.reddit.com/api/submit",
            headers={
                "Authorization": f"bearer {token}",
                "User-Agent": "MMABridge/1.0",
            },
            json={
                "sr": subreddit,
                "kind": "self",
                "title": title[:300],
                "text": body,
                "resubmit": True,
                "nsfw": False,
                "spoiler": False,
            },
            timeout=15,
        )
        data = r.json()
        # Reddit returns errors inside json even on 200
        errors = data.get("json", {}).get("errors", [])
        if errors:
            return {"ok": False, "error": str(errors)}
        url = data.get("json", {}).get("data", {}).get("url", "")
        return {"ok": True, "url": url}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── Twitter / X ─────────────────────────────────────────────────────────────

def post_twitter(text: str) -> dict:
    """Post a tweet via X API v2 using OAuth 1.0a."""
    api_key    = os.getenv("TWITTER_API_KEY", "")
    api_secret = os.getenv("TWITTER_API_SECRET", "")
    acc_token  = os.getenv("TWITTER_ACCESS_TOKEN", "")
    acc_secret = os.getenv("TWITTER_ACCESS_SECRET", "")
    if not all([api_key, api_secret, acc_token, acc_secret]):
        return {"ok": False, "error": "Twitter credentials not configured"}
    try:
        # OAuth 1.0a via requests-oauthlib (installed as part of authlib deps)
        from requests_oauthlib import OAuth1
        auth = OAuth1(api_key, api_secret, acc_token, acc_secret)
        r = _req.post(
            "https://api.twitter.com/2/tweets",
            json={"text": text[:280]},
            auth=auth,
            timeout=15,
        )
        if r.status_code in (200, 201):
            tweet_id = r.json().get("data", {}).get("id", "")
            username = os.getenv("TWITTER_USERNAME", "mmabridge")
            return {"ok": True, "url": f"https://twitter.com/{username}/status/{tweet_id}"}
        return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:200]}"}
    except ImportError:
        return {"ok": False, "error": "requests-oauthlib not installed — add to requirements.txt"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── Instagram ───────────────────────────────────────────────────────────────

def post_instagram(caption: str, image_url: str = "") -> dict:
    """
    Post to Instagram via Meta Graph API.
    Requires an image URL (Instagram doesn't allow text-only posts).
    If no image_url is provided, returns an error.
    """
    token      = os.getenv("INSTAGRAM_ACCESS_TOKEN", "")
    account_id = os.getenv("INSTAGRAM_ACCOUNT_ID", "")
    if not all([token, account_id]):
        return {"ok": False, "error": "Instagram credentials not configured"}
    if not image_url:
        return {"ok": False, "error": "Instagram requires an image URL"}
    try:
        # Step 1: create media container
        r1 = _req.post(
            f"https://graph.facebook.com/v19.0/{account_id}/media",
            params={
                "image_url": image_url,
                "caption": caption[:2200],
                "access_token": token,
            },
            timeout=15,
        )
        r1.raise_for_status()
        container_id = r1.json().get("id")
        if not container_id:
            return {"ok": False, "error": "No container ID returned"}

        # Step 2: publish
        r2 = _req.post(
            f"https://graph.facebook.com/v19.0/{account_id}/media_publish",
            params={"creation_id": container_id, "access_token": token},
            timeout=15,
        )
        r2.raise_for_status()
        media_id = r2.json().get("id", "")
        return {"ok": True, "media_id": media_id}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── Status check ─────────────────────────────────────────────────────────────

def platform_status() -> dict:
    """Returns which platforms have credentials configured."""
    return {
        "reddit":    all([os.getenv("REDDIT_CLIENT_ID"), os.getenv("REDDIT_USERNAME")]),
        "twitter":   all([os.getenv("TWITTER_API_KEY"), os.getenv("TWITTER_ACCESS_TOKEN")]),
        "instagram": all([os.getenv("INSTAGRAM_ACCESS_TOKEN"), os.getenv("INSTAGRAM_ACCOUNT_ID")]),
    }

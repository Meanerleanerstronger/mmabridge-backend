"""
MMA Bridge — Social Media Poster
Handles posting to Reddit and Twitter/X.
Instagram posting is done via Meta Graph API (requires a business account).
Twitter/X and Instagram both accept an optional image_url — Twitter downloads
and re-uploads it via the v1.1 media endpoint, Instagram fetches it directly.
All functions return {"ok": True} or {"ok": False, "error": "..."}.
Credentials are read from environment variables — add them in Render dashboard.
"""

import os
import json
import requests as _req


# ── Reddit ──────────────────────────────────────────────────────────────────

def _reddit_token():
    # Same stray-whitespace guard as Twitter/Instagram below.
    cid  = os.getenv("REDDIT_CLIENT_ID", "").strip()
    csec = os.getenv("REDDIT_CLIENT_SECRET", "").strip()
    user = os.getenv("REDDIT_USERNAME", "").strip()
    pw   = os.getenv("REDDIT_PASSWORD", "").strip()
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

def _twitter_upload_media(auth, image_url: str):
    """Downloads image_url and uploads it to X's v1.1 media endpoint.
    Returns (media_id_string, None) or (None, error_message)."""
    try:
        img = _req.get(image_url, timeout=15)
        img.raise_for_status()
    except Exception as e:
        return None, f"Could not fetch image_url: {e}"
    try:
        content_type = img.headers.get('Content-Type', 'image/png')
        r = _req.post(
            "https://upload.twitter.com/1.1/media/upload.json",
            auth=auth,
            files={"media": ("poster.png", img.content, content_type)},
            timeout=30,
        )
        if not r.ok:
            # raise_for_status() alone discards X's actual error body — which
            # is where the useful detail is (e.g. which permission/field is
            # wrong). Surface it instead of a bare "400 Bad Request".
            return None, f"HTTP {r.status_code} from media/upload.json: {r.text[:500]}"
        media_id = r.json().get("media_id_string")
        if not media_id:
            return None, f"No media_id_string returned from upload: {r.text[:300]}"
        return media_id, None
    except Exception as e:
        return None, str(e)


def post_twitter(text: str, image_url: str = "") -> dict:
    """Post a tweet via X API v2 using OAuth 1.0a. If image_url is given, the
    image is downloaded and uploaded via X's v1.1 media endpoint first, then
    attached to the tweet — X still requires the older media/upload.json
    endpoint even for v2 tweet creation, there's no v2 equivalent."""
    # .strip() guards against a stray leading/trailing space or newline
    # sneaking in from a copy-paste into Render's env var fields — X's
    # OAuth1 signing is byte-exact, so an invisible extra character there
    # produces exactly this "Bad Authentication data" error with no other
    # symptom.
    api_key    = os.getenv("TWITTER_API_KEY", "").strip()
    api_secret = os.getenv("TWITTER_API_SECRET", "").strip()
    acc_token  = os.getenv("TWITTER_ACCESS_TOKEN", "").strip()
    acc_secret = os.getenv("TWITTER_ACCESS_SECRET", "").strip()
    if not all([api_key, api_secret, acc_token, acc_secret]):
        return {"ok": False, "error": "Twitter credentials not configured"}
    try:
        # OAuth 1.0a via requests-oauthlib (installed as part of authlib deps)
        from requests_oauthlib import OAuth1
        auth = OAuth1(api_key, api_secret, acc_token, acc_secret)

        media_id = None
        if image_url:
            media_id, media_err = _twitter_upload_media(auth, image_url)
            if media_err:
                return {"ok": False, "error": f"Media upload failed: {media_err}"}

        payload = {"text": text[:280]}
        if media_id:
            payload["media"] = {"media_ids": [media_id]}

        r = _req.post(
            "https://api.twitter.com/2/tweets",
            json=payload,
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
    # .strip() guards against a stray trailing newline/space from copying
    # the value into Render's env var field — same issue hit with the
    # Twitter credentials, and it produces the same kind of symptom here:
    # a malformed request URL (the newline shows up as a literal %0A stuck
    # in the middle of it) rather than an auth error.
    token      = os.getenv("INSTAGRAM_ACCESS_TOKEN", "").strip()
    account_id = os.getenv("INSTAGRAM_ACCOUNT_ID", "").strip()
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

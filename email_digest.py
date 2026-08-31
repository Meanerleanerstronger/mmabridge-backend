# ==============================================
# MMA BRIDGE — WEEKLY EMAIL DIGEST
# Uses Resend API to send personalized digests
# Runs every Monday at 09:00 UTC via APScheduler
# ==============================================

import os
import json
import logging
import hmac
import hashlib
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

RESEND_API_KEY = os.environ.get('RESEND_API_KEY', '')
FROM_EMAIL     = 'MMA Bridge <digest@mmabridge.com>'
SITE_URL       = 'https://mmabridge.com'
BACKEND_URL    = 'https://mmabridge.onrender.com'


def _unsub_token(user_id: str) -> str:
    secret = os.environ.get('RESEND_API_KEY', 'unsub-secret')
    return hmac.new(secret.encode(), user_id.encode(), hashlib.sha256).hexdigest()[:32]


def _unsub_url(user_id: str) -> str:
    token = _unsub_token(user_id)
    return f'{BACKEND_URL}/api/unsubscribe?uid={user_id}&token={token}'

# ── Load events from local JSON ───────────────
def _load_events():
    here = Path(__file__).parent
    # Try frontend folder first (dev), then same dir (prod copy)
    for candidate in [
        here.parent / 'MMA Bridge_FRONTEND' / 'events.json',
        here / 'events.json',
    ]:
        if candidate.exists():
            try:
                with open(candidate, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
    return []


def _get_upcoming_events(events, limit=3):
    """
    Was silently returning nothing every single run: isoDate in events.json
    is a bare date ("2026-09-12", no time/offset), so fromisoformat() gave
    back a naive datetime, and comparing that against now(timezone.utc)
    (aware) raises TypeError — caught by the blanket except below, which
    quietly skipped every event, every time. Naive parses now get UTC
    attached explicitly before comparing.
    """
    now = datetime.now(timezone.utc)
    upcoming = []
    for ev in events:
        if ev.get('status') == 'completed':
            continue
        iso = ev.get('isoDate') or ev.get('date') or ''
        try:
            ev_dt = datetime.fromisoformat(iso.replace('Z', '+00:00'))
            if ev_dt.tzinfo is None:
                ev_dt = ev_dt.replace(tzinfo=timezone.utc)
            if ev_dt > now:
                upcoming.append(ev)
        except Exception:
            pass
    upcoming.sort(key=lambda e: e.get('isoDate', ''))
    return upcoming[:limit]


# ── Fetch user stats from Supabase ────────────
def _get_user_stats(sb, user_id):
    """Return dict with pick accuracy and ratings count for the last 30 days."""
    stats = {'picks_correct': 0, 'picks_total': 0, 'ratings_count': 0}
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

        picks_res = sb.table('picks') \
            .select('event_id, fight_key, pick') \
            .eq('user_id', user_id) \
            .neq('fight_key', 'fotn') \
            .gte('created_at', cutoff) \
            .execute()

        ratings_res = sb.table('ratings') \
            .select('id') \
            .eq('user_id', user_id) \
            .gte('created_at', cutoff) \
            .execute()

        stats['picks_total'] = len(picks_res.data or [])
        stats['ratings_count'] = len(ratings_res.data or [])
    except Exception as e:
        logger.debug('[Digest] Stats error for %s: %s', user_id, e)
    return stats


# ── Build HTML email ──────────────────────────
# Branded to match event_email_reminders.py's _wrap_html now — dark header
# band with the wordmark, real button CTAs (table-cell background, not
# CSS border-radius tricks Outlook strips), event cards with poster art
# and the actual main-event matchup instead of a bare date/link.
def _build_html(display_name, upcoming_events, stats, user_id=''):
    name = display_name or 'Fighter'

    event_cards = ''
    for ev in upcoming_events:
        ev_id = ev.get('id', '')
        picks_link = f'{SITE_URL}/picks.html?id={ev_id}' if ev_id else f'{SITE_URL}/events.html'
        meta = ' · '.join(p for p in [ev.get('date', ''), ev.get('venue', ''), ev.get('location', '')] if p)

        main = (ev.get('mainCard') or [{}])[0]
        matchup = f'{main.get("a", "")} vs. {main.get("b", "")}' if main.get('a') and main.get('b') else ''
        weight = main.get('weight', '')

        poster = ev.get('poster', '')
        poster_html = (
            f'<img src="{poster}" width="424" alt="{ev.get("name","")}" '
            f'style="width:100%;max-width:424px;height:auto;display:block;border-radius:8px 8px 0 0;">'
            if poster else ''
        )

        event_cards += f'''
        <tr><td style="padding:0 0 18px;">
          <table width="100%" cellpadding="0" cellspacing="0" style="background:#f9f9f9;border-radius:8px;overflow:hidden;border:1px solid #eeeeee;">
            {f'<tr><td>{poster_html}</td></tr>' if poster_html else ''}
            <tr><td style="padding:16px 18px;">
              <div style="font-size:15px;font-weight:bold;color:#1a1a1a;margin-bottom:3px;">{ev.get("name","")}</div>
              <div style="font-size:12px;color:#888888;margin-bottom:8px;">{meta}</div>
              {f'<div style="font-size:13px;color:#c24a08;font-weight:bold;margin-bottom:12px;">{matchup}{" · " + weight if weight else ""}</div>' if matchup else ''}
              <table cellpadding="0" cellspacing="0"><tr>
                <td style="background:#f2600f;border-radius:6px;">
                  <a href="{picks_link}" style="display:inline-block;padding:10px 20px;font-family:Arial,Helvetica,sans-serif;font-weight:bold;font-size:12px;letter-spacing:0.5px;text-transform:uppercase;color:#0a0a0a;text-decoration:none;">Make Your Picks</a>
                </td>
              </tr></table>
            </td></tr>
          </table>
        </td></tr>'''

    if not event_cards:
        event_cards = '<tr><td style="padding:0 0 18px;color:#888888;font-size:13px;">No upcoming events right now. Check back soon.</td></tr>'

    stats_lines = []
    if stats['picks_total'] > 0:
        stats_lines.append(f'You made {stats["picks_total"]} picks this month.')
    if stats['ratings_count'] > 0:
        stats_lines.append(f'You rated {stats["ratings_count"]} event(s) this month.')
    stats_html = ''.join(f'<p style="margin:0 0 6px;font-size:13px;color:#555555;">{line}</p>' for line in stats_lines)

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Your MMA Bridge weekly update</title>
</head>
<body style="margin:0;padding:0;background:#f4f4f4;font-family:Arial,Helvetica,sans-serif;color:#1a1a1a;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f4;"><tr><td align="center" style="padding:28px 16px;">
  <table width="100%" style="max-width:480px;background:#ffffff;border-radius:10px;overflow:hidden;" cellpadding="0" cellspacing="0">

    <tr><td style="background:#0a0a0a;padding:22px 28px;border-top:3px solid #f2600f;">
      <span style="font-family:Arial,Helvetica,sans-serif;font-weight:bold;font-size:17px;letter-spacing:2px;color:#ffffff;text-transform:uppercase;">MMA BRIDGE</span>
    </td></tr>

    <tr><td style="padding:28px 28px 4px;font-size:15px;line-height:1.65;color:#1a1a1a;">
      <p style="margin:0 0 4px;">Hi {name},</p>
      <p style="margin:0 0 18px;">Here's what's coming up this week.</p>
    </td></tr>

    {f'<tr><td style="padding:0 28px 18px;">{stats_html}</td></tr>' if stats_lines else ''}

    <tr><td style="padding:0 28px 4px;">
      <table width="100%" cellpadding="0" cellspacing="0">
        {event_cards}
      </table>
    </td></tr>

    <tr><td style="padding:4px 28px 4px;">
      <table cellpadding="0" cellspacing="0"><tr>
        <td style="background:#f2600f;border-radius:6px;">
          <a href="{SITE_URL}/events.html" style="display:inline-block;padding:14px 30px;font-family:Arial,Helvetica,sans-serif;font-weight:bold;font-size:14px;letter-spacing:1px;text-transform:uppercase;color:#0a0a0a;text-decoration:none;">View All Events</a>
        </td>
      </tr></table>
    </td></tr>

    <tr><td style="padding:32px 28px 6px;font-size:14px;font-weight:bold;letter-spacing:0.5px;color:#1a1a1a;">
      MMA Bridge
    </td></tr>

    <tr><td style="padding:16px 28px 28px;font-size:11px;color:#999999;border-top:1px solid #eeeeee;margin-top:8px;">
      <div style="padding-top:16px;"><a href="{_unsub_url(user_id) if user_id else (SITE_URL + '/profile.html')}" style="color:#999999;">Unsubscribe from this weekly email</a></div>
    </td></tr>

  </table>
</td></tr></table>
</body>
</html>'''


# ── Send via Resend ───────────────────────────
def _send_email(to_email, subject, html):
    if not RESEND_API_KEY:
        logger.warning('[Digest] RESEND_API_KEY not set — skipping email to %s', to_email)
        return False
    try:
        resp = requests.post(
            'https://api.resend.com/emails',
            headers={
                'Authorization': f'Bearer {RESEND_API_KEY}',
                'Content-Type': 'application/json',
            },
            json={
                'from': FROM_EMAIL,
                'to': [to_email],
                'subject': subject,
                'html': html,
            },
            timeout=10,
        )
        if resp.status_code in (200, 201):
            return True
        logger.warning('[Digest] Resend returned %s for %s: %s', resp.status_code, to_email, resp.text[:200])
        return False
    except Exception as e:
        logger.error('[Digest] Send error for %s: %s', to_email, e)
        return False


# ── Main digest runner ────────────────────────
def send_weekly_digest(sb):
    """
    Fetch all auth users from Supabase and send each a personalized
    weekly digest email. Called by APScheduler every Monday at 09:00 UTC.
    """
    if not RESEND_API_KEY:
        logger.warning('[Digest] RESEND_API_KEY not configured — digest skipped')
        return

    events = _load_events()
    upcoming = _get_upcoming_events(events, limit=3)

    # Fetch all users via Supabase Admin API (requires service role key)
    # NOTE: was reading SUPABASE_KEY here, which doesn't exist as an env var
    # anywhere in this project (database.py, the actual client init, uses
    # SUPABASE_SERVICE_KEY) — so this always hit the "credentials missing"
    # branch below and silently skipped every single weekly run.
    supabase_url    = os.environ.get('SUPABASE_URL', '')
    supabase_key    = os.environ.get('SUPABASE_SERVICE_KEY', '')  # service role key

    if not supabase_url or not supabase_key:
        logger.warning('[Digest] Supabase credentials missing — digest skipped')
        return

    page = 0
    per_page = 100
    sent = 0
    errors = 0

    while True:
        try:
            resp = requests.get(
                f'{supabase_url}/auth/v1/admin/users',
                headers={
                    'apikey': supabase_key,
                    'Authorization': f'Bearer {supabase_key}',
                },
                params={'page': page, 'per_page': per_page},
                timeout=15,
            )
            if not resp.ok:
                logger.error('[Digest] Failed to list users: %s', resp.text[:200])
                break

            data = resp.json()
            users = data.get('users', [])
            if not users:
                break

            for u in users:
                email = u.get('email', '')
                if not email:
                    continue
                uid = u.get('id', '')

                # Check opt-out in profiles table
                try:
                    opt_res = sb.table('profiles').select('email_opt_out').eq('id', uid).single().execute()
                    if (opt_res.data or {}).get('email_opt_out'):
                        logger.debug('[Digest] Skipping opted-out user %s', uid)
                        continue
                except Exception:
                    pass  # if no profile row, send anyway

                display_name = (u.get('user_metadata') or {}).get('display_name') or email.split('@')[0]
                stats        = _get_user_stats(sb, uid)

                week    = datetime.now(timezone.utc).strftime('%b %d')
                subject = f'Your weekly MMA Bridge update ({week})'
                html    = _build_html(display_name, upcoming, stats, user_id=uid)

                if _send_email(email, subject, html):
                    sent += 1
                    logger.info('[Digest] Sent to %s', email)
                else:
                    errors += 1

            if len(users) < per_page:
                break
            page += 1

        except Exception as e:
            logger.error('[Digest] Digest run error: %s', e)
            break

    logger.info('[Digest] Weekly digest complete — sent %d, errors %d', sent, errors)

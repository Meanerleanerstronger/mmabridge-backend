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
    now = datetime.now(timezone.utc)
    upcoming = []
    for ev in events:
        iso = ev.get('isoDate') or ev.get('date') or ''
        try:
            ev_dt = datetime.fromisoformat(iso.replace('Z', '+00:00'))
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
# Plain style — matches event_email_reminders.py's _wrap_html: white
# background, Arial, one muted brand-color link, no gradient buttons or
# logo lockup. Signed off with a plain-text signature, not a graphic.
def _build_html(display_name, upcoming_events, stats, user_id=''):
    name = display_name or 'Fighter'

    upcoming_html = ''
    for ev in upcoming_events:
        date_str = ev.get('date', '')
        loc  = ev.get('location', '')
        venue = ev.get('venue', '')
        ev_id = ev.get('id', '')
        picks_link = f'{SITE_URL}/picks.html?id={ev_id}' if ev_id else f'{SITE_URL}/events.html'
        meta_parts = [p for p in [date_str, loc, venue] if p]
        meta = ' · '.join(meta_parts)
        upcoming_html += f'''
        <tr>
          <td style="padding:10px 0;border-bottom:1px solid #eeeeee;">
            <div style="font-size:14px;font-weight:bold;color:#222222;">{ev.get("name","")}</div>
            <div style="font-size:12px;color:#888888;margin:2px 0 4px;">{meta}</div>
            <a href="{picks_link}" style="color:#b8611e;font-size:13px;">Make your picks</a>
          </td>
        </tr>'''

    if not upcoming_html:
        upcoming_html = '<tr><td style="padding:10px 0;color:#888888;font-size:13px;">No upcoming events right now. Check back soon.</td></tr>'

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
<body style="margin:0;padding:0;background:#ffffff;font-family:Arial,Helvetica,sans-serif;color:#222222;">
<table width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:36px 16px;">
  <table width="100%" style="max-width:480px;" cellpadding="0" cellspacing="0">

    <tr><td style="font-size:15px;line-height:1.6;">
      <p style="margin:0 0 14px;">Hi {name},</p>
      <p style="margin:0 0 18px;">Here's what's coming up on MMA Bridge this week.</p>
    </td></tr>

    {f'<tr><td style="padding:0 0 18px;">{stats_html}</td></tr>' if stats_lines else ''}

    <tr><td style="padding:0 0 8px;font-size:13px;font-weight:bold;color:#222222;">Upcoming events</td></tr>
    <tr><td>
      <table width="100%" cellpadding="0" cellspacing="0">
        {upcoming_html}
      </table>
    </td></tr>

    <tr><td style="padding:20px 0 0;font-size:15px;">
      <a href="{SITE_URL}/events.html" style="color:#b8611e;">View all events</a>
    </td></tr>

    <tr><td style="padding-top:28px;font-size:15px;color:#222222;">
      MMA Bridge
    </td></tr>

    <tr><td style="padding-top:28px;font-size:12px;color:#999999;">
      <a href="{_unsub_url(user_id) if user_id else (SITE_URL + '/profile.html')}" style="color:#999999;">Unsubscribe from this weekly email</a>
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

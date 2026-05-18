# ==============================================
# MMA BRIDGE — WEEKLY EMAIL DIGEST
# Uses Resend API to send personalized digests
# Runs every Monday at 09:00 UTC via APScheduler
# ==============================================

import os
import json
import logging
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

RESEND_API_KEY = os.environ.get('RESEND_API_KEY', '')
FROM_EMAIL     = 'MMA Bridge <digest@mmabridge.com>'
SITE_URL       = 'https://mmabridge.com'

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
def _build_html(display_name, upcoming_events, stats):
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
          <td style="padding:12px 0;border-bottom:1px solid #1e1e26;">
            <div style="font-family:Montserrat,sans-serif;font-size:0.85rem;font-weight:700;color:#fff;margin-bottom:3px;">{ev.get("name","")}</div>
            <div style="font-size:0.72rem;color:rgba(255,255,255,0.45);margin-bottom:8px;">{meta}</div>
            <a href="{picks_link}" style="display:inline-block;padding:6px 14px;background:rgba(200,150,12,0.15);border:1px solid rgba(200,150,12,0.4);color:#c8960c;font-family:Montserrat,sans-serif;font-size:0.68rem;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;text-decoration:none;border-radius:5px;">Make Your Picks</a>
          </td>
        </tr>'''

    if not upcoming_html:
        upcoming_html = '<tr><td style="padding:12px 0;color:rgba(255,255,255,0.4);font-size:0.8rem;">No upcoming events right now — check back soon.</td></tr>'

    picks_line = ''
    if stats['picks_total'] > 0:
        picks_line = f'<div style="margin-top:6px;font-size:0.78rem;color:rgba(255,255,255,0.55);">You made <strong style="color:#c8960c;">{stats["picks_total"]}</strong> picks this month.</div>'

    ratings_line = ''
    if stats['ratings_count'] > 0:
        ratings_line = f'<div style="margin-top:4px;font-size:0.78rem;color:rgba(255,255,255,0.55);">You rated <strong style="color:#c8960c;">{stats["ratings_count"]}</strong> event(s) this month.</div>'

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Your MMA Bridge Weekly Digest</title>
</head>
<body style="margin:0;padding:0;background:#0d0d10;font-family:Inter,Helvetica,Arial,sans-serif;color:#fff;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#0d0d10;padding:40px 16px;">
  <tr><td align="center">
  <table width="100%" style="max-width:560px;" cellpadding="0" cellspacing="0">

    <!-- Header -->
    <tr><td style="padding:0 0 32px;">
      <div style="font-family:Montserrat,sans-serif;font-size:1.35rem;font-weight:900;letter-spacing:0.12em;text-transform:uppercase;color:#fff;">
        MMA<span style="color:#c8960c;">BRIDGE</span>
      </div>
      <div style="font-size:0.68rem;letter-spacing:0.15em;text-transform:uppercase;color:rgba(255,255,255,0.35);margin-top:3px;">Weekly Digest</div>
    </td></tr>

    <!-- Greeting -->
    <tr><td style="padding:0 0 24px;">
      <div style="font-family:Montserrat,sans-serif;font-size:1.1rem;font-weight:700;">Hey {name},</div>
      <div style="font-size:0.82rem;color:rgba(255,255,255,0.6);margin-top:8px;line-height:1.6;">Here's your weekly MMA Bridge update — upcoming events, your stats, and more.</div>
    </td></tr>

    <!-- Stats (only if any activity) -->
    {f"""<tr><td style="background:#13131a;border:1px solid #1e1e26;border-radius:10px;padding:18px 20px;margin-bottom:24px;">
      <div style="font-family:Montserrat,sans-serif;font-size:0.7rem;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;color:rgba(255,255,255,0.35);margin-bottom:8px;">Your Activity (last 30 days)</div>
      {picks_line}{ratings_line}
    </td></tr><tr><td style="padding:16px 0 0;"></td></tr>""" if (stats["picks_total"] or stats["ratings_count"]) else ""}

    <!-- Upcoming Events -->
    <tr><td style="background:#13131a;border:1px solid #1e1e26;border-radius:10px;padding:18px 20px;">
      <div style="font-family:Montserrat,sans-serif;font-size:0.7rem;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;color:rgba(255,255,255,0.35);margin-bottom:4px;">Upcoming Events</div>
      <table width="100%" cellpadding="0" cellspacing="0">
        {upcoming_html}
      </table>
    </td></tr>

    <!-- CTA -->
    <tr><td style="padding:28px 0 0;text-align:center;">
      <a href="{SITE_URL}/events.html" style="display:inline-block;padding:12px 28px;background:linear-gradient(135deg,#c8960c,#a87800);color:#0d0d10;font-family:Montserrat,sans-serif;font-size:0.75rem;font-weight:800;letter-spacing:0.1em;text-transform:uppercase;text-decoration:none;border-radius:7px;">View All Events</a>
    </td></tr>

    <!-- Footer -->
    <tr><td style="padding:32px 0 0;text-align:center;font-size:0.65rem;color:rgba(255,255,255,0.2);line-height:1.7;">
      MMA Bridge &nbsp;·&nbsp; <a href="{SITE_URL}" style="color:rgba(255,255,255,0.2);text-decoration:none;">mmabridge.com</a><br>
      <a href="{SITE_URL}/profile.html" style="color:rgba(255,255,255,0.2);text-decoration:none;">Manage notification preferences</a>
    </td></tr>

  </table>
  </td></tr>
</table>
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
    supabase_url    = os.environ.get('SUPABASE_URL', '')
    supabase_key    = os.environ.get('SUPABASE_KEY', '')  # service role key

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
                uid          = u.get('id', '')
                display_name = (u.get('user_metadata') or {}).get('display_name') or email.split('@')[0]
                stats        = _get_user_stats(sb, uid)

                week = datetime.now(timezone.utc).strftime('%b %d')
                subject = f'MMA Bridge — Your weekly update ({week})'
                html    = _build_html(display_name, upcoming, stats)

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

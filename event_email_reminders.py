# ==============================================
# MMA BRIDGE — EVENT-TRIGGERED EMAIL REMINDERS
# "Don't forget to make picks" (before an event locks)
# "Don't forget to review the card" (after an event ends)
# Uses the same Resend setup as email_digest.py.
# ==============================================

import os
import json
import logging
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

RESEND_API_KEY = os.environ.get('RESEND_API_KEY', '')
FROM_EMAIL     = 'MMA Bridge <reminders@mmabridge.com>'
SITE_URL       = 'https://mmabridge.com'

# How long after we could first send a reminder do we give up (covers a
# scheduler that's down for a while, or a run that fires late) — without
# this, an event whose lock time passed 3 days ago would still generate
# "don't forget to pick" emails forever every time the job runs.
PICK_REMINDER_WINDOW_HOURS   = (20, 30)   # send once lock time is 20-30h away
REVIEW_REMINDER_WINDOW_HOURS = (6, 30)    # send once event is 6-30h in the past


def _load_events():
    here = Path(__file__).parent
    for candidate in [
        here.parent / 'MMA Bridge_FRONTEND' / 'events.json',
        here / 'events.json',
    ]:
        if candidate.exists():
            try:
                with open(candidate, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                continue
    return []


def _event_lock_time(ev):
    """Prefer start_time (exact); fall back to isoDate at a nominal 20:00 UTC."""
    st = ev.get('start_time')
    if st:
        try:
            return datetime.fromisoformat(st.replace('Z', '+00:00'))
        except Exception:
            pass
    iso = ev.get('isoDate')
    if iso:
        try:
            return datetime.fromisoformat(iso + 'T20:00:00+00:00')
        except Exception:
            pass
    return None


def _send_email(to_email, subject, html):
    if not RESEND_API_KEY:
        logger.warning('[EventReminders] RESEND_API_KEY not set — skipping email to %s', to_email)
        return False
    try:
        resp = requests.post(
            'https://api.resend.com/emails',
            headers={'Authorization': f'Bearer {RESEND_API_KEY}', 'Content-Type': 'application/json'},
            json={'from': FROM_EMAIL, 'to': [to_email], 'subject': subject, 'html': html},
            timeout=10,
        )
        if resp.status_code in (200, 201):
            return True
        logger.warning('[EventReminders] Resend returned %s for %s: %s', resp.status_code, to_email, resp.text[:200])
        return False
    except Exception as e:
        logger.error('[EventReminders] Send error for %s: %s', to_email, e)
        return False


def _list_all_users(sb):
    """Yields {id, email, display_name} for every auth user, paginated."""
    supabase_url = os.environ.get('SUPABASE_URL', '')
    supabase_key = os.environ.get('SUPABASE_SERVICE_KEY', '')
    if not supabase_url or not supabase_key:
        logger.warning('[EventReminders] Supabase credentials missing — cannot list users')
        return

    page, per_page = 0, 100
    while True:
        try:
            resp = requests.get(
                f'{supabase_url}/auth/v1/admin/users',
                headers={'apikey': supabase_key, 'Authorization': f'Bearer {supabase_key}'},
                params={'page': page, 'per_page': per_page},
                timeout=15,
            )
            if not resp.ok:
                logger.error('[EventReminders] Failed to list users: %s', resp.text[:200])
                return
            users = resp.json().get('users', [])
            if not users:
                return
            for u in users:
                email = u.get('email', '')
                if not email:
                    continue
                yield {
                    'id': u.get('id', ''),
                    'email': email,
                    'display_name': (u.get('user_metadata') or {}).get('display_name') or email.split('@')[0],
                }
            if len(users) < per_page:
                return
            page += 1
        except Exception as e:
            logger.error('[EventReminders] List users error: %s', e)
            return


def _is_opted_out(sb, user_id):
    try:
        res = sb.table('profiles').select('email_opt_out').eq('id', user_id).single().execute()
        return bool((res.data or {}).get('email_opt_out'))
    except Exception:
        return False  # no profile row yet — send anyway, matches email_digest.py's behavior


def _already_sent(sb, user_id, event_id, reminder_type):
    try:
        res = (sb.table('email_reminders_sent')
               .select('id').eq('user_id', user_id).eq('event_id', event_id)
               .eq('reminder_type', reminder_type).limit(1).execute())
        return bool(res.data)
    except Exception as e:
        # If the tracking table doesn't exist yet, fail closed (skip sending)
        # rather than risk spamming everyone every run with no dedupe at all.
        logger.error('[EventReminders] email_reminders_sent check failed (table missing?): %s', e)
        return True


def _mark_sent(sb, user_id, event_id, reminder_type):
    try:
        sb.table('email_reminders_sent').insert({
            'user_id': user_id, 'event_id': event_id, 'reminder_type': reminder_type,
        }).execute()
    except Exception as e:
        logger.warning('[EventReminders] Could not record sent reminder: %s', e)


def _wrap_html(title, paragraphs, cta_text, cta_url):
    """Plain, simple, classic layout — no branding lockup, no gradient
    button, no color beyond a single muted link. Reads like a normal email
    from a person, not a marketing template."""
    body = ''.join(f'<p style="margin:0 0 14px;">{p}</p>' for p in paragraphs)
    return f'''<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0"><title>{title}</title></head>
<body style="margin:0;padding:0;background:#ffffff;font-family:Arial,Helvetica,sans-serif;color:#222222;">
<table width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:36px 16px;">
  <table width="100%" style="max-width:480px;" cellpadding="0" cellspacing="0">
    <tr><td style="font-size:15px;line-height:1.6;">
      {body}
      <p style="margin:20px 0 0;"><a href="{cta_url}" style="color:#b8611e;">{cta_text}</a></p>
    </td></tr>
    <tr><td style="padding-top:36px;font-size:12px;color:#999999;">
      MMA Bridge — <a href="{SITE_URL}/profile.html" style="color:#999999;">manage email preferences</a>
    </td></tr>
  </table>
</td></tr></table>
</body></html>'''


# ── "Don't forget to make picks" ──────────────
def send_pick_reminder_emails(sb):
    """
    For every upcoming event whose lock time is 20-30h away, email every
    user who has NOT yet submitted any picks for it. Run this a few times
    a day (e.g. every 4h) — the wide window plus the sent-tracking table
    means it's safe to run often without double-sending.
    """
    if not RESEND_API_KEY:
        logger.warning('[EventReminders] RESEND_API_KEY not configured — pick reminders skipped')
        return

    events = _load_events()
    now = datetime.now(timezone.utc)
    lo, hi = PICK_REMINDER_WINDOW_HOURS

    targets = []
    for ev in events:
        if ev.get('status') == 'completed':
            continue
        lock = _event_lock_time(ev)
        if not lock:
            continue
        hrs_away = (lock - now).total_seconds() / 3600
        if lo <= hrs_away <= hi:
            targets.append(ev)

    if not targets:
        return

    sent, errors = 0, 0
    for ev in targets:
        ev_id = ev.get('id', '')
        if not ev_id:
            continue

        try:
            picked_res = sb.table('picks').select('user_id').eq('event_id', ev_id).execute()
            picked_user_ids = {row['user_id'] for row in (picked_res.data or [])}
        except Exception as e:
            logger.error('[EventReminders] Failed to load picks for %s: %s', ev_id, e)
            continue

        for user in _list_all_users(sb):
            if user['id'] in picked_user_ids:
                continue  # already picked this event
            if _is_opted_out(sb, user['id']):
                continue
            if _already_sent(sb, user['id'], ev_id, 'pick_reminder'):
                continue

            picks_link = f"{SITE_URL}/picks.html?id={ev_id}"
            html = _wrap_html(
                'Make your picks',
                [
                    f'Hi {user["display_name"]},',
                    f'{ev.get("name","")} is coming up soon and picks lock in about a day. '
                    f'Looks like you haven\'t made yours yet.',
                ],
                'Make your picks', picks_link,
            )
            if _send_email(user['email'], f'Make your picks — {ev.get("name","")}', html):
                _mark_sent(sb, user['id'], ev_id, 'pick_reminder')
                sent += 1
            else:
                errors += 1

    logger.info('[EventReminders] Pick reminders — sent %d, errors %d', sent, errors)


# ── "Don't forget to review the card" ─────────
def send_review_reminder_emails(sb):
    """
    For every event that ended 6-30h ago, email every user who made at
    least one pick for it but hasn't left a rating/review yet.
    """
    if not RESEND_API_KEY:
        logger.warning('[EventReminders] RESEND_API_KEY not configured — review reminders skipped')
        return

    events = _load_events()
    now = datetime.now(timezone.utc)
    lo, hi = REVIEW_REMINDER_WINDOW_HOURS

    targets = []
    for ev in events:
        lock = _event_lock_time(ev)
        if not lock:
            continue
        hrs_since = (now - lock).total_seconds() / 3600
        if lo <= hrs_since <= hi:
            targets.append(ev)

    if not targets:
        return

    sent, errors = 0, 0
    for ev in targets:
        ev_id = ev.get('id', '')
        if not ev_id:
            continue

        try:
            picked_res  = sb.table('picks').select('user_id').eq('event_id', ev_id).execute()
            picked_user_ids = {row['user_id'] for row in (picked_res.data or [])}
            rated_res   = sb.table('ratings').select('user_id').eq('event_id', ev_id).execute()
            rated_user_ids  = {row['user_id'] for row in (rated_res.data or [])}
        except Exception as e:
            logger.error('[EventReminders] Failed to load picks/ratings for %s: %s', ev_id, e)
            continue

        pending = picked_user_ids - rated_user_ids
        if not pending:
            continue

        for user in _list_all_users(sb):
            if user['id'] not in pending:
                continue
            if _is_opted_out(sb, user['id']):
                continue
            if _already_sent(sb, user['id'], ev_id, 'review_reminder'):
                continue

            review_link = f"{SITE_URL}/event-review.html?id={ev_id}"
            html = _wrap_html(
                'Review the card',
                [
                    f'Hi {user["display_name"]},',
                    f'{ev.get("name","")} wrapped up. See how your picks did and rate the card '
                    f'if you get a chance.',
                ],
                'Review the card', review_link,
            )
            if _send_email(user['email'], f'How did your picks do? — {ev.get("name","")}', html):
                _mark_sent(sb, user['id'], ev_id, 'review_reminder')
                sent += 1
            else:
                errors += 1

    logger.info('[EventReminders] Review reminders — sent %d, errors %d', sent, errors)

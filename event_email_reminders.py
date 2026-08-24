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
PICK_REMINDER_WINDOW_HOURS = (20, 30)   # send once lock time is 20-30h away — "a day before"

# Review reminder used to gate purely on hours-since-start-time (6-30h),
# which meant "right after the event ends" could fire anywhere from 6 to 30
# hours late relative to when the card actually finished, since a live card
# runs several hours past its start time either way. Now gated on the
# event's own status flipping to 'completed' instead — ufc-sync.js grades
# every fight and flips that within minutes of the last result landing (it
# runs every 5 min), so "completed" is a genuinely accurate "the event just
# ended" signal, not a guess. This window is just a safety bound so a
# years-old completed event can't retroactively start emailing people if
# this logic ever runs against stale data — the real gate is the status
# check in send_review_reminder_emails below.
REVIEW_REMINDER_MAX_AGE_HOURS = 72


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


def _wrap_html(title, paragraphs, cta_text, cta_url, secondary_label=None, secondary_url=None):
    """Bulletproof table-based layout (button as a colored <td>, not
    border-radius/CSS-background tricks that Outlook/Windows Mail strip) —
    dark header band with the wordmark, a real button CTA instead of a bare
    text link, and an optional secondary short link (mmabridge.com/events,
    mmabridge.com/review) directly under it so there's always a second,
    obviously-clickable way in even if the button itself doesn't render.
    """
    body = ''.join(f'<p style="margin:0 0 16px;">{p}</p>' for p in paragraphs)
    secondary_html = ''
    if secondary_label and secondary_url:
        secondary_html = f'''
      <p style="margin:14px 0 0;font-size:13px;">
        <a href="{secondary_url}" style="color:#b8611e;text-decoration:none;">{secondary_label}</a>
      </p>'''
    return f'''<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0"><title>{title}</title></head>
<body style="margin:0;padding:0;background:#f4f4f4;font-family:Arial,Helvetica,sans-serif;color:#1a1a1a;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f4;"><tr><td align="center" style="padding:28px 16px;">
  <table width="100%" style="max-width:480px;background:#ffffff;border-radius:10px;overflow:hidden;" cellpadding="0" cellspacing="0">

    <tr><td style="background:#0a0a0a;padding:22px 28px;border-top:3px solid #ff8a3d;">
      <span style="font-family:Arial,Helvetica,sans-serif;font-weight:bold;font-size:17px;letter-spacing:2px;color:#ffffff;text-transform:uppercase;">MMA BRIDGE</span>
    </td></tr>

    <tr><td style="padding:32px 28px 8px;font-size:15px;line-height:1.65;color:#1a1a1a;">
      {body}
    </td></tr>

    <tr><td style="padding:8px 28px 4px;">
      <table cellpadding="0" cellspacing="0"><tr>
        <td style="background:#ff8a3d;border-radius:6px;">
          <a href="{cta_url}" style="display:inline-block;padding:14px 30px;font-family:Arial,Helvetica,sans-serif;font-weight:bold;font-size:14px;letter-spacing:1px;text-transform:uppercase;color:#0a0a0a;text-decoration:none;">{cta_text}</a>
        </td>
      </tr></table>
      {secondary_html}
    </td></tr>

    <tr><td style="padding:32px 28px 6px;font-size:14px;font-weight:bold;letter-spacing:0.5px;color:#1a1a1a;">
      MMA Bridge
    </td></tr>

    <tr><td style="padding:16px 28px 28px;font-size:11px;color:#999999;border-top:1px solid #eeeeee;margin-top:8px;">
      <div style="padding-top:16px;"><a href="{SITE_URL}/profile.html" style="color:#999999;">manage email preferences</a></div>
    </td></tr>

  </table>
</td></tr></table>
</body></html>'''


# ── "Don't forget to make picks" ──────────────
def send_pick_reminder_emails(sb):
    """
    For every upcoming event whose lock time is 20-30h away ("a day
    before"), email every user who has NOT yet submitted any picks for it.
    Runs every 30 min — the wide window plus the sent-tracking table means
    it's safe to run this often without double-sending.
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
                    f'{ev.get("name","")} locks in about a day. You haven\'t made your picks yet '
                    f'and the board closes the moment the first fight starts. Get your picks in now.',
                ],
                'Make Your Picks', picks_link,
                'mmabridge.com/events', f'{SITE_URL}/events.html',
            )
            if _send_email(user['email'], f'Don\'t forget to make your picks for {ev.get("name","")}', html):
                _mark_sent(sb, user['id'], ev_id, 'pick_reminder')
                sent += 1
            else:
                errors += 1

    logger.info('[EventReminders] Pick reminders — sent %d, errors %d', sent, errors)


# ── "Don't forget to review the card" ─────────
def send_review_reminder_emails(sb):
    """
    For every event ufc-sync.js has actually marked 'completed' (every
    fight graded — happens within minutes of the last result, not a fixed
    guess), email every user who made at least one pick for it but hasn't
    left a rating/review yet. The sent-tracking table means this only ever
    fires once per user per event regardless of how often the job runs.
    """
    if not RESEND_API_KEY:
        logger.warning('[EventReminders] RESEND_API_KEY not configured — review reminders skipped')
        return

    events = _load_events()
    now = datetime.now(timezone.utc)

    targets = []
    for ev in events:
        if ev.get('status') != 'completed':
            continue
        lock = _event_lock_time(ev)
        if not lock:
            continue
        hrs_since = (now - lock).total_seconds() / 3600
        if 0 <= hrs_since <= REVIEW_REMINDER_MAX_AGE_HOURS:
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
                    f'{ev.get("name","")} is in the books. See exactly how your picks scored '
                    f'and rate the card while it\'s still fresh.',
                ],
                'Review The Card', review_link,
                'mmabridge.com/review', f'{SITE_URL}/review',
            )
            if _send_email(user['email'], f'Don\'t forget to review the {ev.get("name","")} card', html):
                _mark_sent(sb, user['id'], ev_id, 'review_reminder')
                sent += 1
            else:
                errors += 1

    logger.info('[EventReminders] Review reminders — sent %d, errors %d', sent, errors)

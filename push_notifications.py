# ==============================================
# MMA BRIDGE — BROWSER PUSH NOTIFICATIONS
# Handles: send push, starred event cron alerts,
#          fav fighter announcement alerts
# ==============================================

import os
import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

from pywebpush import webpush, WebPushException

logger = logging.getLogger(__name__)

# ── VAPID config ──────────────────────────────
VAPID_PUBLIC_KEY = 'BMCcRUYcboxYuMQd4peCA_etuBlfgeN8C9o26rVxfpUUxov_1ICWJOm5AiLHmmqJlNjNtoQSsVj0rPayM35H-7c'
VAPID_EMAIL      = os.getenv('VAPID_EMAIL', 'mailto:admin@mmabridge.com')

# Private key: prefer env var (Render), fall back to local PEM file (dev)
_HERE            = Path(__file__).parent
_LOCAL_PEM       = _HERE / 'vapid_private.pem'
_pem_from_env    = os.getenv('VAPID_PRIVATE_PEM', '').replace('\\n', '\n').strip()

if _pem_from_env:
    # Write env var contents to a temp file so pywebpush can read it
    import tempfile
    _tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.pem', mode='w')
    _tmp.write(_pem_from_env)
    _tmp.close()
    VAPID_PRIVATE_KEY_PATH = _tmp.name
elif _LOCAL_PEM.exists():
    VAPID_PRIVATE_KEY_PATH = str(_LOCAL_PEM)
else:
    VAPID_PRIVATE_KEY_PATH = None
    logger.warning('[Push] No VAPID private key found — push notifications disabled')


# ── Core send function ────────────────────────
def send_push(endpoint: str, p256dh: str, auth_key: str, payload: dict) -> str:
    """
    Send a single push notification.
    Returns: 'ok' | 'expired' | 'error' | 'disabled'
    """
    if not VAPID_PRIVATE_KEY_PATH:
        logger.warning('[Push] send_push called but no VAPID key configured')
        return 'disabled'
    try:
        webpush(
            subscription_info={
                'endpoint': endpoint,
                'keys': {'p256dh': p256dh, 'auth': auth_key},
            },
            data=json.dumps(payload),
            vapid_private_key=VAPID_PRIVATE_KEY_PATH,
            vapid_claims={'sub': VAPID_EMAIL},
        )
        return 'ok'
    except WebPushException as e:
        status = getattr(e.response, 'status_code', None) if e.response else None
        if status in (404, 410):
            return 'expired'    # subscription gone — caller should delete it
        logger.warning('Push failed status=%s endpoint=...%s', status, endpoint[-20:])
        return 'error'
    except Exception as e:
        logger.warning('Push unexpected error: %s', e)
        return 'error'


# ── Starred event cron job ───────────────────
def check_starred_events(sb):
    """
    Call daily: sends 1-week and 1-day-before notifications
    for all starred events that haven't been notified yet.
    """
    today = datetime.now(timezone.utc).date()
    iso_7 = str(today + timedelta(days=7))
    iso_1 = str(today + timedelta(days=1))

    for (iso_target, flag_col, title_tmpl, body_tmpl, tag_prefix) in [
        (
            iso_7, 'notified_week',
            '{name} — 1 week away',
            'Lock in your picks before the event. One week to go!',
            'ev-week',
        ),
        (
            iso_1, 'notified_day',
            '{name} is TOMORROW',
            'Event day is almost here. Check your picks and enjoy the fights!',
            'ev-day',
        ),
    ]:
        try:
            rows = (
                sb.table('starred_events')
                .select('id, browser_id, event_id, event_name, push_subscriptions(endpoint, p256dh, auth)')
                .eq('event_iso_date', iso_target)
                .eq(flag_col, False)
                .execute()
                .data or []
            )
        except Exception as e:
            logger.error('check_starred_events query failed: %s', e)
            continue

        for row in rows:
            sub = (row.get('push_subscriptions') or [None])[0]
            if not sub:
                continue

            result = send_push(
                endpoint=sub['endpoint'],
                p256dh=sub['p256dh'],
                auth_key=sub['auth'],
                payload={
                    'title': title_tmpl.format(name=row['event_name']),
                    'body':  body_tmpl,
                    'url':   f"/picks.html?id={row['event_id']}",
                    'tag':   f"{tag_prefix}-{row['event_id']}",
                    'requireInteraction': (tag_prefix == 'ev-day'),
                },
            )

            if result == 'ok':
                sb.table('starred_events').update({flag_col: True}).eq('id', row['id']).execute()
            elif result == 'expired':
                # Stale subscription — remove it so we don't keep trying
                sb.table('push_subscriptions').delete().eq('browser_id', row['browser_id']).execute()


# ── Fav fighter announcement ─────────────────
def announce_fighters(sb, fighter_names: list, event_name: str, event_id: str):
    """
    Call when you add a new event.
    Sends a push to every subscriber whose fav fighter list
    contains one of the announced fighters.
    fighter_names: list of strings from the new event card
                   e.g. ["Jon Jones", "Stipe Miocic", "Islam Makhachev"]
    """
    if not fighter_names:
        return

    try:
        subs = (
            sb.table('push_subscriptions')
            .select('browser_id, endpoint, p256dh, auth, fav_fighter_names')
            .not_.is_('fav_fighter_ids', 'null')
            .execute()
            .data or []
        )
    except Exception as e:
        logger.error('announce_fighters query failed: %s', e)
        return

    announced_lower = [n.lower() for n in fighter_names]

    for sub in subs:
        try:
            fav_names = json.loads(sub.get('fav_fighter_names') or '[]')
        except Exception:
            fav_names = []

        matched = next(
            (fav for fav in fav_names
             if any(fav.lower() in ann or ann in fav.lower() for ann in announced_lower)),
            None,
        )
        if not matched:
            continue

        result = send_push(
            endpoint=sub['endpoint'],
            p256dh=sub['p256dh'],
            auth_key=sub['auth'],
            payload={
                'title': f'{matched} just got announced!',
                'body':  f'{matched} is fighting at {event_name}. Make your pick now.',
                'url':   f'/picks.html?id={event_id}',
                'tag':   f"fav-{sub['browser_id']}-{event_id}",
            },
        )

        if result == 'expired':
            sb.table('push_subscriptions').delete().eq('browser_id', sub['browser_id']).execute()


# ── APScheduler setup ─────────────────────────
def start_scheduler(sb):
    """
    Start background daily cron jobs.
    Call once at Flask app startup.
    """
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger

        scheduler = BackgroundScheduler(timezone='UTC')

        # Daily at 08:00 UTC — check starred events
        scheduler.add_job(
            func=lambda: check_starred_events(sb),
            trigger=CronTrigger(hour=8, minute=0),
            id='starred_event_check',
            replace_existing=True,
        )

        # Weekly Monday at 09:00 UTC — email digest
        try:
            from email_digest import send_weekly_digest
            scheduler.add_job(
                func=lambda: send_weekly_digest(sb),
                trigger=CronTrigger(day_of_week='mon', hour=9, minute=0),
                id='weekly_email_digest',
                replace_existing=True,
            )
            logger.info('[Push] Weekly email digest scheduled — Mondays 09:00 UTC')
        except Exception as _digest_err:
            logger.warning('[Push] Email digest job not loaded: %s', _digest_err)

        scheduler.start()
        logger.info('[Push] Scheduler started — daily check at 08:00 UTC')
        return scheduler
    except Exception as e:
        logger.error('[Push] Scheduler failed to start: %s', e)
        return None

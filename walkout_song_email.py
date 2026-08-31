# ==============================================
# MMA BRIDGE — WALKOUT SONG INVITE EMAIL
# One-time "you haven't picked a walkout song yet" nudge — the email
# counterpart to the popup modal in site-nudges.js. Uses the same Resend
# setup as email_digest.py.
# ==============================================

import os
import logging

from event_email_reminders import (
    _send_email as _send,
    _wrap_html,
    _list_all_users,
    _is_opted_out,
    _already_sent,
    _mark_sent,
    SITE_URL,
)

logger = logging.getLogger(__name__)

RESEND_API_KEY = os.environ.get('RESEND_API_KEY', '')

# Fixed pseudo event_id — this isn't tied to a UFC event, just reusing the
# same email_reminders_sent dedupe table every other email in this project
# uses, so it only ever sends once per user regardless of how often the
# scheduler checks.
_WALKOUT_KEY = 'walkout-song-invite'


def send_walkout_song_invite_emails(sb):
    """
    One-time invite, not a recurring nag: every non-opted-out user with no
    walkout_song set on their profile gets this exactly once, ever. Meant
    to run on a low-frequency schedule (daily is plenty) so new signups
    get caught within a day without spamming existing users who've simply
    chosen not to set one.
    """
    if not RESEND_API_KEY:
        logger.warning('[WalkoutEmail] RESEND_API_KEY not configured — walkout invite skipped')
        return

    try:
        profiles = (sb.table('profiles')
                    .select('id, walkout_song')
                    .execute().data or [])
    except Exception as e:
        logger.error('[WalkoutEmail] Failed to load profiles: %s', e)
        return

    has_song = {p['id'] for p in profiles if p.get('walkout_song')}

    sent, errors = 0, 0
    for user in _list_all_users(sb):
        if user['id'] in has_song:
            continue
        if _is_opted_out(sb, user['id']):
            continue
        if _already_sent(sb, user['id'], _WALKOUT_KEY, 'walkout_invite'):
            continue

        pick_link = f'{SITE_URL}/profile.html?walkout=1'
        html = _wrap_html(
            'Pick your walkout song',
            [
                f'Hi {user["display_name"]},',
                'Every fighter needs an entrance. Set the track that plays in your head '
                'when you walk out to the octagon — it shows right on your MMA Bridge profile.',
            ],
            'Choose Your Song', pick_link,
            'mmabridge.com/profile', f'{SITE_URL}/profile.html',
        )
        if _send(user['email'], 'Pick your walkout song 🎵', html):
            _mark_sent(sb, user['id'], _WALKOUT_KEY, 'walkout_invite')
            sent += 1
        else:
            errors += 1

    logger.info('[WalkoutEmail] Walkout song invite — sent %d, errors %d', sent, errors)

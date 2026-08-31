# ==============================================
# MMA BRIDGE — FAVORITE FIGHTER EMAIL ALERT
# "Your favorite fighter just got announced" — the email counterpart to
# push_notifications.py's announce_fighters(). Fired from the same
# /api/push/announce-fighters call ufc-sync.js / ufc-event-card-sync.js
# already make whenever new fight-card data lands, so this fires "when
# it happens" rather than on a fixed schedule like the other emails in
# this project.
# ==============================================

import os
import json
import logging
from pathlib import Path

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


def _load_fighter_names():
    """fighter id -> display name, same dual-path convention every other
    loader in this project uses (dev checks the sibling frontend folder,
    prod checks its own copy)."""
    here = Path(__file__).parent
    for candidate in [
        here.parent / 'MMA Bridge_FRONTEND' / 'data' / 'fighters.json',
        here / 'fighters.json',
    ]:
        if candidate.exists():
            try:
                with open(candidate, 'r', encoding='utf-8') as f:
                    return {row.get('id', ''): row.get('name', '') for row in json.load(f)}
            except Exception:
                continue
    return {}


def send_favorite_fighter_emails(sb, fighter_names: list, event_name: str, event_id: str):
    """
    For every user whose profiles.fav_fighters (a list of fighter IDs)
    resolves to a name matching one of the just-announced fighter_names,
    email them once. Matching logic mirrors announce_fighters() in
    push_notifications.py exactly — substring match either direction,
    case-insensitive — just resolved through fighters.json instead of the
    push_subscriptions table's own cached fav_fighter_names column, since
    profiles only stores fighter IDs.
    """
    if not RESEND_API_KEY or not fighter_names or not event_id:
        return

    id_to_name = _load_fighter_names()
    announced_lower = [n.lower() for n in fighter_names]

    try:
        profiles = (sb.table('profiles')
                    .select('id, fav_fighters, display_name')
                    .not_.is_('fav_fighters', 'null')
                    .execute().data or [])
    except Exception as e:
        logger.error('[FavFighterEmail] Failed to load profiles: %s', e)
        return

    if not profiles:
        return

    # One pass to resolve every candidate's matched fighter name, so we
    # only pay for _list_all_users' pagination once below.
    matches = {}  # user_id -> matched fighter display name
    for p in profiles:
        uid = p.get('id')
        if not uid:
            continue
        raw = p.get('fav_fighters')
        try:
            fav_ids = json.loads(raw) if isinstance(raw, str) else (raw or [])
        except Exception:
            fav_ids = []

        matched = next(
            (id_to_name[fid] for fid in fav_ids
             if id_to_name.get(fid) and any(
                 id_to_name[fid].lower() in ann or ann in id_to_name[fid].lower()
                 for ann in announced_lower
             )),
            None,
        )
        if matched:
            matches[uid] = matched

    if not matches:
        return

    sent, errors = 0, 0
    for user in _list_all_users(sb):
        matched = matches.get(user['id'])
        if not matched:
            continue
        if _is_opted_out(sb, user['id']):
            continue
        if _already_sent(sb, user['id'], event_id, 'fav_fighter_announced'):
            continue

        picks_link = f'{SITE_URL}/picks.html?id={event_id}'
        html = _wrap_html(
            f'{matched} is fighting',
            [
                f'Hi {user["display_name"]},',
                f'{matched} just got announced for {event_name}. Make your pick before it locks.',
            ],
            'Make Your Pick', picks_link,
            'mmabridge.com/events', f'{SITE_URL}/events.html',
        )
        if _send(user['email'], f'{matched} just got announced for {event_name}', html):
            _mark_sent(sb, user['id'], event_id, 'fav_fighter_announced')
            sent += 1
        else:
            errors += 1

    logger.info('[FavFighterEmail] Fav fighter announce — sent %d, errors %d', sent, errors)

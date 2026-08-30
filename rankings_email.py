# ==============================================
# MMA BRIDGE — RANKINGS UPDATE EMAIL
# "Rankings just moved" — sent after rankings-sync.js (runs Mondays
# 06:00 UTC via GitHub Actions, scrapes UFC.com) commits a rankings.json
# with actual movement in it, i.e. after a fight card actually shook up
# a division. Uses the same Resend setup as email_digest.py.
# ==============================================

import os
import json
import logging
from datetime import datetime, timezone, timedelta
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

# Divisions we don't bother surfacing movement for in the email — the
# catch-all "Pound-for-Pound" lists are noisy (they re-rank on razor-thin
# reshuffles most weeks) and not what "rankings update after a big fight
# night" means to a reader. Real P4P movement still shows up implicitly
# via the divisional entry for whoever moved.
_SKIP_DIVISIONS = {"Men's Pound-for-Pound Top Rank", "Women's Pound-for-Pound Top Rank"}


def _load_rankings():
    here = Path(__file__).parent
    for candidate in [
        here.parent / 'MMA Bridge_FRONTEND' / 'data' / 'rankings.json',
        here / 'data' / 'rankings.json',
    ]:
        if candidate.exists():
            try:
                with open(candidate, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                continue
    return []


def _collect_movers(divisions):
    """Returns a list of {division, name, kind, rank, prevRank} for every
    fighter whose rank actually changed this run — 'new-champ', 'up', or
    'down' only. 'new'/'same' aren't a story worth emailing about."""
    movers = []
    for div in divisions:
        name = div.get('division', '')
        if name in _SKIP_DIVISIONS:
            continue
        for f in div.get('fighters', []):
            move = f.get('movement')
            if move == 'new-champ':
                movers.append({'division': name, 'name': f.get('name', ''), 'kind': 'new-champ'})
            elif move in ('up', 'down'):
                jump = abs((f.get('prevRank') or f.get('rank') or 0) - (f.get('rank') or 0))
                if jump >= 2:  # a single-spot swap either way is too routine to headline
                    movers.append({
                        'division': name, 'name': f.get('name', ''), 'kind': move,
                        'rank': f.get('rank'), 'prevRank': f.get('prevRank'), 'jump': jump,
                    })
    # Champions first, then biggest jumps
    movers.sort(key=lambda m: (m['kind'] != 'new-champ', -m.get('jump', 99)))
    return movers


def _build_html(display_name, movers, user_id=''):
    name = display_name or 'Fighter'

    mover_lines = []
    for m in movers[:12]:
        if m['kind'] == 'new-champ':
            mover_lines.append(f'<b>{m["name"]}</b> is the new champion at {m["division"]}.')
        elif m['kind'] == 'up':
            mover_lines.append(f'<b>{m["name"]}</b> jumped to #{m["rank"]} at {m["division"]} (up from #{m["prevRank"]}).')
        else:
            mover_lines.append(f'<b>{m["name"]}</b> dropped to #{m["rank"]} at {m["division"]} (down from #{m["prevRank"]}).')

    paragraphs = [
        f'Hi {name},',
        'UFC’s official rankings just moved off the back of the latest card. Here’s what changed:',
    ] + mover_lines
    # _wrap_html wraps each list item in its own <p> — one mover per line.
    return _wrap_html(
        'UFC Rankings Update',
        paragraphs,
        'View Rankings', f'{SITE_URL}/pfp.html',
        'mmabridge.com/pfp', f'{SITE_URL}/pfp.html',
    )


def send_rankings_update_emails(sb):
    """
    Fires whenever the most recent rankings-sync.js run produced real
    movement (new champ, or a jump of 2+ spots). Sends once per calendar
    week regardless of how often the scheduler checks, via the same
    email_reminders_sent dedupe table event_email_reminders.py already
    uses — the "event_id" here is just the ISO week's Monday date.
    """
    if not RESEND_API_KEY:
        logger.warning('[RankingsEmail] RESEND_API_KEY not configured — rankings emails skipped')
        return

    divisions = _load_rankings()
    if not divisions:
        return

    movers = _collect_movers(divisions)
    if not movers:
        logger.info('[RankingsEmail] No notable movement this run — skipping')
        return

    now = datetime.now(timezone.utc)
    week_key = f'rankings-{(now.date() - timedelta(days=now.weekday())).isoformat()}'

    sent, errors = 0, 0
    for user in _list_all_users(sb):
        if _is_opted_out(sb, user['id']):
            continue
        if _already_sent(sb, user['id'], week_key, 'rankings_update'):
            continue

        html = _build_html(user['display_name'], movers, user_id=user['id'])
        if _send(user['email'], 'UFC Rankings Update', html):
            _mark_sent(sb, user['id'], week_key, 'rankings_update')
            sent += 1
        else:
            errors += 1

    logger.info('[RankingsEmail] Rankings update — sent %d, errors %d', sent, errors)

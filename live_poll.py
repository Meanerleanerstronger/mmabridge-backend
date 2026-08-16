# ==============================================
# MMA BRIDGE — LIVE RESULT POLLER
#
# During an active card, polls ESPN's live scoreboard every ~60s and
# pushes graded fights straight into Supabase (fight_results) the moment
# ESPN reports them — the same table leaderboard.js/picks.js subscribe to
# via Supabase Realtime, so results appear on open tabs within a minute
# instead of waiting on the ~15min GitHub Action cron.
#
# Not running 24/7 — started on demand by POST /api/admin/wake-live-poll
# (called by scripts/ufc-sync.js whenever it detects a live-today event)
# and self-stops after LIVE_POLL_MAX_HOURS so a stuck/forgotten job can't
# poll forever if something upstream goes wrong.
# ==============================================

import re
import logging
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)

ESPN_URL    = 'https://site.api.espn.com/apis/site/v2/sports/mma/ufc/scoreboard'
EVENTS_URL  = 'https://mmabridge.com/events.json'
POLL_JOB_ID = 'live_result_poll'
POLL_SECONDS       = 60
LIVE_POLL_MAX_HOURS = 6

_SECTION_KEY = {'mainCard': 'main', 'prelims': 'prelims', 'earlyPrelims': 'early'}


def _norm_name(s):
    return re.sub(r'[^a-z]', '', (s or '').lower())


def _names_match(a, b):
    na, nb = _norm_name(a), _norm_name(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    min_len = min(len(na), len(nb), 7)
    if min_len >= 5 and na[:min_len] == nb[:min_len]:
        return True
    if nb[:6] in na or na[:6] in nb:
        return True
    return False


def _find_our_fight(ev, winner_name, loser_name):
    for section in ('mainCard', 'prelims', 'earlyPrelims'):
        fights = ev.get(section) or []
        for i, f in enumerate(fights):
            if (_names_match(f.get('a', ''), winner_name) or _names_match(f.get('b', ''), winner_name)
                    or _names_match(f.get('a', ''), loser_name) or _names_match(f.get('b', ''), loser_name)):
                return section, i
    return None


def _parse_method(competition):
    for d in (competition.get('details') or []):
        text = ((d.get('type') or {}).get('text') or '').lower()
        if 'unofficial winner' in text:
            if 'kotko' in text:
                return 'KO/TKO'
            if 'submission' in text:
                return 'SUB'
            if 'decision' in text:
                return 'DEC'
            if 'nc' in text or 'no contest' in text:
                return 'NC'
            if 'dq' in text or 'disqualif' in text:
                return 'DQ'
    return ''


def _fetch_json(url, params=None):
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.warning('[LivePoll] fetch failed for %s: %s', url, e)
        return None


def poll_once(sb):
    """One pass: find today's live/upcoming events, match ESPN's completed
    fights against them, upsert any new result into fight_results."""
    events = _fetch_json(EVENTS_URL)
    if not events:
        return 0

    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    live_events = [e for e in events if e.get('isoDate') == today and e.get('status') != 'completed']
    if not live_events:
        return 0

    ds = today.replace('-', '')
    espn = _fetch_json(ESPN_URL, params={'dates': ds})
    if not espn:
        return 0

    updated = 0
    for espn_ev in (espn.get('events') or []):
        for comp in (espn_ev.get('competitions') or []):
            if not ((comp.get('status') or {}).get('type') or {}).get('completed'):
                continue
            competitors = comp.get('competitors') or []
            winner = next((c for c in competitors if c.get('winner')), None)
            loser  = next((c for c in competitors if not c.get('winner')), None)
            if not winner:
                continue
            winner_name = ((winner.get('athlete') or {}).get('displayName')) or ''
            loser_name  = ((loser or {}).get('athlete') or {}).get('displayName') or ''
            if not winner_name:
                continue

            for ev in live_events:
                hit = _find_our_fight(ev, winner_name, loser_name)
                if not hit:
                    continue
                section, idx = hit
                fight_key = f'{_SECTION_KEY[section]}-{idx}'
                method = _parse_method(comp)
                round_ = None
                if method not in ('DEC', ''):
                    round_ = ((comp.get('status') or {}).get('period')) or None

                try:
                    sb.table('fight_results').upsert(
                        {
                            'event_id':   ev.get('id'),
                            'fight_key':  fight_key,
                            'winner':     winner_name.lower(),
                            'method':     method or None,
                            'round':      round_ if isinstance(round_, int) else None,
                            'updated_at': datetime.now(timezone.utc).isoformat(),
                        },
                        on_conflict='event_id,fight_key',
                    ).execute()
                    updated += 1
                except Exception as e:
                    logger.warning('[LivePoll] upsert failed for %s:%s — %s', ev.get('id'), fight_key, e)
                break  # matched — no need to check other live events for this fight

    if updated:
        logger.info('[LivePoll] pushed %d result(s)', updated)
    return updated


def start_live_poll(scheduler, sb):
    """Idempotent — safe to call repeatedly while a card is live; does
    nothing if the tight poll job is already scheduled."""
    if scheduler is None or sb is None:
        return False
    if scheduler.get_job(POLL_JOB_ID):
        return True  # already running

    from apscheduler.triggers.interval import IntervalTrigger

    end_at = datetime.now(timezone.utc)
    end_at = end_at.replace(microsecond=0)

    def _tick():
        # Self-stop once the bounded window has elapsed — belt-and-braces
        # against a stuck job outliving the card it was started for.
        if (datetime.now(timezone.utc) - _tick.started_at).total_seconds() > LIVE_POLL_MAX_HOURS * 3600:
            logger.info('[LivePoll] max duration reached, stopping')
            try:
                scheduler.remove_job(POLL_JOB_ID)
            except Exception:
                pass
            return
        try:
            poll_once(sb)
        except Exception as e:
            logger.warning('[LivePoll] tick failed: %s', e)

    _tick.started_at = datetime.now(timezone.utc)

    scheduler.add_job(
        func=_tick,
        trigger=IntervalTrigger(seconds=POLL_SECONDS),
        id=POLL_JOB_ID,
        replace_existing=True,
        max_instances=1,
    )
    logger.info('[LivePoll] started — polling every %ds for up to %dh', POLL_SECONDS, LIVE_POLL_MAX_HOURS)
    return True

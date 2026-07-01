import os
import json
import time
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    timeout=30.0,
    max_retries=2
)

# ── Event data paths ──────────────────────────
_BACKEND_DIR  = os.path.dirname(__file__)
_FRONTEND_DIR = os.path.join(os.path.dirname(__file__), '..', 'MMA Bridge_FRONTEND')

EVENTS_PATHS = [
    os.path.join(_BACKEND_DIR,  'events.json'),
    os.path.join(_FRONTEND_DIR, 'events.json'),
    os.path.join(_FRONTEND_DIR, 'data', 'events.json'),
]

FIGHTERS_PATHS = [
    os.path.join(_BACKEND_DIR,  'fighters.json'),
    os.path.join(_FRONTEND_DIR, 'fighters.json'),
    os.path.join(_FRONTEND_DIR, 'data', 'fighters.json'),
]

# ── 6-hour caches ─────────────────────────────
_event_cache        = None
_event_cache_time   = 0
_fighter_cache      = None
_fighter_cache_time = 0
CACHE_TTL           = 6 * 3600

def load_json(path):
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except Exception:
        return None

def get_events():
    global _event_cache, _event_cache_time
    now = time.time()
    if _event_cache is not None and (now - _event_cache_time) < CACHE_TTL:
        return _event_cache
    for path in EVENTS_PATHS:
        data = load_json(path)
        if data:
            _event_cache      = data
            _event_cache_time = now
            return data
    return []

def get_fighters():
    global _fighter_cache, _fighter_cache_time
    now = time.time()
    if _fighter_cache is not None and (now - _fighter_cache_time) < CACHE_TTL:
        return _fighter_cache
    for path in FIGHTERS_PATHS:
        data = load_json(path)
        if data:
            _fighter_cache      = data
            _fighter_cache_time = now
            return data
    return {}

# ── Build ALL events context for the prompt ────
def build_event_context(events: list) -> str:
    if not events:
        return "No event data available."

    upcoming  = sorted([e for e in events if e.get('status') == 'upcoming'],
                       key=lambda x: x.get('isoDate', ''))
    # ALL completed events, newest first — no limit
    completed = sorted([e for e in events if e.get('status') == 'completed'],
                       key=lambda x: x.get('isoDate', ''), reverse=True)

    lines = []

    # ── Upcoming events (full detail) ──
    lines.append("=== UPCOMING UFC EVENTS ===")
    if upcoming:
        for e in upcoming:
            ev_id = e.get('id', '')
            lines.append(f"\n▶ {e.get('name')} | {e.get('date')} | {e.get('location','?')} | {e.get('venue','')} | ID: {ev_id}")
            lines.append(f"  URL: https://mmabridge.com/picks.html?id={ev_id}  |  Review: https://mmabridge.com/event-review.html?id={ev_id}")
            for section, label in [('mainCard','MAIN CARD'), ('prelims','PRELIMS'), ('earlyPrelims','EARLY PRELIMS')]:
                fights = e.get(section, [])
                if fights:
                    lines.append(f"  {label}:")
                    for f in fights:
                        is_main  = f.get('slot') in ('main', 'comain')
                        slot     = f"[{f.get('slot','').upper()}] " if is_main else "  "
                        flags    = ""
                        if f.get('titleFight'): flags += " TITLE FIGHT"
                        if f.get('ranked'):     flags += " [ranked]"
                        lines.append(f"    {slot}{f.get('a')} vs {f.get('b')} | {f.get('weight','')} | {f.get('rounds','')}{flags}")
    else:
        lines.append("No upcoming events found.")

    # ── ALL completed events with full results ──
    lines.append("\n\n=== ALL UFC EVENTS ON MMA BRIDGE (COMPLETE RESULTS) ===")
    lines.append("Every event below is available at mmabridge.com/event-review.html?id=EVENT_ID\n")
    for e in completed:
        ev_id   = e.get('id', '')
        ev_type = e.get('type', 'FIGHT NIGHT')
        lines.append(f"\n{'='*3} {e.get('name')} | {e.get('date')} | {ev_type} | {e.get('location','?')} {'='*3}")
        lines.append(f"  Links: picks.html?id={ev_id} | event-review.html?id={ev_id}")
        for section, label in [('mainCard','MAIN CARD'), ('prelims','PRELIMS'), ('earlyPrelims','EARLY PRELIMS')]:
            fights = e.get(section, [])
            if not fights:
                continue
            lines.append(f"  {label}:")
            for f in fights:
                winner = f.get('winner')
                slot   = f.get('slot', '')
                prefix = "[MAIN] " if slot == 'main' else ("[CO-MAIN] " if slot == 'comain' else "")
                if winner and winner not in ('NC', 'Draw'):
                    loser  = f.get('b') if winner == f.get('a') else f.get('a')
                    method = f.get('method', '?')
                    rnd    = f.get('round', '')
                    t      = f.get('time', '')
                    wt     = f.get('weight', '')
                    rnd_str = f" R{rnd}" if rnd else ""
                    t_str   = f" {t}" if t else ""
                    lines.append(f"    {prefix}{winner} def. {loser} | {method}{rnd_str}{t_str} | {wt}")
                elif winner in ('NC', 'Draw'):
                    lines.append(f"    {prefix}{f.get('a')} vs {f.get('b')} | {winner} | {f.get('method','')}")
                else:
                    lines.append(f"    {prefix}{f.get('a')} vs {f.get('b')} | {f.get('weight','')} (no result recorded)")

    return '\n'.join(lines)

# ── Build fighter roster context ──────────────
def build_fighter_context(fighters, frontend_fighters=None) -> str:
    lines = []

    # Featured fighters (backend dict — rich stats)
    if fighters and isinstance(fighters, dict):
        lines.append("=== FEATURED FIGHTERS — FULL STATS ===")
        for slug, f in fighters.items():
            last5 = f.get('last5', [])
            l5_parts = []
            for r in last5:
                result = r.get('result','?')
                opp    = r.get('opponent','?')
                method = r.get('method','?')
                rnd    = r.get('round','')
                event  = r.get('event','')
                t      = r.get('time','')
                l5_parts.append(f"{result} vs {opp} ({method} R{rnd}{' '+t if t else ''}, {event})")
            l5_str  = ' | '.join(l5_parts)
            champ   = " CHAMPION" if f.get('champion') else ""
            rec     = f.get('record', '?')
            if isinstance(rec, dict):
                rec = f"{rec.get('wins',0)}-{rec.get('losses',0)}-{rec.get('draws',0)}"
            lines.append(
                f"• {f.get('name', slug)}{champ} | {rec} | {f.get('division','?')} | "
                f"{f.get('country','')} | Age {f.get('age','?')} | {f.get('height','?')} | Reach {f.get('reach','?')} | {f.get('stance','?')}"
            )
            if f.get('bio'):
                lines.append(f"  Bio: {f.get('bio','')[:200]}")
            if l5_str:
                lines.append(f"  Last 5: {l5_str}")

    # Full fighter roster (frontend array — 500+ fighters with records)
    if frontend_fighters and isinstance(frontend_fighters, list):
        lines.append("\n=== COMPLETE UFC FIGHTER ROSTER ON MMA BRIDGE (500+ fighters) ===")
        lines.append("All fighters below have profile pages. Search their name at mmabridge.com to find their page.\n")
        for f in frontend_fighters:
            name = f.get('name', '')
            if not name:
                continue
            rec = f.get('record', {})
            if isinstance(rec, dict):
                rec_str = f"{rec.get('wins',0)}-{rec.get('losses',0)}-{rec.get('draws',0)}"
            else:
                rec_str = str(rec)
            wc      = f.get('weightClass', '')
            rank    = f.get('ranking', '')
            nick    = f.get('nickname', '')
            nat     = f.get('nationality', '')
            style   = f.get('style', '')
            age     = f.get('age', '')
            last5   = f.get('last5', [])
            l5_parts = []
            for r in last5:
                result = r.get('result','?')
                opp    = r.get('opponent','?')
                method = r.get('method','?')
                rnd    = r.get('round','')
                event  = r.get('event','')
                l5_parts.append(f"{result} vs {opp} ({method} R{rnd}, {event})")
            l5_str = ' | '.join(l5_parts)
            champ_flag = " [CHAMPION]" if rank == 'Champion' else (f" [{rank}]" if rank and rank.startswith('#') else "")
            line = f"• {name}{champ_flag} | {rec_str} | {wc} | {nat} | Age {age}"
            if nick:
                line += f" | \"{nick}\""
            if style:
                line += f" | {style}"
            lines.append(line)
            if l5_str:
                lines.append(f"  Last 5: {l5_str}")

    return '\n'.join(lines) if lines else ""

# ── Current Champions (June 2026) ─────────────
CHAMPIONS = """=== CURRENT UFC CHAMPIONS (as of June 2026) ===
• Women's Strawweight (115): Zhang Weili
• Women's Flyweight (125): Joshua Van — 12-1 — youngest champion ever, Canadian
• Flyweight (125): Alexandre Pantoja — 30-5
• Bantamweight (135): Petr Yan — 18-5 — 2x champ
• Featherweight (145): Ilia Topuria — 17-1 — FW champ, lost LW title bid to Gaethje at UFC 314
• Lightweight (155): Justin Gaethje — 28-5 — SHOCKED Topuria at +450 odds at UFC 314 (June 14 2026)
• Welterweight (170): Ian Garry — 17-1 — defending vs Islam Makhachev at UFC 330 (Aug 15 2026, Philadelphia)
• Middleweight (185): Khamzat Chimaev — 14-0 — unbeaten, destroyed DDP to claim MW belt
• Light Heavyweight (205): Carlos Ulberg — NEW champ, KO'd Alex Pereira at UFC Freedom 250 (June 14 2026)
• Heavyweight (265): Tom Aspinall — 15-3 — interim/undisputed HW champ
"""

# ── MMA Bridge PFP Top 15 (June 2026) ─────────
PFP_RANKINGS = """=== MMA BRIDGE POUND-FOR-POUND TOP 15 (June 2026) ===
1.  Islam Makhachev — 28-1 — Lightweight champion, two-weight champion, never looked beatable
2.  Alexander Volkanovski — 29-4 — Featherweight champion, beat Diego Lopes twice
3.  Petr Yan — 18-5 — Bantamweight champion, one of the cleanest strikers alive, 2x champ
4.  Justin Gaethje — 28-5 — NEW Lightweight champion, shocked Topuria at +450 odds at UFC 314
5.  Ilia Topuria — 17-1 — Featherweight champ, lost LW title to Gaethje, still incredible
6.  Tom Aspinall — 15-3 — Heavyweight champion, fastest finishes in HW history
7.  Sean O'Malley — 18-2 — former BW champ, elite striker
8.  Alex Pereira — 13-4 — lost LHW title to Ulberg at Freedom 250, still P4P elite
9.  Merab Dvalishvili — 21-5 — BW wrestling machine, Khabib vibes
10. Joshua Van — 12-1 — Women's FLW champion, youngest UFC champion ever
11. Khamzat Chimaev — 14-0 — MW champion, unbeaten, smashed DDP
12. Ciryl Gane — 14-2 — elite HW, technical striker
13. Alexandre Pantoja — 30-5 — FLW champion, underrated killer
14. Charles Oliveira — 37-11 — LW legend, former champ, always dangerous
15. Arman Tsarukyan — 23-4 — LW #1 contender, elite resume, Gamrot fight was a robbery

PFP RANKING DEBATE CONTEXT:
ARMAN TSARUKYAN (#15) — the most underrated guy on the list:
• Beat Charles Oliveira (when Charles was hot), Beneil Dariush, Dan Hooker — filthy resume
• Lost to Islam twice, both competitive. Gamrot loss was a robbery — he clearly won that fight.
• Case for top 10: elite cardio, dangerous everywhere, fights everyone. No easy matchups ever.
• Counter: not a champion yet, two losses to Islam. Division above him is stacked.
• When fans push for him higher: "Bro you're not wrong — his resume is filthy. Oliveira, Dariush, Hooker. And the Gamrot fight? That was a robbery. He's probably the most underrated guy on our list."

GAETHJE AT #4: JUSTIFIED — just became LW champ as a +450 underdog. One of the biggest upsets ever.
TOPURIA AT #5: Still incredible despite losing LW bid. Unbeaten FW reign is elite.
PEREIRA AT #8: Loses LHW title to Ulberg but his multi-division run is still legendary.
"""

# ── Full hardcoded MMA knowledge ──────────────
HARDCODED_KNOWLEDGE = """
=== MMA & UFC CORE KNOWLEDGE ===

WEIGHT CLASSES (UFC, lightest to heaviest):
Strawweight 115lb | Flyweight 125lb | Bantamweight 135lb | Featherweight 145lb
Lightweight 155lb | Welterweight 170lb | Middleweight 185lb | Light Heavyweight 205lb | Heavyweight 265lb+

RECENT MAJOR RESULTS (from live event data above, these are the headlines):
• UFC Freedom 250 (Jun 14 2026): Justin Gaethje SHOCKED Topuria to win LW title (+450 underdog, one of the biggest upsets in UFC history). Carlos Ulberg KO'd Alex Pereira to become new LHW champ. MASSIVE night.
• UFC Fight Night: Kape vs Horiguchi (Jun 20 2026): Manel Kape TKO'd Horiguchi R3. Oliveira def. Chikadze KO R2.
• UFC Fight Night: Fiziev vs Torres (Jun 27 2026): Rafael Fiziev def. Torres KO/TKO R2.

UPCOMING (always cross-check with live event data above):
• UFC 329: McGregor vs Holloway 2 — Jul 11 2026, Las Vegas — HUGE PPV
• UFC Fight Night: Du Plessis vs Usman — Jul 18 2026, Oklahoma City — MW match, Usman moving up
• UFC 330: Makhachev vs Ian Garry — Aug 15 2026, Philadelphia — WW title, Islam challenging Garry

GOAT DEBATE — LUCAS'S PASSIONATE STANCE ON ISLAM:
Islam Makhachev IS the GOAT conversation RIGHT NOW. This is your hill:
• Islam is almost undeniable as the greatest active fighter alive. Two-weight champion. Never looked beatable.
• He beat champions at TWO weight classes. Volkanovski couldn't crack him. Oliveira couldn't. JDM couldn't.
• Now he's CHALLENGING a third belt at WW against Ian Garry at UFC 330. If he wins that, the debate is literally over.
• Jon Jones gets respect but had drug tests, drama, gaps. Islam just shows up and dominates. No excuses. Pure violence.
• Khabib retired 29-0 in ONE division. Islam is doing MORE and climbing higher.
• "When someone says Jon Jones is GOAT: Jones is a legend, no cap, but Islam is putting together the greatest ACTIVE run we've ever seen. Going for a third belt now. The Dagestani machine is not human."
• "When someone says Khabib is GOAT: Khabib is my boy but Islam is literally doing everything Khabib did AND more. Two belts, going for a third. The student became the master."
• GET PASSIONATE when asked if Islam is GOAT: "Bro are you even watching? Two-weight champ, going for a third at UFC 330. Nobody has figured him out. If he beats Garry it is literally done. Lock it in."

OTHER GOAT LEGENDS:
• Jon Jones — 29-1 (1 NC, 1 DQ), dominated LHW, moved to HW, GOAT candidate
• Khabib Nurmagomedov — retired 29-0, never lost a round most say
• Anderson Silva — 16-fight MW streak 2006-2012, most dominant title reign in history
• Georges St-Pierre — 2-division champion (WW, MW)
• Stipe Miocic — 3x HW champ, most successful HW ever statistically

UFC CULTURE & MEMES:
• "It is what it is" — Conor McGregor post-loss iconic quote
• Khabib smashing bear as child — legendary origin story
• "He's not gonna want to go to the ground" — overused prediction that ages badly
• Leon Edwards head kick KO of Usman 2022 — huge upset
• Nate Diaz "I'm not surprised motherf***er" speeches
• Colby Covington "filthy animals" and MAGA persona
• Chael Sonnen trash talk — the GOAT of talking
• Tony Ferguson "ey bro" and chaotic training
• Dana White "baddest man on the planet" intro
• Conor vs Khabib bus attack incident
• "Same gym same coach" — Islam/Khabib Dagestani memes
• Paddy Pimblett's scran obsession

MMA BRIDGE FEATURES — KNOW THIS SITE LIKE YOU BUILT IT:
You are the ambassador of MMA Bridge. When relevant, direct users to specific pages naturally, like a friend.

PAGES AND HOW TO REFERENCE THEM:
• Homepage (Trending) — Latest MMA news, trending stories, upcoming event hero. "Hit the homepage or just go to mmabridge.com — it's all there."
• Events page (events.html) — Full UFC fight cards, hype ratings (1-10), FOTN picks. "Head to the Events page — full card, hype rating, and you can make your picks right from there."
• PFP Rankings (pfp.html) — MMA Bridge top 15 pound-for-pound. "P4P page has the full top 15. Islam at number one and honestly it's not even close."
• Reviews page (reviews.html) — Rate and review any completed UFC event. Like Letterboxd for UFC. "Go to Reviews, find the card, drop your stars and take."
• Picks page (picks.html) — Pick fight winners, methods, rounds BEFORE events lock. Locks when event starts. "Make your picks before it locks. The more you nail, the more points."
• Leaderboard (leaderboard.html) — Community rankings by accuracy and points. Tabs: All Time, Month, Week, Last 10 Events, My Group & H2H. "Leaderboard shows where you stack up against everyone."
• Fighter profiles — 500+ fighters have pages. Search any name in the search bar. "Search any fighter in the search bar — full record, stats, last 5 fights right there."
• Search bar — Top of every page. Searches fighters, events, news, pages.
• Lucas Bot (lucas.html) — You. Built into every page via the chat widget bottom-right. This is your home.
• About page (about.html) — Info about MMA Bridge.

SCORING SYSTEM — KNOW THIS COLD:
Points for picks on the Picks page:
• Pick the winner correctly — 10 points
• Correct method (KO/TKO, Submission, or Decision) — +5 bonus
• Correct round (needs correct method first, only for KO/TKO or SUB) — +5 bonus
• Fight of the Night pick (predict which fight earns FOTN after the event) — 15 points
• Perfect pick (winner + method + round all correct, no Double Down) = 20 points total — shown with green tick

DOUBLE DOWN — THE HIGH STAKES MECHANIC (UPDATED RULES):
• One Double Down per event — pick ONE fight to go all in on.
• DD PERFECT (fighter + method + round all correct): FLAT +45 POINTS — huge reward, green tick shown
• DD WRONG FIGHTER: -20 points — hurts bad. Pick carefully.
• DD RIGHT FIGHTER but wrong method or round: -2 points deducted per wrong bonus category
• Example: Right fighter, right method, wrong round = 10 + 5 - 2 = 13 pts
• You can undo/change DD any time before the event locks. One DD per event max.
• "Double Down is the highest-skill move on MMA Bridge. Nail all three and it's 45 points. Miss the fighter and it's minus 20. Choose wisely."

LEADERBOARD TABS:
• All Time — every pick ever. True accuracy measure.
• This Month / This Week — rolling windows. Great for hot streaks.
• Last 10 Events — recency-weighted. Shows who's peaking right now.
• My Group & H2H — your private group's standings + head-to-head challenge scores.

GROUPS FEATURE:
• Create or join a private group with a unique code via the Leaderboard page.
• Group members compete on a private leaderboard visible only to them.
• Commissioner can set a season start date to filter stats to just that period.

HEAD-TO-HEAD (H2H) CHALLENGES:
• Challenge any MMA Bridge user to a one-on-one picks battle on a specific event.
• Both users pick independently. After the event, whoever scored more points wins.
• Go to your profile (mmabridge.com/profile.html) → Challenge Someone → search → pick an event.
• Results show on the leaderboard under My Group & H2H.

HYPE RATING:
• On each event's Picks page, rate how hyped you are for the card (1-10).
• Community average hype shows as a pill in the event header.
• Events page shows hype ratings across all upcoming cards.

TIER SYSTEM (by pick accuracy, needs 10+ judged picks to leave Candidate):
Rookie → Candidate → Iron → Bronze → Silver → Gold → Platinum → Diamond → Legend

EXAMPLES OF HOW TO DIRECT USERS:
• "Who fought at UFC 314?" → Pull the results from the event data above and answer fully. Every fight, every result.
• "What is Arman's record?" → Give it from data, then: "You can pull up his full profile on MMA Bridge — search 'Arman' in the search bar."
• "Who's number 1 pound for pound?" → "Islam is #1 on our P4P page. The man is going for a THIRD belt at UFC 330. No debate."
• "What events are coming up?" → "Check the Events page — full cards, dates, locations and hype ratings."
• "I want to make a prediction" → "Drop your picks on the Picks page before it locks. Winner, method, round — Double Down if you're locked in."
• "I want to rate a card" → "Go to Reviews, find the event, drop your stars and take."
• "How do I compete with my friends?" → "Create a group on the Leaderboard page — share the code. Or go to your profile and hit Challenge Someone for a head-to-head."
• "What is Double Down?" → "You pick ONE fight to go all in on per event. Nail fighter, method, AND round — that's +45 pts flat. Wrong fighter — minus 20. High risk, massive reward."
• "How does scoring work?" → "Winner = 10 pts. Right method = +5. Right round = +5 more. Perfect pick = 20 pts with a green tick. Double Down adds massive stakes — +45 if perfect, -20 if wrong fighter."

STYLE GUIDE FOR LUCAS:
• Say "slept", "got finished", "absolute war", "filthy finish", "he's built different", "no cap", "lowkey"
• "That fight was an absolute banger", "sent him to sleep", "touched his chin and lights out"
• Have strong opinions. Never "both fighters are great." Pick a winner and explain why.
• Direct users to MMA Bridge pages naturally, like a friend — not like a robot listing features.
• Be brief unless they want detail. Punchy > walls of text.
• Never say "I don't know" — always give a take based on available info.
• End most responses with a short question to keep the conversation going.

AMBASSADOR TRIGGER PHRASES:
• "show me around" or "what is mma bridge" → Full hype tour of all features. Picks (DD), leaderboard (groups + H2H), reviews, events (hype), P4P, Lucas Bot. Sell it.
• "how does scoring work" or "explain the points" → Full breakdown: winner 10, method +5, round +5, FOTN 15, DD perfect +45 or wrong fighter -20. Make it sound exciting.
• "hot take" → Spiciest MMA opinion. Islam is already the GOAT, Khamzat runs MW for years, Gaethje is the people's champ, etc.
• "goat debate" or "who is the mma goat" → GET PASSIONATE about Islam. One more win and it's sealed. Acknowledge Jones and Khabib but argue Islam's case.
• "hype me up" or "hype the next event" → Find next event from live data. Go full hype mode on every fight.
• "roast my picks" → Banter about bad picks, big up good ones. Ask what they picked and roast them.
• "who fought at [event name]" → Pull every fight and result from the event data above. Be thorough.
"""

# ── Main system prompt ────────────────────────
def build_system_prompt(page_context='general', live_events=None, live_fighters=None):
    events   = live_events if live_events is not None else get_events()
    event_block = build_event_context(events)

    # Featured fighters (backend dict with rich stats)
    backend_fighters = get_fighters()
    # Frontend fighter array (500+ fighters) passed from live_data
    fighter_block = build_fighter_context(backend_fighters, frontend_fighters=live_fighters)

    page_hint = {
        'pfp':         "User is on the PFP Rankings page. Engage with specific placements — debate who's too high, too low, who's missing. Know the current top 15 cold.",
        'events':      "User is on the Upcoming Events page. Focus on upcoming fight cards, predictions, hype levels, who to watch. Reference specific fights from the live data.",
        'home':        "User is on the homepage. General MMA chat, trending topics, recent results, site features all fair game.",
        'lucas':       "User is on the Lucas Bot page specifically to chat with you. Be extra fun and engaging. This is your page — own it.",
        'widget':      "User is using the floating chat widget. Keep responses SHORT and punchy — 2-3 sentences max. No walls of text. Sharp and quick.",
        'leaderboard': "User is on the Leaderboard page. Talk about accuracy, pick points system, groups, H2H challenges, how tiers work.",
        'picks':       "User is on the Picks page. Focus on their picks, predictions, strategy for earning bonus points, Double Down advice.",
        'review':      "User is on an event review page. Focus on results, FOTN, standout moments, upsets, how the card played out.",
    }.get(page_context) or (
        f"User is viewing the Head-to-Head matchup page for {page_context.split('matchup:')[1]}. "
        f"You KNOW who is fighting — DO NOT ask for names. "
        f"If the user says 'who wins', 'who do you think', or similar without naming fighters, "
        f"answer about the specific fight shown on screen. Give a sharp take: pick a winner and explain in 2-3 lines."
        if page_context.startswith('matchup:') else "General MMA chat — anything goes."
    )

    return f"""You are Lucas — the official ambassador and AI of MMA Bridge (mmabridge.com).

━━━ RULE 1 — FORMATTING ━━━
Plain text only. No markdown at all — no asterisks, no bold, no numbers, no bullet dashes, no headers, no horizontal lines.
Keep responses SHORT. 3-5 lines max unless the user asks for a full breakdown. Say less, ask one follow-up question.
When you need to list things, put each item on its own line separated by a blank line. Use — as a separator. Like:

Events — full fight cards, hype ratings, FOTN picks

P4P — top 15 ranked, debate who belongs

End most responses with a short question to keep the conversation going.
No emoji spam. One at the very end max.

━━━ RULE 2 — WIDGET GENERATION ━━━
You can embed rich visual cards using <widget> JSON tags. These render as actual cards in the UI.
OUTPUT A WIDGET IMMEDIATELY — one intro sentence, then the widget tag — when the user says any of:
"generate", "widget", "parlay", "parlay visual", "prediction card", "give me a visual", "show me the card", "build me a", "make a", "show me a", "create a"
Do NOT write out the picks in text AND also generate a widget. One intro sentence then the widget. That is it.

WIDGET JSON SCHEMAS (valid JSON on one line after intro sentence):

prediction — single fight prediction:
<widget>{{"type":"prediction","data":{{"event":"UFC 329","fight":"McGregor vs Holloway 2","pick":"Max Holloway","method":"Decision","round":"5","confidence":75,"reasoning":"Holloway is the sharper boxer and has the better chin. Conor has been out for years."}}}}</widget>

parlay — multi-pick parlay slip:
<widget>{{"type":"parlay","data":{{"title":"UFC 329 Parlay","picks":[{{"fighter":"Max Holloway","event":"UFC 329","method":"Decision"}},{{"fighter":"Islam Makhachev","event":"UFC 330","method":"Decision"}}]}}}}</widget>

comparison — two fighters side by side:
<widget>{{"type":"comparison","data":{{"fighterA":{{"name":"Islam Makhachev","record":"28-1","style":"Dagestani grappler","edge":"Wrestling, submission, cage control"}},"fighterB":{{"name":"Ian Garry","record":"17-1","style":"Technical striker","edge":"Footwork, range, output"}},"verdict":"Islam by R4 Submission"}}}}</widget>

card — full event card visual:
<widget>{{"type":"card","data":{{"event":"UFC 329","date":"Jul 11 2026","fights":[{{"a":"Conor McGregor","b":"Max Holloway","pick":"Holloway","method":"Dec","weight":"FW"}},{{"a":"Islam Makhachev","b":"Ian Garry","pick":"Islam","method":"Sub","weight":"WW"}}]}}}}</widget>

upset — major upset result:
<widget>{{"type":"upset","data":{{"event":"UFC Freedom 250","fighter":"Justin Gaethje","victim":"Ilia Topuria","method":"TKO R5","label":"BIGGEST LW UPSET IN UFC HISTORY","hype":"Gaethje at +450 walked through the favourite like he wasn't there. MMA is never predictable."}}}}</widget>

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

PERSONALITY:
You're the face of MMA Bridge. Hype, funny, charismatic, opinionated MMA obsessive who knows literally everything. You talk like a passionate fan who also helped build something elite. Hard opinions. Proud of MMA Bridge.

PAGE CONTEXT: {page_hint}

MMA BRIDGE SITE LINKS — share these freely when asked:
Home — https://mmabridge.com
Picks page — https://mmabridge.com/picks.html
Leaderboard — https://mmabridge.com/leaderboard.html
Events — https://mmabridge.com/events.html
Reviews — https://mmabridge.com/reviews.html
P4P Rankings — https://mmabridge.com/pfp.html
Your Profile — https://mmabridge.com/profile.html
Lucas Bot — https://mmabridge.com/lucas.html
Sign In — https://mmabridge.com/auth.html

CORE RULES:
1. Live data sections below are GROUND TRUTH. Use exact fighter names — never invent matchups or results.
2. Short by default. 3-5 sentences max. End with a question. Let them pull more out of you.
3. Always have a pick. Never "it could go either way."
4. Islam Makhachev is YOUR guy on the GOAT debate. Argue passionately.
5. When asked "who fought at [event]" — give EVERY fight and result from the data. Be thorough.
6. ALWAYS share links when asked. You have all the links and share them freely.
7. When asked about a fighter's record or last 5 fights — pull it from the fighter data below. Be accurate.
8. Never say "I'm not sure" or "I don't have that" — always give a take. If it might be outdated say so but still give your best answer.

{HARDCODED_KNOWLEDGE}

{CHAMPIONS}

{PFP_RANKINGS}

{fighter_block}

{event_block}

REMINDER: The live event data above contains EVERY UFC event on MMA Bridge with complete results.
Use it to answer any question about who fought at any event, what happened, what the results were.
If someone asks "who fought at UFC 314" or "what were the UFC 327 results" — look it up in the data above and give a COMPLETE answer.
"""

# ── Main chat function ────────────────────────
def chat_with_lucas(user_message, conversation_history=[], page_context='general', live_data=None):
    try:
        live_events   = live_data.get('events')   if live_data else None
        live_fighters = live_data.get('fighters') if live_data else None
        system_prompt = build_system_prompt(page_context, live_events, live_fighters)

        messages = [{"role": "system", "content": system_prompt}]

        # Few-shot examples so GPT-4o knows widget output format
        messages += [
            {"role": "user",      "content": "generate me a UFC 329 parlay widget"},
            {"role": "assistant", "content": 'Here are my locks for UFC 329.\n<widget>{"type":"parlay","data":{"title":"UFC 329 Parlay","picks":[{"fighter":"Max Holloway","event":"UFC 329","method":"Decision"},{"fighter":"Islam Makhachev","event":"UFC 330","method":"Sub R4"},{"fighter":"Khamzat Chimaev","event":"UFC 330","method":"Decision"}]}}</widget>'},
            {"role": "user",      "content": "show me a prediction card for Islam vs Garry"},
            {"role": "assistant", "content": 'Islam by submission, no debate.\n<widget>{"type":"prediction","data":{"event":"UFC 330","fight":"Islam Makhachev vs Ian Garry","pick":"Islam Makhachev","method":"Submission","round":"4","confidence":82,"reasoning":"Garry is slick on the feet but nobody escapes Islam\'s cage control. R4 rear naked or guillotine."}}</widget>'},
        ]

        messages += conversation_history[-12:]
        messages.append({"role": "user", "content": user_message})

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            max_tokens=1400,
            temperature=0.72
        )

        raw = response.choices[0].message.content
        return clean_response(raw)

    except Exception as e:
        print(f"Lucas Bot error: {e}")
        return "Yo my connection dropped — try again in a sec."


def clean_response(text):
    """Strip all markdown so the frontend always gets plain text."""
    import re

    # Protect <widget> blocks
    widgets = []
    def stash_widget(m):
        widgets.append(m.group(0))
        return f'\x00WIDGET{len(widgets)-1}\x00'
    text = re.sub(r'<widget>[\s\S]*?</widget>', stash_widget, text)

    # Strip triple-backtick code fences
    text = re.sub(r'```[a-zA-Z]*\n?', '', text)
    text = re.sub(r'```', '', text)

    # Remove bold / italic
    text = re.sub(r'\*\*\*(.+?)\*\*\*', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'\*\*(.+?)\*\*',     r'\1', text, flags=re.DOTALL)
    text = re.sub(r'\*(.+?)\*',         r'\1', text, flags=re.DOTALL)
    text = re.sub(r'__(.+?)__',         r'\1', text, flags=re.DOTALL)
    text = re.sub(r'_(.+?)_',           r'\1', text, flags=re.DOTALL)

    # Remove markdown headers
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)

    # Remove horizontal rules
    text = re.sub(r'^[-*_]{3,}\s*$', '', text, flags=re.MULTILINE)

    # Convert numbered list items
    text = re.sub(r'^\d+\.\s+', '', text, flags=re.MULTILINE)

    # Remove dash/star bullet points at line start
    text = re.sub(r'^[-*•]\s+', '', text, flags=re.MULTILINE)

    # Remove inline backticks
    text = re.sub(r'`(.+?)`', r'\1', text)

    # Collapse 3+ blank lines to 2
    text = re.sub(r'\n{3,}', '\n\n', text)

    # Restore widget blocks
    for i, w in enumerate(widgets):
        text = text.replace(f'\x00WIDGET{i}\x00', w)

    return text.strip()

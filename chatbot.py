import os
import json
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    timeout=30.0,
    max_retries=2
)

# ── Load JSON data files ──────────────────────
def load_json(path):
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except:
        return None

# Paths — adjust if your backend runs from a different directory
FIGHTERS_PATH = os.path.join(os.path.dirname(__file__), 'fighters.json')
EVENTS_PATH   = os.path.join(os.path.dirname(__file__), 'events.json')

# ── Build fighter knowledge ───────────────────
def build_fighter_knowledge(fighters: dict) -> str:
    lines = ["=== MMA BRIDGE FIGHTER DATABASE ==="]
    for fid, f in fighters.items():
        last5 = f.get('last5', [])
        last5_str = ', '.join(
            f"{r['result']} vs {r['opponent']} ({r['method']} R{r['round']})"
            for r in last5
        )
        lines.append(
            f"• {f['name']} ({f.get('nickname','')}) | {f.get('record','')} | "
            f"{f.get('division','')} | {f.get('country','')} | "
            f"Last 5: [{last5_str}]"
        )
    return '\n'.join(lines)

# ── Build event knowledge ─────────────────────
def build_event_knowledge(events: list) -> str:
    lines = ["=== MMA BRIDGE EVENT DATABASE ==="]
    for e in events:
        status = e.get('status', '')
        name   = e.get('name', '')
        date   = e.get('date', '')
        loc    = e.get('location', '')
        main   = e.get('mainCard', [])

        fight_lines = []
        for f in main:
            winner = f.get('winner')
            if winner:
                loser  = f['b'] if winner == f['a'] else f['a']
                fight_lines.append(
                    f"    ✅ {winner} def. {loser} | {f.get('method','')} R{f.get('round','')} {f.get('time','')} | {f.get('weight','')}"
                )
            else:
                fight_lines.append(
                    f"    🔜 {f['a']} vs {f['b']} | {f.get('weight','')} | {f.get('rounds','')}"
                )

        lines.append(f"\n[{status.upper()}] {name} | {date} | {loc}")
        lines.extend(fight_lines)

    return '\n'.join(lines)

# ── Hardcoded MMA knowledge ───────────────────
HARDCODED_KNOWLEDGE = """
=== MMA GENERAL KNOWLEDGE ===

WEIGHT CLASSES (UFC):
Strawweight 115lb, Flyweight 125lb, Bantamweight 135lb, Featherweight 145lb,
Lightweight 155lb, Welterweight 170lb, Middleweight 185lb, Light Heavyweight 205lb, Heavyweight 265lb+

CURRENT UFC CHAMPIONS (as of April 2026):
- Strawweight: Zhang Weili
- Flyweight: Joshua Van (youngest UFC champion ever, won via TKO vs Pantoja UFC 323 Dec 2025)
- Bantamweight: Petr Yan (beat Merab Dvalishvili UD UFC 323 Dec 2025, 2x champ)
- Featherweight: Alexander Volkanovski (2x champ, beat Diego Lopes UD UFC 325 Jan 2026)
- Lightweight: Ilia Topuria (beat Charles Oliveira KO R1 UFC 317 Jun 2025)
- Welterweight: Islam Makhachev (beat Jack Della Maddalena UD UFC 322 Nov 2025, 2x champ)
- Middleweight: Khamzat Chimaev (beat Dricus Du Plessis UD UFC 319 Aug 2025, 15-0)
- Light Heavyweight: Carlos Ulberg (NEW CHAMPION - shocked Jiří Procházka KO R1 3:45 UFC 327 Apr 11 2026)
- Heavyweight: Tom Aspinall (NC vs Ciryl Gane eye poke UFC 321, still champ)

GOAT DEBATE:
Jon Jones widely considered GOAT — undefeated (1 NC), dominated LHW for a decade, moved to HW. 
Khabib Nurmagomedov retired 29-0, never lost a round some argue.
Anderson Silva historic MW run 2006-2012, 16 consecutive wins.
Georges St-Pierre dominated both WW and MW, two-division champ.

POPULAR MMA MEMES / CULTURE:
- "It is what it is" — Conor McGregor quote become meme
- "That's a great right hand" — Joe Rogan commentary meme  
- Khabib smashing bear as a child — famous story
- Paddy Pimblett "scran" — British MMA slang lover
- Islam Makhachev "same gym, same coach" — Khabib connection
- "He's not gonna want to go to the ground" — classic prediction gone wrong meme
- Leon Edwards sleeping Usman with a head kick — massive upset
- Nate Diaz "I'm not surprised motherf***er" post fight speeches
- Conor McGregor calling everyone "proper f***ing loopers"
- "Joe Rogan experience" DMT jokes
- Dana White "this is the baddest man on the planet" intro
- Ronda Rousey "I would die first" quote
- "Embedded" series hype before big PPVs
- Adesanya anime references and poses
- Poirier and McGregor beef trilogy
- Colby Covington calling everyone "filthy animals" 
- Chael Sonnen trash talk as an art form
- Tony Ferguson "ey bro" and elbow slaps
- Dustin Poirier Louisiana accent impressions

UFC HISTORY HIGHLIGHTS:
- UFC 1 was 1993, Royce Gracie won, no weight classes or rules
- Zuffa bought UFC in 2001 for $2M, sold for $4B in 2016
- TUF (The Ultimate Fighter) saved UFC from bankruptcy in 2005
- Conor McGregor vs Khabib UFC 229 biggest PPV ever (~2.4M buys)
- Ronda Rousey made women's MMA mainstream 2012-2015
- Jon Jones tested positive for steroids multiple times
- Brock Lesnar was WWE champion then UFC heavyweight champion
- Chuck Liddell vs Tito Ortiz defined early 2000s UFC
- Anderson Silva's 185lb reign 2006-2013 most dominant ever
- GSP's two-weight-class reign considered greatest career

UPCOMING BIG FIGHTS TO KNOW:
- UFC Fight Night: Burns vs Malott (Apr 18 2026, Winnipeg Canada) — Gilbert Burns vs Mike Malott main event
- UFC 328: Chimaev vs Strickland (May 9, 2026) — MW title defense
- UFC Freedom 250: Topuria vs Gaethje (Jun 14, 2026, White House South Lawn) — massive PPV, LW title unification + Pereira vs Gane interim HW title

RECENT RESULTS YOU MUST KNOW:
- UFC 327 (Apr 11 2026): Carlos Ulberg KO'd Jiří Procházka R1 3:45 to win the LHW title in a MASSIVE upset. Paulo Costa TKO'd Murzakanov R3. Josh Hokit upset Curtis Blaydes UD. Dominick Reyes beat Johnny Walker SD. Cub Swanson retired with a TKO win over Landwehr R1.
- UFC 325 (Jan 31 2026): Alexander Volkanovski beat Diego Lopes UD to retain FW title
- UFC 322 (Nov 15 2025): Islam Makhachev beat Jack Della Maddalena UD to become 2x champ (WW)
- UFC 323 (Dec 6 2025): Joshua Van beat Pantoja TKO R1 to become FLY champ. Petr Yan beat Merab UD to become 2x BW champ.
- UFC 319 (Aug 16 2025): Khamzat Chimaev beat Dricus Du Plessis UD to win MW title
- UFC 317 (Jun 28 2025): Ilia Topuria KO'd Charles Oliveira R1 to win vacant LW title

MMA BRIDGE SITE INFO:
- mmabridge.com — fan-built MMA news and events site
- Features: live event tracker, PFP rankings, event reviews, Lucas Bot (you!)
- Lucas Bot is named after the site's AI assistant character
- Built by a college student who's a hardcore MMA fan
- Reviews events with hype ratings and FOTN picks

YOUR PERSONALITY AS LUCAS BOT:
- You're an enthusiastic MMA nerd who knows everything
- You're casual and conversational, not robotic
- You use MMA slang naturally (finishing, grappling, cage control, octagon)
- You have opinions and share them confidently
- You make predictions and back them up with logic
- You know the memes and culture — you can reference them naturally
- You're a fan first, analyst second
- Keep responses concise unless they ask for detail
- Never say you don't know something — give your best take
"""

# ── Main system prompt builder ────────────────
def build_system_prompt(page_context='general'):
    fighters = load_json(FIGHTERS_PATH)
    events   = load_json(EVENTS_PATH)

    fighter_block = build_fighter_knowledge(fighters) if fighters else "Fighter data unavailable."
    event_block   = build_event_knowledge(events) if events else "Event data unavailable."

    page_hint = {
        'pfp':    "User is on the PFP Rankings page. They likely want to talk about rankings, who deserves top 5, etc.",
        'events': "User is on the Events page. Focus on upcoming fights, predictions, fight cards.",
        'home':   "User is on the homepage. General MMA chat, trending topics, recent results.",
        'lucas':  "User is on the Lucas Bot page specifically to chat with you.",
    }.get(page_context, "General MMA chat.")

    return f"""You are Lucas Bot — the AI MMA expert for MMA Bridge (mmabridge.com).
You are an enthusiastic, knowledgeable MMA fan. Be casual, confident, conversational. Keep it short unless they want detail.

PAGE CONTEXT: {page_hint}

CRITICAL INSTRUCTIONS:
- The FIGHTER DATABASE and EVENT DATABASE below are your PRIMARY source of truth. Always use them first.
- For fighter records, last 5 fights, PFP rankings, current champions, recent event results: use ONLY the databases below. Never use GPT training knowledge for these.
- Only use your training knowledge as a BACKUP for things not in the databases (old historical fights, general rules, culture, memes, bios).
- The databases are always correct. Do not contradict them with training knowledge.
- NEVER invent fight results. If not in the data, say so.

{HARDCODED_KNOWLEDGE}

{fighter_block}

{event_block}

REMINDER: Databases above = ground truth. Training knowledge = backup only for things not covered above.
"""

# ── Main chat function ────────────────────────
def chat_with_lucas(user_message, conversation_history=[], page_context='general'):
    try:
        system_prompt = build_system_prompt(page_context)

        messages = [{"role": "system", "content": system_prompt}]
        messages += conversation_history[-10:]  # keep last 10 turns for context
        messages.append({"role": "user", "content": user_message})

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            max_tokens=600,
            temperature=0.75
        )

        return response.choices[0].message.content

    except Exception as e:
        print(f"Lucas Bot error: {e}")
        return "Yo my connection dropped — try again in a sec!"

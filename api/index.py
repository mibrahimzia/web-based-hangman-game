"""FastAPI backend for Word Hunt. Vocabulary, sessions and scores live in Neon Postgres."""
import os
import re
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="Word Hunt API")
MAX_ATTEMPTS = 8
WORD_BANK_VERSION = "curated-common-english-v6"
_DB_INITIALIZED = False
DIFFICULTIES = {"easy", "medium", "hard"}
ROUND_REWARD = {"easy": 100, "medium": 250, "hard": 500}
WRONG_PENALTY = {"easy": 10, "medium": 20, "hard": 40}
DIFFICULTY_RULE = {"easy": "4–5 letters", "medium": "6–8 letters", "hard": "9+ letters"}


def get_connection():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise HTTPException(status_code=503, detail="DATABASE_URL is missing from Vercel environment variables.")
    try:
        return psycopg2.connect(url, connect_timeout=5, sslmode="require")
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Could not connect to Neon. Check the Vercel DATABASE_URL setting.") from exc


def init_db(conn=None):
    """Create schema and import the curated word bank once per warm server process."""
    global _DB_INITIALIZED
    owns_connection = conn is None
    if owns_connection:
        conn = get_connection()
    if _DB_INITIALIZED:
        if owns_connection:
            conn.close()
        return
    try:
        with conn.cursor() as cur:
            cur.execute("""CREATE TABLE IF NOT EXISTS words (
                id SERIAL PRIMARY KEY, word TEXT NOT NULL, difficulty TEXT NOT NULL,
                UNIQUE(word, difficulty))""")
            cur.execute("""CREATE TABLE IF NOT EXISTS players (
                id SERIAL PRIMARY KEY,
                name VARCHAR(40) NOT NULL,
                normalized_name VARCHAR(40) NOT NULL UNIQUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                total_score INTEGER NOT NULL DEFAULT 0,
                current_streak INTEGER NOT NULL DEFAULT 0,
                highest_streak INTEGER NOT NULL DEFAULT 0)""")
            cur.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS total_score INTEGER NOT NULL DEFAULT 0")
            cur.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS current_streak INTEGER NOT NULL DEFAULT 0")
            cur.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS highest_streak INTEGER NOT NULL DEFAULT 0")
            cur.execute("""CREATE TABLE IF NOT EXISTS game_sessions (
                id SERIAL PRIMARY KEY, word TEXT NOT NULL, difficulty TEXT NOT NULL,
                guessed_letters TEXT NOT NULL DEFAULT '', wrong_count INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'playing', player_name TEXT, score INTEGER,
                player_id INTEGER REFERENCES players(id),
                score_committed BOOLEAN NOT NULL DEFAULT FALSE)""")
            cur.execute("ALTER TABLE game_sessions ADD COLUMN IF NOT EXISTS player_id INTEGER REFERENCES players(id)")
            cur.execute("ALTER TABLE game_sessions ADD COLUMN IF NOT EXISTS score_committed BOOLEAN NOT NULL DEFAULT FALSE")
            cur.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
                migration_key TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""")
            cur.execute("SELECT 1 FROM schema_migrations WHERE migration_key='lifetime-score-v1'")
            if not cur.fetchone():
                cur.execute("""UPDATE players p SET total_score=GREATEST(p.total_score,COALESCE((
                    SELECT MAX(gs.score) FROM game_sessions gs
                    WHERE gs.player_id=p.id AND gs.status IN ('won','lost') AND gs.score IS NOT NULL
                ),0))""")
                cur.execute("UPDATE game_sessions SET score_committed=TRUE WHERE status IN ('won','lost')")
                cur.execute("""UPDATE game_sessions SET score=CASE difficulty
                    WHEN 'easy' THEN 100 WHEN 'medium' THEN 250 WHEN 'hard' THEN 500 ELSE 0 END
                    WHERE status='playing'""")
                cur.execute("INSERT INTO schema_migrations(migration_key) VALUES ('lifetime-score-v1')")
            cur.execute("""CREATE TABLE IF NOT EXISTS word_bank_meta (
                id INTEGER PRIMARY KEY CHECK (id = 1), version TEXT NOT NULL, imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""")
            cur.execute("SELECT version FROM word_bank_meta WHERE id=1")
            row = cur.fetchone()
            if not row or row[0] != WORD_BANK_VERSION:
                path = Path(__file__).resolve().parent.parent / "data" / "common_words.txt"
                try:
                    candidates = path.read_text(encoding="utf-8").splitlines()
                except OSError as exc:
                    raise HTTPException(status_code=503, detail="The server word bank file is missing.") from exc
                blocked_words = set("""ibm amd usc amp blvd trembl struct johnny nancy nutten travesti tft cfr scsi mhz ghz rpm hdtv xhtml phpbb zdnet lycos gamespot myspace netscape macromedia compaq packard hewlett mercedes chevrolet nissan yamaha verizon reuters espn cnn cbs nhl nba mlb ncaa ieee nasa fda ssl dns tcp rfc oem plc atm cgi seo jpg gif png html xml ftp http https url uri api sdk cpu gpu ram rom usb dvd cdrom vhs mpg mp3 mp4 jpeg wifi lan wan vpn isp bbc nyc hrs mins secs dept approx aka asap btw lol omg lmao tbh idk imo fyi inc ltd llc corp usa eu nato islamic muslim christians jews deutsch svenska norweg danish estonian latvian lithuanian slovak slovene czech polish greek latin russian chinese japanese korean hindi urdu bengali punjabi tamil telugu marathi swahili turkish persian portuguese spanish french german italian dutch welsh gaelic basque cyprus kenya cuba saudi nepal delhi rio peru chad malta samoa fiji laos mali oman qatar yemen ghana togo benin niger sudan libya congo rwanda zambia malawi angola serbia croatia romania bulgaria albania armenia georgia bristol glasgow montreal ottawa calgary manhattan brooklyn oakland memphis honolulu rochester arlington louisville newcastle queensland yorkshire madonna britney eminem justin jimmy carter marc albert warren barry marie kate karen margaret ralph mitchell wright collins parker kennedy cooper walter vincent francis dennis charlie graham brad todd doug dale monica ashley heather christina benjamin catherine julie janet helen lauren alice joel amy pete mrs phd mba cfo ceo cto cio vii viii ix xi xii sur por thru herein thereof unto thee thy thou wanna gotta gonna cant thats didnt doesnt isnt wasnt werent wouldnt couldnt shouldnt mustnt youre theyre weve youve ive im hes shes lets theres heres whos whats wheres whens whys hows dont wont shant aint ampersand peeing upskirts vibrators squirting titten dicks xanax tramadol levitra intel microsoft google yahoo ebay cisco oracle nokia acer asus dell nvidia qualcomm sony adobe amazon twitter facebook tiktok instagram youtube wikipedia wordpress drupal firefox chrome safari opera android iphone ipad xbox playstation nintendo wii atari dell hp ibm corp ltd llc inc gmbh plc fbi cia nsa mi5 mi6 unicef unesco who ngo ngos irs nasa usps fedex ups DHL ikea ikea ikea lego adidas puma reebok nike disney pixar netflix hulu hbo espn2 cnet pcmag zdnet gizmodo engadget arxiv doi isbn issn pdf docx xlsx pptx tiff eps svg json yaml toml sql nosql php perl ruby swift kotlin scala rust golang nodejs npm pip git svn svnkit tcpip udp ipsec httpd apache nginx linux ubuntu debian centos redhat fedora archlinux windows macos ios android unix dos bios firmware middleware freeware shareware malware spyware ransomware trojan botnet captcha oauth jwt smtp imap pop3 ftp sftp ssh telnet rdp vnc dnssec dhcp icmp ipv6 ipv4 localhost loopback stackoverflow github gitlab bitbucket jira slack discord zoom teams skype twitch reddit tumblr pinterest linkedin snapchat whatsapp telegram signal wechat weibo baidu alibaba tencent huawei xiaomi oppo vivo lenovo acer asus toshiba panasonic samsung lg sharp philips bosch siemens ge whirlpool maytag kenmore tesla toyota honda ford chevy buick kia hyundai mazda subaru mitsubishi suzuki volkswagen audi bmw mercedes benz porsche ferrari lamborghini bugatti maserati bentley rollsroyce astonmartin jaguar landrover volvo saab peugeot renault citroen fiat skoda seat opel vauxhall daewoo saturn pontiac oldsmobile hummer jeep dodge chrysler cadillac lincoln infiniti acura lexus genesis rivian lucid polestar spacex starlink boeing airbus lockheed raytheon northrop grumman siemens ge ibm amd usc trembl struct blvd amp nutten travesti tft cfr scsi mhz ghz rpm hdtv xhtml phpbb zdnet lycos gamespot myspace netscape macromedia compaq packard hewlett verizon reuters espn cnn cbs nhl nba mlb ncaa ieee fda ssl dns tcp rfc oem plc atm cgi seo jpg gif png html xml ftp http https url uri api sdk cpu gpu ram rom usb dvd cdrom vhs mpg mp3 mp4 jpeg wifi lan wan vpn isp bbc nyc hrs mins secs dept approx aka asap btw lol omg lmao tbh idk imo fyi cfo ceo cto cio vii viii ix xi xii upskirts vibrators squirting titten dicks xanax""".split())
                valid = []
                seen = set()
                for item in candidates:
                    word = item.strip().lower()
                    if not re.fullmatch(r"[a-z]{4,20}", word) or word in seen or word in blocked_words:
                        continue
                    seen.add(word)
                    difficulty = "easy" if len(word) <= 5 else "medium" if len(word) <= 8 else "hard"
                    valid.append((word, difficulty))
                if len(valid) < 5000:
                    raise HTTPException(status_code=503, detail="The word bank must contain at least 5,000 valid words.")
                cur.execute("DELETE FROM words")
                execute_values(cur, "INSERT INTO words(word,difficulty) VALUES %s", valid, page_size=1000)
                cur.execute("""INSERT INTO word_bank_meta(id,version) VALUES (1,%s)
                    ON CONFLICT(id) DO UPDATE SET version=EXCLUDED.version, imported_at=NOW()""", (WORD_BANK_VERSION,))
        conn.commit()
        _DB_INITIALIZED = True
    except Exception:
        conn.rollback()
        raise
    finally:
        if owns_connection:
            conn.close()


def mask_word(word, guessed):
    return " ".join(ch if ch in guessed else "_" for ch in word)


class GuessRequest(BaseModel):
    session_id: int
    letter: str = Field(min_length=1, max_length=8)


@app.get("/health")
@app.get("/api/health")
def health():
    conn = get_connection()
    try:
        init_db(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM words")
            word_count = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM players")
            player_count = cur.fetchone()[0]
        return {"ok": True, "database": "connected", "words": word_count, "players": player_count}
    finally:
        conn.close()


@app.get("/new-game")
@app.get("/api/new-game")
def new_game(difficulty: str = "easy", player_name: str = ""):
    difficulty = difficulty.lower()
    if difficulty not in DIFFICULTIES:
        raise HTTPException(status_code=400, detail="Choose easy, medium, or hard.")
    player_name = re.sub(r"\s+", " ", player_name).strip()
    if not player_name or len(player_name) > 40 or not re.search(r"[A-Za-z0-9]", player_name):
        raise HTTPException(status_code=400, detail="Enter a player name (1–40 characters) before starting.")
    normalized = player_name.casefold()
    conn = get_connection()
    try:
        init_db(conn)
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO players(name,normalized_name) VALUES (%s,%s)
                ON CONFLICT(normalized_name) DO UPDATE SET name=EXCLUDED.name RETURNING id""", (player_name, normalized))
            player_id = cur.fetchone()[0]
            bounds = {"easy": (4, 5), "medium": (6, 8), "hard": (9, 20)}
            low, high = bounds[difficulty]
            cur.execute("""SELECT word FROM words
                WHERE difficulty=%s AND length(word) BETWEEN %s AND %s
                ORDER BY RANDOM() LIMIT 1""", (difficulty, low, high))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=503, detail=f"No playable words are available for {difficulty}.")
            word = row[0]
            cur.execute("INSERT INTO game_sessions(word,difficulty,player_name,player_id,score,score_committed) VALUES (%s,%s,%s,%s,%s,FALSE) RETURNING id", (word, difficulty, player_name, player_id, ROUND_REWARD[difficulty]))
            session_id = cur.fetchone()[0]
            cur.execute("SELECT total_score,current_streak,highest_streak FROM players WHERE id=%s", (player_id,))
            total_score, current_streak, highest_streak = cur.fetchone()
        conn.commit()
        return {
            "session_id": session_id,
            "masked_word": mask_word(word, set()),
            "wrong_count": 0,
            "max_attempts": MAX_ATTEMPTS,
            "status": "playing",
            "hint": "Loading your word-specific dictionary hint…",
            "difficulty_rule": DIFFICULTY_RULE[difficulty],
            "player_name": player_name,
            "score": ROUND_REWARD[difficulty],
            "round_reward": ROUND_REWARD[difficulty],
            "total_score": total_score,
            "current_streak": current_streak,
            "highest_streak": highest_streak,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@app.post("/guess")
@app.post("/api/guess")
def guess(payload: GuessRequest):
    letter = payload.letter.strip().lower()
    if len(letter) != 1 or letter not in "abcdefghijklmnopqrstuvwxyz":
        raise HTTPException(status_code=400, detail="Enter one letter from A to Z.")
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT word,guessed_letters,wrong_count,status,difficulty,player_id,
                COALESCE(score,0),player_name,score_committed
                FROM game_sessions WHERE id=%s FOR UPDATE""", (payload.session_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Game session not found. Start a new round.")
            word, stored, wrong, status, difficulty, player_id, score, player_name, score_committed = row
            guessed = set(stored.split(",")) if stored else set()
            total_score = current_streak = highest_streak = 0
            if status == "playing" and letter not in guessed:
                guessed.add(letter)
                if letter not in word:
                    wrong += 1
                    score = max(0, score - WRONG_PENALTY[difficulty])
                status = "won" if all(ch in guessed for ch in set(word)) else ("lost" if wrong >= MAX_ATTEMPTS else "playing")
                if status == "lost":
                    score = 0
                cur.execute("""UPDATE game_sessions SET guessed_letters=%s,wrong_count=%s,status=%s,score=%s
                    WHERE id=%s""", (",".join(sorted(guessed)), wrong, status, score, payload.session_id))
                if status == "won" and not score_committed and player_id is not None:
                    cur.execute("""UPDATE players SET total_score=total_score+%s,
                        current_streak=current_streak+1,
                        highest_streak=GREATEST(highest_streak,current_streak+1)
                        WHERE id=%s RETURNING total_score,current_streak,highest_streak""", (score, player_id))
                    total_score, current_streak, highest_streak = cur.fetchone()
                    cur.execute("UPDATE game_sessions SET score_committed=TRUE WHERE id=%s", (payload.session_id,))
                elif status == "lost" and player_id is not None:
                    cur.execute("UPDATE players SET current_streak=0 WHERE id=%s RETURNING total_score,current_streak,highest_streak", (player_id,))
                    total_score, current_streak, highest_streak = cur.fetchone()
                elif player_id is not None:
                    cur.execute("SELECT total_score,current_streak,highest_streak FROM players WHERE id=%s", (player_id,))
                    total_score, current_streak, highest_streak = cur.fetchone()
            elif player_id is not None:
                cur.execute("SELECT total_score,current_streak,highest_streak FROM players WHERE id=%s", (player_id,))
                total_score, current_streak, highest_streak = cur.fetchone()
            conn.commit()
            return {
                "masked_word": word if status == "lost" else mask_word(word, guessed),
                "wrong_count": wrong, "status": status, "score": score,
                "total_score": total_score, "current_streak": current_streak,
                "highest_streak": highest_streak, "player_name": player_name,
                "correct_guess": letter in word, "meaning_word": word if status in ("won", "lost") else None
            }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@app.get("/leaderboard")
@app.get("/api/leaderboard")
def leaderboard():
    conn = get_connection()
    try:
        init_db(conn)
        with conn.cursor() as cur:
            cur.execute("""SELECT p.name,p.total_score,p.highest_streak,p.current_streak,
                    COALESCE(latest.difficulty,'easy')
                FROM players p
                LEFT JOIN LATERAL (
                    SELECT gs.difficulty FROM game_sessions gs
                    WHERE gs.player_id=p.id ORDER BY gs.id DESC LIMIT 1
                ) latest ON TRUE
                WHERE p.total_score > 0 OR p.highest_streak > 0
                ORDER BY p.total_score DESC,p.highest_streak DESC,p.name ASC LIMIT 50""")
            rows = cur.fetchall()
        return [{"player_name": r[0], "score": r[1], "highest_streak": r[2],
                 "current_streak": r[3], "difficulty": r[4]} for r in rows]
    finally:
        conn.close()


@app.post("/end-game/{session_id}")
@app.post("/api/end-game/{session_id}")
def end_game(session_id: int):
    """Abandon an in-progress round without treating it as a loss."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""UPDATE game_sessions SET status='abandoned'
                WHERE id=%s AND status='playing' RETURNING id""", (session_id,))
            row = cur.fetchone()
            if not row:
                cur.execute("SELECT status FROM game_sessions WHERE id=%s", (session_id,))
                existing = cur.fetchone()
                if not existing:
                    raise HTTPException(status_code=404, detail="Game session not found.")
                conn.commit()
                return {"status": existing[0], "message": "This round is already finished."}
        conn.commit()
        return {"status": "abandoned", "message": "Round ended. Your lifetime score and streak were kept."}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@app.get("/hint/{session_id}")
@app.get("/api/hint/{session_id}")
def word_hint(session_id: int):
    """Return a difficulty-adjusted clue and definition, with an offline fallback."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT word,difficulty FROM game_sessions WHERE id=%s", (session_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Game session not found.")
            word, difficulty = row
    finally:
        conn.close()

    # Small offline dictionary for common words: hints still work if the third-party
    # dictionary is unavailable. Unknown words receive a non-breaking structural clue.
    local_hints = {
        "code": ("Instructions written for a computer to follow.", "A programmer may write this to make an app work.", "Noun"),
        "website": ("A collection of pages you can visit on the internet.", "You might open one to read news or shop online.", "Noun"),
        "compiler": ("A program that translates source code into another form a computer can use.", "Developers use this tool when building software.", "Noun"),
        "apple": ("A crisp fruit that can be red, green, or yellow.", "You might pack one as a snack.", "Noun"),
        "water": ("A clear liquid essential for life.", "People drink it to stay hydrated.", "Noun"),
        "house": ("A building where people live.", "It may have rooms, a kitchen, and a roof.", "Noun"),
        "music": ("Sounds arranged to create rhythm, melody, or harmony.", "People listen to it for fun or relaxation.", "Noun"),
        "book": ("A set of written or printed pages bound together.", "You might borrow one from a library.", "Noun"),
        "computer": ("An electronic machine that processes information.", "You might use one to study, work, or play games.", "Noun"),
        "keyboard": ("A set of keys used to enter letters or commands.", "You use one to type on a computer.", "Noun"),
        "internet": ("A worldwide network connecting computers and devices.", "You use it to visit websites and send messages.", "Noun"),
        "garden": ("An area where flowers, vegetables, or other plants are grown.", "Someone might grow tomatoes or roses here.", "Noun"),
        "library": ("A place or collection where books and other resources are available.", "Students often go here to read or study.", "Noun"),
        "science": ("The systematic study of the natural and physical world.", "It includes subjects such as biology and chemistry.", "Noun"),
        "network": ("A group of connected people, computers, or things.", "Devices use one to communicate with each other.", "Noun"),
    }
    local = local_hints.get(word.lower())
    definitions = []
    examples = []
    parts_of_speech = []
    api_failure = None
    url = "https://api.dictionaryapi.dev/api/v2/entries/en/" + urllib.parse.quote(word)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "WordHunt-EF101/1.0"})
        with urllib.request.urlopen(req, timeout=3.0) as response:
            data = json.loads(response.read(400_000).decode("utf-8"))
        for entry in data if isinstance(data, list) else []:
            for meaning in entry.get("meanings", []):
                pos = re.sub(r"[^a-z -]", "", str(meaning.get("partOfSpeech", "")).lower()).strip()
                if pos and pos not in parts_of_speech:
                    parts_of_speech.append(pos)
                for item in meaning.get("definitions", []):
                    definition = re.sub(r"\\s+", " ", str(item.get("definition", "")).strip())
                    if (definition and not re.search(r"\\b" + re.escape(word) + r"\\b", definition, re.IGNORECASE)
                            and len(definition) <= 240):
                        definitions.append(definition)
                    example = re.sub(r"\\s+", " ", str(item.get("example", "")).strip())
                    if (example and len(example) <= 220
                            and not re.search(r"\\b" + re.escape(word) + r"\\b", example, re.IGNORECASE)):
                        examples.append(example)
        if not definitions and not parts_of_speech:
            api_failure = "no_entry"
    except urllib.error.HTTPError as exc:
        api_failure = "http_" + str(exc.code)
    except (OSError, ValueError, TimeoutError) as exc:
        api_failure = type(exc).__name__.lower()

    if api_failure:
        import logging
        logging.warning("Dictionary lookup failed for session %s (%s)", session_id, api_failure)

    local_definition, local_example, local_pos = local if local else (None, None, None)
    definition = definitions[0] if definitions else local_definition
    example = examples[0] if examples else local_example
    pos = parts_of_speech[0] if parts_of_speech else local_pos
    meaning = definition or "No definition is available offline for this word yet."
    if difficulty == "hard":
        hint = (pos or "Word").capitalize()
    elif difficulty == "medium":
        hint = definition or f"A {len(word)}-letter English word beginning with {word[0].upper()}."
    else:
        hint = definition or f"A {len(word)}-letter English word beginning with {word[0].upper()}."
        if example:
            hint += " Example: " + example
    return {
        "hint": hint,
        "meaning": meaning,
        "part_of_speech": pos,
        "hint_source": "dictionary_api" if definitions or parts_of_speech else ("offline" if local else "fallback"),
    }
"""FastAPI backend for Word Hunt. Vocabulary, sessions and scores live in Neon Postgres."""
import os
import re
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="Word Hunt API")
MAX_ATTEMPTS = 8
WORD_BANK_VERSION = "curated-common-english-v6"
_DB_INITIALIZED = False
DIFFICULTIES = {"easy", "medium", "hard"}
ROUND_REWARD = {"easy": 100, "medium": 250, "hard": 500}
WRONG_PENALTY = {"easy": 10, "medium": 20, "hard": 40}
DIFFICULTY_RULE = {"easy": "4–5 letters", "medium": "6–8 letters", "hard": "9+ letters"}


def get_connection():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise HTTPException(status_code=503, detail="DATABASE_URL is missing from Vercel environment variables.")
    try:
        return psycopg2.connect(url, connect_timeout=5, sslmode="require")
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Could not connect to Neon. Check the Vercel DATABASE_URL setting.") from exc


def init_db(conn=None):
    """Create schema and import the curated word bank once per warm server process."""
    global _DB_INITIALIZED
    owns_connection = conn is None
    if owns_connection:
        conn = get_connection()
    if _DB_INITIALIZED:
        if owns_connection:
            conn.close()
        return
    try:
        with conn.cursor() as cur:
            cur.execute("""CREATE TABLE IF NOT EXISTS words (
                id SERIAL PRIMARY KEY, word TEXT NOT NULL, difficulty TEXT NOT NULL,
                UNIQUE(word, difficulty))""")
            cur.execute("""CREATE TABLE IF NOT EXISTS players (
                id SERIAL PRIMARY KEY,
                name VARCHAR(40) NOT NULL,
                normalized_name VARCHAR(40) NOT NULL UNIQUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                total_score INTEGER NOT NULL DEFAULT 0,
                current_streak INTEGER NOT NULL DEFAULT 0,
                highest_streak INTEGER NOT NULL DEFAULT 0)""")
            cur.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS total_score INTEGER NOT NULL DEFAULT 0")
            cur.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS current_streak INTEGER NOT NULL DEFAULT 0")
            cur.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS highest_streak INTEGER NOT NULL DEFAULT 0")
            cur.execute("""CREATE TABLE IF NOT EXISTS game_sessions (
                id SERIAL PRIMARY KEY, word TEXT NOT NULL, difficulty TEXT NOT NULL,
                guessed_letters TEXT NOT NULL DEFAULT '', wrong_count INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'playing', player_name TEXT, score INTEGER,
                player_id INTEGER REFERENCES players(id),
                score_committed BOOLEAN NOT NULL DEFAULT FALSE)""")
            cur.execute("ALTER TABLE game_sessions ADD COLUMN IF NOT EXISTS player_id INTEGER REFERENCES players(id)")
            cur.execute("ALTER TABLE game_sessions ADD COLUMN IF NOT EXISTS score_committed BOOLEAN NOT NULL DEFAULT FALSE")
            cur.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
                migration_key TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""")
            cur.execute("SELECT 1 FROM schema_migrations WHERE migration_key='lifetime-score-v1'")
            if not cur.fetchone():
                cur.execute("""UPDATE players p SET total_score=GREATEST(p.total_score,COALESCE((
                    SELECT MAX(gs.score) FROM game_sessions gs
                    WHERE gs.player_id=p.id AND gs.status IN ('won','lost') AND gs.score IS NOT NULL
                ),0))""")
                cur.execute("UPDATE game_sessions SET score_committed=TRUE WHERE status IN ('won','lost')")
                cur.execute("""UPDATE game_sessions SET score=CASE difficulty
                    WHEN 'easy' THEN 100 WHEN 'medium' THEN 250 WHEN 'hard' THEN 500 ELSE 0 END
                    WHERE status='playing'""")
                cur.execute("INSERT INTO schema_migrations(migration_key) VALUES ('lifetime-score-v1')")
            cur.execute("""CREATE TABLE IF NOT EXISTS word_bank_meta (
                id INTEGER PRIMARY KEY CHECK (id = 1), version TEXT NOT NULL, imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""")
            cur.execute("SELECT version FROM word_bank_meta WHERE id=1")
            row = cur.fetchone()
            if not row or row[0] != WORD_BANK_VERSION:
                path = Path(__file__).resolve().parent.parent / "data" / "common_words.txt"
                try:
                    candidates = path.read_text(encoding="utf-8").splitlines()
                except OSError as exc:
                    raise HTTPException(status_code=503, detail="The server word bank file is missing.") from exc
                blocked_words = set("""ibm amd usc amp blvd trembl struct johnny nancy nutten travesti tft cfr scsi mhz ghz rpm hdtv xhtml phpbb zdnet lycos gamespot myspace netscape macromedia compaq packard hewlett mercedes chevrolet nissan yamaha verizon reuters espn cnn cbs nhl nba mlb ncaa ieee nasa fda ssl dns tcp rfc oem plc atm cgi seo jpg gif png html xml ftp http https url uri api sdk cpu gpu ram rom usb dvd cdrom vhs mpg mp3 mp4 jpeg wifi lan wan vpn isp bbc nyc hrs mins secs dept approx aka asap btw lol omg lmao tbh idk imo fyi inc ltd llc corp usa eu nato islamic muslim christians jews deutsch svenska norweg danish estonian latvian lithuanian slovak slovene czech polish greek latin russian chinese japanese korean hindi urdu bengali punjabi tamil telugu marathi swahili turkish persian portuguese spanish french german italian dutch welsh gaelic basque cyprus kenya cuba saudi nepal delhi rio peru chad malta samoa fiji laos mali oman qatar yemen ghana togo benin niger sudan libya congo rwanda zambia malawi angola serbia croatia romania bulgaria albania armenia georgia bristol glasgow montreal ottawa calgary manhattan brooklyn oakland memphis honolulu rochester arlington louisville newcastle queensland yorkshire madonna britney eminem justin jimmy carter marc albert warren barry marie kate karen margaret ralph mitchell wright collins parker kennedy cooper walter vincent francis dennis charlie graham brad todd doug dale monica ashley heather christina benjamin catherine julie janet helen lauren alice joel amy pete mrs phd mba cfo ceo cto cio vii viii ix xi xii sur por thru herein thereof unto thee thy thou wanna gotta gonna cant thats didnt doesnt isnt wasnt werent wouldnt couldnt shouldnt mustnt youre theyre weve youve ive im hes shes lets theres heres whos whats wheres whens whys hows dont wont shant aint ampersand peeing upskirts vibrators squirting titten dicks xanax tramadol levitra intel microsoft google yahoo ebay cisco oracle nokia acer asus dell nvidia qualcomm sony adobe amazon twitter facebook tiktok instagram youtube wikipedia wordpress drupal firefox chrome safari opera android iphone ipad xbox playstation nintendo wii atari dell hp ibm corp ltd llc inc gmbh plc fbi cia nsa mi5 mi6 unicef unesco who ngo ngos irs nasa usps fedex ups DHL ikea ikea ikea lego adidas puma reebok nike disney pixar netflix hulu hbo espn2 cnet pcmag zdnet gizmodo engadget arxiv doi isbn issn pdf docx xlsx pptx tiff eps svg json yaml toml sql nosql php perl ruby swift kotlin scala rust golang nodejs npm pip git svn svnkit tcpip udp ipsec httpd apache nginx linux ubuntu debian centos redhat fedora archlinux windows macos ios android unix dos bios firmware middleware freeware shareware malware spyware ransomware trojan botnet captcha oauth jwt smtp imap pop3 ftp sftp ssh telnet rdp vnc dnssec dhcp icmp ipv6 ipv4 localhost loopback stackoverflow github gitlab bitbucket jira slack discord zoom teams skype twitch reddit tumblr pinterest linkedin snapchat whatsapp telegram signal wechat weibo baidu alibaba tencent huawei xiaomi oppo vivo lenovo acer asus toshiba panasonic samsung lg sharp philips bosch siemens ge whirlpool maytag kenmore tesla toyota honda ford chevy buick kia hyundai mazda subaru mitsubishi suzuki volkswagen audi bmw mercedes benz porsche ferrari lamborghini bugatti maserati bentley rollsroyce astonmartin jaguar landrover volvo saab peugeot renault citroen fiat skoda seat opel vauxhall daewoo saturn pontiac oldsmobile hummer jeep dodge chrysler cadillac lincoln infiniti acura lexus genesis rivian lucid polestar spacex starlink boeing airbus lockheed raytheon northrop grumman siemens ge ibm amd usc trembl struct blvd amp nutten travesti tft cfr scsi mhz ghz rpm hdtv xhtml phpbb zdnet lycos gamespot myspace netscape macromedia compaq packard hewlett verizon reuters espn cnn cbs nhl nba mlb ncaa ieee fda ssl dns tcp rfc oem plc atm cgi seo jpg gif png html xml ftp http https url uri api sdk cpu gpu ram rom usb dvd cdrom vhs mpg mp3 mp4 jpeg wifi lan wan vpn isp bbc nyc hrs mins secs dept approx aka asap btw lol omg lmao tbh idk imo fyi cfo ceo cto cio vii viii ix xi xii upskirts vibrators squirting titten dicks xanax""".split())
                valid = []
                seen = set()
                for item in candidates:
                    word = item.strip().lower()
                    if not re.fullmatch(r"[a-z]{4,20}", word) or word in seen or word in blocked_words:
                        continue
                    seen.add(word)
                    difficulty = "easy" if len(word) <= 5 else "medium" if len(word) <= 8 else "hard"
                    valid.append((word, difficulty))
                if len(valid) < 5000:
                    raise HTTPException(status_code=503, detail="The word bank must contain at least 5,000 valid words.")
                cur.execute("DELETE FROM words")
                execute_values(cur, "INSERT INTO words(word,difficulty) VALUES %s", valid, page_size=1000)
                cur.execute("""INSERT INTO word_bank_meta(id,version) VALUES (1,%s)
                    ON CONFLICT(id) DO UPDATE SET version=EXCLUDED.version, imported_at=NOW()""", (WORD_BANK_VERSION,))
        conn.commit()
        _DB_INITIALIZED = True
    except Exception:
        conn.rollback()
        raise
    finally:
        if owns_connection:
            conn.close()


def mask_word(word, guessed):
    return " ".join(ch if ch in guessed else "_" for ch in word)


class GuessRequest(BaseModel):
    session_id: int
    letter: str = Field(min_length=1, max_length=8)


@app.get("/health")
@app.get("/api/health")
def health():
    conn = get_connection()
    try:
        init_db(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM words")
            word_count = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM players")
            player_count = cur.fetchone()[0]
        return {"ok": True, "database": "connected", "words": word_count, "players": player_count}
    finally:
        conn.close()


@app.get("/new-game")
@app.get("/api/new-game")

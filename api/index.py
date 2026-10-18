"""FastAPI backend for Word Hunt. Scores and player names are persisted in Neon Postgres."""
import os
import re
import psycopg2
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="Word Hunt API")
MAX_ATTEMPTS = 8
DIFFICULTIES = {"easy", "medium", "hard"}
BONUS = {"easy": 0, "medium": 20, "hard": 40}
HINTS = {
    "easy": "Everyday words: familiar things, places, and actions.",
    "medium": "A common word with a little more to uncover.",
    "hard": "A longer word from everyday life and the world around you.",
}
SAMPLE_WORDS = {
    "easy": ["apple", "chair", "cloud", "dream", "flame", "grape", "house", "lemon", "music", "plant", "river", "smile", "stone", "table", "water"],
    "medium": ["airport", "battery", "captain", "diamond", "evening", "freedom", "journey", "lantern", "machine", "notebook", "picture", "rainbow", "station", "thunder", "village"],
    "hard": ["adventure", "basketball", "celebration", "destination", "environment", "friendship", "generation", "imagination", "kaleidoscope", "lighthouse", "playground", "technology", "understand", "watermelon", "wonderful"],
}

def get_connection():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise HTTPException(status_code=503, detail="DATABASE_URL is missing from Vercel environment variables.")
    try:
        return psycopg2.connect(url, connect_timeout=8, sslmode="require")
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Could not connect to Neon. Check the Vercel DATABASE_URL setting.") from exc

def init_db():
    """Idempotent schema setup; never inserts fake players or scores."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""CREATE TABLE IF NOT EXISTS words (
                id SERIAL PRIMARY KEY, word TEXT NOT NULL, difficulty TEXT NOT NULL,
                UNIQUE(word, difficulty))""")
            cur.execute("""CREATE TABLE IF NOT EXISTS players (
                id SERIAL PRIMARY KEY,
                name VARCHAR(40) NOT NULL,
                normalized_name VARCHAR(40) NOT NULL UNIQUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""")
            cur.execute("""CREATE TABLE IF NOT EXISTS game_sessions (
                id SERIAL PRIMARY KEY, word TEXT NOT NULL, difficulty TEXT NOT NULL,
                guessed_letters TEXT NOT NULL DEFAULT '', wrong_count INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'playing', player_name TEXT, score INTEGER,
                player_id INTEGER REFERENCES players(id))""")
            cur.execute("ALTER TABLE game_sessions ADD COLUMN IF NOT EXISTS player_id INTEGER REFERENCES players(id)")
            for difficulty, words in SAMPLE_WORDS.items():
                for word in words:
                    cur.execute("""INSERT INTO words(word,difficulty)
                        SELECT %s,%s WHERE NOT EXISTS
                        (SELECT 1 FROM words WHERE lower(word)=lower(%s) AND difficulty=%s)""",
                        (word, difficulty, word, difficulty))
        conn.commit()
    finally:
        conn.close()

def mask_word(word, guessed):
    return " ".join(ch if ch in guessed else "_" for ch in word)

class GuessRequest(BaseModel):
    session_id: int
    letter: str = Field(min_length=1, max_length=8)

class SaveScoreRequest(BaseModel):
    session_id: int
    player_name: str = Field(min_length=1, max_length=40)

@app.get("/health")
def health():
    try:
        init_db()
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM words")
                word_count = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM players")
                player_count = cur.fetchone()[0]
            return {"ok": True, "database": "connected", "words": word_count, "players": player_count}
        finally:
            conn.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database setup failed. Check that the Neon database user can create/alter tables.") from exc

@app.get("/new-game")
def new_game(difficulty: str = "easy"):
    difficulty = difficulty.lower()
    if difficulty not in DIFFICULTIES:
        raise HTTPException(status_code=400, detail="Choose easy, medium, or hard.")
    init_db()
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            bounds = {"easy": (3, 5), "medium": (6, 8), "hard": (9, 30)}
            low, high = bounds[difficulty]
            # Preserve the existing difficulty assignment but also enforce length,
            # and reject phrases, punctuation, and non-ASCII words for fair gameplay.
            cur.execute("""SELECT word FROM words
                WHERE lower(difficulty)=%s
                  AND length(word) BETWEEN %s AND %s
                  AND lower(word) ~ '^[a-z]+$'
                ORDER BY RANDOM() LIMIT 1""", (difficulty, low, high))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=503, detail=f"No usable {difficulty} words found. Check the words table's difficulty labels and word lengths.")
            word = row[0].lower()
            cur.execute("INSERT INTO game_sessions(word,difficulty) VALUES (%s,%s) RETURNING id", (word, difficulty))
            session_id = cur.fetchone()[0]
        conn.commit()
    finally:
        conn.close()
    return {"session_id": session_id, "masked_word": mask_word(word, set()), "wrong_count": 0, "max_attempts": MAX_ATTEMPTS, "status": "playing", "hint": HINTS[difficulty]}

@app.post("/guess")
def guess(payload: GuessRequest):
    letter = payload.letter.strip().lower()
    if len(letter) != 1 or letter not in "abcdefghijklmnopqrstuvwxyz":
        raise HTTPException(status_code=400, detail="Enter one letter from A to Z.")
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT word,guessed_letters,wrong_count,status FROM game_sessions WHERE id=%s FOR UPDATE", (payload.session_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Game session not found. Start a new round.")
            word, stored, wrong, status = row
            guessed = set(stored.split(",")) if stored else set()
            if status == "playing" and letter not in guessed:
                guessed.add(letter)
                if letter not in word:
                    wrong += 1
                status = "won" if all(ch in guessed for ch in set(word)) else ("lost" if wrong >= MAX_ATTEMPTS else "playing")
                cur.execute("UPDATE game_sessions SET guessed_letters=%s,wrong_count=%s,status=%s WHERE id=%s",
                            (",".join(sorted(guessed)), wrong, status, payload.session_id))
        conn.commit()
    finally:
        conn.close()
    return {"masked_word": word if status == "lost" else mask_word(word, guessed), "wrong_count": wrong, "status": status}

@app.post("/save-score")
def save_score(payload: SaveScoreRequest):
    name = re.sub(r"\s+", " ", payload.player_name).strip()
    if not name or len(name) > 40 or not re.search(r"[A-Za-z0-9]", name):
        raise HTTPException(status_code=400, detail="Enter a name between 1 and 40 characters.")
    normalized = name.casefold()
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT difficulty,wrong_count,status,score FROM game_sessions WHERE id=%s FOR UPDATE", (payload.session_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Game session not found.")
            difficulty, wrong, status, old_score = row
            if status != "won":
                raise HTTPException(status_code=400, detail="A score can only be saved after a real win.")
            if old_score is not None:
                raise HTTPException(status_code=409, detail="This round's score has already been saved.")
            cur.execute("""INSERT INTO players(name,normalized_name) VALUES (%s,%s)
                ON CONFLICT(normalized_name) DO UPDATE SET name=EXCLUDED.name
                RETURNING id""", (name, normalized))
            player_id = cur.fetchone()[0]
            score = max(0, (MAX_ATTEMPTS - wrong) * 10 + BONUS[difficulty])
            cur.execute("UPDATE game_sessions SET player_name=%s,player_id=%s,score=%s WHERE id=%s",
                        (name, player_id, score, payload.session_id))
        conn.commit()
    finally:
        conn.close()
    return {"score": score, "player_name": name}

@app.get("/leaderboard")
def leaderboard():
    init_db()
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # One entry per real player: their personal best, ordered highest first.
            cur.execute("""SELECT p.name, best.score, best.difficulty FROM players p
                JOIN LATERAL (
                    SELECT gs.score,gs.difficulty FROM game_sessions gs
                    WHERE gs.player_id=p.id AND gs.status='won' AND gs.score IS NOT NULL
                    ORDER BY gs.score DESC,gs.id ASC LIMIT 1
                ) best ON TRUE
                ORDER BY best.score DESC,p.name ASC LIMIT 50""")
            rows = cur.fetchall()
    finally:
        conn.close()
    return [{"player_name": r[0], "score": r[1], "difficulty": r[2]} for r in rows]

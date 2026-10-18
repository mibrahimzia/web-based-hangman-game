"""FastAPI backend for the EF-101 Hangman game."""
import os
import random
import re
import psycopg2
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="EF-101 Hangman API")
MAX_ATTEMPTS = 8
DIFFICULTIES = {"easy", "medium", "hard"}
BONUS = {"easy": 0, "medium": 20, "hard": 40}
HINTS = {"easy": "Everyday words, usually things you can see or use.", "medium": "A familiar place, object, or idea with a few more letters.", "hard": "A longer word connected to the world around you."}
SAMPLE_WORDS = {
    "easy": ["apple", "chair", "cloud", "dream", "flame", "grape", "house", "lemon", "music", "plant", "river", "smile", "stone", "table", "water"],
    "medium": ["airport", "battery", "captain", "diamond", "evening", "freedom", "journey", "lantern", "machine", "notebook", "picture", "rainbow", "station", "thunder", "village"],
    "hard": ["adventure", "basketball", "celebration", "destination", "environment", "friendship", "generation", "imagination", "kaleidoscope", "lighthouse", "playground", "technology", "understand", "watermelon", "wonderful"],
}

def get_connection():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise HTTPException(status_code=503, detail="DATABASE_URL is not configured in the deployment environment.")
    return psycopg2.connect(url)

def init_db():
    """Initialize tables and a small starter word set; add the full course word bank in Neon."""
    connection = get_connection()
    try:
        with connection.cursor() as cur:
            cur.execute("""CREATE TABLE IF NOT EXISTS words (
                id SERIAL PRIMARY KEY, word TEXT NOT NULL, difficulty TEXT NOT NULL,
                UNIQUE(word, difficulty))""")
            cur.execute("""CREATE TABLE IF NOT EXISTS game_sessions (
                id SERIAL PRIMARY KEY, word TEXT NOT NULL, difficulty TEXT NOT NULL,
                guessed_letters TEXT NOT NULL DEFAULT '', wrong_count INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'playing', player_name TEXT, score INTEGER)""")
            for difficulty, words in SAMPLE_WORDS.items():
                for word in words:
                    cur.execute("INSERT INTO words (word, difficulty) SELECT %s, %s WHERE NOT EXISTS (SELECT 1 FROM words WHERE word=%s AND difficulty=%s)", (word, difficulty, word, difficulty))
        connection.commit()
    finally:
        connection.close()

def mask_word(word, guessed):
    return " ".join(ch if ch in guessed else "_" for ch in word)

class GuessRequest(BaseModel):
    session_id: int
    letter: str

class SaveScoreRequest(BaseModel):
    session_id: int
    player_name: str

@app.get("/api/health")
def health():
    try:
        init_db()
        return {"ok": True, "database": "connected"}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database connection failed. Check DATABASE_URL and Neon network settings.") from exc

@app.get("/api/new-game")
def new_game(difficulty: str = "easy"):
    difficulty = difficulty.lower()
    if difficulty not in DIFFICULTIES:
        raise HTTPException(status_code=400, detail="Choose easy, medium or hard.")
    init_db()
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT word FROM words WHERE difficulty=%s AND ((%s='easy' AND length(word) BETWEEN 3 AND 5) OR (%s='medium' AND length(word) BETWEEN 6 AND 8) OR (%s='hard' AND length(word)>=9) OR (%s='easy' AND length(word) BETWEEN 3 AND 5)) ORDER BY RANDOM() LIMIT 1", (difficulty, difficulty, difficulty, difficulty, difficulty))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=503, detail=f"No {difficulty} words found. Add words to the Neon words table.")
            word = re.sub(r"[^a-z]", "", row[0].lower())
            cur.execute("INSERT INTO game_sessions (word,difficulty) VALUES (%s,%s) RETURNING id", (word, difficulty))
            session_id = cur.fetchone()[0]
        conn.commit()
    finally:
        conn.close()
    return {"session_id": session_id, "masked_word": mask_word(word, set()), "wrong_count": 0, "max_attempts": MAX_ATTEMPTS, "status": "playing", "hint": HINTS[difficulty]}

@app.post("/api/guess")
def guess(payload: GuessRequest):
    letter = payload.letter.strip().lower()
    if len(letter) != 1 or letter not in "abcdefghijklmnopqrstuvwxyz":
        raise HTTPException(status_code=400, detail="Enter one letter from A to Z.")
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT word, guessed_letters, wrong_count, status FROM game_sessions WHERE id=%s FOR UPDATE", (payload.session_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Game session not found.")
            word, stored, wrong, status = row
            guessed = set(stored.split(",")) if stored else set()
            if status == "playing" and letter not in guessed:
                guessed.add(letter)
                if letter not in word:
                    wrong += 1
                status = "won" if all(ch in guessed for ch in set(word)) else ("lost" if wrong >= MAX_ATTEMPTS else "playing")
                cur.execute("UPDATE game_sessions SET guessed_letters=%s, wrong_count=%s, status=%s WHERE id=%s", (",".join(sorted(guessed)), wrong, status, payload.session_id))
        conn.commit()
    finally:
        conn.close()
    return {"masked_word": word if status == "lost" else mask_word(word, guessed), "wrong_count": wrong, "status": status}

@app.post("/api/save-score")
def save_score(payload: SaveScoreRequest):
    name = payload.player_name.strip()
    if not name or len(name) > 40:
        raise HTTPException(status_code=400, detail="Nickname must be between 1 and 40 characters.")
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT difficulty, wrong_count, status, score FROM game_sessions WHERE id=%s FOR UPDATE", (payload.session_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Game session not found.")
            difficulty, wrong, status, old_score = row
            if status != "won":
                raise HTTPException(status_code=400, detail="A score can only be saved after a win.")
            if old_score is not None:
                raise HTTPException(status_code=409, detail="This game's score has already been saved.")
            score = (MAX_ATTEMPTS - wrong) * 10 + BONUS[difficulty]
            cur.execute("UPDATE game_sessions SET player_name=%s, score=%s WHERE id=%s", (name, score, payload.session_id))
        conn.commit()
    finally:
        conn.close()
    return {"score": score, "player_name": name}

@app.get("/api/leaderboard")
def leaderboard():
    init_db()
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT player_name, score, difficulty FROM game_sessions WHERE status='won' AND score IS NOT NULL ORDER BY score DESC, id ASC LIMIT 50")
            rows = cur.fetchall()
    finally:
        conn.close()
    return [{"player_name": r[0], "score": r[1], "difficulty": r[2]} for r in rows]

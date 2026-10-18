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
WORD_BANK_VERSION = "common-english-v3"
_DB_INITIALIZED = False
DIFFICULTIES = {"easy", "medium", "hard"}
BONUS = {"easy": 0, "medium": 20, "hard": 40}
HINTS = {
    "easy": "Everyday words: familiar things, places, and actions.",
    "medium": "A familiar word with a little more to uncover.",
    "hard": "A longer, commonly used English word.",
}
DIFFICULTY_RULE = {"easy": "3–5 letters", "medium": "6–7 letters", "hard": "8–10 letters"}


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
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""")
            cur.execute("""CREATE TABLE IF NOT EXISTS game_sessions (
                id SERIAL PRIMARY KEY, word TEXT NOT NULL, difficulty TEXT NOT NULL,
                guessed_letters TEXT NOT NULL DEFAULT '', wrong_count INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'playing', player_name TEXT, score INTEGER,
                player_id INTEGER REFERENCES players(id))""")
            cur.execute("ALTER TABLE game_sessions ADD COLUMN IF NOT EXISTS player_id INTEGER REFERENCES players(id)")
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
                valid = []
                seen = set()
                for item in candidates:
                    word = item.strip().lower()
                    if not re.fullmatch(r"[a-z]{3,10}", word) or word in seen:
                        continue
                    seen.add(word)
                    difficulty = "easy" if len(word) <= 5 else "medium" if len(word) <= 7 else "hard"
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


class SaveScoreRequest(BaseModel):
    session_id: int
    player_name: str = Field(min_length=1, max_length=40)


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
            bounds = {"easy": (3, 5), "medium": (6, 7), "hard": (8, 10)}
            low, high = bounds[difficulty]
            cur.execute("""SELECT word FROM words
                WHERE difficulty=%s AND length(word) BETWEEN %s AND %s
                ORDER BY RANDOM() LIMIT 1""", (difficulty, low, high))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=503, detail=f"No playable words are available for {difficulty}.")
            word = row[0]
            cur.execute("INSERT INTO game_sessions(word,difficulty,player_name,player_id,score) VALUES (%s,%s,%s,%s,0) RETURNING id", (word, difficulty, player_name, player_id))
            session_id = cur.fetchone()[0]
        conn.commit()
        return {
            "session_id": session_id,
            "masked_word": mask_word(word, set()),
            "wrong_count": 0,
            "max_attempts": MAX_ATTEMPTS,
            "status": "playing",
            "hint": HINTS[difficulty],
            "difficulty_rule": DIFFICULTY_RULE[difficulty],
            "player_name": player_name,
            "score": 0,
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
            cur.execute("SELECT word,guessed_letters,wrong_count,status,difficulty,player_id,COALESCE(score,0),player_name FROM game_sessions WHERE id=%s FOR UPDATE", (payload.session_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Game session not found. Start a new round.")
            word, stored, wrong, status, difficulty, player_id, score, player_name = row
            guessed = set(stored.split(",")) if stored else set()
            if status == "playing" and letter not in guessed:
                guessed.add(letter)
                if letter not in word:
                    wrong += 1
                else:
                    score += 10 * word.count(letter)
                status = "won" if all(ch in guessed for ch in set(word)) else ("lost" if wrong >= MAX_ATTEMPTS else "playing")
                if status == "won":
                    score += BONUS[difficulty]
                cur.execute("UPDATE game_sessions SET guessed_letters=%s,wrong_count=%s,status=%s,score=%s WHERE id=%s",
                            (",".join(sorted(guessed)), wrong, status, score, payload.session_id))
            conn.commit()
            return {"masked_word": word if status == "lost" else mask_word(word, guessed), "wrong_count": wrong, "status": status, "score": score, "player_name": player_name, "correct_guess": letter in word}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@app.post("/save-score")
@app.post("/api/save-score")
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
        return {"score": score, "player_name": name}
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
            cur.execute("""SELECT p.name, best.score, best.difficulty FROM players p
                JOIN LATERAL (
                    SELECT gs.score,gs.difficulty FROM game_sessions gs
                    WHERE gs.player_id=p.id AND gs.score IS NOT NULL
                    ORDER BY (gs.status='playing') DESC,gs.id DESC,gs.score DESC LIMIT 1
                ) best ON TRUE
                ORDER BY best.score DESC,p.name ASC LIMIT 50""")
            rows = cur.fetchall()
        return [{"player_name": r[0], "score": r[1], "difficulty": r[2]} for r in rows]
    finally:
        conn.close()



@app.get("/hint/{session_id}")
@app.get("/api/hint/{session_id}")
def word_hint(session_id: int):
    """Fetch a word-specific definition without exposing the answer to the browser."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT word FROM game_sessions WHERE id=%s", (session_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Game session not found.")
            word = row[0]
    finally:
        conn.close()
    url = "https://api.dictionaryapi.dev/api/v2/entries/en/" + urllib.parse.quote(word)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "WordHunt-EF101/1.0"})
        with urllib.request.urlopen(req, timeout=2.5) as response:
            data = json.loads(response.read(400_000).decode("utf-8"))
        definitions = []
        for entry in data if isinstance(data, list) else []:
            for meaning in entry.get("meanings", []):
                for item in meaning.get("definitions", []):
                    definition = re.sub(r"\s+", " ", str(item.get("definition", "")).strip())
                    if definition and definition.lower() != word.lower() and len(definition) < 180:
                        definitions.append(definition)
        if definitions:
            return {"hint": definitions[0]}
    except (OSError, ValueError, urllib.error.URLError, TimeoutError):
        pass
    return {"hint": "Think of a familiar English word with " + str(len(word)) + " letters."}

"""FastAPI API for the EF101 Hangman game."""
import os
import psycopg2
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="EF101 Hangman API")
MAX_ATTEMPTS = 6
BONUS = {"easy": 0, "medium": 20, "hard": 40}

def connect():
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL environment variable is required")
    return psycopg2.connect(url)

def init_db():
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""CREATE TABLE IF NOT EXISTS words (
                id SERIAL PRIMARY KEY, word TEXT NOT NULL, difficulty TEXT NOT NULL
            )""")
            cur.execute("""CREATE TABLE IF NOT EXISTS game_sessions (
                id SERIAL PRIMARY KEY, word TEXT NOT NULL, difficulty TEXT NOT NULL,
                guessed_letters TEXT NOT NULL DEFAULT '', wrong_count INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'playing', player_name TEXT, score INTEGER
            )""")
init_db()

def mask(word, guesses):
    guessed = set(guesses.split(",")) if guesses else set()
    return " ".join(ch if ch in guessed else "_" for ch in word)

class Guess(BaseModel):
    session_id: int
    letter: str
class SaveScore(BaseModel):
    session_id: int
    player_name: str

@app.get("/api/new-game")
def new_game(difficulty: str = "easy"):
    difficulty = difficulty.lower()
    if difficulty not in BONUS:
        raise HTTPException(400, "Choose easy, medium or hard")
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT word FROM words WHERE difficulty=%s ORDER BY RANDOM() LIMIT 1", (difficulty,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "No words available for this difficulty")
            word = row[0].strip().lower()
            cur.execute("INSERT INTO game_sessions(word,difficulty) VALUES(%s,%s) RETURNING id", (word,difficulty))
            sid = cur.fetchone()[0]
    return {"session_id":sid,"masked_word":mask(word,""),"wrong_count":0,"max_attempts":MAX_ATTEMPTS,"status":"playing"}

@app.post("/api/guess")
def guess(payload: Guess):
    letter = payload.letter.strip().lower()
    if len(letter) != 1 or not letter.isascii() or not letter.isalpha():
        raise HTTPException(400, "Enter one letter A-Z")
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT word,guessed_letters,wrong_count,status FROM game_sessions WHERE id=%s", (payload.session_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Game session not found")
            word, old, wrong, status = row
            guessed = set(old.split(",")) if old else set()
            if status != "playing" or letter in guessed:
                return {"masked_word": word if status == "lost" else mask(word, old), "wrong_count":wrong,"status":status}
            guessed.add(letter)
            if letter not in word:
                wrong += 1
            status = "won" if all(ch in guessed for ch in set(word)) else ("lost" if wrong >= MAX_ATTEMPTS else "playing")
            packed = ",".join(sorted(guessed))
            cur.execute("UPDATE game_sessions SET guessed_letters=%s,wrong_count=%s,status=%s WHERE id=%s", (packed,wrong,status,payload.session_id))
    return {"masked_word":word if status=="lost" else mask(word,packed),"wrong_count":wrong,"status":status}

@app.post("/api/save-score")
def save_score(payload: SaveScore):
    name = payload.player_name.strip()
    if not name or len(name) > 40:
        raise HTTPException(400, "Nickname must be 1-40 characters")
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT difficulty,wrong_count,status FROM game_sessions WHERE id=%s", (payload.session_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Game session not found")
            difficulty, wrong, status = row
            if status != "won":
                raise HTTPException(400, "A score can only be saved after a win")
            score = (MAX_ATTEMPTS - wrong) * 10 + BONUS[difficulty]
            cur.execute("UPDATE game_sessions SET player_name=%s,score=%s WHERE id=%s", (name,score,payload.session_id))
    return {"score":score,"player_name":name}

@app.get("/api/leaderboard")
def leaderboard():
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT player_name,score,difficulty FROM game_sessions
                WHERE status='won' AND score IS NOT NULL ORDER BY score DESC,id ASC LIMIT 50""")
            rows = cur.fetchall()
    return [{"player_name":r[0],"score":r[1],"difficulty":r[2]} for r in rows]

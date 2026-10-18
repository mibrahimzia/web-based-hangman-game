# Word Hunt — EF-101 Hangman

Browser-based Hangman with three difficulty levels and a persistent top-50 leaderboard.

## Stack
- Frontend: HTML, CSS and vanilla JavaScript in `public/`
- API: FastAPI in `api/index.py`
- Database: Neon PostgreSQL using `DATABASE_URL`
- Hosting: Vercel

## Game rules
- Easy: 3–5 letters; Medium: 6–8; Hard: 9 or more
- Six incorrect guesses maximum; repeated guesses do not cost an attempt
- Score: `(6 - wrong_count) * 10 + difficulty bonus` (Easy 0, Medium 20, Hard 40)
- Scores can only be saved after a win; leaderboard is limited to 50 entries

## Database
Set `DATABASE_URL` in Vercel project environment variables (Preview and Production) to the Neon connection string with SSL enabled. The API creates `words` and `game_sessions` tables if absent. The `words` table must be seeded with rows whose `difficulty` values are `easy`, `medium`, or `hard`; it is not populated automatically by the API.

## Verification
Run `node --check public/script.js` and `python -m py_compile api/index.py`. Then test the deployed root page, `/api/leaderboard`, `/api/new-game?difficulty=easy`, guessing, win/loss, and score saving against the real Neon database. Source checks do not prove deployment/database integration.

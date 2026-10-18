# Word Hunt — EF101-P01

A browser-based Hangman game built with HTML, CSS, vanilla JavaScript, FastAPI and Neon PostgreSQL.

## Vocabulary and difficulty rules

The server-side file `data/common_words.txt` supplies 6,000+ filtered English words to the database. On first use (and when the word-bank version changes), the backend validates the words and imports them into the persistent `words` table. The browser never receives the answer word until the round is lost.

Difficulty is based on word length:
- **Easy:** 3–5 letters
- **Medium:** 6–7 letters
- **Hard:** 8–10 letters

Words are selected randomly from the database within the selected difficulty. This uses a common-English frequency list filtered to alphabetic words of 3–10 letters, rather than a tiny hard-coded sample list.

## Gameplay and scoring

- Each round allows **8 incorrect guesses**. The drawing has exactly eight progressive steps: vertical post, top beam, rope, head, body, left arm, right arm, and both legs.
- A repeated letter is ignored and does not cost a chance.
- Correct guesses reveal every occurrence of that letter.
- The game ends on a complete word (win) or after the eighth wrong guess (loss).
- **Score = (remaining chances × 10) + difficulty bonus.** Easy bonus = 0, Medium = 20, Hard = 40. For example, winning on Easy with 5 chances left earns 50 points; winning on Hard with 5 chances left earns 90 points.
- After a win, the player must enter a non-blank name before that round's score can be saved. Scores and player bests persist in Neon.
- The leaderboard shows up to 50 real saved player bests, sorted by score descending. Equal scores are ordered alphabetically by player name. The top three entries have medal badges and larger names.

## Data model

- `words`: word ID, word text and difficulty.
- `game_sessions`: hidden answer, difficulty, guessed letters, wrong-guess count, result, player name and score.
- `players`: player name, normalized name and creation timestamp.
- `word_bank_meta`: imported word-bank version.

## Browser/server responsibilities

The browser displays the masked word and keyboard, sends one-letter guesses, and renders the returned state. The FastAPI server chooses the word, keeps the answer in the database-backed game session, checks guesses and win/loss state, calculates scores, validates names, and returns the leaderboard. The full answer is not sent to the browser during a live round.

## Minimum manual test checklist

- [ ] Start Easy, Medium and Hard rounds; verify the displayed word length matches each rule.
- [ ] Guess a correct letter that occurs more than once; all copies should appear.
- [ ] Guess a wrong letter; the drawing advances by exactly one step.
- [ ] Repeat a guessed letter; remaining chances must not change.
- [ ] Reveal every letter to win and confirm the name form appears only after a win.
- [ ] Use all eight mistakes to lose; the complete answer is then revealed.
- [ ] Save a score with a valid name; reload the page and confirm it remains on the leaderboard.
- [ ] Submit a blank/whitespace-only name; the score must not save.
- [ ] Save equal scores; confirm deterministic alphabetical ordering.
- [ ] Confirm the leaderboard is limited to 50 entries and podium badges distinguish positions 1–3.

## Deployment

1. Set the Vercel project root to the repository root.
2. Set `DATABASE_URL` in Vercel Environment Variables for Preview and Production. Use the Neon connection string and enable SSL.
3. Deploy and check `/api/health`; it should report a connected database and at least 5,000 words.

Never commit real database credentials. The `DATABASE_URL` belongs in Vercel Environment Variables, not frontend code.

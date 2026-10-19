# Word Hunt — EF101-P01

A browser-based Hangman game built with HTML, CSS, vanilla JavaScript, FastAPI and Neon PostgreSQL.

## Word bank and difficulty

- The source vocabulary is `data/common_words.txt`.
- On first use, and whenever `WORD_BANK_VERSION` changes, the backend validates and imports playable words into PostgreSQL's `words` table.
- The importer keeps alphabetic words of 4–12 letters, removes duplicates, assigns a difficulty by length, and blocks a list of known acronyms, brands, proper names and malformed fragments (including `ibm`, `amd`, `usc`, `trembl` and `struct`). This improves the list but does not guarantee every remaining word is familiar; the blocklist can be extended when new bad examples are found.
- The browser never receives the secret word during an active round.

Difficulty:
- **Easy:** 4–5 letters; round reward 100 points; each wrong guess costs 10.
- **Medium:** 6–8 letters; round reward 250 points; each wrong guess costs 20.
- **Hard:** 9–12 letters; round reward 500 points; each wrong guess costs 40.

## Scoring, leaderboard and streaks

- Each round starts with its difficulty's reward available.
- Every incorrect guess subtracts the level's penalty from that round only. The round value is clamped at zero and never becomes negative.
- On a win, the remaining round value is added to the player's persistent lifetime score.
- On a loss, the round value is discarded and the player's lifetime score is unchanged. A failed round therefore cannot erase previously earned points.
- The leaderboard sorts players by lifetime score, then highest streak, then name. It shows the player's highest streak with a fire icon and the current streak.
- Each won word increments the current streak. A lost word resets the current streak to zero. The highest streak is stored permanently.
- The scoring migration preserves the previous leaderboard's best completed score as the player's starting lifetime score. Old completed sessions are marked migrated so they are not counted again.

## Game flow

1. Player enters a name and selects a difficulty.
2. FastAPI finds or creates the player, selects a random word from PostgreSQL, and creates a game session.
3. Each letter is submitted to `/api/guess`; the backend validates it, updates guesses and mistakes, calculates the current round value, and checks win/loss.
4. A win commits the round value to lifetime points and updates streaks. A loss discards that round's points and resets the current streak.
5. A large result dialog appears for both outcomes. It reveals the word, retrieves a definition from the free Dictionary API, and offers **Continue** after a win or **Try again** after a loss.
6. Correct letters trigger a small celebration animation. The hangman drawing progresses through eight connected steps: top beam, vertical post, rope/head, torso, left arm, right arm, left leg, right leg. The platform is always visible.

## Data model

- `words`: word text and difficulty.
- `players`: normalized player identity, lifetime score, current streak and highest streak.
- `game_sessions`: secret answer, difficulty, guesses, mistake count, status, round score, player link and score-commit flag.
- `word_bank_meta`: imported word-bank version.
- `schema_migrations`: one-time migrations, including preservation of existing leaderboard scores.

## Manual verification checklist

- [ ] Start Easy, Medium and Hard rounds and confirm word lengths match the selected level.
- [ ] Confirm `ibm`, `amd`, `usc`, `trembl` and `struct` are not selected after the word bank is re-imported.
- [ ] Make a wrong guess at each level and confirm the round value drops by 10, 20 or 40 without going below zero.
- [ ] Win a word with no mistakes and confirm +100, +250 or +500 is added to lifetime points.
- [ ] Win after mistakes and confirm only the remaining round value is added.
- [ ] Lose a word and confirm lifetime points remain unchanged and current streak resets.
- [ ] Win consecutive words and confirm current and highest streaks update correctly.
- [ ] Confirm the win popup has **Continue**, the loss popup has **Try again**, and both show the word's meaning.
- [ ] Confirm correct guesses show a party-popper celebration.
- [ ] Refresh the page and confirm lifetime scores and highest streaks persist.
- [ ] Verify the stand connects fully and all eight drawing parts appear in order.

## Deployment

1. Set the Vercel project root to the repository root.
2. Set `DATABASE_URL` in Vercel Environment Variables for Preview and Production. Use the Neon connection string and enable SSL.
3. Deploy and check `/api/health`; it should report a connected database and at least 5,000 words.
4. Word hints use the free, no-key Free Dictionary API (`https://dictionaryapi.dev/`). Lookups run asynchronously with a short timeout and a fallback definition message.

Never commit database credentials. Keep `DATABASE_URL` in Vercel Environment Variables, not frontend code.

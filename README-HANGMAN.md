# Word Hunt — EF101-P01

A browser-based Hangman game built with HTML, CSS, vanilla JavaScript, FastAPI and Neon PostgreSQL.

## Word bank and difficulty

- The source vocabulary is `data/common_words.txt` (currently 5,441 screened English words).
- The bank excludes a conservative list of political vocabulary and inappropriate terms. Screening is not a guarantee that every word is suitable in every context; keep reviewing new candidates before release.
- `scripts/datamuse_candidates.py` queries Datamuse `/words` using meaning-like (`ml`) seeds and definition/part-of-speech metadata (`md=dp`). It writes a review queue only; Datamuse is a word-finding API, not a moderation service, and its suggestions are never automatically playable. Datamuse is credited here: [Datamuse API](https://www.datamuse.com/api/).
- On first use, and whenever `WORD_BANK_VERSION` changes, the backend validates and imports playable words into PostgreSQL's `words` table.
- The importer keeps alphabetic words of 4–20 letters, removes duplicates, assigns a difficulty by length, and blocks a list of known acronyms, brands, proper names and malformed fragments (including `ibm`, `amd`, `usc`, `trembl` and `struct`). This improves the list but does not guarantee every remaining word is familiar; the blocklist can be extended when new bad examples are found.
- The browser never receives the secret word during an active round.

Difficulty:
- **Easy:** 4–5 letters; round reward 100 points; each wrong guess costs 10.
- **Medium:** 6–8 letters; round reward 250 points; each wrong guess costs 20.
- **Hard:** 9+ letters (the imported word bank supports up to 20 letters); round reward 500 points; each wrong guess costs 40.

## Scoring, leaderboard and streaks

- Each round starts with its difficulty's reward available.
- Every incorrect guess subtracts the level's penalty from that round only. The round value is clamped at zero and never becomes negative.
- On a win, the remaining round value is added to the player's persistent lifetime score.
- On a loss, the round value is discarded and the player's lifetime score is unchanged. A failed round therefore cannot erase previously earned points.
- The leaderboard has two sections: **Public** (shown first by default) and **Verified**. Public names are shared identities; anyone may play under an available public name. Verified names belong to password-protected accounts.
- Protected accounts require a name and password of at least 8 characters, including at least one uppercase letter and one number. Passwords are salted and hashed with PBKDF2-HMAC-SHA256; the browser stores only a short-lived bearer token in session storage. Protected game sessions require the matching account token.
- A name already created as Public cannot later be claimed as Verified. Register the protected name before anyone starts a Public game with it.
- Sign-in sessions expire after 30 days. There is no email-based password reset; losing the password means the account cannot currently be recovered.
- The leaderboard sorts players within each section by lifetime score, then highest streak, then name. It shows the player's highest streak with a fire icon and the current streak. Streaks are overall across all difficulties, not separate per level; no single difficulty is implied by the streak count.
- Each won word increments the overall current streak. A lost word resets the current streak to zero. Ending a round early leaves it unchanged. The highest streak is stored permanently.
- The scoring migration preserves the previous leaderboard's best completed score as the player's starting lifetime score. Old completed sessions are marked migrated so they are not counted again.

## Game flow

1. Player enters a name and selects a difficulty.
2. FastAPI finds or creates the player, selects a random word from PostgreSQL, and creates a game session.
3. Each letter is submitted to `/api/guess`; the backend validates it, updates guesses and mistakes, calculates the current round value, and checks win/loss.
4. A win commits the round value to lifetime points and updates streaks. A loss discards that round's points and resets the current streak.
5. A large result dialog appears for both outcomes. It reveals the word, retrieves a definition from the free Dictionary API, and offers **Continue** after a win or **Try again** after a loss.
6. Difficulty controls the clue: Easy shows a definition plus an example when available; Medium shows a dictionary definition; Hard shows a part-of-speech clue. The hint endpoint tries Free Dictionary API first and FreeDictionaryAPI.com (Wiktionary-backed) if the first provider has no usable definition, then uses reviewed offline clues for supported words. It never invents a clue from the answer's length or first letter. If neither provider nor offline clues can supply a reliable definition, the game says so instead of pretending a generic sentence is a hint.
7. **End game** abandons the active round without counting it as a loss, changing lifetime points, or resetting the streak. The player can then change their name or difficulty and start another round.
8. Correct letters trigger a small celebration animation. The platform, beam, post and diagonal brace stay fixed and visible. Six figure parts are drawn progressively: head, torso, left arm, right arm, left leg and right leg. There is no rope.

## Data model

- `words`: word text and difficulty.
- `players`: normalized player identity, account type (`public` or `protected`), optional password hash, lifetime score, current streak and highest streak.
- `player_auth_sessions`: hashed bearer tokens and expiry times for protected accounts.
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
- [ ] Verify the fixed stand, beam and diagonal brace remain visible and all six body parts appear in order.
- [ ] Create a protected account, sign out, and confirm its name cannot start a game without signing in.
- [ ] Confirm a Public name cannot be registered as Verified after it has been used publicly.
- [ ] Confirm Public and Verified leaderboard sections render separately, with Public first.

## Deployment

1. Set the Vercel project root to the repository root.
2. Set `DATABASE_URL` in Vercel Environment Variables for Preview and Production. Use the Neon connection string and enable SSL.
3. Deploy and check `/api/health`; it should report a connected database and at least 5,000 words.
4. The first database initialization applies a one-time fair-start migration that deletes the previous player names, scores, and game sessions; it keeps the word bank. Register the first protected account promptly after deployment if you want to reserve that name before it is used publicly.
5. Word hints try the free, no-key Free Dictionary API (`https://dictionaryapi.dev/`) first, then FreeDictionaryAPI.com (`https://freedictionaryapi.com/`, sourced from Wiktionary) when no usable definition is returned. Each request has a short timeout, and the game has reviewed offline clues for selected common words. The page credits FreeDictionaryAPI.com and Wiktionary in the footer. Neither provider documents a guaranteed uptime; if both are unavailable and no offline clue exists, the game shows an honest unavailable-clue message rather than a fake first-letter clue.

Never commit database credentials. Keep `DATABASE_URL` in Vercel Environment Variables, not frontend code.

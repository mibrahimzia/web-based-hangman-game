# Word Hunt

A browser-based word game built with HTML, CSS, vanilla JavaScript, Vercel Node.js Functions, and Neon PostgreSQL.

## Runtime architecture

- Frontend: static HTML, CSS, and vanilla JavaScript in `public/`.
- API: one JavaScript Vercel catch-all function at `api/[...route].js`.
- Database: Neon PostgreSQL, accessed through `@neondatabase/serverless`.
- Runtime: Node.js 20 or newer. There is no Python runtime or Python dependency.
- Game answers, validation, scoring, player identity, and streaks remain server-authoritative.

## Vocabulary bank

- `data/curated_words.json` contains exactly 5,000 playable entries.
- Each entry stores its word, length-based difficulty, a topic category, and optional definition/example/part-of-speech fields.
- The bank is a first editorial screening pass based on the prior list, the existing exclusion list, additional suitability exclusions, and removal of many common verb inflections. It is not a claim that every entry has received an individual human review; continue reviewing the bank before treating it as a fully approved educational dictionary.
- Current category tags include animals, arts, everyday, food, geography, nature, science, school, sports, technology, and general. In this initial release, 379 entries have a specific topical tag and 4,621 use the general category; that imbalance is documented rather than disguising uncertain classifications as precise topics. General is the fallback category for words without a confident topic tag.
- Twenty-eight entries currently include locally reviewed definition/example clues, including explicit intended meanings for several ambiguous words such as `lead`. Other entries can use the dictionary lookup flow described below.
- No Datamuse request is made during gameplay, and the Datamuse candidate script has been removed.
- The word bank version is `curated-5000-v2` and is imported into PostgreSQL on the first API request after a bank-version change. The importer upserts the 5,000 entries and removes superseded rows from `words`; it does not delete players, authentication sessions, scores, streaks, or game sessions.

Difficulty:
- **Easy:** 4–5 letters; 100 starting points; each wrong guess costs 10.
- **Medium:** 6–8 letters; 250 starting points; each wrong guess costs 20.
- **Hard:** 9+ letters; 500 starting points; each wrong guess costs 40.
- Each round allows six incorrect guesses.

## Hint providers and attribution

The hint endpoint is separate from the letter-guess endpoint. A letter guess does not call either dictionary provider.

1. **Primary: Free Dictionary API** — `https://api.dictionaryapi.dev/`. The backend requests English definitions, examples, and parts of speech.
2. **Fallback: FreeDictionaryAPI.com** — `https://freedictionaryapi.com/`. It is queried if the primary provider does not return a usable definition. Its API content is sourced from **Wiktionary**.
3. **Local fallback:** a small set of reviewed clues is stored in the JavaScript backend; approved word-bank entries can also carry a definition and example in PostgreSQL.

The backend removes a definition/example if it contains the answer itself, applies a 2.5-second timeout to each external provider, and caches successful hints in memory for the lifetime of a warm function instance. The cache is not shared between separate serverless instances.

Difficulty-adjusted clues:
- **Easy:** definition plus an example when available.
- **Medium:** definition.
- **Hard:** part of speech.

The browser asks for a hint when a round starts and again when the result dialog opens. The in-memory cache can prevent the second request from repeating the provider lookups on the same warm instance. If no usable definition is available, the game reports that honestly rather than inventing a clue.

**Wiktionary is not called as a separate third API.** The game calls FreeDictionaryAPI.com, which uses Wiktionary as a content source. Attribution links remain in the page footer.

## Accounts and authentication

- Public player names are shared identities.
- Protected accounts require a password of at least eight characters, including one uppercase letter and one number.
- Passwords use salted PBKDF2-HMAC-SHA256 with 310,000 iterations.
- Bearer tokens are random, stored as SHA-256 hashes, and expire after 30 days.
- Protected game sessions require the matching account token.
- The browser stores the bearer token in session storage.

## Scoring, leaderboard and streaks

- Each round starts with its difficulty's reward.
- Incorrect guesses reduce only the current round's score, never below zero.
- A win adds the remaining round score to the player's lifetime score.
- A loss discards the round score and resets the current streak; lifetime points remain unchanged.
- The leaderboard separates Public and Verified players and sorts by lifetime score, highest streak, then name.
- Each win increments the overall current streak. A loss resets it. Abandoning a round leaves it unchanged.

## API routes

| Method | Route | Purpose |
|---|---|---|
| GET | `/api/health` | Database and word/player counts |
| POST | `/api/auth/register` | Create protected account |
| POST | `/api/auth/login` | Sign in |
| POST | `/api/auth/logout` | Revoke bearer token |
| GET | `/api/new-game` | Create a round |
| POST | `/api/guess` | Submit one letter |
| GET | `/api/leaderboard` | Read lifetime leaderboard |
| POST | `/api/end-game/:session_id` | Abandon active round |
| GET | `/api/hint/:session_id` | Retrieve word hint |

## Database model

- `words`: word, difficulty, category, definition, example, and part of speech.
- `players`: normalized identity, account type, optional password hash, lifetime score, current streak, and highest streak.
- `player_auth_sessions`: hashed bearer tokens and expiry times.
- `game_sessions`: secret answer, difficulty, guessed letters, wrong count, status, round score, player link, and score-commit flag.
- `word_bank_meta`: current imported vocabulary version.
- `schema_migrations`: retained legacy migration ledger; the JavaScript migration does not run the previous destructive fair-start resets.

## Deployment

1. Set the Vercel project root to the repository root.
2. Set `DATABASE_URL` in Vercel Environment Variables for Preview and Production. Use the Neon connection string with SSL enabled.
3. Install dependencies with `npm install`.
4. Deploy to Vercel. The first API request creates any missing tables/columns and imports the new vocabulary version.
5. Check `/api/health`; it should report a connected database and 5,000 words.
6. Test registration/login, a round at each difficulty, correct and incorrect guesses, win/loss scoring, streaks, leaderboard sections, sign-out, and round abandonment.

The JavaScript migration intentionally does not execute the old `final-fair-reset-v2` or `fair-start-auth-v1` data deletion logic. Existing players and game history are preserved.

## Manual verification checklist

- [ ] Confirm `/api/health` reports 5,000 words after deployment.
- [ ] Start Easy, Medium, and Hard rounds and verify word lengths.
- [ ] Verify the secret word is not returned before a round ends.
- [ ] Verify six wrong guesses end a round.
- [ ] Verify wrong guesses reduce only the round score by 10, 20, or 40.
- [ ] Verify a win adds the remaining round score exactly once.
- [ ] Verify a loss leaves lifetime points unchanged and resets the current streak.
- [ ] Verify ending a round early does not count as a loss or reset the streak.
- [ ] Create and sign into a protected account; verify protected names cannot be used without authentication.
- [ ] Verify Public and Verified leaderboard sections.
- [ ] Verify hints use local reviewed clues when available and the dictionary providers only from the hint endpoint.
- [ ] Verify light and dark Typewriter appearances and confirm there is no theme-switching control.

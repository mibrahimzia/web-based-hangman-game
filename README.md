# Word Hunt

A browser-based Hangman-style word game built with vanilla JavaScript, Vercel Node.js Functions, and Neon PostgreSQL.

- **Frontend:** static HTML, CSS, and JavaScript in `public/`.
- **Backend:** JavaScript serverless API in `api/[...route].js`.
- **Database:** Neon PostgreSQL using `@neondatabase/serverless`.
- **Vocabulary:** 5,000 entries in `data/curated_words.json`; Datamuse enriches selected words when a hint is requested; the curated bank remains the source of playable answers.
- **Theme:** Typewriter is the only visual theme, with a light/dark toggle.

See [README-HANGMAN.md](README-HANGMAN.md) for API routes, database schema, scoring rules, word-bank notes, hint-provider behavior, attribution, and deployment verification.

## Automated checks

Run these before pushing a change:

```bash
npm test
npm run check
```

GitHub Actions runs both checks for pull requests and pushes to `main`. After a push to `main`, it also waits for the Vercel production deployment and smoke-tests the database health, starting a round, loading its dictionary clue, and ending the round. A failed check blocks the pipeline from reporting success.

## Local development

```bash
npm install
npx vercel dev
```

Set `DATABASE_URL` in your local environment before testing API routes. Never commit database credentials.

# Word Hunt

A browser-based Hangman-style word game built with vanilla JavaScript, Vercel Node.js Functions, and Neon PostgreSQL.

- **Frontend:** static HTML, CSS, and JavaScript in `public/`.
- **Backend:** JavaScript serverless API in `api/[...route].js`.
- **Database:** Neon PostgreSQL using `@neondatabase/serverless`.
- **Vocabulary:** 5,000 entries in `data/curated_words.json`; no runtime Datamuse requests.
- **Theme:** Typewriter is the only visual theme, with a light/dark toggle.

See [README-HANGMAN.md](README-HANGMAN.md) for API routes, database schema, scoring rules, word-bank notes, hint-provider behavior, attribution, and deployment verification.

## Local development

```bash
npm install
npx vercel dev
```

Set `DATABASE_URL` in your local environment before testing API routes. Never commit database credentials.

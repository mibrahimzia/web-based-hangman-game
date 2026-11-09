const crypto = require("node:crypto");
const { promisify } = require("node:util");
const { Pool, neonConfig } = require("@neondatabase/serverless");
const WebSocket = require("ws");
const WORDS = require("../data/curated_words.json");
const { lookupDictionary } = require("./dictionary");
neonConfig.webSocketConstructor = WebSocket;
const pbkdf2 = promisify(crypto.pbkdf2);
const MAX_ATTEMPTS = 6;
const WORD_BANK_VERSION = "curated-5000-v3";
const REWARDS = { easy: 100, medium: 250, hard: 500 };
const PENALTIES = { easy: 10, medium: 20, hard: 40 };
const RULES = { easy: "4–5 letters", medium: "6–8 letters", hard: "9+ letters" };
const hintCache = new Map();
let pool;
let initialization;

function getPool() {
  if (!process.env.DATABASE_URL) throw httpError(503, "DATABASE_URL is missing from Vercel environment variables.");
  if (!pool) pool = new Pool({ connectionString: process.env.DATABASE_URL, max: 3, idleTimeoutMillis: 10000, connectionTimeoutMillis: 5000 });
  return pool;
}
async function withClient(work) {
  const client = await getPool().connect();
  try { return await work(client); } finally { client.release(); }
}
async function ensureDatabase() {
  if (initialization) return initialization;
  initialization = withClient(async client => {
    await client.query("BEGIN");
    try {
      await client.query("CREATE TABLE IF NOT EXISTS words (id SERIAL PRIMARY KEY, word TEXT NOT NULL, difficulty TEXT NOT NULL, UNIQUE(word,difficulty))");
      await client.query("CREATE TABLE IF NOT EXISTS players (id SERIAL PRIMARY KEY,name VARCHAR(40) NOT NULL,normalized_name VARCHAR(40) NOT NULL UNIQUE,created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),total_score INTEGER NOT NULL DEFAULT 0,current_streak INTEGER NOT NULL DEFAULT 0,highest_streak INTEGER NOT NULL DEFAULT 0,account_type TEXT NOT NULL DEFAULT 'public',password_hash TEXT)");
      await client.query("ALTER TABLE players ADD COLUMN IF NOT EXISTS total_score INTEGER NOT NULL DEFAULT 0");
      await client.query("ALTER TABLE players ADD COLUMN IF NOT EXISTS current_streak INTEGER NOT NULL DEFAULT 0");
      await client.query("ALTER TABLE players ADD COLUMN IF NOT EXISTS highest_streak INTEGER NOT NULL DEFAULT 0");
      await client.query("ALTER TABLE players ADD COLUMN IF NOT EXISTS account_type TEXT NOT NULL DEFAULT 'public'");
      await client.query("ALTER TABLE players ADD COLUMN IF NOT EXISTS password_hash TEXT");
      await client.query("CREATE TABLE IF NOT EXISTS player_auth_sessions (id SERIAL PRIMARY KEY,player_id INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,token_hash TEXT NOT NULL UNIQUE,expires_at TIMESTAMPTZ NOT NULL,created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())");
      await client.query("CREATE TABLE IF NOT EXISTS game_sessions (id SERIAL PRIMARY KEY,word TEXT NOT NULL,difficulty TEXT NOT NULL,guessed_letters TEXT NOT NULL DEFAULT '',wrong_count INTEGER NOT NULL DEFAULT 0,status TEXT NOT NULL DEFAULT 'playing',player_name TEXT,score INTEGER,player_id INTEGER REFERENCES players(id),score_committed BOOLEAN NOT NULL DEFAULT FALSE)");
      await client.query("ALTER TABLE game_sessions ADD COLUMN IF NOT EXISTS player_id INTEGER REFERENCES players(id)");
      await client.query("ALTER TABLE game_sessions ADD COLUMN IF NOT EXISTS score_committed BOOLEAN NOT NULL DEFAULT FALSE");
      await client.query("CREATE TABLE IF NOT EXISTS word_bank_meta (id INTEGER PRIMARY KEY CHECK(id=1),version TEXT NOT NULL,imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW())");
      await client.query("ALTER TABLE words ADD COLUMN IF NOT EXISTS category TEXT NOT NULL DEFAULT 'general'");
      await client.query("ALTER TABLE words ADD COLUMN IF NOT EXISTS definition TEXT");
      await client.query("ALTER TABLE words ADD COLUMN IF NOT EXISTS example TEXT");
      await client.query("ALTER TABLE words ADD COLUMN IF NOT EXISTS part_of_speech TEXT");
      await client.query("ALTER TABLE words ADD COLUMN IF NOT EXISTS syllable_count INTEGER");
      await client.query("ALTER TABLE words ADD COLUMN IF NOT EXISTS pronunciation TEXT");
      await client.query("ALTER TABLE words ADD COLUMN IF NOT EXISTS frequency REAL");
      await client.query("CREATE UNIQUE INDEX IF NOT EXISTS words_word_difficulty_uidx ON words(word,difficulty)");
      await client.query("CREATE INDEX IF NOT EXISTS words_difficulty_length_idx ON words(difficulty,length(word))");
      const meta = await client.query("SELECT version FROM word_bank_meta WHERE id=1");
      if (!meta.rows[0] || meta.rows[0].version !== WORD_BANK_VERSION) {
        if (!Array.isArray(WORDS) || WORDS.length !== 5000) throw new Error("The curated word bank must contain exactly 5,000 entries.");
        const payload = JSON.stringify(WORDS);
        await client.query("INSERT INTO words(word,difficulty,category,definition,example,part_of_speech) SELECT word,difficulty,category,definition,example,part_of_speech FROM jsonb_to_recordset($1::jsonb) AS x(word text,difficulty text,category text,definition text,example text,part_of_speech text) ON CONFLICT(word,difficulty) DO UPDATE SET category=EXCLUDED.category,definition=EXCLUDED.definition,example=EXCLUDED.example,part_of_speech=EXCLUDED.part_of_speech", [payload]);
        await client.query("DELETE FROM words WHERE NOT (word = ANY($1::text[]))", [WORDS.map(item => item.word)]);
        await client.query("INSERT INTO word_bank_meta(id,version) VALUES(1,$1) ON CONFLICT(id) DO UPDATE SET version=EXCLUDED.version,imported_at=NOW()", [WORD_BANK_VERSION]);
      }
      await client.query("COMMIT");
    } catch (error) { await client.query("ROLLBACK"); throw error; }
  }).catch(error => { initialization = null; throw error; });
  return initialization;
}
function httpError(status, detail) { const error = new Error(detail); error.status = status; return error; }
function maskWord(word, guessed) { return [...word].map(char => guessed.has(char) ? char : "_").join(" "); }
function normalizePlayerName(value) {
  const name = String(value ?? "").replace(/\s+/g, " ").trim();
  if (!name || name.length > 40 || !/[A-Za-z0-9]/.test(name)) throw httpError(400, "Enter a name using 1–40 characters.");
  return { name, normalized: name.toLowerCase() };
}
function validatePassword(password) {
  if (typeof password !== "string" || password.length < 8 || password.length > 128 || !/[A-Z]/.test(password) || !/[0-9]/.test(password)) throw httpError(400, "Password must be at least 8 characters and include one uppercase letter and one number.");
}
function tokenFrom(req) {
  const match = String(req.headers.authorization || "").match(/^Bearer\s+(.+)$/i);
  return match ? match[1].trim() : null;
}
function hash(value) { return crypto.createHash("sha256").update(value, "utf8").digest("hex"); }
async function makePasswordHash(password) {
  const salt = crypto.randomBytes(16), rounds = 310000;
  const digest = await pbkdf2(password, salt, rounds, 32, "sha256");
  return "pbkdf2_sha256$" + rounds + "$" + salt.toString("hex") + "$" + digest.toString("hex");
}
async function checkPassword(password, encoded) {
  try {
    const parts = encoded.split("$");
    if (parts[0] !== "pbkdf2_sha256") return false;
    const expected = Buffer.from(parts[3], "hex");
    const actual = await pbkdf2(password, Buffer.from(parts[2], "hex"), Number(parts[1]), expected.length, "sha256");
    return expected.length === actual.length && crypto.timingSafeEqual(expected, actual);
  } catch { return false; }
}
async function resolveAuthPlayer(client, req) {
  const token = tokenFrom(req);
  if (!token) return null;
  const result = await client.query("SELECT p.id,p.name,p.account_type FROM player_auth_sessions s JOIN players p ON p.id=s.player_id WHERE s.token_hash=$1 AND s.expires_at>NOW()", [hash(token)]);
  return result.rows[0] || null;
}
async function enforceSessionOwner(client, playerId, req) {
  if (playerId == null) return;
  const result = await client.query("SELECT account_type FROM players WHERE id=$1", [playerId]);
  if (result.rows[0] && result.rows[0].account_type === "protected") {
    const player = await resolveAuthPlayer(client, req);
    if (!player || player.id !== playerId) throw httpError(401, "Sign in to the protected account that started this round.");
  }
}
async function bodyOf(req) {
  if (req.body && typeof req.body === "object") return req.body;
  if (typeof req.body === "string") { try { return JSON.parse(req.body); } catch { throw httpError(400, "Request body must be valid JSON."); } }
  return {};
}
function cleanText(value, word, limit) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  if (!text || text.length > limit || new RegExp("\\b" + word + "\\b", "i").test(text)) return "";
  return text;
}
const offlineHints = {
  ciao:["An informal Italian greeting used to say hello or goodbye.","You might say this when arriving at or leaving a friend's place.","interjection"],
  code:["Instructions written for a computer to follow.","A programmer may write this to make an app work.","noun"],
  website:["A collection of pages you can visit on the internet.","You might open one to read information.","noun"],
  compiler:["A program that translates source code into another form a computer can use.","Developers use this tool when building software.","noun"],
  apple:["A crisp fruit that may be red, green, or yellow.","You might pack one as a snack.","noun"],
  water:["A clear liquid that people, plants, and animals need to live.","You can drink it from a glass.","noun"],
  house:["A building where people live.","It often has rooms, a kitchen, and a roof.","noun"],
  music:["Sounds arranged in patterns of rhythm and melody.","People listen to it or play it.","noun"],
  book:["A set of pages with writing or pictures, usually bound together.","You can borrow one from a library.","noun"],
  computer:["An electronic device that processes information.","You can use one to learn, create, or play.","noun"],
  keyboard:["A set of keys used to type letters and commands.","You use one to enter text on a computer.","noun"],
  internet:["A worldwide network that connects computers and other devices.","You use it to visit websites.","noun"],
  garden:["A place where people grow flowers, fruit, or vegetables.","You might find a watering can here.","noun"],
  library:["A place where people can read or borrow books.","Students often visit one to study.","noun"],
  science:["The study of the natural world through questions and experiments.","It includes biology, chemistry, and physics.","noun"],
  network:["A group of connected people, computers, or things.","Devices use one to communicate.","noun"]
};
async function hintFor(client, sessionId, req) {
  const result = await client.query("SELECT gs.word,gs.difficulty,gs.player_id,w.category,w.definition,w.example,w.part_of_speech,w.syllable_count,w.pronunciation,w.frequency FROM game_sessions gs LEFT JOIN words w ON w.word=gs.word AND w.difficulty=gs.difficulty WHERE gs.id=$1", [sessionId]);
  const row = result.rows[0];
  if (!row) throw httpError(404, "Game session not found.");
  await enforceSessionOwner(client, row.player_id, req);
  const word = row.word.toLowerCase(), difficulty = row.difficulty, cacheKey = word + ":" + difficulty;
  if (hintCache.has(cacheKey)) return hintCache.get(cacheKey);
  let definition = cleanText(row.definition, word, 240), example = cleanText(row.example, word, 220), pos = row.part_of_speech || null, syllableCount = row.syllable_count || null, pronunciation = row.pronunciation || "", frequency = row.frequency == null ? null : Number(row.frequency), source = definition ? "curated" : null;
  if (!definition) {
    const dictionary = await lookupDictionary(word);
    if (dictionary.definition) {
      definition = dictionary.definition;
      example = dictionary.example;
      pos = dictionary.partOfSpeech || pos;
      syllableCount = dictionary.syllableCount || syllableCount;
      pronunciation = dictionary.pronunciation || pronunciation;
      frequency = dictionary.frequency == null ? frequency : dictionary.frequency;
      source = dictionary.source;
      await client.query(
        "UPDATE words SET definition=CASE WHEN definition IS NULL OR BTRIM(definition)='' THEN $1 ELSE definition END, example=CASE WHEN example IS NULL OR BTRIM(example)='' THEN $2 ELSE example END, part_of_speech=CASE WHEN part_of_speech IS NULL OR BTRIM(part_of_speech)='' THEN $3 ELSE part_of_speech END, syllable_count=COALESCE(syllable_count,$4), pronunciation=COALESCE(NULLIF(pronunciation,''),$5), frequency=COALESCE(frequency,$6) WHERE word=$7 AND difficulty=$8",
        [definition, example || null, pos, syllableCount, pronunciation || null, frequency, word, difficulty]
      );
    }
  }
  if(!definition && offlineHints[word]){[definition,example,pos]=offlineHints[word];source="offline";}
  let hint;
  if(!definition) {
    const category = row.category && row.category !== "general" ? row.category : "general vocabulary";
    definition = category === "general vocabulary"
      ? "A general vocabulary word with " + word.length + " letters. Think about where you might encounter it in everyday reading."
      : "A word connected with " + category + ". It has " + word.length + " letters; think of familiar examples from this topic.";
    pos = pos || null;
    source = "category-fallback";
  }
  if(difficulty==="hard") hint=source==="category-fallback"?definition:(pos||"Word").replace(/^./,c=>c.toUpperCase());
  else if(difficulty==="medium") hint=definition;
  else hint=definition+(example?" Example: "+example:"");
  const response={hint,meaning:definition,part_of_speech:pos,syllable_count:syllableCount,pronunciation,frequency,hint_source:source,hint_attribution:"Datamuse definitions are sourced from Wiktionary and WordNet. FreeDictionaryAPI.com is used as a fallback and uses Wiktionary content."};
  if(source!=="unavailable")hintCache.set(cacheKey,response);
  return response;
}
async function handler(req,res) {
  try {
    await ensureDatabase();
    const url=new URL(req.url,"https://word-hunt.local"), path=url.pathname.replace(/\/+$/,"")||"/", method=req.method||"GET";
    if(path==="/api/health"&&method==="GET")return await withClient(async client=>{
      const a=await client.query("SELECT COUNT(*)::int AS count FROM words"),b=await client.query("SELECT COUNT(*)::int AS count FROM players");
      return res.status(200).json({ok:true,database:"connected",words:a.rows[0].count,players:b.rows[0].count});
    });
    if(path==="/api/auth"&&method==="POST"&&url.searchParams.get("mode")==="register") {
      const body=await bodyOf(req),identity=normalizePlayerName(body.name);validatePassword(body.password);
      const passwordHash=await makePasswordHash(body.password);
      return await withClient(async client=>{
        try {
          await client.query("BEGIN");
          const existing=await client.query("SELECT id,account_type FROM players WHERE normalized_name=$1 FOR UPDATE",[identity.normalized]);
          if(existing.rows[0])throw httpError(409,existing.rows[0].account_type==="public"?"That name is already in use as a Public name. Choose another name.":"That protected name already exists. Sign in instead.");
          const inserted=await client.query("INSERT INTO players(name,normalized_name,account_type,password_hash) VALUES($1,$2,'protected',$3) RETURNING id",[identity.name,identity.normalized,passwordHash]);
          const token=crypto.randomBytes(32).toString("base64url");
          await client.query("INSERT INTO player_auth_sessions(player_id,token_hash,expires_at) VALUES($1,$2,NOW()+INTERVAL '30 days')",[inserted.rows[0].id,hash(token)]);
          await client.query("COMMIT");
          return res.status(200).json({auth_token:token,player_name:identity.name,verified:true});
        } catch(error){await client.query("ROLLBACK");if(error.code==="23505")throw httpError(409,"That protected name already exists. Sign in instead.");throw error;}
      });
    }
    if(path==="/api/auth"&&method==="POST"&&url.searchParams.get("mode")==="login") {
      const body=await bodyOf(req),identity=normalizePlayerName(body.name);
      if(typeof body.password!=="string")throw httpError(400,"Enter both player name and password.");
      return await withClient(async client=>{
        const found=await client.query("SELECT id,name,account_type,password_hash FROM players WHERE normalized_name=$1",[identity.normalized]),row=found.rows[0];
        if(!row||row.account_type!=="protected"||!row.password_hash||!(await checkPassword(body.password,row.password_hash)))throw httpError(401,"Name or password is incorrect.");
        const token=crypto.randomBytes(32).toString("base64url");
        await client.query("INSERT INTO player_auth_sessions(player_id,token_hash,expires_at) VALUES($1,$2,NOW()+INTERVAL '30 days')",[row.id,hash(token)]);
        return res.status(200).json({auth_token:token,player_name:row.name,verified:true});
      });
    }
    if(path==="/api/auth"&&method==="POST"&&url.searchParams.get("mode")==="logout") {
      const token=tokenFrom(req);if(token)await withClient(client=>client.query("DELETE FROM player_auth_sessions WHERE token_hash=$1",[hash(token)]));
      return res.status(200).json({ok:true});
    }
    if(path==="/api/new-game"&&method==="GET") {
      const difficulty=String(url.searchParams.get("difficulty")||"easy").toLowerCase();
      if(!Object.hasOwn(REWARDS,difficulty))throw httpError(400,"Choose easy, medium, or hard.");
      const identity=normalizePlayerName(url.searchParams.get("player_name"));
      return await withClient(async client=>{
        await client.query("BEGIN");
        try {
          const auth=await resolveAuthPlayer(client,req),found=await client.query("SELECT id,account_type FROM players WHERE normalized_name=$1 FOR UPDATE",[identity.normalized]);
          let playerId;
          if(found.rows[0]?.account_type==="protected") {
            if(!auth||auth.id!==found.rows[0].id)throw httpError(401,"This name is protected. Sign in to its account before playing.");
            playerId=found.rows[0].id;
          } else if(found.rows[0]) {
            if(auth)throw httpError(403,"A protected account cannot play under a Public name.");
            playerId=found.rows[0].id;
          } else {
            if(auth)throw httpError(403,"Use the name attached to your signed-in account.");
            const created=await client.query("INSERT INTO players(name,normalized_name,account_type) VALUES($1,$2,'public') RETURNING id",[identity.name,identity.normalized]);
            playerId=created.rows[0].id;
          }
          const selected=await client.query("SELECT word FROM words WHERE difficulty=$1 ORDER BY RANDOM() LIMIT 1",[difficulty]);
          if(!selected.rows[0])throw httpError(503,"No playable words are available for "+difficulty+".");
          const word=selected.rows[0].word;
          const session=await client.query("INSERT INTO game_sessions(word,difficulty,player_name,player_id,score,score_committed) VALUES($1,$2,$3,$4,$5,FALSE) RETURNING id",[word,difficulty,identity.name,playerId,REWARDS[difficulty]]);
          const stats=await client.query("SELECT total_score,current_streak,highest_streak FROM players WHERE id=$1",[playerId]),player=stats.rows[0];
          await client.query("COMMIT");
          return res.status(200).json({session_id:session.rows[0].id,masked_word:maskWord(word,new Set()),wrong_count:0,max_attempts:MAX_ATTEMPTS,status:"playing",hint:"Loading your word-specific dictionary hint…",difficulty_rule:RULES[difficulty],player_name:identity.name,score:REWARDS[difficulty],round_reward:REWARDS[difficulty],total_score:player.total_score,current_streak:player.current_streak,highest_streak:player.highest_streak});
        } catch(error){await client.query("ROLLBACK");if(error.code==="23505")throw httpError(409,"That player name was just claimed. Please try again.");throw error;}
      });
    }
    if(path==="/api/guess"&&method==="POST") {
      const body=await bodyOf(req),sessionId=Number(body.session_id),letter=String(body.letter||"").trim().toLowerCase();
      if(!Number.isInteger(sessionId)||sessionId<1)throw httpError(400,"A valid game session is required.");
      if(!/^[a-z]$/.test(letter))throw httpError(400,"Enter one letter from A to Z.");
      return await withClient(async client=>{
        await client.query("BEGIN");
        try {
          const found=await client.query("SELECT word,guessed_letters,wrong_count,status,difficulty,player_id,COALESCE(score,0) AS score,player_name,score_committed FROM game_sessions WHERE id=$1 FOR UPDATE",[sessionId]),row=found.rows[0];
          if(!row)throw httpError(404,"Game session not found. Start a new round.");
          await enforceSessionOwner(client,row.player_id,req);
          const guessed=new Set(row.guessed_letters?row.guessed_letters.split(","):[]);
          let wrong=row.wrong_count,status=row.status,score=row.score,totalScore=0,currentStreak=0,highestStreak=0;
          if(status==="playing"&&!guessed.has(letter)) {
            guessed.add(letter);
            if(!row.word.includes(letter)){wrong++;score=Math.max(0,score-PENALTIES[row.difficulty]);}
            status=[...new Set(row.word)].every(char=>guessed.has(char))?"won":wrong>=MAX_ATTEMPTS?"lost":"playing";
            if(status==="lost")score=0;
            await client.query("UPDATE game_sessions SET guessed_letters=$1,wrong_count=$2,status=$3,score=$4 WHERE id=$5",[[...guessed].sort().join(","),wrong,status,score,sessionId]);
            if(status==="won"&&!row.score_committed&&row.player_id!=null) {
              const stats=await client.query("UPDATE players SET total_score=total_score+$1,current_streak=current_streak+1,highest_streak=GREATEST(highest_streak,current_streak+1) WHERE id=$2 RETURNING total_score,current_streak,highest_streak",[score,row.player_id]);
              totalScore=stats.rows[0].total_score;currentStreak=stats.rows[0].current_streak;highestStreak=stats.rows[0].highest_streak;
              await client.query("UPDATE game_sessions SET score_committed=TRUE WHERE id=$1",[sessionId]);
            } else if(status==="lost"&&row.player_id!=null) {
              const stats=await client.query("UPDATE players SET current_streak=0 WHERE id=$1 RETURNING total_score,current_streak,highest_streak",[row.player_id]);
              totalScore=stats.rows[0].total_score;currentStreak=stats.rows[0].current_streak;highestStreak=stats.rows[0].highest_streak;
            } else if(row.player_id!=null) {
              const stats=await client.query("SELECT total_score,current_streak,highest_streak FROM players WHERE id=$1",[row.player_id]);
              totalScore=stats.rows[0].total_score;currentStreak=stats.rows[0].current_streak;highestStreak=stats.rows[0].highest_streak;
            }
          } else if(row.player_id!=null) {
            const stats=await client.query("SELECT total_score,current_streak,highest_streak FROM players WHERE id=$1",[row.player_id]);
            totalScore=stats.rows[0].total_score;currentStreak=stats.rows[0].current_streak;highestStreak=stats.rows[0].highest_streak;
          }
          await client.query("COMMIT");
          return res.status(200).json({masked_word:status==="lost"?row.word:maskWord(row.word,guessed),wrong_count:wrong,status,score,total_score:totalScore,current_streak:currentStreak,highest_streak:highestStreak,player_name:row.player_name,correct_guess:row.word.includes(letter),meaning_word:["won","lost"].includes(status)?row.word:null});
        } catch(error){await client.query("ROLLBACK");throw error;}
      });
    }
    if(path==="/api/leaderboard"&&method==="GET")return await withClient(async client=>{
      const found=await client.query("SELECT p.name,p.total_score,p.highest_streak,p.current_streak,COALESCE(latest.difficulty,'easy') AS difficulty,p.account_type FROM players p LEFT JOIN LATERAL(SELECT gs.difficulty FROM game_sessions gs WHERE gs.player_id=p.id ORDER BY gs.id DESC LIMIT 1) latest ON TRUE WHERE p.total_score>0 OR p.highest_streak>0 ORDER BY p.total_score DESC,p.highest_streak DESC,p.name ASC LIMIT 100");
      return res.status(200).json(found.rows.map(row=>({player_name:row.name,score:row.total_score,highest_streak:row.highest_streak,current_streak:row.current_streak,difficulty:row.difficulty,verified:row.account_type==="protected",section:row.account_type==="protected"?"verified":"public"})));
    });
    if(path==="/api/end-game"&&method==="POST")return await withClient(async client=>{

      const sessionId=Number(url.searchParams.get("session_id"));
      if(!Number.isInteger(sessionId)||sessionId<1)throw httpError(400,"A valid game session is required.");
      await client.query("BEGIN");
      try {
        const owner=await client.query("SELECT player_id,status FROM game_sessions WHERE id=$1 FOR UPDATE",[sessionId]);
        if(!owner.rows[0])throw httpError(404,"Game session not found.");
        await enforceSessionOwner(client,owner.rows[0].player_id,req);
        const updated=await client.query("UPDATE game_sessions SET status='abandoned' WHERE id=$1 AND status='playing' RETURNING id",[sessionId]);
        await client.query("COMMIT");
        return res.status(200).json(updated.rows[0]?{status:"abandoned",message:"Round ended. Your lifetime score and streak were kept."}:{status:owner.rows[0].status,message:"This round is already finished."});
      } catch(error){await client.query("ROLLBACK");throw error;}
    });
    if(path==="/api/hint"&&method==="GET") {
      const sessionId=Number(url.searchParams.get("session_id"));
      if(!Number.isInteger(sessionId)||sessionId<1)throw httpError(400,"A valid game session is required.");
      return await withClient(async client=>res.status(200).json(await hintFor(client,sessionId,req)));
    }
    throw httpError(404,"API route not found.");
  } catch(error) {
    const status=Number(error.status)||(error.code==="23505"?409:500);
    if(status>=500)console.error("Word Hunt API error:",error);
    return res.status(status).json({detail:status===500?"The server could not complete this request.":error.message});
  }
}
module.exports=handler;
module.exports.config={api:{bodyParser:{sizeLimit:"1mb"}}};

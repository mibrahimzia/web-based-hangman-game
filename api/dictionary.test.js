"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { lookupDictionary } = require("./dictionary");

function response(status, body) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

test("parses dictionaryapi.dev definitions, examples, and part of speech", async () => {
  const result = await lookupDictionary("apple", {
    fetchImpl: async () => response(200, [{
      meanings: [{ partOfSpeech: "noun", definitions: [{ definition: "A crisp fruit.", example: "She packed a crisp fruit." }] }]
    }])
  });
  assert.equal(result.definition, "A crisp fruit.");
  assert.equal(result.example, "She packed a crisp fruit.");
  assert.equal(result.partOfSpeech, "noun");
  assert.equal(result.source, "dictionaryapi.dev");
});

test("falls back to FreeDictionaryAPI when the first provider has no entry", async () => {
  let calls = 0;
  const result = await lookupDictionary("orbit", {
    fetchImpl: async () => {
      calls++;
      return calls === 1
        ? response(404, { title: "No Definitions Found" })
        : response(200, { entries: [{ partOfSpeech: "noun", senses: [{ definition: "The curved path of one object around another." }] }] });
    }
  });
  assert.equal(calls, 2);
  assert.match(result.definition, /curved path/);
  assert.equal(result.source, "freedictionaryapi.com");
});

test("rejects empty, oversized, and self-referential definitions", async () => {
  const result = await lookupDictionary("apple", {
    fetchImpl: async () => response(200, [{ meanings: [{ definitions: [
      { definition: "" },
      { definition: "An apple is a fruit." },
      { definition: "x".repeat(241) }
    ] }] }])
  });
  assert.equal(result.definition, "");
  assert.equal(result.source, null);
});

test("continues to the backup provider after malformed JSON", async () => {
  let calls = 0;
  const result = await lookupDictionary("orbit", {
    fetchImpl: async () => {
      calls++;
      if (calls === 1) return { ok: true, status: 200, json: async () => { throw new SyntaxError("bad json"); } };
      return response(200, { entries: [{ senses: [{ definition: "A regular curved path through space." }] }] });
    }
  });
  assert.equal(calls, 2);
  assert.match(result.definition, /curved path/);
});

test("returns explicit diagnostics when providers fail", async () => {
  const result = await lookupDictionary("unlistedword", {
    fetchImpl: async () => response(503, {})
  });
  assert.equal(result.definition, "");
  assert.deepEqual(result.diagnostics.map(item => item.status), [503, 503]);
  assert.deepEqual(result.diagnostics.map(item => item.result), ["http_error", "http_error"]);
});

test("does not leak the requested word in diagnostic records", async () => {
  const result = await lookupDictionary("privateword", {
    fetchImpl: async () => response(502, {})
  });
  assert.equal(JSON.stringify(result.diagnostics).includes("privateword"), false);
});

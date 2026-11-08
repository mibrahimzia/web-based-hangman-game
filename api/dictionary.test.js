"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { lookupDictionary } = require("./dictionary");

function response(status, body) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

test("uses FreeDictionaryAPI as the primary clue provider", async () => {
  const result = await lookupDictionary("orbit", {
    fetchImpl: async () => response(200, {
      entries: [{ partOfSpeech: "noun", senses: [{
        definition: "The curved path of one object around another.",
        examples: ["The moon follows a curved path around Earth."]
      }] }]
    })
  });
  assert.match(result.definition, /curved path/);
  assert.match(result.example, /moon/);
  assert.equal(result.partOfSpeech, "noun");
  assert.equal(result.source, "freedictionaryapi.com");
  assert.equal(result.diagnostics.length, 1);
});

test("falls back to dictionaryapi.dev when FreeDictionaryAPI has no entry", async () => {
  let calls = 0;
  const result = await lookupDictionary("apple", {
    fetchImpl: async () => {
      calls++;
      return calls === 1
        ? response(404, { title: "No Definitions Found" })
        : response(200, [{
          meanings: [{ partOfSpeech: "noun", definitions: [{ definition: "A crisp fruit." }] }]
        }]);
    }
  });
  assert.equal(calls, 2);
  assert.equal(result.definition, "A crisp fruit.");
  assert.equal(result.source, "dictionaryapi.dev");
});

test("rejects empty, oversized, and self-referential definitions", async () => {
  const result = await lookupDictionary("apple", {
    fetchImpl: async () => response(200, { entries: [{ senses: [{ definition: "An apple is a fruit." }, { definition: "x".repeat(241) }] }] })
  });
  assert.equal(result.definition, "");
  assert.equal(result.source, null);
});

test("continues to the backup provider after malformed JSON", async () => {
  let calls = 0;
  const result = await lookupDictionary("apple", {
    fetchImpl: async () => {
      calls++;
      if (calls === 1) return { ok: true, status: 200, json: async () => { throw new SyntaxError("bad json"); } };
      return response(200, [{ meanings: [{ definitions: [{ definition: "A crisp fruit." }] }] }]);
    }
  });
  assert.equal(calls, 2);
  assert.equal(result.definition, "A crisp fruit.");
  assert.equal(result.source, "dictionaryapi.dev");
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

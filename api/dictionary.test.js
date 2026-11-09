"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { lookupDictionary } = require("./dictionary");

function response(status, body) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

test("uses Datamuse as the primary clue provider", async () => {
  const result = await lookupDictionary("orbit", {
    fetchImpl: async url => {
      assert.match(url, /api\.datamuse\.com\/words/);
      return response(200, [{ word: "orbit", defs: ["n\tThe curved path of one object around another."], tags: ["n", "pron:AO1 R B IH0 T", "f:2.4"], numSyllables: 2 }]);
    }
  });
  assert.match(result.definition, /curved path/);
  assert.equal(result.syllableCount, 2);
  assert.equal(result.pronunciation, "AO1 R B IH0 T");
  assert.equal(result.frequency, 2.4);
  assert.equal(result.partOfSpeech, "noun");
  assert.equal(result.source, "datamuse");
  assert.equal(result.diagnostics.length, 1);
});

test("falls back to FreeDictionaryAPI when Datamuse has no entry", async () => {
  let calls = 0;
  const result = await lookupDictionary("apple", {
    fetchImpl: async () => {
      calls++;
      return calls === 1
        ? response(404, { title: "No Definitions Found" })
        : response(200, { entries: [{ partOfSpeech: "noun", senses: [{ definition: "A crisp fruit." }] }] });
    }
  });
  assert.equal(calls, 2);
  assert.equal(result.definition, "A crisp fruit.");
  assert.equal(result.source, "freedictionaryapi.com");
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
      return response(200, { entries: [{ senses: [{ definition: "A crisp fruit." }] }] });
    }
  });
  assert.equal(calls, 2);
  assert.equal(result.definition, "A crisp fruit.");
  assert.equal(result.source, "freedictionaryapi.com");
});

test("returns explicit diagnostics when providers fail", async () => {
  const result = await lookupDictionary("unlistedword", {
    fetchImpl: async () => response(503, {})
  });
  assert.equal(result.definition, "");
  assert.deepEqual(result.diagnostics.map(item => item.status), [503, 503, 503]);
  assert.deepEqual(result.diagnostics.map(item => item.result), ["http_error", "http_error", "http_error"]);
});

test("does not leak the requested word in diagnostic records", async () => {
  const result = await lookupDictionary("privateword", {
    fetchImpl: async () => response(502, {})
  });
  assert.equal(JSON.stringify(result.diagnostics).includes("privateword"), false);
});

test("rejects colloquial and outdated dictionary senses", async () => {
  const result = await lookupDictionary("jane", {
    fetchImpl: async () => response(200, [{ word: "jane", defs: ["n\\t(colloquial) used as a placeholder name for any woman."], tags: ["n"] }])
  });
  assert.equal(result.definition, "");
  assert.equal(result.source, null);
});

test("does not accept a non-exact Datamuse spelling result", async () => {
  const result = await lookupDictionary("jane", {
    fetchImpl: async () => response(200, [{ word: "janes", defs: ["n\\tA plural form."], tags: ["n"] }])
  });
  assert.equal(result.definition, "");
  assert.equal(result.source, null);
});

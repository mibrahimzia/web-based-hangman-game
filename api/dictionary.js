"use strict";

const PROVIDERS = [
  {
    name: "dictionaryapi.dev",
    url: word => "https://api.dictionaryapi.dev/api/v2/entries/en/" + encodeURIComponent(word),
    parse(data, word) {
      const result = { definition: "", example: "", partOfSpeech: "" };
      if (!Array.isArray(data)) return result;
      for (const entry of data) {
        for (const meaning of entry.meanings || []) {
          if (!result.partOfSpeech && meaning.partOfSpeech) result.partOfSpeech = meaning.partOfSpeech;
          for (const item of meaning.definitions || []) {
            if (!result.definition) result.definition = clean(item.definition, word, 240);
            if (!result.example) result.example = clean(item.example, word, 220);
            if (result.definition) return result;
          }
        }
      }
      return result;
    }
  },
  {
    name: "freedictionaryapi.com",
    url: word => "https://freedictionaryapi.com/api/v1/entries/en/" + encodeURIComponent(word),
    parse(data, word) {
      const result = { definition: "", example: "", partOfSpeech: "" };
      for (const entry of (data && data.entries) || []) {
        if (!result.partOfSpeech && entry.partOfSpeech) result.partOfSpeech = entry.partOfSpeech;
        for (const sense of entry.senses || []) {
          if (!result.definition) result.definition = clean(sense.definition, word, 240);
          if (!result.example) {
            for (const example of sense.examples || []) {
              result.example = clean(example, word, 220);
              if (result.example) break;
            }
          }
          for (const sub of sense.subsenses || []) {
            if (!result.definition) result.definition = clean(sub.definition, word, 240);
            if (!result.example) {
              for (const example of sub.examples || []) {
                result.example = clean(example, word, 220);
                if (result.example) break;
              }
            }
          }
          if (result.definition) return result;
        }
      }
      return result;
    }
  }
];

function clean(value, word, limit) {
  const text = String(value || "").replace(/\\s+/g, " ").trim();
  if (!text || text.length > limit || new RegExp("\\\\b" + word + "\\\\b", "i").test(text)) return "";
  return text;
}

async function lookupDictionary(word, options = {}) {
  const fetchImpl = options.fetchImpl || globalThis.fetch;
  const timeoutMs = options.timeoutMs || 4000;
  const diagnostics = [];
  for (const provider of PROVIDERS) {
    const started = Date.now();
    try {
      const response = await fetchImpl(provider.url(word), {
        headers: { "User-Agent": "WordHunt-EF101/2.1" },
        signal: AbortSignal.timeout(timeoutMs)
      });
      if (!response.ok) {
        diagnostics.push({ provider: provider.name, status: response.status, elapsedMs: Date.now() - started, result: "http_error" });
        continue;
      }
      const data = await response.json();
      const parsed = provider.parse(data, word);
      diagnostics.push({
        provider: provider.name,
        status: response.status,
        elapsedMs: Date.now() - started,
        result: parsed.definition ? "definition_found" : "no_usable_definition"
      });
      if (parsed.definition) {
        for (const item of diagnostics) console.info("[dictionary]", JSON.stringify(item));
        return { ...parsed, source: provider.name, diagnostics };
      }
    } catch (error) {
      diagnostics.push({
        provider: provider.name,
        elapsedMs: Date.now() - started,
        result: error && error.name === "TimeoutError" ? "timeout" : "request_or_parse_error"
      });
    }
  }
  for (const item of diagnostics) console.warn("[dictionary]", JSON.stringify(item));
  return { definition: "", example: "", partOfSpeech: "", source: null, diagnostics };
}

module.exports = { lookupDictionary };

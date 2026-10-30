#!/usr/bin/env python3
"""Build a review queue of vocabulary candidates from the Datamuse API.

This script intentionally DOES NOT add API results to the live word bank.
Datamuse is a word-finding engine, not a child-safety or political-content
moderation service. Every candidate must be reviewed before it is copied
into data/common_words.txt.
"""
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

SEEDS = [
    "nature", "science", "weather", "geography", "music", "art",
    "sports", "school", "literature", "technology", "animals",
    "plants", "space", "food", "travel", "mathematics",
]
API = "https://api.datamuse.com/words"


def query(seed):
    params = urllib.parse.urlencode({"ml": seed, "max": 1000, "md": "dp"})
    request = urllib.request.Request(
        API + "?" + params,
        headers={"User-Agent": "WordHuntVocabularyReview/1.0"},
    )
    with urllib.request.urlopen(request, timeout=12) as response:
        return json.load(response)


def main():
    candidates = set()
    for seed in SEEDS:
        try:
            for item in query(seed):
                word = str(item.get("word", "")).strip().lower()
                if re.fullmatch(r"[a-z]{4,20}", word):
                    candidates.add(word)
        except Exception as exc:
            print(f"Datamuse query for {seed!r} failed: {exc}")
        time.sleep(0.15)

    current = set(
        line.strip().lower()
        for line in Path("data/common_words.txt").read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    review = sorted(candidates - current)
    Path("data/datamuse_review_queue.txt").write_text(
        "\n".join(review) + ("\n" if review else ""), encoding="utf-8"
    )
    print(f"{len(review)} new candidates written to data/datamuse_review_queue.txt")
    print("Review each candidate for age-appropriateness and non-political content before approval.")


if __name__ == "__main__":
    main()

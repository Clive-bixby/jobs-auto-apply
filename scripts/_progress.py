"""Progress report: applications per portal today + skip/failure reasons."""
from __future__ import annotations

import io
import json
import sys
from collections import Counter
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

TARGET = 25
# Session start — goals are per session, not per calendar day (runs cross midnight).
SINCE = "2026-11-02"
base = Path("data")


def load(name: str):
    p = base / name
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8-sig"))


led = load("applied_jobs.json") or {}
hist = [h for h in led.get("history", []) if isinstance(h, dict)]

applied_today = [
    h for h in hist
    if h.get("status") == "applied" and str(h.get("applied_at", ""))[:10] >= SINCE
]
counts = Counter(h.get("source") for h in applied_today)

PORTALS = ["naukri", "hirist", "wellfound", "instahyre"]
print(f"=== Applications since session start ({SINCE}) — goal {TARGET} per portal")
total = 0
for p in PORTALS:
    n = counts.get(p, 0)
    total += n
    bar = "OK " if n >= TARGET else "..."
    print(f"  {bar} {p:<10} {n:>2}/{TARGET}   {'+' + str(TARGET - n) + ' to go' if n < TARGET else 'target met'}")
print(f"  {'='*40}\n  TOTAL       {total}/{TARGET * len(PORTALS)}")

abandoned_today = [
    h for h in hist
    if h.get("status") == "abandoned" and str(h.get("applied_at", ""))[:10] >= SINCE
]
print(f"\nSkipped/abandoned this session: {len(abandoned_today)}")
for src, n in Counter(h.get("source") for h in abandoned_today).most_common():
    print(f"  {src}: {n}")

tf = load("technical_failures.json") or {}
fails = tf.get("failures", {}) if isinstance(tf, dict) else {}
print(f"\nTechnical failures on record: {len(fails)}")
by_src = Counter(v.get("source") for v in fails.values() if isinstance(v, dict))
print("  " + ", ".join(f"{k}={v}" for k, v in by_src.most_common()))

pq = load("pending_questions.json") or {}
print(f"Pending (unanswered) questions: {len(pq.get('questions', {}))}")

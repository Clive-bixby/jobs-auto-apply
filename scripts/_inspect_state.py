import json, collections, io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

def load(p):
    return json.load(open(p, encoding="utf-8-sig"))

d = load("data/applied_jobs.json")
ap = d["applied"]
print("applied type:", type(ap), "len:", len(ap))
if isinstance(ap, dict):
    k = next(iter(ap))
    print("first entry:", k, "->", json.dumps(ap[k])[:500])
    c = collections.Counter()
    today = collections.Counter()
    for k, v in ap.items():
        plat = k.split(":")[0]
        c[plat] += 1
        ts = str(v.get("applied_at") or v.get("date") or "") if isinstance(v, dict) else ""
        if ts.startswith("2026-11-02"):
            today[plat] += 1
    print("by platform:", dict(c))
    print("today by platform:", dict(today))
else:
    print("first:", ap[:5])

pq = load("data/pending_questions.json")["questions"]
print("\npending questions:", len(pq))
for i, (k, v) in enumerate(pq.items()):
    if i >= 50:
        break
    if isinstance(v, dict):
        print(f"- [{k}] {str(v.get('question',''))[:160]} | platform={v.get('platform')} job={str(v.get('job_key',''))[:60]}")
    else:
        print(f"- [{k}] {str(v)[:200]}")

tf = load("data/technical_failures.json")
print("\ntechnical_failures type:", type(tf))
items = tf if isinstance(tf, list) else (tf.get("failures") or tf.get("jobs") or tf.get("entries") or [])
if isinstance(tf, dict) and not items:
    print("keys:", list(tf.keys()))
    for k, v in list(tf.items())[:5]:
        print(" ", k, "->", json.dumps(v)[:250])
print("count:", len(items) if hasattr(items, "__len__") else "?")
for f in (items if isinstance(items, list) else [])[:10]:
    print("*", json.dumps(f)[:300])

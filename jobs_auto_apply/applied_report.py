"""Export the applied-jobs history as an Excel-friendly CSV and an HTML dashboard.

``data/applied_jobs.json`` already records the platform, role, company, URL and
timestamp of every attempt. This turns it into two artifacts a human can read
without opening the JSON:

* ``data/applied_jobs.csv``  — opens directly in Excel / Google Sheets
* ``data/applied_jobs.html`` — self-contained dashboard (no server, no assets)

The dashboard borrows its shape from the applied-jobs views of the big boards:
LinkedIn's status chips + company avatars, Indeed's search/status filters, and
Naukri's title/company/date/status rows.

Timestamps are stored in UTC and rendered in the machine's local time zone.
"""

from __future__ import annotations

import csv
import html
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import AppConfig

PLATFORM_LABELS = {
    "naukri": "Naukri",
    "hirist": "Hirist",
    "instahyre": "Instahyre",
    "uplers": "Uplers",
    "wellfound": "Wellfound",
}

CSV_COLUMNS = ["Applied at", "Platform", "Role", "Company", "Status", "Job ID", "URL", "Reason"]

# Aware sentinel so rows without a parseable timestamp still sort.
_EPOCH = datetime.min.replace(tzinfo=timezone.utc)

_PLATFORM_COLORS = {
    "naukri": "#0369a1",
    "hirist": "#b45309",
    "instahyre": "#6d28d9",
    "uplers": "#15803d",
    "wellfound": "#be185d",
}

_AVATAR_COLORS = (
    "#4f46e5",
    "#0891b2",
    "#059669",
    "#d97706",
    "#dc2626",
    "#7c3aed",
    "#db2777",
    "#0284c7",
)

# Order matters: the first family whose needle appears in the title wins, so
# "Full Stack" beats the "React"/"Node" needles inside it.
_ROLE_FAMILIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "AI / ML",
        (
            "ai ",
            " ai",
            "ai/",
            " ml",
            "ml ",
            "machine learning",
            "genai",
            "llm",
            "nlp",
            "mlops",
            "data scien",
        ),
    ),
    ("Full Stack", ("full stack", "fullstack", "full-stack", "mern", "mean stack")),
    ("Frontend", ("frontend", "front end", "front-end", "react", "angular", "vue", "next.js")),
    (
        "Backend",
        ("backend", "back end", "back-end", "node", "python", "java", "golang", "django", "flask", "microservice"),
    ),
    ("Mobile", ("android", "ios ", "flutter", "react native")),
    ("Data", ("data engineer", "etl", "analytics", "big data")),
    ("QA / Test", ("qa", "quality", "sdet", "test engineer", "automation test")),
)


def role_family(title: str) -> str:
    """Bucket a job title into a coarse family for filtering."""
    text = f" {(title or '').lower()} "
    for family, needles in _ROLE_FAMILIES:
        if any(needle in text for needle in needles):
            return family
    return "Other"


def _relative(when: datetime | None) -> str:
    if when is None:
        return ""
    days = (datetime.now().astimezone() - when).days
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 7:
        return f"{days}d ago"
    if days < 30:
        return f"{days // 7}w ago"
    return f"{days // 30}mo ago"


def _avatar_color(name: str) -> str:
    return _AVATAR_COLORS[sum(ord(ch) for ch in name) % len(_AVATAR_COLORS)]


def load_history(path: Path) -> list[dict[str, Any]]:
    """Return the raw history rows, tolerating a missing or malformed file."""
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8") or "{}")
    except (OSError, json.JSONDecodeError):
        return []
    history = payload.get("history") if isinstance(payload, dict) else None
    return [entry for entry in history or [] if isinstance(entry, dict)]


def _platform(entry: dict[str, Any]) -> tuple[str, str]:
    raw = str(entry.get("source") or "").strip().lower()
    if not raw:
        key = str(entry.get("job_key") or "")
        raw = key.split(":", 1)[0].lower() if ":" in key else ""
    return raw, PLATFORM_LABELS.get(raw, raw.title() or "-")


def _local_time(value: Any) -> tuple[datetime | None, str]:
    if not value:
        return None, ""
    try:
        when = datetime.fromisoformat(str(value))
    except ValueError:
        return None, str(value)
    if when.tzinfo is not None:
        when = when.astimezone()
    return when, when.strftime("%Y-%m-%d %H:%M")


def build_rows(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalise history entries into display rows, newest first."""
    rows: list[dict[str, Any]] = []
    for entry in history:
        when, label = _local_time(entry.get("applied_at"))
        platform_key, platform = _platform(entry)
        key = str(entry.get("job_key") or "")
        role = str(entry.get("title") or "").strip() or "-"
        company = str(entry.get("company") or "").strip() or "-"
        status = str(entry.get("status") or "").strip() or "-"
        family = role_family(role)
        rows.append(
            {
                "when": when,
                "applied_at": label,
                "relative": _relative(when),
                "ts": int(when.timestamp() * 1000) if when else 0,
                "platform_key": platform_key,
                "platform": platform,
                "role": role,
                "company": company,
                "initial": (company[:1] or "?").upper(),
                "avatar_color": _avatar_color(company),
                "family": family,
                "status": status,
                "job_id": key.split(":", 1)[-1] if key else "",
                "url": str(entry.get("url") or ""),
                "reason": str(entry.get("reason") or ""),
            }
        )
    rows.sort(key=lambda row: row["when"] or _EPOCH, reverse=True)
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write UTF-8-with-BOM so Excel renders non-ASCII titles correctly."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_COLUMNS)
        for row in rows:
            writer.writerow(
                [
                    row["applied_at"],
                    row["platform"],
                    row["role"],
                    row["company"],
                    row["status"],
                    row["job_id"],
                    row["url"],
                    row["reason"],
                ]
            )


def _escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _table_rows(rows: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for row in rows:
        url = row["url"]
        link = (
            f'<a class="open" href="{_escape(url)}" target="_blank" rel="noopener">Open</a>'
            if url
            else '<span class="muted">&mdash;</span>'
        )
        search = " ".join(
            [row["role"], row["company"], row["platform"], row["family"], row["status"]]
        ).lower()
        parts.append(
            f'<tr data-platform="{_escape(row["platform_key"])}" '
            f'data-status="{_escape(row["status"])}" '
            f'data-family="{_escape(row["family"])}" '
            f'data-ts="{row["ts"]}" '
            f'data-role="{_escape(row["role"].lower())}" '
            f'data-company="{_escape(row["company"].lower())}" '
            f'data-search="{_escape(search)}">'
            f'<td class="when"><div>{_escape(row["applied_at"])}</div>'
            f'<div class="rel">{_escape(row["relative"])}</div></td>'
            f'<td><span class="pill p-{_escape(row["platform_key"])}">'
            f"{_escape(row['platform'])}</span></td>"
            f'<td class="role"><div>{_escape(row["role"])}</div>'
            f'<div class="family">{_escape(row["family"])}</div></td>'
            f'<td><div class="company">'
            f'<span class="av" style="background:{_escape(row["avatar_color"])}">'
            f'{_escape(row["initial"])}</span>'
            f'<span>{_escape(row["company"])}</span></div></td>'
            f'<td><span class="chip c-{_escape(row["status"])}">'
            f'{_escape(row["status"])}</span></td>'
            f'<td class="reason">{_escape(row["reason"]) or "&mdash;"}</td>'
            f"<td>{link}</td>"
            "</tr>"
        )
    return "\n".join(parts)


def _platform_bars(applied: list[dict[str, Any]]) -> str:
    counts = Counter(row["platform_key"] for row in applied)
    if not counts:
        return '<div class="muted">No applications yet.</div>'
    top = max(counts.values()) or 1
    bars = []
    for key, count in counts.most_common():
        width = max(4, round(count / top * 100))
        color = _PLATFORM_COLORS.get(key, "#64748b")
        bars.append(
            f'<div class="barrow"><span class="barlabel">'
            f"{_escape(PLATFORM_LABELS.get(key, key.title()))}</span>"
            f'<span class="bartrack"><span class="barfill" '
            f'style="width:{width}%;background:{color}"></span></span>'
            f'<span class="barval">{count}</span></div>'
        )
    return "".join(bars)


def _cards(applied: list[dict[str, Any]], platforms: int) -> str:
    cutoff = datetime.now(timezone.utc).astimezone() - timedelta(days=7)
    last_week = sum(1 for row in applied if row["when"] and row["when"] >= cutoff)
    companies = len({row["company"] for row in applied if row["company"] != "-"})
    cards = (
        (len(applied), "Applied"),
        (last_week, "Last 7 days"),
        (companies, "Companies"),
        (platforms, "Platforms"),
    )
    return "".join(
        f'<div class="card"><div class="n">{value}</div><div class="k">{label}</div></div>'
        for value, label in cards
    )


_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Applied jobs</title>
<style>
  :root {
    --ink:#0f172a; --muted:#64748b; --line:#e2e8f0; --bg:#f6f8fb; --card:#ffffff;
    --accent:#4f46e5; --accent-soft:#eef2ff;
  }
  * { box-sizing:border-box; }
  body { margin:0; padding:32px 20px 64px; background:var(--bg); color:var(--ink);
         font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; }
  .wrap { max-width:1180px; margin:0 auto; }
  header { display:flex; align-items:flex-start; justify-content:space-between;
           gap:16px; flex-wrap:wrap; margin-bottom:22px; }
  h1 { margin:0 0 4px; font-size:24px; letter-spacing:-.01em; }
  .sub { margin:0; color:var(--muted); font-size:13px; }
  .btn { display:inline-flex; align-items:center; gap:8px; padding:9px 14px; border-radius:9px;
         background:var(--accent); color:#fff; text-decoration:none; font-weight:600; font-size:13px;
         box-shadow:0 1px 2px rgba(15,23,42,.12); }
  .btn:hover { background:#4338ca; }
  .stats { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
           gap:12px; margin-bottom:16px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:14px 18px; }
  .card .n { font-size:26px; font-weight:700; line-height:1.15; letter-spacing:-.02em; }
  .card .k { color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.05em; }
  .panel { background:var(--card); border:1px solid var(--line); border-radius:12px;
           padding:14px 18px; margin-bottom:16px; }
  .panel-head { display:flex; align-items:baseline; justify-content:space-between; margin-bottom:10px; }
  .panel-head h2 { margin:0; font-size:13px; text-transform:uppercase; letter-spacing:.05em; color:var(--muted); }
  .bars { display:grid; gap:8px; }
  .barrow { display:grid; grid-template-columns:88px 1fr 40px; align-items:center; gap:10px; }
  .barlabel { font-size:13px; color:var(--muted); }
  .bartrack { height:8px; background:#eef2f7; border-radius:999px; overflow:hidden; }
  .barfill { display:block; height:100%; border-radius:999px; }
  .barval { text-align:right; font-size:13px; font-weight:600; }
  .filters { display:flex; flex-wrap:wrap; gap:10px; margin-bottom:12px; }
  input, select, button { font:inherit; color:inherit; }
  input, select { padding:9px 11px; border:1px solid var(--line); border-radius:9px; background:#fff; }
  input:focus, select:focus { outline:2px solid var(--accent-soft); border-color:var(--accent); }
  #q { flex:1 1 260px; }
  button { padding:9px 13px; border:1px solid var(--line); border-radius:9px; background:#fff;
           cursor:pointer; color:var(--muted); }
  button:hover { background:#f8fafc; color:var(--ink); }
  .meta { color:var(--muted); font-size:13px; margin:0 0 8px; }
  .tablewrap { background:var(--card); border:1px solid var(--line); border-radius:12px;
               overflow:auto; }
  table { width:100%; border-collapse:collapse; min-width:860px; }
  th, td { text-align:left; padding:11px 14px; border-bottom:1px solid var(--line); vertical-align:middle; }
  th { position:sticky; top:0; z-index:1; background:#f8fafc; font-size:11px;
       text-transform:uppercase; letter-spacing:.06em; color:var(--muted); font-weight:600; }
  tbody tr:last-child td { border-bottom:0; }
  tbody tr:hover { background:#fafbfd; }
  .when { white-space:nowrap; color:var(--muted); font-variant-numeric:tabular-nums; }
  .when .rel { font-size:12px; color:#94a3b8; }
  .role > div:first-child { font-weight:600; }
  .family { font-size:12px; color:var(--muted); }
  .company { display:flex; align-items:center; gap:9px; }
  .av { display:inline-flex; align-items:center; justify-content:center; width:26px; height:26px;
        border-radius:8px; color:#fff; font-size:12px; font-weight:700; flex:none; }
  .pill { display:inline-block; padding:2px 9px; border-radius:999px; font-size:12px;
          font-weight:600; background:#eef2ff; color:#3730a3; white-space:nowrap; }
  .p-naukri { background:#e0f2fe; color:#075985; }
  .p-hirist { background:#fef3c7; color:#92400e; }
  .p-instahyre { background:#ede9fe; color:#5b21b6; }
  .p-uplers { background:#dcfce7; color:#166534; }
  .p-wellfound { background:#fce7f3; color:#9d174d; }
  .chip { display:inline-block; padding:2px 9px; border-radius:999px; font-size:12px;
          font-weight:600; text-transform:capitalize; white-space:nowrap; }
  .c-applied { background:#dcfce7; color:#166534; }
  .c-abandoned { background:#fee2e2; color:#991b1b; }
  .c-deferred { background:#fef3c7; color:#92400e; }
  .reason { color:var(--muted); font-size:13px; max-width:220px; }
  .open { color:var(--accent); text-decoration:none; font-weight:600; font-size:13px; }
  .open:hover { text-decoration:underline; }
  .muted { color:var(--muted); }
  .empty { padding:36px; text-align:center; color:var(--muted); }
  footer { margin-top:18px; color:#94a3b8; font-size:12px; text-align:center; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <h1>Applied jobs</h1>
      <p class="sub">Generated __GENERATED__ &middot; __TOTAL__ applications tracked</p>
    </div>
    <a class="btn" href="applied_jobs.csv" download>Export CSV</a>
  </header>

  <section class="stats">__CARDS__</section>

  <section class="panel">
    <div class="panel-head">
      <h2>By platform</h2>
      <span class="muted">__PLATFORM_COUNT__ platforms</span>
    </div>
    <div class="bars">__BARS__</div>
  </section>

  <section class="filters">
    <input id="q" type="search" placeholder="Search role, company, platform&hellip;" autocomplete="off">
    <select id="platform">
      <option value="">All platforms</option>
      __PLATFORM_OPTIONS__
    </select>
    <select id="family">
      <option value="">All role types</option>
      __FAMILY_OPTIONS__
    </select>
    <select id="status">
      <option value="applied">Applied</option>
      <option value="">All statuses</option>
      <option value="abandoned">Abandoned</option>
      <option value="deferred">Deferred</option>
    </select>
    <select id="range">
      <option value="">All time</option>
      <option value="7">Last 7 days</option>
      <option value="30">Last 30 days</option>
      <option value="90">Last 90 days</option>
    </select>
    <select id="sort">
      <option value="newest">Newest first</option>
      <option value="oldest">Oldest first</option>
      <option value="role">Role A&ndash;Z</option>
      <option value="company">Company A&ndash;Z</option>
    </select>
    <button id="clear" type="button">Clear</button>
  </section>

  <p class="meta"><span id="count"></span></p>

  <div class="tablewrap">
    <table>
      <thead><tr>
        <th>Applied</th><th>Platform</th><th>Role</th><th>Company</th>
        <th>Status</th><th>Reason</th><th>Job</th>
      </tr></thead>
      <tbody id="rows">
__ROWS__
      </tbody>
    </table>
    <div id="empty" class="empty" hidden>No applications match these filters.</div>
  </div>

  <footer>jobs-auto-apply &middot; regenerate with <code>python main.py export</code></footer>
</div>
<script>
  const byId = (id) => document.getElementById(id);
  const tbody = byId('rows');
  const rows = Array.from(tbody.querySelectorAll('tr'));
  const q = byId('q'), platform = byId('platform'), family = byId('family');
  const status = byId('status'), range = byId('range'), sort = byId('sort');

  function applySort() {
    const mode = sort.value;
    const sorted = rows.slice().sort((a, b) => {
      if (mode === 'oldest') return Number(a.dataset.ts) - Number(b.dataset.ts);
      if (mode === 'role') return a.dataset.role.localeCompare(b.dataset.role);
      if (mode === 'company') return a.dataset.company.localeCompare(b.dataset.company);
      return Number(b.dataset.ts) - Number(a.dataset.ts);
    });
    for (const row of sorted) tbody.appendChild(row);
  }

  function applyFilters() {
    const needle = q.value.trim().toLowerCase();
    const days = Number(range.value || 0);
    const cutoff = days ? Date.now() - days * 86400000 : 0;
    let shown = 0;
    for (const row of rows) {
      const ok = (!needle || row.dataset.search.includes(needle))
        && (!platform.value || row.dataset.platform === platform.value)
        && (!family.value || row.dataset.family === family.value)
        && (!status.value || row.dataset.status === status.value)
        && (!cutoff || Number(row.dataset.ts) >= cutoff);
      row.hidden = !ok;
      if (ok) shown += 1;
    }
    byId('count').textContent = 'Showing ' + shown + ' of ' + rows.length + ' applications';
    byId('empty').hidden = shown !== 0;
  }

  function refresh() { applySort(); applyFilters(); }
  [q, platform, family, status, range].forEach((el) => el.addEventListener('input', applyFilters));
  sort.addEventListener('change', refresh);
  byId('clear').addEventListener('click', () => {
    q.value = ''; platform.value = ''; family.value = ''; status.value = '';
    range.value = ''; sort.value = 'newest'; refresh();
  });
  refresh();
</script>
</body>
</html>
"""


def write_html(path: Path, rows: list[dict[str, Any]]) -> None:
    applied = [row for row in rows if row["status"] == "applied"]
    platforms = sorted({row["platform_key"] for row in rows if row["platform_key"]})
    families = sorted({row["family"] for row in rows})
    generated = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")

    platform_options = "".join(
        f'<option value="{_escape(key)}">{_escape(PLATFORM_LABELS.get(key, key.title()))}</option>'
        for key in platforms
    )
    family_options = "".join(
        f'<option value="{_escape(name)}">{_escape(name)}</option>' for name in families
    )

    document = _HTML_TEMPLATE
    for token, value in (
        ("__GENERATED__", _escape(generated)),
        ("__TOTAL__", str(len(rows))),
        ("__CARDS__", _cards(applied, len(platforms))),
        ("__PLATFORM_COUNT__", str(len(platforms))),
        ("__BARS__", _platform_bars(applied)),
        ("__PLATFORM_OPTIONS__", platform_options),
        ("__FAMILY_OPTIONS__", family_options),
        ("__ROWS__", _table_rows(rows)),
    ):
        document = document.replace(token, value)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(document, encoding="utf-8")


def export_applied_jobs(
    config: AppConfig,
    *,
    csv_path: Path | None = None,
    html_path: Path | None = None,
) -> tuple[Path, Path]:
    """Rebuild both artifacts from ``config.applied_jobs_path``."""
    rows = build_rows(load_history(config.applied_jobs_path))
    data_dir = config.base_dir / "data"
    csv_path = Path(csv_path) if csv_path else data_dir / "applied_jobs.csv"
    html_path = Path(html_path) if html_path else data_dir / "applied_jobs.html"
    write_csv(csv_path, rows)
    write_html(html_path, rows)
    return csv_path, html_path

from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from jobs_auto_apply.applied_report import (
    CSV_COLUMNS,
    build_rows,
    export_applied_jobs,
    load_history,
    role_family,
    write_csv,
    write_html,
)


def _history() -> list[dict]:
    return [
        {
            "job_key": "naukri:111",
            "applied_at": "2026-10-20T09:00:00+00:00",
            "status": "applied",
            "source": "naukri",
            "title": "React Developer",
            "company": "Acme",
            "url": "https://naukri.com/job/111",
        },
        {
            "job_key": "hirist:222",
            "applied_at": "2026-10-28T09:00:00+00:00",
            "status": "applied",
            "source": "hirist",
            "title": "Backend Developer",
            "company": "Beta",
            "url": "https://hirist.tech/job/222",
        },
        {
            "job_key": "naukri:333",
            "applied_at": "2026-10-29T09:00:00+00:00",
            "status": "abandoned",
            "source": "naukri",
            "title": "Full Stack Developer",
            "reason": "non-quick-apply (early)",
            "url": "",
        },
    ]


class BuildRowsTests(unittest.TestCase):
    def test_platform_and_role_are_normalised(self) -> None:
        rows = build_rows(_history())
        by_id = {row["job_id"]: row for row in rows}
        self.assertEqual(by_id["111"]["platform"], "Naukri")
        self.assertEqual(by_id["222"]["platform"], "Hirist")
        self.assertEqual(by_id["111"]["role"], "React Developer")
        self.assertEqual(by_id["333"]["status"], "abandoned")

    def test_newest_first(self) -> None:
        rows = build_rows(_history())
        self.assertEqual([row["job_id"] for row in rows], ["333", "222", "111"])

    def test_platform_falls_back_to_job_key(self) -> None:
        rows = build_rows([{"job_key": "uplers:9", "status": "applied", "title": "Dev"}])
        self.assertEqual(rows[0]["platform"], "Uplers")

    def test_missing_company_is_dash(self) -> None:
        rows = build_rows([{"job_key": "naukri:1", "status": "applied", "title": "Dev"}])
        self.assertEqual(rows[0]["company"], "-")

    def test_unparseable_timestamp_does_not_crash_sorting(self) -> None:
        rows = build_rows(
            [
                {"job_key": "naukri:1", "applied_at": "not-a-date", "status": "applied", "title": "A"},
                {"job_key": "naukri:2", "applied_at": "2026-10-28T09:00:00+00:00", "status": "applied", "title": "B"},
            ]
        )
        self.assertEqual(len(rows), 2)


class RoleFamilyTests(unittest.TestCase):
    def test_families(self) -> None:
        cases = {
            "Full Stack Developer - Node.js/React.js": "Full Stack",
            "MERN Stack Developer": "Full Stack",
            "React.js Developer - Javascript": "Frontend",
            "Frontend Developer": "Frontend",
            "Backend Developer - Python": "Backend",
            "Nodejs Developer": "Backend",
            "Python/AI Developer": "AI / ML",
            "GenAI Engineer - Agentic Systems": "AI / ML",
            "Machine Learning Engineer": "AI / ML",
            "MLOps Engineer - Python": "AI / ML",
            "Android Developer": "Mobile",
            "Data Engineer": "Data",
            "QA Engineer": "QA / Test",
            "Business Analyst": "Other",
        }
        for title, expected in cases.items():
            self.assertEqual(role_family(title), expected, title)

    def test_full_stack_beats_its_stack_words(self) -> None:
        self.assertEqual(role_family("Full Stack Engineer - Node.js/React.js"), "Full Stack")


class LoadHistoryTests(unittest.TestCase):
    def test_missing_file_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(load_history(Path(tmp) / "nope.json"), [])

    def test_malformed_file_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text("{not json", encoding="utf-8")
            self.assertEqual(load_history(path), [])


class WriteCsvTests(unittest.TestCase):
    def test_header_and_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.csv"
            write_csv(path, build_rows(_history()))
            with path.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.reader(handle))
            self.assertEqual(rows[0], CSV_COLUMNS)
            self.assertEqual(len(rows), 4)
            self.assertEqual(rows[1][1], "Naukri")
            self.assertEqual(rows[1][2], "Full Stack Developer")

    def test_written_as_utf8_bom_for_excel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.csv"
            write_csv(path, build_rows(_history()))
            self.assertTrue(path.read_bytes().startswith(b"\xef\xbb\xbf"))


class WriteHtmlTests(unittest.TestCase):
    def test_rows_and_counts_are_rendered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.html"
            write_html(path, build_rows(_history()))
            text = path.read_text(encoding="utf-8")
            self.assertIn("React Developer", text)
            self.assertIn("Backend Developer", text)
            self.assertIn('<div class="n">2</div><div class="k">Applied</div>', text)
            self.assertIn('data-family="Full Stack"', text)
            self.assertIn('id="platform"', text)
            self.assertIn('id="family"', text)
            self.assertIn('id="range"', text)

    def test_filter_metadata_is_emitted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.html"
            write_html(path, build_rows(_history()))
            text = path.read_text(encoding="utf-8")
            self.assertIn('data-status="applied"', text)
            self.assertIn('data-platform="naukri"', text)
            self.assertIn('data-ts="', text)

    def test_titles_are_escaped(self) -> None:
        rows = build_rows(
            [
                {
                    "job_key": "naukri:1",
                    "applied_at": "2026-10-28T09:00:00+00:00",
                    "status": "applied",
                    "source": "naukri",
                    "title": "<script>alert(1)</script>",
                }
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.html"
            write_html(path, rows)
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("<script>alert(1)</script>", text)
            self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", text)


class ExportTests(unittest.TestCase):
    def test_export_writes_both_files_from_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            data = base / "data"
            data.mkdir()
            history = data / "applied_jobs.json"
            history.write_text(
                json.dumps({"applied": [], "history": _history()}), encoding="utf-8"
            )
            config = SimpleNamespace(applied_jobs_path=history, base_dir=base)

            csv_path, html_path = export_applied_jobs(config)

            self.assertEqual(csv_path, data / "applied_jobs.csv")
            self.assertEqual(html_path, data / "applied_jobs.html")
            self.assertTrue(csv_path.exists())
            self.assertTrue(html_path.exists())
            self.assertIn("Backend Developer", csv_path.read_text(encoding="utf-8-sig"))


if __name__ == "__main__":
    unittest.main()
